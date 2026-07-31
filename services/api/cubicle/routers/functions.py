"""Namespaces, functions, versions, deploys and the playground."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from slugify import slugify
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from .. import analytics
from .. import clusters as cluster_svc
from ..crypto import decrypt, encrypt, mask
from ..db import session_scope
from ..deps import CurrentCluster, CurrentPrincipal, DbSession, RequireDeveloper
from ..logging_setup import log
from ..metrics import BUILDS
from ..models import Cluster, Function, FunctionSecret, FunctionVersion, Group, Invocation, LogEntry
from ..runtime import builder, invoker
from ..runtime.nodes import pick_node
from ..runtime.pool import pool
from ..schemas import (
    RESERVED_NAMESPACES,
    ContextState,
    DeployRequest,
    FunctionCreate,
    FunctionDetail,
    FunctionUpdate,
    GroupCreate,
    GroupOut,
    LogOut,
    SecretIn,
    SecretOut,
    TestInvokeRequest,
    TestInvokeResult,
    VersionOut,
    validate_slug,
)
from ..templates import RUNTIME_LABELS, scaffold

router = APIRouter(prefix="/api", tags=["functions"])


# ── helpers ──────────────────────────────────────────────────────────────────


def base_url(cluster: Cluster, ns: str = "", name: str = "") -> str:
    return cluster_svc.function_url(cluster, ns, name)


def serialize_function(
    fn: Function, cluster: Cluster, *, version: FunctionVersion | None = None
) -> dict:
    return {
        "id": fn.id,
        "group_id": fn.group_id,
        "namespace": fn.group.ns,
        "name": fn.name,
        "method": fn.method,
        "runtime": fn.runtime,
        "runtime_label": RUNTIME_LABELS.get(fn.runtime, fn.runtime),
        "ctx_access": fn.ctx_access,
        "memory_mb": fn.memory_mb,
        "timeout_s": fn.timeout_s,
        "min_instances": fn.min_instances,
        "max_instances": fn.max_instances,
        "node_pool": fn.node_pool,
        "auth_required": fn.auth_required,
        "status": fn.status,
        "path": f"/{fn.group.ns}/{fn.name}",
        "cluster": cluster.slug,
        "url": base_url(cluster, fn.group.ns, fn.name),
        "version": version.number if version else 0,
        "version_status": version.status if version else "pending",
        "updated_at": fn.updated_at,
        "created_at": fn.created_at,
    }


async def _load_group(db, group_id: uuid.UUID, cluster: Cluster) -> Group | None:
    return (
        await db.execute(select(Group).where(Group.id == group_id, Group.cluster_id == cluster.id))
    ).scalar_one_or_none()


async def load_function(db, function_id: uuid.UUID, cluster: Cluster | None = None) -> Function:
    """Fetch a function, refusing to look outside ``cluster`` when one is given."""
    stmt = select(Function).options(selectinload(Function.group)).where(Function.id == function_id)
    if cluster is not None:
        stmt = stmt.join(Group, Group.id == Function.group_id).where(Group.cluster_id == cluster.id)
    fn = (await db.execute(stmt)).scalar_one_or_none()
    if fn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such function.")
    return fn


async def current_version(db, fn: Function) -> FunctionVersion | None:
    if fn.current_version_id:
        return await db.get(FunctionVersion, fn.current_version_id)
    return (
        await db.execute(
            select(FunctionVersion)
            .where(FunctionVersion.function_id == fn.id)
            .order_by(FunctionVersion.number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


# ── namespaces ───────────────────────────────────────────────────────────────


@router.get("/groups", response_model=list[GroupOut])
async def list_groups(db: DbSession, cluster: CurrentCluster, _: CurrentPrincipal):
    rows = (
        await db.execute(
            select(Group, func.count(Function.id))
            .outerjoin(Function, Function.group_id == Group.id)
            .where(Group.cluster_id == cluster.id)
            .group_by(Group.id)
            .order_by(Group.created_at)
        )
    ).all()
    return [
        GroupOut(
            id=group.id,
            name=group.name,
            ns=group.ns,
            base_url=base_url(cluster, group.ns),
            function_count=count,
            created_at=group.created_at,
        )
        for group, count in rows
    ]


@router.post("/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: GroupCreate, db: DbSession, cluster: CurrentCluster, _: RequireDeveloper
):
    ns = payload.ns or slugify(payload.name)
    ns = validate_slug(ns, what="Namespace")
    if ns in RESERVED_NAMESPACES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"'{ns}' is reserved.")

    # Read anything needed for the error message before committing: a rollback
    # expires the ORM objects, and touching one afterwards would attempt IO
    # from a context that cannot await it.
    cluster_label = cluster.name
    group = Group(cluster_id=cluster.id, name=payload.name.strip(), ns=ns)
    db.add(group)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"The namespace '{ns}' is already in use in {cluster_label}.",
        ) from exc
    await db.refresh(group)
    return GroupOut(
        id=group.id,
        name=group.name,
        ns=group.ns,
        base_url=base_url(cluster, group.ns),
        function_count=0,
        created_at=group.created_at,
    )


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: uuid.UUID, db: DbSession, cluster: CurrentCluster, _: RequireDeveloper
) -> Response:
    group = await _load_group(db, group_id, cluster)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such namespace.")

    functions = (
        (await db.execute(select(Function).where(Function.group_id == group_id))).scalars().all()
    )
    for fn in functions:
        await pool.drain(function_id=str(fn.id))
    await db.delete(group)
    await db.commit()
    log.info("namespace deleted", ns=group.ns, functions=len(functions))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── functions ────────────────────────────────────────────────────────────────


@router.get("/functions", response_model=list[dict])
async def list_functions(
    db: DbSession,
    cluster: CurrentCluster,
    _: CurrentPrincipal,
    group_id: uuid.UUID | None = None,
):
    stmt = (
        select(Function)
        .options(selectinload(Function.group))
        .join(Group, Group.id == Function.group_id)
        .where(Group.cluster_id == cluster.id)
        .order_by(Function.created_at)
    )
    if group_id:
        stmt = stmt.where(Function.group_id == group_id)
    functions = (await db.execute(stmt)).scalars().all()
    stats = await analytics.bulk_function_stats(db, cluster_id=cluster.id)

    result = []
    for fn in functions:
        version = await current_version(db, fn)
        payload = serialize_function(fn, cluster, version=version)
        payload["stats"] = stats.get(
            fn.id,
            {
                "invocations": 0,
                "invocations_label": "0",
                "p50": analytics.DASH,
                "p95": analytics.DASH,
                "error_rate": analytics.DASH,
                "cold_rate": analytics.DASH,
                "errors": 0,
            },
        )
        payload["node_pool"] = fn.node_pool
        result.append(payload)
    return result


@router.post(
    "/groups/{group_id}/functions",
    response_model=FunctionDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_function(
    group_id: uuid.UUID,
    payload: FunctionCreate,
    db: DbSession,
    cluster: CurrentCluster,
    _: RequireDeveloper,
):
    group = await _load_group(db, group_id, cluster)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such namespace.")

    fn = Function(
        group_id=group.id,
        name=payload.name,
        method=payload.method,
        runtime=payload.runtime,
        ctx_access=payload.ctx_access,
        memory_mb=payload.memory_mb,
        timeout_s=payload.timeout_s,
        auth_required=payload.auth_required,
        node_pool=payload.node_pool,
    )
    namespace = group.ns
    db.add(fn)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"'{payload.name}' already exists in {namespace}.",
        ) from exc
    # The whole row, not just the relationship: `updated_at` carries an
    # onupdate, so the flush expires it, and reading an expired column while
    # building the response would attempt IO outside the async context.
    await db.refresh(fn)

    files = scaffold(
        name=fn.name,
        namespace=group.ns,
        runtime=fn.runtime,
        method=fn.method,
        memory_mb=fn.memory_mb,
        timeout_s=fn.timeout_s,
        ctx_access=fn.ctx_access,
        base_url=base_url(cluster, group.ns, fn.name),
    )
    version = FunctionVersion(function_id=fn.id, number=1, files=files, status="pending")
    db.add(version)
    await db.commit()
    await db.refresh(version)

    asyncio.create_task(  # noqa: RUF006
        _build_and_activate(str(fn.id), str(version.id), str(cluster.id))
    )
    log.info("function created", ns=group.ns, name=fn.name)
    return await _detail(db, fn, cluster)


@router.get("/functions/{function_id}", response_model=FunctionDetail)
async def get_function(
    function_id: uuid.UUID, db: DbSession, cluster: CurrentCluster, _: CurrentPrincipal
):
    fn = await load_function(db, function_id, cluster)
    return await _detail(db, fn, cluster)


@router.patch("/functions/{function_id}", response_model=FunctionDetail)
async def update_function(
    function_id: uuid.UUID,
    payload: FunctionUpdate,
    db: DbSession,
    cluster: CurrentCluster,
    _: RequireDeveloper,
):
    fn = await load_function(db, function_id, cluster)
    data = payload.model_dump(exclude_unset=True)
    runtime_changed = "runtime" in data and data["runtime"] != fn.runtime
    limits_changed = any(k in data for k in ("memory_mb", "timeout_s", "node_pool"))

    for key, value in data.items():
        setattr(fn, key, value)

    # Read before the rollback: it expires the instance, and re-reading an
    # attribute to build the message would then attempt IO of its own.
    ceiling, floor = fn.max_instances, fn.min_instances
    if ceiling < floor:
        await db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Max instances ({ceiling}) cannot be below the {floor} warm "
            "instance(s) this function keeps resident.",
        )

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That name is already taken.") from exc
    # The whole row, not just the relationship: `updated_at` carries an
    # onupdate, so the flush expires it, and reading an expired column while
    # building the response would attempt IO outside the async context.
    await db.refresh(fn)

    if runtime_changed:
        # A different interpreter needs a rebuild, not just a restart.
        version = await current_version(db, fn)
        if version:
            asyncio.create_task(  # noqa: RUF006
                _build_and_activate(str(fn.id), str(version.id), str(cluster.id))
            )
    elif limits_changed or fn.status == "paused":
        await pool.drain(function_id=str(fn.id))

    return await _detail(db, fn, cluster)


@router.delete("/functions/{function_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_function(
    function_id: uuid.UUID, db: DbSession, cluster: CurrentCluster, _: RequireDeveloper
) -> Response:
    fn = await load_function(db, function_id, cluster)
    await pool.drain(function_id=str(fn.id))

    versions = (
        (await db.execute(select(FunctionVersion).where(FunctionVersion.function_id == fn.id)))
        .scalars()
        .all()
    )
    node = await pick_node(db, cluster, fn.node_pool)
    for version in versions:
        await builder.remove_volume(
            node.docker_host, builder.volume_name(str(fn.id), version.number)
        )

    fn.current_version_id = None
    await db.flush()
    await db.delete(fn)
    await db.commit()
    log.info("function deleted", name=fn.name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── source and deploys ───────────────────────────────────────────────────────


@router.get("/functions/{function_id}/versions", response_model=list[VersionOut])
async def list_versions(function_id: uuid.UUID, db: DbSession, _: CurrentPrincipal):
    rows = (
        (
            await db.execute(
                select(FunctionVersion)
                .where(FunctionVersion.function_id == function_id)
                .order_by(FunctionVersion.number.desc())
                .limit(25)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@router.post("/functions/{function_id}/deploy", response_model=FunctionDetail)
async def deploy(
    function_id: uuid.UUID,
    payload: DeployRequest,
    db: DbSession,
    cluster: CurrentCluster,
    _: RequireDeveloper,
):
    fn = await load_function(db, function_id, cluster)
    latest = (
        await db.execute(
            select(func.max(FunctionVersion.number)).where(FunctionVersion.function_id == fn.id)
        )
    ).scalar_one() or 0

    previous = await current_version(db, fn)
    files = dict(previous.files) if previous else {}
    files.update(payload.files)

    version = FunctionVersion(function_id=fn.id, number=latest + 1, files=files, status="building")
    db.add(version)
    await db.commit()
    await db.refresh(version)

    await _build_and_activate(str(fn.id), str(version.id), str(cluster.id))
    await db.refresh(fn)
    return await _detail(db, fn, cluster)


async def _build_and_activate(function_id: str, version_id: str, cluster_id: str) -> None:
    """Build a version and, if it succeeds, make it the one that serves traffic."""
    async with session_scope() as db:
        cluster = await db.get(Cluster, uuid.UUID(cluster_id))
        fn = await load_function(db, uuid.UUID(function_id))
        version = await db.get(FunctionVersion, uuid.UUID(version_id))
        if version is None:
            return
        version.status = "building"
        await db.flush()
        node = await pick_node(db, cluster, fn.node_pool)

    result = await builder.build_version(
        host=node.docker_host,
        runtime=fn.runtime,
        function_id=function_id,
        version_number=version.number,
        files=version.files,
    )

    async with session_scope() as db:
        fn = await load_function(db, uuid.UUID(function_id))
        version = await db.get(FunctionVersion, uuid.UUID(version_id))
        if version is None:
            return
        version.build_log = result.log
        version.build_ms = result.duration_ms
        if result.ok:
            version.status = "ready"
            version.deployed_at = datetime.now(UTC)
            previous_id = fn.current_version_id
            fn.current_version_id = version.id
            BUILDS.labels(result="ok").inc()
        else:
            version.status = "failed"
            previous_id = None
            BUILDS.labels(result="failed").inc()

    if result.ok:
        # Old isolates keep serving until the new version is ready, then go.
        if previous_id:
            await pool.drain(version_id=str(previous_id))
        await invoker.system_log(
            "INFO",
            f"deployed version {version.number} in {result.duration_ms}ms",
            fn,
            cluster_id=uuid.UUID(cluster_id),
        )
    else:
        await invoker.system_log(
            "ERROR",
            f"build failed for version {version.number}",
            fn,
            cluster_id=uuid.UUID(cluster_id),
        )


# ── playground test runs ─────────────────────────────────────────────────────


@router.post("/functions/{function_id}/test", response_model=TestInvokeResult)
async def test_invoke(
    function_id: uuid.UUID,
    payload: TestInvokeRequest,
    db: DbSession,
    cluster: CurrentCluster,
    _: RequireDeveloper,
):
    fn = await load_function(db, function_id, cluster)
    version = await current_version(db, fn)
    if version is None or version.status != "ready":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This function has no successfully built version yet.",
        )
    node = await pick_node(db, cluster, fn.node_pool)

    result = await invoker.invoke(
        db,
        cluster=cluster,
        function=fn,
        version=version,
        node=node,
        method=fn.method,
        path=f"/{fn.group.ns}/{fn.name}",
        headers={"content-type": "application/json", **payload.headers},
        query=payload.query,
        body=payload.body,
        session_id=payload.session_id,
    )
    return TestInvokeResult(
        status_code=result.status_code,
        duration_ms=result.duration_ms,
        cold=result.cold,
        body=result.body,
        logs=[f"{entry.get('level', 'INFO')} {entry.get('message', '')}" for entry in result.logs],
        error=result.error,
        context_read=result.context_read,
        context_wrote=result.context_wrote,
    )


# ── session context ──────────────────────────────────────────────────────────


@router.get("/groups/{group_id}/context", response_model=ContextState)
async def get_context(
    group_id: uuid.UUID,
    db: DbSession,
    cluster: CurrentCluster,
    _: CurrentPrincipal,
    session: str = Query(...),
):
    group = await _load_group(db, group_id, cluster)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such namespace.")
    scope = invoker.scope_for(cluster.slug, group.ns)
    data = await invoker.read_context(scope, session)
    log_entries = await invoker.context_log(scope, session)
    import json as _json

    return ContextState(
        session_id=session,
        data=data,
        log=log_entries,
        size_bytes=len(_json.dumps(data)) if data else 0,
    )


@router.delete("/groups/{group_id}/context", status_code=status.HTTP_204_NO_CONTENT)
async def clear_context(
    group_id: uuid.UUID,
    db: DbSession,
    cluster: CurrentCluster,
    _: RequireDeveloper,
    session: str = Query(...),
) -> Response:
    group = await _load_group(db, group_id, cluster)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such namespace.")
    await invoker.clear_context(invoker.scope_for(cluster.slug, group.ns), session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── per-function secrets ─────────────────────────────────────────────────────


@router.get("/functions/{function_id}/secrets", response_model=list[SecretOut])
async def list_secrets(
    function_id: uuid.UUID, db: DbSession, cluster: CurrentCluster, _: CurrentPrincipal
):
    rows = (
        (await db.execute(select(FunctionSecret).where(FunctionSecret.function_id == function_id)))
        .scalars()
        .all()
    )
    return [
        SecretOut(key=row.key, value=mask(_safe(row, function_id)), updated_at=row.updated_at)
        for row in rows
    ]


@router.post("/functions/{function_id}/secrets", response_model=SecretOut)
async def upsert_secret(
    function_id: uuid.UUID,
    payload: SecretIn,
    db: DbSession,
    cluster: CurrentCluster,
    _: RequireDeveloper,
):
    await load_function(db, function_id, cluster)
    row = (
        await db.execute(
            select(FunctionSecret).where(
                FunctionSecret.function_id == function_id, FunctionSecret.key == payload.key
            )
        )
    ).scalar_one_or_none()
    ciphertext = encrypt(payload.value, aad=f"secret:{function_id}:{payload.key}")
    if row is None:
        row = FunctionSecret(function_id=function_id, key=payload.key, value_ciphertext=ciphertext)
        db.add(row)
    else:
        row.value_ciphertext = ciphertext
    await db.commit()
    await db.refresh(row)
    invoker.invalidate_secret_cache(str(function_id))
    await invoker.bump_env_revision()
    return SecretOut(key=row.key, value=mask(payload.value), updated_at=row.updated_at)


@router.get("/functions/{function_id}/secrets/{key}/reveal", response_model=SecretOut)
async def reveal_secret(
    function_id: uuid.UUID,
    key: str,
    db: DbSession,
    cluster: CurrentCluster,
    principal: CurrentPrincipal,
):
    if not principal.can("admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can reveal secret values.")
    row = (
        await db.execute(
            select(FunctionSecret).where(
                FunctionSecret.function_id == function_id, FunctionSecret.key == key
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such secret.")
    log.info("secret revealed", key=key, by=principal.user.email)
    return SecretOut(
        key=row.key,
        value=decrypt(row.value_ciphertext, aad=f"secret:{function_id}:{key}"),
        updated_at=row.updated_at,
    )


@router.delete("/functions/{function_id}/secrets/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(
    function_id: uuid.UUID, key: str, db: DbSession, _: RequireDeveloper
) -> Response:
    await db.execute(
        delete(FunctionSecret).where(
            FunctionSecret.function_id == function_id, FunctionSecret.key == key
        )
    )
    await db.commit()
    invoker.invalidate_secret_cache(str(function_id))
    await invoker.bump_env_revision()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _safe(row: FunctionSecret, function_id: uuid.UUID) -> str:
    try:
        return decrypt(row.value_ciphertext, aad=f"secret:{function_id}:{row.key}")
    except Exception:  # noqa: BLE001 - a bad root key must not break the page
        return ""


# ── per-function observability ───────────────────────────────────────────────


@router.get("/functions/{function_id}/logs", response_model=list[LogOut])
async def function_logs(
    function_id: uuid.UUID, db: DbSession, _: CurrentPrincipal, limit: int = 60
):
    rows = (
        (
            await db.execute(
                select(LogEntry)
                .where(LogEntry.function_id == function_id)
                .order_by(LogEntry.ts.desc())
                .limit(min(limit, 500))
            )
        )
        .scalars()
        .all()
    )
    return [_log_out(row) for row in rows]


@router.get("/functions/{function_id}/metrics")
async def function_metrics(
    function_id: uuid.UUID, db: DbSession, _: CurrentPrincipal, hours: int = 24
):
    stats = await analytics.function_stats(db, function_id, hours=hours)
    return {
        "stats": stats,
        "latency": await analytics.latency_series(db, function_id, hours=hours),
        "invocations": await analytics.invocation_series(
            db, hours=hours, buckets=28, function_id=function_id
        ),
    }


def _log_out(row: LogEntry) -> LogOut:
    return LogOut(
        id=row.id,
        ts=row.ts,
        time=row.ts.strftime("%H:%M:%S.") + f"{row.ts.microsecond // 1000:03d}",
        level=row.level,
        function_name=row.function_name,
        message=row.message,
        duration=analytics.fmt_ms(row.duration_ms) if row.duration_ms is not None else None,
        request_id=row.request_id,
    )


async def _detail(db, fn: Function, cluster: Cluster) -> dict[str, Any]:
    version = await current_version(db, fn)
    stats = await analytics.function_stats(db, fn.id)
    payload = serialize_function(fn, cluster, version=version)
    payload.update(
        {
            "files": version.files if version else {},
            "build_log": version.build_log if version else "",
            "build_ms": version.build_ms if version else 0,
            "stats": {
                **{k: v for k, v in stats.items() if k not in ("gb_seconds", "last_invocation")},
                "last_deploy": analytics.relative(version.deployed_at) if version else None,
            },
        }
    )
    return payload


@router.get("/functions/{function_id}/invocations")
async def recent_invocations(
    function_id: uuid.UUID, db: DbSession, _: CurrentPrincipal, limit: int = 20
):
    rows = (
        (
            await db.execute(
                select(Invocation)
                .where(Invocation.function_id == function_id)
                .order_by(Invocation.ts.desc())
                .limit(min(limit, 200))
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "request_id": row.request_id,
            "ts": row.ts,
            "duration": analytics.fmt_ms(row.duration_ms),
            "status_code": row.status_code,
            "cold": row.cold,
            "error": row.error,
            "node": row.node_name,
        }
        for row in rows
    ]
