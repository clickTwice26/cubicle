"""First-run setup.

There is no registration anywhere in Cubicle. The very first person to open the
console names the cluster and chooses the administrator password, and that is
the only account creation path that exists. Once ``setup_complete`` is set the
endpoints below refuse to run again.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from .. import security
from ..config import settings
from ..db import get_redis, session_scope
from ..deps import DbSession, InstanceDep
from ..logging_setup import log
from ..models import ApiKey, Instance, Node, User
from ..runtime.engine import EngineError, engines
from ..runtime.nodes import ensure_local_node, format_spec
from ..schemas import SetupRequest, SetupStatus

router = APIRouter(prefix="/api/setup", tags=["setup"])

PROGRESS_KEY = "cubicle:setup:progress"

STEPS = [
    ("keys", "Generating the admin credential and CLI deploy token", "argon2id · hmac-sha256"),
    ("control", "Writing control plane configuration", "postgres · raft-free"),
    ("nodes", "Registering nodes", "docker engine"),
    ("ingress", "Configuring ingress and routing", ""),
    ("runtimes", "Warming runtime snapshots", "python3.12 · python3.11"),
]


@router.get("/status", response_model=SetupStatus)
async def setup_status(instance: InstanceDep) -> SetupStatus:
    return SetupStatus(
        setup_complete=instance.setup_complete,
        version=settings.version,
        cluster_name=instance.cluster_name if instance.setup_complete else None,
        public_url=settings.public_url,
        domain=settings.domain,
        tls=settings.public_url.startswith("https://"),
    )


@router.get("/nodes")
async def joinable_nodes(db: DbSession, instance: InstanceDep) -> list[dict]:
    """Engines this control plane can already see, for the join step."""
    if instance.setup_complete:
        raise HTTPException(status.HTTP_409_CONFLICT, "This instance is already set up.")
    try:
        node = await ensure_local_node(db)
    except EngineError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"The Docker engine is unreachable, so no isolates could run: {exc}",
        ) from exc

    nodes = (await db.execute(select(Node).order_by(Node.created_at))).scalars().all()
    return [
        {
            "name": n.name,
            "spec": format_spec(n),
            "status": n.status,
            "is_local": n.is_local,
            "engine_version": n.engine_version,
            "detected": n.id == node.id,
        }
        for n in nodes
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def run_setup(
    payload: SetupRequest, request: Request, response: Response, db: DbSession
) -> dict:
    instance = await db.get(Instance, 1)
    if instance is None:
        instance = Instance(id=1)
        db.add(instance)
        await db.flush()
    if instance.setup_complete:
        raise HTTPException(status.HTTP_409_CONFLICT, "This instance is already set up.")

    existing = (await db.execute(select(func.count(User.id)))).scalar_one()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "An administrator already exists.")

    policy = security.check_password_policy(payload.password)
    if not policy.ok:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, policy.reason)

    await _reset_progress()

    # 1 — keys
    await _mark("keys", "running")
    user = User(
        email=str(payload.admin_email).lower(),
        name=payload.admin_name.strip(),
        role="owner",
        password_hash=security.hash_password(payload.password),
    )
    db.add(user)
    await db.flush()

    token, prefix, token_hash = security.generate_api_key()
    db.add(
        ApiKey(
            name="cli-first-run",
            prefix=prefix,
            token_hash=token_hash,
            scope="admin",
            created_by=user.id,
        )
    )
    await _mark("keys", "done")

    # 2 — control plane configuration
    await _mark("control", "running")
    instance.cluster_name = payload.cluster_name
    instance.ingress_domain = payload.ingress_domain.strip().lstrip("*.") or settings.domain
    instance.data_dir = payload.data_dir.strip() or "/var/lib/cubicle"
    instance.kms_backend = payload.kms_backend
    instance.version = settings.version
    instance.setup_complete = True
    user.last_login_at = datetime.now(UTC)
    await db.commit()
    await _mark("control", "done")

    session_token = await security.create_session(str(user.id))
    security.set_session_cookie(response, session_token)

    asyncio.create_task(_finish_provisioning(payload.nodes))  # noqa: RUF006

    log.info(
        "instance set up",
        cluster=instance.cluster_name,
        admin=user.email,
        ip=security.client_ip(request),
    )
    return {
        "cluster_name": instance.cluster_name,
        "ingress_domain": instance.ingress_domain,
        "cli_token": token,
        "user": {"name": user.name, "email": user.email, "role": user.role},
    }


@router.get("/progress")
async def progress_stream() -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        last = None
        for _ in range(600):
            raw = await get_redis().get(PROGRESS_KEY)
            if raw and raw != last:
                last = raw
                yield f"data: {raw}\n\n"
                if json.loads(raw).get("complete"):
                    return
            await asyncio.sleep(0.25)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── provisioning ─────────────────────────────────────────────────────────────


async def _reset_progress() -> None:
    payload = {
        "complete": False,
        "steps": [
            {"id": sid, "label": label, "meta": meta, "status": "pending"}
            for sid, label, meta in STEPS
        ],
    }
    await get_redis().setex(PROGRESS_KEY, 3600, json.dumps(payload))


async def _mark(step_id: str, state: str, meta: str | None = None) -> None:
    raw = await get_redis().get(PROGRESS_KEY)
    if not raw:
        await _reset_progress()
        raw = await get_redis().get(PROGRESS_KEY)
    payload = json.loads(raw)
    for step in payload["steps"]:
        if step["id"] == step_id:
            step["status"] = state
            if meta is not None:
                step["meta"] = meta
    payload["complete"] = all(s["status"] in ("done", "failed") for s in payload["steps"])
    await get_redis().setex(PROGRESS_KEY, 3600, json.dumps(payload))


async def _finish_provisioning(selected: list[str]) -> None:
    """Steps 3–5: real work, streamed to the wizard while it animates."""
    try:
        await _mark("nodes", "running")
        async with session_scope() as db:
            node = await ensure_local_node(db)
            nodes = (await db.execute(select(Node))).scalars().all()
            for n in nodes:
                n.schedulable = (not selected) or n.name in selected
            if not any(n.schedulable for n in nodes):
                node.schedulable = True
        await _mark("nodes", "done", f"{len([n for n in nodes if n.schedulable])} schedulable")

        await _mark("ingress", "running")
        await engines.ensure_network(node.docker_host, settings.function_network)
        await _mark("ingress", "done", settings.public_url)

        await _mark("runtimes", "running")
        missing = []
        for runtime in ("python312", "python311"):
            image = settings.runtime_image(runtime)
            if not await engines.image_present(node.docker_host, image):
                missing.append(image)
        if missing:
            await _mark(
                "runtimes",
                "failed",
                "missing: " + ", ".join(missing),
            )
            log.error("runtime images are not built", missing=missing)
        else:
            await _mark("runtimes", "done", "python3.12 · python3.11")
    except Exception as exc:  # noqa: BLE001 - surfaced in the wizard
        log.exception("provisioning failed")
        await _mark("runtimes", "failed", str(exc)[:120])
