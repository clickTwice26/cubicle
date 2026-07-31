"""The database management surface for a cluster's managed PostgreSQL.

Everything here is admin-only and reaches exactly one database: the managed
instance belonging to the active cluster. The control plane's own database is
not addressable from this router at all.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..deps import CurrentCluster, DbSession, RequireAdmin
from ..logging_setup import log
from ..runtime import dbadmin, services

router = APIRouter(prefix="/api/services/postgres/db", tags=["database"])


class RowKey(BaseModel):
    key: dict[str, Any] = Field(default_factory=dict)


class RowWrite(RowKey):
    values: dict[str, Any] = Field(default_factory=dict)


class QueryRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=200_000)


async def _service(db, cluster):
    service = await services.get_service(db, cluster.id, "postgres")
    if service is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"{cluster.name} has no PostgreSQL instance. Create one first.",
        )
    if service.status != "running":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The PostgreSQL instance is stopped. Start it first."
        )
    return service


def _fail(exc: dbadmin.DatabaseError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("/overview")
async def overview(db: DbSession, cluster: CurrentCluster, _: RequireAdmin):
    service = await _service(db, cluster)
    try:
        return await dbadmin.overview(service)
    except dbadmin.DatabaseError as exc:
        raise _fail(exc) from exc


@router.get("/tables")
async def list_tables(
    db: DbSession,
    cluster: CurrentCluster,
    _: RequireAdmin,
    include_system: bool = False,
):
    service = await _service(db, cluster)
    try:
        return await dbadmin.list_tables(service, include_system=include_system)
    except dbadmin.DatabaseError as exc:
        raise _fail(exc) from exc


@router.get("/tables/{schema}/{table}")
async def browse_table(
    schema: str,
    table: str,
    db: DbSession,
    cluster: CurrentCluster,
    _: RequireAdmin,
    limit: int = Query(50, ge=1, le=dbadmin.MAX_PAGE),
    offset: int = Query(0, ge=0),
    order_by: str | None = None,
    descending: bool = False,
    search: str | None = None,
):
    service = await _service(db, cluster)
    try:
        return await dbadmin.browse(
            service,
            schema,
            table,
            limit=limit,
            offset=offset,
            order_by=order_by,
            descending=descending,
            search=search,
        )
    except dbadmin.DatabaseError as exc:
        raise _fail(exc) from exc


@router.get("/tables/{schema}/{table}/structure")
async def table_structure(
    schema: str, table: str, db: DbSession, cluster: CurrentCluster, _: RequireAdmin
):
    service = await _service(db, cluster)
    try:
        return await dbadmin.describe(service, schema, table)
    except dbadmin.DatabaseError as exc:
        raise _fail(exc) from exc


@router.post("/tables/{schema}/{table}/rows", status_code=status.HTTP_201_CREATED)
async def insert_row(
    schema: str,
    table: str,
    payload: RowWrite,
    db: DbSession,
    cluster: CurrentCluster,
    principal: RequireAdmin,
):
    service = await _service(db, cluster)
    try:
        row = await dbadmin.insert_row(service, schema, table, payload.values)
    except dbadmin.DatabaseError as exc:
        raise _fail(exc) from exc
    log.info(
        "database row inserted",
        cluster=cluster.slug,
        table=f"{schema}.{table}",
        by=principal.user.email,
    )
    return row


@router.patch("/tables/{schema}/{table}/rows")
async def update_row(
    schema: str,
    table: str,
    payload: RowWrite,
    db: DbSession,
    cluster: CurrentCluster,
    principal: RequireAdmin,
):
    service = await _service(db, cluster)
    try:
        row = await dbadmin.update_row(service, schema, table, payload.key, payload.values)
    except dbadmin.DatabaseError as exc:
        raise _fail(exc) from exc
    log.info(
        "database row updated",
        cluster=cluster.slug,
        table=f"{schema}.{table}",
        by=principal.user.email,
    )
    return row


@router.post("/tables/{schema}/{table}/rows/delete")
async def delete_row(
    schema: str,
    table: str,
    payload: RowKey,
    db: DbSession,
    cluster: CurrentCluster,
    principal: RequireAdmin,
):
    service = await _service(db, cluster)
    try:
        deleted = await dbadmin.delete_row(service, schema, table, payload.key)
    except dbadmin.DatabaseError as exc:
        raise _fail(exc) from exc
    log.info(
        "database row deleted",
        cluster=cluster.slug,
        table=f"{schema}.{table}",
        by=principal.user.email,
    )
    return {"deleted": deleted}


@router.post("/query")
async def run_query(
    payload: QueryRequest, db: DbSession, cluster: CurrentCluster, principal: RequireAdmin
):
    service = await _service(db, cluster)
    try:
        result = await dbadmin.run_query(service, payload.sql)
    except dbadmin.DatabaseError as exc:
        raise _fail(exc) from exc
    log.info(
        "database query run",
        cluster=cluster.slug,
        kind=result["kind"],
        rows=result["row_count"],
        by=principal.user.email,
    )
    return result
