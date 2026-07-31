"""Managed PostgreSQL and Redis."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from ..analytics import fmt_bytes
from ..deps import CurrentPrincipal, DbSession, RequireAdmin
from ..runtime import services
from ..schemas import ServiceCreate, ServiceOut

router = APIRouter(prefix="/api/services", tags=["services"])

DEFAULTS = {
    "postgres": {"versions": ["16.3", "15.6", "14.11"], "version": "16.3"},
    "redis": {"versions": ["7.2", "7.0", "6.2"], "version": "7.2"},
}


async def _describe(db, kind: str, *, reveal: bool = False) -> ServiceOut:
    service = await services.get_service(db, kind)
    if service is None:
        return ServiceOut(
            kind=kind,
            created=False,
            status="not_created",
            version=DEFAULTS[kind]["version"],
            config={},
        )

    state = await services.runtime_state(db, service)
    if state.running != (service.status == "running"):
        service.status = "running" if state.running else "stopped"
        await db.commit()

    stats = dict(state.stats)
    if kind == "postgres" and "size_bytes" in stats:
        stats["size_label"] = fmt_bytes(stats["size_bytes"])
    if kind == "redis" and "used_memory" in stats:
        stats["memory_label"] = fmt_bytes(stats["used_memory"])

    return ServiceOut(
        kind=kind,
        created=True,
        status=service.status,
        version=service.version,
        config=service.config or {},
        connection_url=services.connection_url(service, masked=not reveal)
        if state.running
        else None,
        node=service.node_name,
        stats=stats,
        last_error=service.last_error,
    )


@router.get("", response_model=list[ServiceOut])
async def list_services(db: DbSession, _: CurrentPrincipal):
    return [await _describe(db, "postgres"), await _describe(db, "redis")]


@router.get("/{kind}", response_model=ServiceOut)
async def get_service(kind: str, db: DbSession, _: CurrentPrincipal):
    _check(kind)
    return await _describe(db, kind)


@router.get("/{kind}/connection", response_model=ServiceOut)
async def reveal_connection(kind: str, db: DbSession, principal: CurrentPrincipal):
    _check(kind)
    if not principal.can("admin"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only admins can reveal connection credentials."
        )
    return await _describe(db, kind, reveal=True)


@router.post("/{kind}", response_model=ServiceOut, status_code=status.HTTP_201_CREATED)
async def create_service(kind: str, payload: ServiceCreate, db: DbSession, _: RequireAdmin):
    _check(kind)
    try:
        if kind == "postgres":
            await services.create_postgres(
                db,
                version=payload.version,
                memory=payload.memory,
                storage=payload.storage,
                pool_name=payload.node_pool,
            )
        else:
            await services.create_redis(
                db,
                version=payload.version,
                memory=payload.memory,
                eviction=payload.eviction or "allkeys-lru",
                pool_name=payload.node_pool,
            )
    except services.ServiceError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _describe(db, kind)


@router.post("/{kind}/start", response_model=ServiceOut)
async def start_service(kind: str, db: DbSession, _: RequireAdmin):
    return await _toggle(kind, db, True)


@router.post("/{kind}/stop", response_model=ServiceOut)
async def stop_service(kind: str, db: DbSession, _: RequireAdmin):
    return await _toggle(kind, db, False)


@router.delete("/{kind}", status_code=status.HTTP_204_NO_CONTENT)
async def destroy_service(
    kind: str, db: DbSession, _: RequireAdmin, keep_data: bool = False
) -> Response:
    _check(kind)
    service = await services.get_service(db, kind)
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That service does not exist.")
    await services.destroy(db, service, keep_data=keep_data)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _toggle(kind: str, db, running: bool) -> ServiceOut:
    _check(kind)
    service = await services.get_service(db, kind)
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That service does not exist.")
    try:
        await services.set_running(db, service, running)
    except services.ServiceError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _describe(db, kind)


def _check(kind: str) -> None:
    if kind not in DEFAULTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown service.")
