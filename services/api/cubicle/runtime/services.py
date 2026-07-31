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

from ..config import settings
from ..crypto import decrypt, encrypt
from ..logging_setup import log
from ..models import ManagedService, Node
from .engine import LOCAL_HOST, engines

POSTGRES_IMAGES = {
    "16.3": "postgres:16.3-alpine",
    "15.6": "postgres:15.6-alpine",
    "14.11": "postgres:14.11-alpine",
}
REDIS_IMAGES = {"7.2": "redis:7.2-alpine", "7.0": "redis:7.0-alpine", "6.2": "redis:6.2-alpine"}

PG_CONTAINER = "cubicle-svc-postgres"
REDIS_CONTAINER = "cubicle-svc-redis"
PG_VOLUME = "cubicle-svc-postgres-data"
REDIS_VOLUME = "cubicle-svc-redis-data"

MEMORY_BYTES = {
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


async def _node_for(db: AsyncSession, pool_name: str) -> Node:
    node = (
        await db.execute(
            select(Node).where(Node.pool == pool_name, Node.schedulable.is_(True)).limit(1)
        )
    ).scalar_one_or_none()
    if node is None:
        node = (
            await db.execute(select(Node).where(Node.schedulable.is_(True)).limit(1))
        ).scalar_one_or_none()
    if node is None:
        raise ServiceError("no schedulable node available")
    return node


async def get_service(db: AsyncSession, kind: str) -> ManagedService | None:
    return (
        await db.execute(select(ManagedService).where(ManagedService.kind == kind))
    ).scalar_one_or_none()


# ── provisioning ─────────────────────────────────────────────────────────────


async def create_postgres(
    db: AsyncSession, *, version: str, memory: str, storage: str, pool_name: str
) -> ManagedService:
    if version not in POSTGRES_IMAGES:
        raise ServiceError(f"unsupported PostgreSQL version {version}")
    existing = await get_service(db, "postgres")
    if existing:
        raise ServiceError("a PostgreSQL instance already exists")

    node = await _node_for(db, pool_name)
    password = secrets.token_urlsafe(24)
    await engines.ensure_network(node.docker_host, settings.function_network)

    def _create(client: docker.DockerClient) -> str:
        _remove_container(client, PG_CONTAINER)
        client.volumes.create(name=PG_VOLUME, labels={"cubicle.role": "service-volume"})
        container = client.containers.run(
            POSTGRES_IMAGES[version],
            name=PG_CONTAINER,
            detach=True,
            labels={"cubicle.role": "service", "cubicle.service": "postgres"},
            environment={
                "POSTGRES_USER": "cubicle",
                "POSTGRES_PASSWORD": password,
                "POSTGRES_DB": "cubicle",
                "PGDATA": "/var/lib/postgresql/data/pgdata",
            },
            volumes={PG_VOLUME: {"bind": "/var/lib/postgresql/data", "mode": "rw"}},
            network=settings.function_network,
            mem_limit=_memory_arg(memory),
            restart_policy={"Name": "unless-stopped"},
        )
        return container.id

    container_id = await engines.call(node.docker_host, _create)

    service = ManagedService(
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
        container_name=PG_CONTAINER,
        volume_name=PG_VOLUME,
        node_name=node.name,
        password_ciphertext=encrypt(password, aad="service:postgres"),
    )
    db.add(service)
    await db.commit()
    await db.refresh(service)
    log.info("provisioned managed postgres", version=version, node=node.name)
    return service


async def create_redis(
    db: AsyncSession, *, version: str, memory: str, eviction: str, pool_name: str
) -> ManagedService:
    if version not in REDIS_IMAGES:
        raise ServiceError(f"unsupported Redis version {version}")
    if await get_service(db, "redis"):
        raise ServiceError("a Redis instance already exists")

    node = await _node_for(db, pool_name)
    password = secrets.token_urlsafe(24)
    max_memory = _memory_arg(memory)
    await engines.ensure_network(node.docker_host, settings.function_network)

    def _create(client: docker.DockerClient) -> str:
        _remove_container(client, REDIS_CONTAINER)
        client.volumes.create(name=REDIS_VOLUME, labels={"cubicle.role": "service-volume"})
        container = client.containers.run(
            REDIS_IMAGES[version],
            name=REDIS_CONTAINER,
            detach=True,
            labels={"cubicle.role": "service", "cubicle.service": "redis"},
            command=[
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
            volumes={REDIS_VOLUME: {"bind": "/data", "mode": "rw"}},
            network=settings.function_network,
            mem_limit=int(max_memory * 1.3),
            restart_policy={"Name": "unless-stopped"},
        )
        return container.id

    container_id = await engines.call(node.docker_host, _create)

    service = ManagedService(
        kind="redis",
        version=version,
        status="running",
        config={"memory": memory, "eviction": eviction, "node_pool": pool_name},
        container_id=container_id,
        container_name=REDIS_CONTAINER,
        volume_name=REDIS_VOLUME,
        node_name=node.name,
        password_ciphertext=encrypt(password, aad="service:redis"),
    )
    db.add(service)
    await db.commit()
    await db.refresh(service)
    log.info("provisioned managed redis", version=version, node=node.name)
    return service


async def set_running(db: AsyncSession, service: ManagedService, running: bool) -> ManagedService:
    node = (
        await db.execute(select(Node).where(Node.name == service.node_name))
    ).scalar_one_or_none()
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
    node = (
        await db.execute(select(Node).where(Node.name == service.node_name))
    ).scalar_one_or_none()
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
    node = (
        await db.execute(select(Node).where(Node.name == service.node_name))
    ).scalar_one_or_none()
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
    if service.kind == "postgres":
        return f"postgres://cubicle:{password}@{PG_CONTAINER}:5432/cubicle"
    return f"redis://:{password}@{REDIS_CONTAINER}:6379/0"


async def connection_urls(db: AsyncSession) -> dict[str, str]:
    """URLs handed to isolates so ``cubicle_db`` can connect with no config."""
    urls: dict[str, str] = {}
    for kind in ("postgres", "redis"):
        service = await get_service(db, kind)
        if service and service.status == "running":
            urls[kind] = connection_url(service)
    return urls


async def _postgres_stats(service: ManagedService) -> dict[str, Any]:
    try:
        conn = await asyncpg.connect(
            host=PG_CONTAINER,
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
        f"redis://:{password_for(service)}@{REDIS_CONTAINER}:6379/0",
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
