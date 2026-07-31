"""Node registry.

A node is a Docker engine Cubicle may schedule isolates onto. The engine this
control plane runs on registers itself on first boot; further engines are added
by URL from Settings. Capacity comes from the engine itself, and utilisation is
computed from what is actually scheduled — no agent to install, nothing to
estimate.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_setup import log
from ..models import Node
from .engine import LOCAL_HOST, EngineError, engines
from .pool import pool


async def ensure_local_node(db: AsyncSession) -> Node:
    node = (await db.execute(select(Node).where(Node.is_local.is_(True)))).scalar_one_or_none()
    try:
        info = await engines.info(LOCAL_HOST)
    except EngineError as exc:
        log.error("local Docker engine unreachable", error=str(exc))
        if node:
            node.status = "down"
            node.last_error = str(exc)
            await db.commit()
            return node
        raise

    if node is None:
        node = Node(name="node-01", docker_host=LOCAL_HOST, is_local=True)
        db.add(node)

    node.cpus = info.cpus
    node.memory_bytes = info.memory_bytes
    node.arch = info.arch
    node.engine_version = info.engine_version
    node.status = "ready"
    node.last_error = None
    node.last_seen_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(node)
    return node


async def register_node(db: AsyncSession, *, name: str, docker_host: str, pool_name: str) -> Node:
    info = await engines.info(docker_host)
    node = Node(
        name=name,
        docker_host=docker_host,
        pool=pool_name,
        cpus=info.cpus,
        memory_bytes=info.memory_bytes,
        arch=info.arch,
        engine_version=info.engine_version,
        status="ready",
        is_local=False,
        last_seen_at=datetime.now(UTC),
    )
    db.add(node)
    await db.commit()
    await db.refresh(node)
    log.info("node registered", node=name, host=docker_host)
    return node


async def refresh_nodes(db: AsyncSession) -> list[Node]:
    nodes = (await db.execute(select(Node).order_by(Node.created_at))).scalars().all()
    for node in nodes:
        try:
            info = await engines.info(node.docker_host)
        except EngineError as exc:
            node.status = "down"
            node.last_error = str(exc)
            continue
        node.cpus = info.cpus
        node.memory_bytes = info.memory_bytes
        node.arch = info.arch
        node.engine_version = info.engine_version
        node.last_seen_at = datetime.now(UTC)
        node.last_error = None
        if node.status == "down":
            node.status = "ready"
    await db.commit()
    return list(nodes)


async def pick_node(db: AsyncSession, pool_name: str) -> Node:
    """Least-loaded schedulable node in the requested pool."""
    candidates = (
        (
            await db.execute(
                select(Node).where(
                    Node.pool == pool_name, Node.schedulable.is_(True), Node.status == "ready"
                )
            )
        )
        .scalars()
        .all()
    )
    if not candidates:
        candidates = (
            (
                await db.execute(
                    select(Node).where(Node.schedulable.is_(True), Node.status == "ready")
                )
            )
            .scalars()
            .all()
        )
    if not candidates:
        node = (await db.execute(select(Node).where(Node.is_local.is_(True)))).scalar_one_or_none()
        if node is None:
            raise RuntimeError("no node is available to schedule this function")
        return node

    load = allocation_by_node()
    return min(candidates, key=lambda n: load.get(n.name, {}).get("isolates", 0))


def allocation_by_node() -> dict[str, dict[str, float]]:
    """What the scheduler has actually placed, per node."""
    result: dict[str, dict[str, float]] = {}
    for isolate in pool.snapshot():
        entry = result.setdefault(
            isolate["node"], {"isolates": 0, "memory_mb": 0.0, "cpus": 0.0, "busy": 0}
        )
        entry["isolates"] += 1
        entry["memory_mb"] += isolate["memory_mb"]
        entry["cpus"] += isolate.get("cpus", 0.0)
        entry["busy"] += 1 if isolate["busy"] else 0
    return result


def format_spec(node: Node) -> str:
    gb = node.memory_bytes / 1024**3
    return f"{node.cpus} vCPU · {gb:.0f} GB · {node.arch}"
