"""Managed data services.

PostgreSQL and Redis run as ordinary containers on the same cluster as the
isolates, on the function network, so a handler reaches them by name with no
credentials to copy around. Nothing is provisioned until the operator creates
it from the console — an untouched instance runs neither.
"""

from __future__ import annotations

import contextlib
import secrets
from dataclasses import dataclass
from typing import Any

import asyncpg
import docker
import redis.asyncio as aioredis
from docker.errors import DockerException, NotFound
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import clusters as cluster_svc
from ..config import settings
from ..crypto import decrypt, encrypt
from ..logging_setup import log
from ..models import Cluster, ManagedService, Node
from .engine import LOCAL_HOST, engines

POSTGRES_IMAGES = {
    "16.3": "postgres:16.3-alpine",
    "15.6": "postgres:15.6-alpine",
    "14.11": "postgres:14.11-alpine",
}
REDIS_IMAGES = {"7.2": "redis:7.2-alpine", "7.0": "redis:7.0-alpine", "6.2": "redis:6.2-alpine"}

# Base names. Every cluster after the first suffixes them with its slug, so a
# staging Postgres and a production Postgres coexist on one engine.
PG_CONTAINER = "cubicle-svc-postgres"
REDIS_CONTAINER = "cubicle-svc-redis"
PG_VOLUME = "cubicle-svc-postgres-data"
REDIS_VOLUME = "cubicle-svc-redis-data"


def _names(cluster: Cluster, kind: str) -> tuple[str, str]:
    """``(container, volume)`` for this cluster's instance of ``kind``.

    The default cluster keeps the unsuffixed names an existing install already
    has running, so upgrading to multi-cluster does not orphan its databases.
    """
    container = PG_CONTAINER if kind == "postgres" else REDIS_CONTAINER
    volume = PG_VOLUME if kind == "postgres" else REDIS_VOLUME
    if cluster.is_default:
        return container, volume
    suffix = cluster_svc.resource_suffix(cluster)
    return f"{container}-{suffix}", f"{volume}-{suffix}"


MEMORY_BYTES = {
    "32 MB": 32 * 1024**2,
    "64 MB": 64 * 1024**2,
    "128 MB": 128 * 1024**2,
    "256 MB": 256 * 1024**2,
    "512 MB": 512 * 1024**2,
    "1 GB": 1024**3,
    "2 GB": 2 * 1024**3,
    "4 GB": 4 * 1024**3,
}


class ServiceError(RuntimeError):
    pass


@dataclass(slots=True)
class ServiceRuntime:
    running: bool
    container_id: str | None
    stats: dict[str, Any]


def _memory_arg(label: str) -> int:
    return MEMORY_BYTES.get(label, 1024**3)


def _postgres_tuning(memory_bytes: int) -> list[str]:
    """Postgres sized to the memory it was given.

    Stock Postgres asks for 128 MB of shared buffers and room for 100 backends,
    which is why an untuned container under about 256 MB is killed during
    ``initdb`` rather than starting. Scaling the four settings that actually
    allocate — the buffer pool, the per-sort workspace, the maintenance
    workspace and the connection ceiling — is what makes a 128 MB instance a
    working database instead of a checkbox.
    """
    mb = memory_bytes // 1024**2
    shared = max(16, mb // 4)
    connections = (
        20 if mb <= 128 else 30 if mb <= 256 else 50 if mb <= 512 else 75 if mb <= 1024 else 100
    )
    # Parallel query costs a worker's memory per gather, which a small instance
    # does not have to spare and would not benefit from anyway.
    parallel = 0 if mb <= 256 else 2
    return [
        "postgres",
        "-c",
        f"shared_buffers={shared}MB",
        "-c",
        f"effective_cache_size={max(32, mb // 2)}MB",
        "-c",
        f"maintenance_work_mem={min(256, max(8, mb // 8))}MB",
        "-c",
        f"work_mem={min(16, max(1, mb // 128))}MB",
        "-c",
        f"max_connections={connections}",
        "-c",
        f"max_parallel_workers_per_gather={parallel}",
        "-c",
        f"max_worker_processes={max(2, parallel * 2)}",
    ]


def _postgres_spec(
    *,
    image: str,
    container_name: str,
    volume_name: str,
    cluster_slug: str,
    password: str,
    memory: str,
) -> dict:
    memory_bytes = _memory_arg(memory)
    return {
        "image": image,
        "name": container_name,
        "detach": True,
        "labels": _labels("postgres", cluster_slug),
        "command": _postgres_tuning(memory_bytes),
        "environment": {
            "POSTGRES_USER": "cubicle",
            "POSTGRES_PASSWORD": password,
            "POSTGRES_DB": "cubicle",
            "PGDATA": "/var/lib/postgresql/data/pgdata",
        },
        "volumes": {volume_name: {"bind": "/var/lib/postgresql/data", "mode": "rw"}},
        "network": settings.function_network,
        "mem_limit": memory_bytes,
        # /dev/shm is where parallel workers meet. Docker's 64 MB default is
        # plenty for the small tiers, which do not run them at all.
        "shm_size": max(64 * 1024**2, min(memory_bytes // 4, 256 * 1024**2)),
        "restart_policy": {"Name": "unless-stopped"},
    }


def _redis_spec(
    *,
    image: str,
    container_name: str,
    volume_name: str,
    cluster_slug: str,
    password: str,
    memory: str,
    eviction: str,
) -> dict:
    max_memory = _memory_arg(memory)
    return {
        "image": image,
        "name": container_name,
        "detach": True,
        "labels": _labels("redis", cluster_slug),
        "command": [
            "redis-server",
            "--requirepass",
            password,
            "--maxmemory",
            str(max_memory),
            "--maxmemory-policy",
            eviction,
            "--appendonly",
            "yes",
        ],
        "volumes": {volume_name: {"bind": "/data", "mode": "rw"}},
        "network": settings.function_network,
        # Headroom over the data itself for the fork an AOF rewrite makes. The
        # floor keeps the smallest tiers above Redis' own ~10 MB baseline.
        "mem_limit": max(int(max_memory * 1.3), 64 * 1024**2),
        "restart_policy": {"Name": "unless-stopped"},
    }


def _labels(kind: str, cluster_slug: str) -> dict[str, str]:
    return {"cubicle.role": "service", "cubicle.service": kind, "cubicle.cluster": cluster_slug}


def _spec_for(service: ManagedService, cluster: Cluster) -> dict:
    """Rebuild the run arguments for a service that already exists."""
    config = service.config or {}
    password = password_for(service)
    if service.kind == "postgres":
        return _postgres_spec(
            image=POSTGRES_IMAGES[service.version],
            container_name=service.container_name,
            volume_name=service.volume_name,
            cluster_slug=cluster.slug,
            password=password,
            memory=config.get("memory", "1 GB"),
        )
    return _redis_spec(
        image=REDIS_IMAGES[service.version],
        container_name=service.container_name,
        volume_name=service.volume_name,
        cluster_slug=cluster.slug,
        password=password,
        memory=config.get("memory", "512 MB"),
        eviction=config.get("eviction", "allkeys-lru"),
    )


async def recreate(db: AsyncSession, service: ManagedService, cluster: Cluster) -> ManagedService:
    """Replace the container, keeping the volume and the stored credentials.

    Used when the running container has drifted from what the control plane
    would create today — different labels, different limits, an older image
    tag. The data is in the volume, and the volume is never touched, so this
    costs a restart and nothing else.
    """
    node = await _service_node(db, service)
    host = node.docker_host if node else LOCAL_HOST
    spec = _spec_for(service, cluster)
    volume = service.volume_name
    name = service.container_name
    # A service the operator stopped stays stopped — recreating is a repair,
    # not a start.
    was_running = service.status == "running"

    def _replace(client: docker.DockerClient) -> str:
        # The volume has to survive, so it is created only if absent and the
        # container is removed without it.
        try:
            client.volumes.get(volume)
        except NotFound:
            client.volumes.create(name=volume, labels={"cubicle.role": "service-volume"})
        _remove_container(client, name)
        container = client.containers.run(**spec)
        if not was_running:
            container.stop(timeout=20)
        return container.id

    try:
        container_id = await engines.call(host, _replace)
    except DockerException as exc:
        service.last_error = str(exc)
        await db.commit()
        raise ServiceError(f"could not recreate the container: {exc}") from exc

    service.container_id = container_id
    service.status = "running" if was_running else "stopped"
    service.last_error = None
    await db.commit()
    await db.refresh(service)
    log.info("service container recreated", kind=service.kind, cluster=cluster.slug, volume=volume)
    return service


async def _node_for(db: AsyncSession, cluster: Cluster, pool_name: str) -> Node:
    in_cluster = Node.cluster_id == cluster.id
    node = (
        await db.execute(
            select(Node)
            .where(in_cluster, Node.pool == pool_name, Node.schedulable.is_(True))
            .limit(1)
        )
    ).scalar_one_or_none()
    if node is None:
        node = (
            await db.execute(select(Node).where(in_cluster, Node.schedulable.is_(True)).limit(1))
        ).scalar_one_or_none()
    if node is None:
        raise ServiceError(f"cluster '{cluster.slug}' has no schedulable node")
    return node


async def _service_node(db: AsyncSession, service: ManagedService) -> Node | None:
    """The node this service runs on.

    Scoped by cluster because node names repeat across clusters — every cluster
    has its own ``node-01``, and picking the wrong one would talk to the wrong
    engine.
    """
    return (
        await db.execute(
            select(Node).where(
                Node.cluster_id == service.cluster_id, Node.name == service.node_name
            )
        )
    ).scalar_one_or_none()


async def get_service(db: AsyncSession, cluster_id, kind: str) -> ManagedService | None:
    return (
        await db.execute(
            select(ManagedService).where(
                ManagedService.cluster_id == cluster_id, ManagedService.kind == kind
            )
        )
    ).scalar_one_or_none()


# ── provisioning ─────────────────────────────────────────────────────────────


async def create_postgres(
    db: AsyncSession, cluster: Cluster, *, version: str, memory: str, storage: str, pool_name: str
) -> ManagedService:
    if version not in POSTGRES_IMAGES:
        raise ServiceError(f"unsupported PostgreSQL version {version}")
    if await get_service(db, cluster.id, "postgres"):
        raise ServiceError("this cluster already has a PostgreSQL instance")

    container_name, volume_name = _names(cluster, "postgres")
    node = await _node_for(db, cluster, pool_name)
    password = secrets.token_urlsafe(24)
    await engines.ensure_network(node.docker_host, settings.function_network)

    spec = _postgres_spec(
        image=POSTGRES_IMAGES[version],
        container_name=container_name,
        volume_name=volume_name,
        cluster_slug=cluster.slug,
        password=password,
        memory=memory,
    )

    def _create(client: docker.DockerClient) -> str:
        _remove_container(client, container_name)
        client.volumes.create(name=volume_name, labels={"cubicle.role": "service-volume"})
        return client.containers.run(**spec).id

    container_id = await engines.call(node.docker_host, _create)

    service = ManagedService(
        cluster_id=cluster.id,
        kind="postgres",
        version=version,
        status="running",
        config={
            "memory": memory,
            "storage": storage,
            "node_pool": pool_name,
            "database": "cubicle",
            "user": "cubicle",
        },
        container_id=container_id,
        container_name=container_name,
        volume_name=volume_name,
        node_name=node.name,
        password_ciphertext=encrypt(password, aad="service:postgres"),
    )
    db.add(service)
    await db.commit()
    await db.refresh(service)
    log.info("provisioned managed postgres", version=version, node=node.name, cluster=cluster.slug)
    return service


async def create_redis(
    db: AsyncSession, cluster: Cluster, *, version: str, memory: str, eviction: str, pool_name: str
) -> ManagedService:
    if version not in REDIS_IMAGES:
        raise ServiceError(f"unsupported Redis version {version}")
    if await get_service(db, cluster.id, "redis"):
        raise ServiceError("this cluster already has a Redis instance")

    container_name, volume_name = _names(cluster, "redis")
    node = await _node_for(db, cluster, pool_name)
    password = secrets.token_urlsafe(24)
    await engines.ensure_network(node.docker_host, settings.function_network)

    spec = _redis_spec(
        image=REDIS_IMAGES[version],
        container_name=container_name,
        volume_name=volume_name,
        cluster_slug=cluster.slug,
        password=password,
        memory=memory,
        eviction=eviction,
    )

    def _create(client: docker.DockerClient) -> str:
        _remove_container(client, container_name)
        client.volumes.create(name=volume_name, labels={"cubicle.role": "service-volume"})
        return client.containers.run(**spec).id

    container_id = await engines.call(node.docker_host, _create)

    service = ManagedService(
        cluster_id=cluster.id,
        kind="redis",
        version=version,
        status="running",
        config={"memory": memory, "eviction": eviction, "node_pool": pool_name},
        container_id=container_id,
        container_name=container_name,
        volume_name=volume_name,
        node_name=node.name,
        password_ciphertext=encrypt(password, aad="service:redis"),
    )
    db.add(service)
    await db.commit()
    await db.refresh(service)
    log.info("provisioned managed redis", version=version, node=node.name, cluster=cluster.slug)
    return service


async def set_running(db: AsyncSession, service: ManagedService, running: bool) -> ManagedService:
    node = await _service_node(db, service)
    host = node.docker_host if node else LOCAL_HOST

    def _toggle(client: docker.DockerClient) -> None:
        try:
            container = client.containers.get(service.container_name)
        except NotFound as exc:
            raise ServiceError("the container backing this service is gone") from exc
        if running:
            container.start()
        else:
            container.stop(timeout=20)

    await engines.call(host, _toggle)
    service.status = "running" if running else "stopped"
    service.last_error = None
    await db.commit()
    await db.refresh(service)
    return service


async def destroy(db: AsyncSession, service: ManagedService, *, keep_data: bool = False) -> None:
    node = await _service_node(db, service)
    host = node.docker_host if node else LOCAL_HOST
    volume = service.volume_name

    def _destroy(client: docker.DockerClient) -> None:
        _remove_container(client, service.container_name)
        if not keep_data and volume:
            with contextlib.suppress(NotFound, DockerException):
                client.volumes.get(volume).remove(force=True)

    await engines.call(host, _destroy)
    await db.delete(service)
    await db.commit()
    log.info("destroyed managed service", kind=service.kind, keep_data=keep_data)


def _remove_container(client: docker.DockerClient, name: str) -> None:
    with contextlib.suppress(NotFound, DockerException):
        client.containers.get(name).remove(force=True)


# ── runtime state ────────────────────────────────────────────────────────────


async def runtime_state(db: AsyncSession, service: ManagedService) -> ServiceRuntime:
    node = await _service_node(db, service)
    host = node.docker_host if node else LOCAL_HOST

    def _inspect(client: docker.DockerClient) -> tuple[bool, str | None]:
        try:
            container = client.containers.get(service.container_name)
        except NotFound:
            return False, None
        return container.status == "running", container.id

    try:
        running, container_id = await engines.call(host, _inspect)
    except Exception as exc:  # noqa: BLE001 - a node may be unreachable
        return ServiceRuntime(False, None, {"error": str(exc)})

    stats: dict[str, Any] = {}
    if running:
        stats = (
            await _postgres_stats(service)
            if service.kind == "postgres"
            else await _redis_stats(service)
        )
    return ServiceRuntime(running, container_id, stats)


def password_for(service: ManagedService) -> str:
    if not service.password_ciphertext:
        return ""
    return decrypt(service.password_ciphertext, aad=f"service:{service.kind}")


def connection_url(service: ManagedService, *, masked: bool = False) -> str:
    password = "••••••" if masked else password_for(service)
    host = service.container_name
    if service.kind == "postgres":
        return f"postgres://cubicle:{password}@{host}:5432/cubicle"
    return f"redis://:{password}@{host}:6379/0"


async def connection_urls(db: AsyncSession, cluster_id) -> dict[str, str]:
    """URLs handed to this cluster's isolates so ``cubicle_db`` needs no config."""
    urls: dict[str, str] = {}
    for kind in ("postgres", "redis"):
        service = await get_service(db, cluster_id, kind)
        if service and service.status == "running":
            urls[kind] = connection_url(service)
    return urls


async def _postgres_stats(service: ManagedService) -> dict[str, Any]:
    try:
        conn = await asyncpg.connect(
            host=service.container_name,
            port=5432,
            user="cubicle",
            password=password_for(service),
            database="cubicle",
            timeout=4,
        )
    except Exception as exc:  # noqa: BLE001 - reported in the console
        return {"error": str(exc)}
    try:
        size = await conn.fetchval("SELECT pg_database_size(current_database())")
        connections = await conn.fetchval("SELECT count(*) FROM pg_stat_activity")
        max_conns = await conn.fetchval("SHOW max_connections")
        tables = await conn.fetchval(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
        )
        return {
            "size_bytes": int(size or 0),
            "connections": int(connections or 0),
            "max_connections": int(max_conns or 100),
            "tables": int(tables or 0),
        }
    finally:
        await conn.close()


async def _redis_stats(service: ManagedService) -> dict[str, Any]:
    client = aioredis.from_url(
        f"redis://:{password_for(service)}@{service.container_name}:6379/0",
        decode_responses=True,
        socket_timeout=4,
    )
    try:
        info = await client.info("memory")
        keys = await client.dbsize()
        return {
            "used_memory": int(info.get("used_memory", 0)),
            "max_memory": int(info.get("maxmemory", 0)),
            "keys": int(keys),
        }
    except Exception as exc:  # noqa: BLE001 - reported in the console
        return {"error": str(exc)}
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()
