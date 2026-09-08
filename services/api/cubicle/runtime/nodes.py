"""Node registry.

A node is a Docker engine Cubicle may schedule isolates onto. The engine this
control plane runs on registers itself on first boot; further engines are added
by URL from Settings. Capacity comes from the engine itself, and utilisation is
computed from what is actually scheduled — no agent to install, nothing to
estimate.
"""

from __future__ import annotations

from datetime import UTC, datetime

import docker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..logging_setup import log
from ..models import Cluster, Node
from .engine import LOCAL_HOST, EngineError, engines
from .pool import pool


async def ensure_local_node(db: AsyncSession, cluster: Cluster) -> Node:
    """Register the engine this control plane runs on against ``cluster``.

    Every cluster gets its own row for the same engine: they share hardware but
    schedule independently, and draining one must not drain the other.
    """
    node = (
        await db.execute(select(Node).where(Node.cluster_id == cluster.id, Node.is_local.is_(True)))
    ).scalar_one_or_none()
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
        node = Node(
            cluster_id=cluster.id,
            name="node-01",
            docker_host=LOCAL_HOST,
            pool=cluster.default_node_pool,
            is_local=True,
        )
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


async def register_node(
    db: AsyncSession, cluster: Cluster, *, name: str, docker_host: str, pool_name: str
) -> Node:
    info = await engines.info(docker_host)
    node = Node(
        cluster_id=cluster.id,
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


async def refresh_nodes(db: AsyncSession, cluster: Cluster) -> list[Node]:
    nodes = (
        (
            await db.execute(
                select(Node).where(Node.cluster_id == cluster.id).order_by(Node.created_at)
            )
        )
        .scalars()
        .all()
    )
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


async def pick_node(db: AsyncSession, cluster: Cluster, pool_name: str) -> Node:
    """Least-loaded schedulable node in the cluster's requested pool.

    Scheduling never crosses a cluster boundary, even when two clusters happen
    to sit on the same engine.
    """
    in_cluster = Node.cluster_id == cluster.id
    candidates = (
        (
            await db.execute(
                select(Node).where(
                    in_cluster,
                    Node.pool == pool_name,
                    Node.schedulable.is_(True),
                    Node.status == "ready",
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
                    select(Node).where(
                        in_cluster, Node.schedulable.is_(True), Node.status == "ready"
                    )
                )
            )
            .scalars()
            .all()
        )
    if not candidates:
        node = (
            await db.execute(select(Node).where(in_cluster, Node.is_local.is_(True)))
        ).scalar_one_or_none()
        if node is None:
            raise RuntimeError(f"cluster '{cluster.slug}' has no node to schedule onto")
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


# ── the address a DNS record should point at ─────────────────────────────────

#: Detected once per process. A machine's primary address does not change
#: without a restart of something more significant than this.
_ADDRESS_CACHE: dict[str, str] = {}

PRIVATE_PREFIXES = ("10.", "192.168.", "127.", "169.254.")


def is_private(address: str) -> bool:
    if address.startswith(PRIVATE_PREFIXES):
        return True
    if address.startswith("172."):
        second = address.split(".")[1] if address.count(".") >= 1 else "0"
        return second.isdigit() and 16 <= int(second) <= 31
    return False


async def public_address(host: str = LOCAL_HOST) -> str:
    """The IP a wildcard record for this instance should point at.

    Asked of the machine itself rather than of an address-reflecting service on
    the internet: a throwaway container on the host's own network stack, reading
    the source address the kernel would use to reach the internet. No packets
    are sent — connecting a UDP socket only picks a route — and nothing outside
    this machine is contacted, which is the point.

    Behind NAT this is the private address, which is the honest answer to "what
    is this machine's IP" and is labelled as such where it is shown.
    """
    if host in _ADDRESS_CACHE:
        return _ADDRESS_CACHE[host]

    probe = (
        "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);"
        "s.connect(('1.1.1.1',53));print(s.getsockname()[0])"
    )

    def _detect(client: docker.DockerClient) -> str:
        output = client.containers.run(
            f"cubicle/api:{settings.version}",
            command=["-c", probe],
            entrypoint=["python"],
            network_mode="host",
            remove=True,
            stdout=True,
            stderr=False,
        )
        return output.decode("utf-8", "replace").strip().splitlines()[-1].strip()

    try:
        address = await engines.call(host, _detect)
    except Exception as exc:  # noqa: BLE001 - the guide falls back to prose
        log.info("could not detect the host address", error=str(exc))
        return ""

    if address.count(".") != 3:
        return ""
    _ADDRESS_CACHE[host] = address
    return address
