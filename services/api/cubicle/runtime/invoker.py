"""The invocation path.

Resolve the function, hand the event to a warm isolate, apply whatever the
handler wrote to the session context, and record the invocation. Everything
the console shows on the dashboard, the logs page and the metering page is
derived from the rows written here — nothing is sampled or estimated.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..crypto import DecryptionError, decrypt
from ..db import get_redis, session_scope
from ..logging_setup import log
from ..metrics import COLD_STARTS, GB_SECONDS, INVOCATION_SECONDS, INVOCATIONS
from ..models import EnvVar, Function, FunctionSecret, FunctionVersion, Invocation, LogEntry
from .pool import FunctionSpec, Isolate, IsolateError, pool

CTX_PREFIX = "cubicle:ctx:"
CTX_LOG_PREFIX = "cubicle:ctxlog:"
LOG_CHANNEL = "cubicle:logs"
ENV_REVISION_KEY = "cubicle:env:rev"

_env_cache: tuple[str, dict[str, str]] | None = None
_secret_cache: dict[str, tuple[str, dict[str, str]]] = {}


@dataclass(slots=True)
class InvokeResult:
    status_code: int
    body: Any
    headers: dict[str, str]
    duration_ms: float
    cold: bool
    error: str | None
    logs: list[dict[str, Any]]
    context_read: list[str]
    context_wrote: list[str]
    request_id: str


# ── configuration bundles ────────────────────────────────────────────────────


async def bump_env_revision() -> None:
    await get_redis().incr(ENV_REVISION_KEY)


async def _env_bundle(db: AsyncSession) -> dict[str, str]:
    global _env_cache
    revision = await get_redis().get(ENV_REVISION_KEY) or "0"
    if _env_cache and _env_cache[0] == revision:
        return _env_cache[1]

    rows = (await db.execute(select(EnvVar))).scalars().all()
    bundle: dict[str, str] = {}
    for row in rows:
        try:
            bundle[row.key] = decrypt(row.value_ciphertext, aad=f"env:{row.key}")
        except DecryptionError as exc:
            log.error("env var could not be decrypted", key=row.key, error=str(exc))
    _env_cache = (revision, bundle)
    return bundle


async def _secret_bundle(db: AsyncSession, function_id: str) -> dict[str, str]:
    revision = await get_redis().get(ENV_REVISION_KEY) or "0"
    cached = _secret_cache.get(function_id)
    if cached and cached[0] == revision:
        return cached[1]

    rows = (
        (await db.execute(select(FunctionSecret).where(FunctionSecret.function_id == function_id)))
        .scalars()
        .all()
    )
    bundle: dict[str, str] = {}
    for row in rows:
        try:
            bundle[row.key] = decrypt(row.value_ciphertext, aad=f"secret:{function_id}:{row.key}")
        except DecryptionError as exc:
            log.error("secret could not be decrypted", key=row.key, error=str(exc))
    _secret_cache[function_id] = (revision, bundle)
    return bundle


def invalidate_secret_cache(function_id: str | None = None) -> None:
    if function_id is None:
        _secret_cache.clear()
    else:
        _secret_cache.pop(function_id, None)


# ── session context ──────────────────────────────────────────────────────────


def _ctx_key(namespace: str, session_id: str) -> str:
    return f"{CTX_PREFIX}{namespace}:{session_id}"


async def read_context(namespace: str, session_id: str) -> dict[str, Any]:
    raw = await get_redis().get(_ctx_key(namespace, session_id))
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


async def write_context(namespace: str, session_id: str, data: dict[str, Any]) -> None:
    key = _ctx_key(namespace, session_id)
    if data:
        await get_redis().setex(key, settings.context_ttl, json.dumps(data))
    else:
        await get_redis().delete(key)


async def context_log(namespace: str, session_id: str) -> list[dict[str, Any]]:
    entries = await get_redis().lrange(f"{CTX_LOG_PREFIX}{namespace}:{session_id}", 0, 15)
    return [json.loads(e) for e in entries]


async def append_context_log(namespace: str, session_id: str, function: str, detail: str) -> None:
    key = f"{CTX_LOG_PREFIX}{namespace}:{session_id}"
    entry = json.dumps(
        {"time": datetime.now(UTC).strftime("%H:%M:%S"), "fn": function, "detail": detail}
    )
    await get_redis().lpush(key, entry)
    await get_redis().ltrim(key, 0, 15)
    await get_redis().expire(key, settings.context_ttl)


async def clear_context(namespace: str, session_id: str) -> None:
    await get_redis().delete(_ctx_key(namespace, session_id))
    await get_redis().delete(f"{CTX_LOG_PREFIX}{namespace}:{session_id}")


# ── invocation ───────────────────────────────────────────────────────────────


def spec_for(function: Function, version: FunctionVersion, node) -> FunctionSpec:
    return FunctionSpec(
        id=str(function.id),
        name=function.name,
        namespace=function.group.ns,
        runtime=function.runtime,
        memory_mb=function.memory_mb,
        timeout_s=function.timeout_s,
        min_instances=function.min_instances,
        version_id=str(version.id),
        version_number=version.number,
        node_name=node.name,
        docker_host=node.docker_host,
        node_is_local=node.is_local,
    )


async def invoke(
    db: AsyncSession,
    *,
    function: Function,
    version: FunctionVersion,
    node,
    method: str,
    path: str,
    headers: dict[str, str],
    query: dict[str, str],
    body: Any,
    session_id: str | None,
    record: bool = True,
) -> InvokeResult:
    request_id = "req_" + uuid.uuid4().hex[:12]
    namespace = function.group.ns
    session_id = session_id or "sess_" + uuid.uuid4().hex[:12]
    started = time.perf_counter()

    ctx_access = function.ctx_access
    ctx_before = await read_context(namespace, session_id) if ctx_access in ("rw", "r") else {}

    payload = {
        "request_id": request_id,
        "session_id": session_id,
        "namespace": namespace,
        "function": function.name,
        "method": method,
        "path": path,
        "headers": headers,
        "query": query,
        "body": body,
        "timeout_s": function.timeout_s,
        "ctx_access": ctx_access,
        "context": ctx_before,
        "env": await _env_bundle(db),
        "secrets": await _secret_bundle(db, str(function.id)),
        "services": await _service_urls(db),
    }

    spec = spec_for(function, version, node)
    isolate: Isolate | None = None
    cold = False
    healthy = True
    error: str | None = None
    status_code = 500
    response_body: Any = None
    response_headers: dict[str, str] = {}
    handler_logs: list[dict[str, Any]] = []
    ctx_wrote: list[str] = []

    try:
        isolate, cold = await pool.acquire(spec)
        result = await pool.invoke(isolate, payload, timeout=function.timeout_s)

        status_code = int(result.get("status_code", 200))
        response_body = result.get("body")
        response_headers = result.get("headers") or {}
        handler_logs = result.get("logs") or []
        error = result.get("error")

        writes: dict[str, Any] = result.get("context_writes") or {}
        deletes: list[str] = result.get("context_deletes") or []
        if ctx_access in ("rw", "w") and (writes or deletes):
            merged = await read_context(namespace, session_id)
            merged.update(writes)
            for key in deletes:
                merged.pop(key, None)
            await write_context(namespace, session_id, merged)
            ctx_wrote = sorted({*writes.keys(), *deletes})
            await append_context_log(
                namespace, session_id, function.name, "wrote " + ", ".join(ctx_wrote)
            )
        elif ctx_access in ("rw", "r"):
            detail = (
                "read " + ", ".join(sorted(ctx_before)) if ctx_before else "read · context empty"
            )
            await append_context_log(namespace, session_id, function.name, detail)

    except IsolateError as exc:
        healthy = False
        error = str(exc)
        status_code = 503
        response_body = {"error": "isolate_unavailable", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a 502
        healthy = False
        error = f"{exc.__class__.__name__}: {exc}"
        status_code = 502
        response_body = {"error": "invocation_failed", "message": str(exc)}
        log.exception("invocation failed", function=function.name, namespace=namespace)
    finally:
        if isolate is not None:
            await pool.release(isolate, healthy=healthy)

    duration_ms = (time.perf_counter() - started) * 1000
    result = InvokeResult(
        status_code=status_code,
        body=response_body,
        headers=response_headers,
        duration_ms=round(duration_ms, 2),
        cold=cold,
        error=error,
        logs=handler_logs,
        context_read=sorted(ctx_before) if ctx_access in ("rw", "r") else [],
        context_wrote=ctx_wrote,
        request_id=request_id,
    )

    INVOCATIONS.labels(namespace=namespace, function=function.name, status=str(status_code)).inc()
    INVOCATION_SECONDS.labels(namespace=namespace, function=function.name).observe(
        duration_ms / 1000
    )
    if cold:
        COLD_STARTS.labels(namespace=namespace, function=function.name).inc()

    if record:
        await _record(function, node.name, result, handler_logs)
    return result


def _response_size(body: Any) -> int:
    if body is None:
        return 0
    try:
        return len(json.dumps(body).encode()) if not isinstance(body, str) else len(body.encode())
    except (TypeError, ValueError):
        return 0


async def _service_urls(db: AsyncSession) -> dict[str, str]:
    from .services import connection_urls  # imported here to avoid a cycle

    return await connection_urls(db)


async def _record(
    function: Function, node_name: str, result: InvokeResult, handler_logs: list[dict[str, Any]]
) -> None:
    """Persist the invocation and its logs on a session of their own.

    Recording must never fail the request, so it gets its own transaction.
    """
    # An invocation that never reached the handler — no isolate available, or
    # the pool failed — is recorded, but not metered. Billing a customer for a
    # platform failure would make the metering page a lie.
    reached_handler = result.status_code not in (502, 503)
    gb_seconds = (
        (function.memory_mb / 1024) * (result.duration_ms / 1000) if reached_handler else 0.0
    )
    if gb_seconds:
        GB_SECONDS.labels(namespace=function.group.ns).inc(gb_seconds)

    try:
        async with session_scope() as db:
            db.add(
                Invocation(
                    function_id=function.id,
                    function_name=function.name,
                    namespace=function.group.ns,
                    duration_ms=result.duration_ms,
                    status_code=result.status_code,
                    cold=result.cold,
                    error=result.error,
                    request_id=result.request_id,
                    memory_mb=function.memory_mb,
                    gb_seconds=gb_seconds,
                    egress_bytes=_response_size(result.body),
                    node_name=node_name,
                )
            )

            entries: list[LogEntry] = []
            for entry in handler_logs:
                entries.append(
                    LogEntry(
                        function_id=function.id,
                        function_name=function.name,
                        level=str(entry.get("level", "INFO")).upper()[:8],
                        message=str(entry.get("message", ""))[:8000],
                        request_id=result.request_id,
                    )
                )
            summary_level = (
                "ERROR"
                if result.status_code >= 500
                else "WARN"
                if result.status_code >= 400
                else "INFO"
            )
            summary = (
                f"{function.method} {function.path} → {result.status_code}"
                f"{' · cold start' if result.cold else ''}"
            )
            if result.error:
                summary += f" · {result.error}"
            entries.append(
                LogEntry(
                    function_id=function.id,
                    function_name=function.name,
                    level=summary_level,
                    message=summary[:8000],
                    duration_ms=result.duration_ms,
                    request_id=result.request_id,
                )
            )
            db.add_all(entries)

        await _publish_logs(function, result, handler_logs)
    except Exception:  # noqa: BLE001 - telemetry must not break the request
        log.exception("could not record invocation", function=function.name)


async def _publish_logs(
    function: Function, result: InvokeResult, handler_logs: list[dict[str, Any]]
) -> None:
    now = datetime.now(UTC)
    payload = [
        {
            "ts": now.isoformat(),
            "time": now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}",
            "level": str(entry.get("level", "INFO")).upper(),
            "function_name": function.name,
            "message": str(entry.get("message", "")),
            "duration": None,
            "request_id": result.request_id,
        }
        for entry in handler_logs
    ]
    payload.append(
        {
            "ts": now.isoformat(),
            "time": now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}",
            "level": "ERROR"
            if result.status_code >= 500
            else "WARN"
            if result.status_code >= 400
            else "INFO",
            "function_name": function.name,
            "message": f"{function.method} {function.path} → {result.status_code}",
            "duration": f"{result.duration_ms:.0f}ms",
            "request_id": result.request_id,
        }
    )
    await get_redis().publish(LOG_CHANNEL, json.dumps(payload))


async def system_log(level: str, message: str, function: Function | None = None) -> None:
    """Record a control-plane event so it shows up in the logs page too."""
    now = datetime.now(UTC)
    async with session_scope() as db:
        db.add(
            LogEntry(
                function_id=function.id if function else None,
                function_name=function.name if function else "control-plane",
                level=level.upper(),
                message=message[:8000],
            )
        )
    await get_redis().publish(
        LOG_CHANNEL,
        json.dumps(
            [
                {
                    "ts": now.isoformat(),
                    "time": now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}",
                    "level": level.upper(),
                    "function_name": function.name if function else "control-plane",
                    "message": message,
                    "duration": None,
                    "request_id": "",
                }
            ]
        ),
    )
