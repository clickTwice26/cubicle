"""The key browser for a cluster's managed Redis.

The mirror of the database router next door: admin-only, and reaching exactly
one instance — the managed Redis belonging to the active cluster. Keys arrive as
query parameters rather than path segments because a Redis key routinely
contains slashes and colons, and a path would have to be double-encoded to
survive them.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..deps import CurrentCluster, DbSession, RequireAdmin
from ..logging_setup import log
from ..runtime import redisadmin, services

router = APIRouter(prefix="/api/services/redis/db", tags=["redis"])


class KeyRef(BaseModel):
    key: str = Field(min_length=1, max_length=8_000)


class EntryRef(KeyRef):
    field: str = Field(min_length=1, max_length=8_000)


class KeyWrite(KeyRef):
    value: str = Field(default="", max_length=512_000)
    field: str | None = Field(default=None, max_length=8_000)
    score: float | None = None
    ttl: int | None = None
    # Only consulted when the key does not exist yet.
    type: str | None = None


class TtlWrite(KeyRef):
    ttl: int = Field(ge=-1, le=10 * 365 * 24 * 3600)


class CommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=100_000)


async def _service(db, cluster):
    service = await services.get_service(db, cluster.id, "redis")
    if service is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"{cluster.name} has no Redis instance. Create one first.",
        )
    if service.status != "running":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The Redis instance is stopped. Start it first."
        )
    return service


def _fail(exc: redisadmin.RedisAdminError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("/overview")
async def overview(db: DbSession, cluster: CurrentCluster, _: RequireAdmin):
    service = await _service(db, cluster)
    try:
        return await redisadmin.overview(service)
    except redisadmin.RedisAdminError as exc:
        raise _fail(exc) from exc


@router.get("/keys")
async def scan_keys(
    db: DbSession,
    cluster: CurrentCluster,
    _: RequireAdmin,
    cursor: int = Query(0, ge=0),
    match: str | None = None,
    type: str | None = None,
    limit: int = Query(50, ge=1, le=redisadmin.MAX_PAGE),
):
    service = await _service(db, cluster)
    try:
        return await redisadmin.scan_keys(
            service, cursor=cursor, match=match, type_filter=type, limit=limit
        )
    except redisadmin.RedisAdminError as exc:
        raise _fail(exc) from exc


@router.get("/value")
async def read_key(
    db: DbSession,
    cluster: CurrentCluster,
    _: RequireAdmin,
    key: str = Query(min_length=1),
    cursor: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=redisadmin.MAX_PAGE),
):
    service = await _service(db, cluster)
    try:
        return await redisadmin.read_key(service, key, cursor=cursor, limit=limit)
    except redisadmin.RedisAdminError as exc:
        raise _fail(exc) from exc


@router.post("/value")
async def write_key(
    payload: KeyWrite, db: DbSession, cluster: CurrentCluster, principal: RequireAdmin
):
    service = await _service(db, cluster)
    try:
        result = await redisadmin.write_key(
            service,
            payload.key,
            value=payload.value,
            field=payload.field,
            score=payload.score,
            ttl=payload.ttl,
            type_hint=payload.type,
        )
    except redisadmin.RedisAdminError as exc:
        raise _fail(exc) from exc
    log.info("redis key written", cluster=cluster.slug, by=principal.user.email)
    return result


@router.post("/ttl")
async def set_ttl(
    payload: TtlWrite, db: DbSession, cluster: CurrentCluster, principal: RequireAdmin
):
    service = await _service(db, cluster)
    try:
        result = await redisadmin.set_ttl(service, payload.key, payload.ttl)
    except redisadmin.RedisAdminError as exc:
        raise _fail(exc) from exc
    log.info("redis ttl set", cluster=cluster.slug, ttl=payload.ttl, by=principal.user.email)
    return result


@router.post("/entries/delete")
async def delete_entry(
    payload: EntryRef, db: DbSession, cluster: CurrentCluster, principal: RequireAdmin
):
    service = await _service(db, cluster)
    try:
        result = await redisadmin.delete_entry(service, payload.key, payload.field)
    except redisadmin.RedisAdminError as exc:
        raise _fail(exc) from exc
    log.info("redis entry deleted", cluster=cluster.slug, by=principal.user.email)
    return result


@router.post("/keys/delete")
async def delete_key(
    payload: KeyRef, db: DbSession, cluster: CurrentCluster, principal: RequireAdmin
):
    service = await _service(db, cluster)
    try:
        result = await redisadmin.delete_key(service, payload.key)
    except redisadmin.RedisAdminError as exc:
        raise _fail(exc) from exc
    log.info("redis key deleted", cluster=cluster.slug, by=principal.user.email)
    return result


@router.post("/command")
async def run_command(
    payload: CommandRequest, db: DbSession, cluster: CurrentCluster, principal: RequireAdmin
):
    service = await _service(db, cluster)
    try:
        result = await redisadmin.run_command(service, payload.command)
    except redisadmin.RedisAdminError as exc:
        raise _fail(exc) from exc
    log.info("redis command run", cluster=cluster.slug, by=principal.user.email)
    return result
