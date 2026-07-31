"""Browsing and editing a managed PostgreSQL instance.

The console needs to show and change real rows, which means building SQL around
identifiers the caller supplied. Identifiers cannot be bound as parameters, so
every schema, table and column name here is checked against what the database
actually reports before it is quoted into a statement — an allowlist drawn from
``information_schema``, not an escaping routine. Values are always bound.

Only the cluster's own managed instance is reachable from here. The control
plane's database is never exposed.
"""

from __future__ import annotations

import datetime
import decimal
import ipaddress
import time
import uuid
from dataclasses import dataclass
from typing import Any

import asyncpg

from ..logging_setup import log
from ..models import ManagedService
from .services import password_for

# A browse page is capped so a wide table cannot flood the console, and a query
# is capped so a careless SELECT cannot pull the whole database into memory.
MAX_PAGE = 200
MAX_QUERY_ROWS = 500
STATEMENT_TIMEOUT_MS = 15_000
CONNECT_TIMEOUT = 5

# Postgres' own bookkeeping. Hidden by default: showing 60 catalog tables above
# the two the operator created is not a useful default.
SYSTEM_SCHEMAS = ("pg_catalog", "information_schema", "pg_toast")


class DatabaseError(RuntimeError):
    """Something the operator should read: a bad identifier, or Postgres saying no."""


@dataclass(slots=True)
class Column:
    name: str
    data_type: str
    nullable: bool
    default: str | None
    is_primary_key: bool
    position: int


async def _connect(service: ManagedService) -> asyncpg.Connection:
    try:
        conn = await asyncpg.connect(
            host=service.container_name,
            port=5432,
            user=(service.config or {}).get("user", "cubicle"),
            password=password_for(service),
            database=(service.config or {}).get("database", "cubicle"),
            timeout=CONNECT_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the console verbatim
        raise DatabaseError(f"could not connect to the database: {exc}") from exc
    await conn.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")
    return conn


def _jsonable(value: Any) -> Any:
    """Coerce a Postgres value into something JSON can carry."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, decimal.Decimal):
        # Round-trips exactly, unlike float.
        return str(value)
    if isinstance(value, datetime.datetime | datetime.date | datetime.time):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return f"\\x{bytes(value).hex()}"
    if isinstance(value, ipaddress.IPv4Address | ipaddress.IPv6Address):
        return str(value)
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def _quote(identifier: str) -> str:
    """Quote an identifier that has already been checked against the catalog."""
    return '"' + identifier.replace('"', '""') + '"'


# ── introspection ────────────────────────────────────────────────────────────


async def list_tables(service: ManagedService, *, include_system: bool = False) -> list[dict]:
    conn = await _connect(service)
    try:
        rows = await conn.fetch(
            """
            SELECT n.nspname                                    AS schema,
                   c.relname                                    AS name,
                   c.relkind::text                              AS kind,
                   GREATEST(c.reltuples, 0)::bigint             AS estimate,
                   pg_total_relation_size(c.oid)                AS size_bytes,
                   EXISTS (
                       SELECT 1 FROM pg_index i
                       WHERE i.indrelid = c.oid AND i.indisprimary
                   )                                            AS has_pk
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'p', 'v', 'm')
              AND ($1 OR n.nspname <> ALL($2::text[]))
            ORDER BY n.nspname, c.relname
            """,
            include_system,
            list(SYSTEM_SCHEMAS),
        )
        return [
            {
                "schema": r["schema"],
                "name": r["name"],
                "kind": {"r": "table", "p": "table", "v": "view", "m": "view"}[r["kind"]],
                "estimated_rows": int(r["estimate"]),
                "size_bytes": int(r["size_bytes"]),
                "editable": r["has_pk"] and r["kind"] in ("r", "p"),
            }
            for r in rows
        ]
    finally:
        await conn.close()


async def _columns(conn: asyncpg.Connection, schema: str, table: str) -> list[Column]:
    rows = await conn.fetch(
        """
        SELECT a.attname                                        AS name,
               format_type(a.atttypid, a.atttypmod)             AS data_type,
               NOT a.attnotnull                                 AS nullable,
               pg_get_expr(d.adbin, d.adrelid)                  AS default,
               COALESCE(pk.is_pk, false)                        AS is_pk,
               a.attnum                                         AS position
        FROM pg_attribute a
        JOIN pg_class c      ON c.oid = a.attrelid
        JOIN pg_namespace n  ON n.oid = c.relnamespace
        LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
        LEFT JOIN LATERAL (
            SELECT true AS is_pk
            FROM pg_index i
            WHERE i.indrelid = c.oid AND i.indisprimary AND a.attnum = ANY(i.indkey)
        ) pk ON true
        WHERE n.nspname = $1 AND c.relname = $2
          AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        schema,
        table,
    )
    if not rows:
        raise DatabaseError(f'no table "{schema}"."{table}" in this database')
    return [
        Column(
            name=r["name"],
            data_type=r["data_type"],
            nullable=r["nullable"],
            default=r["default"],
            is_primary_key=r["is_pk"],
            position=r["position"],
        )
        for r in rows
    ]


async def describe(service: ManagedService, schema: str, table: str) -> dict:
    conn = await _connect(service)
    try:
        columns = await _columns(conn, schema, table)
        indexes = await conn.fetch(
            """
            SELECT i.relname AS name, pg_get_indexdef(x.indexrelid) AS definition,
                   x.indisprimary AS primary, x.indisunique AS unique
            FROM pg_index x
            JOIN pg_class c ON c.oid = x.indrelid
            JOIN pg_class i ON i.oid = x.indexrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = $1 AND c.relname = $2
            ORDER BY x.indisprimary DESC, i.relname
            """,
            schema,
            table,
        )
        return {
            "schema": schema,
            "table": table,
            "columns": [
                {
                    "name": c.name,
                    "data_type": c.data_type,
                    "nullable": c.nullable,
                    "default": c.default,
                    "is_primary_key": c.is_primary_key,
                }
                for c in columns
            ],
            "primary_key": [c.name for c in columns if c.is_primary_key],
            "indexes": [
                {
                    "name": i["name"],
                    "definition": i["definition"],
                    "primary": i["primary"],
                    "unique": i["unique"],
                }
                for i in indexes
            ],
        }
    finally:
        await conn.close()


# ── browsing ─────────────────────────────────────────────────────────────────


async def browse(
    service: ManagedService,
    schema: str,
    table: str,
    *,
    limit: int = 50,
    offset: int = 0,
    order_by: str | None = None,
    descending: bool = False,
    search: str | None = None,
) -> dict:
    limit = max(1, min(limit, MAX_PAGE))
    conn = await _connect(service)
    try:
        columns = await _columns(conn, schema, table)
        names = {c.name for c in columns}
        qualified = f"{_quote(schema)}.{_quote(table)}"

        if order_by and order_by not in names:
            raise DatabaseError(f'no column "{order_by}" on {schema}.{table}')
        primary_key = [c.name for c in columns if c.is_primary_key]
        sort = order_by or (primary_key[0] if primary_key else columns[0].name)

        where, args = "", []
        if search:
            # Every column cast to text so one box searches the whole row.
            clauses = " OR ".join(f"{_quote(c.name)}::text ILIKE $1" for c in columns)
            where = f"WHERE {clauses}"
            args.append(f"%{search}%")

        total = await conn.fetchval(f"SELECT count(*) FROM {qualified} {where}", *args)  # noqa: S608
        rows = await conn.fetch(  # noqa: S608 - identifiers validated above
            f"SELECT * FROM {qualified} {where} "
            f"ORDER BY {_quote(sort)} {'DESC' if descending else 'ASC'} "
            f"LIMIT {limit} OFFSET {max(0, offset)}",
            *args,
        )
        return {
            "schema": schema,
            "table": table,
            "columns": [
                {
                    "name": c.name,
                    "data_type": c.data_type,
                    "nullable": c.nullable,
                    "is_primary_key": c.is_primary_key,
                }
                for c in columns
            ],
            "primary_key": primary_key,
            "editable": bool(primary_key),
            "rows": [{k: _jsonable(v) for k, v in dict(r).items()} for r in rows],
            "total": int(total or 0),
            "limit": limit,
            "offset": max(0, offset),
            "order_by": sort,
            "descending": descending,
        }
    except asyncpg.PostgresError as exc:
        raise DatabaseError(str(exc)) from exc
    finally:
        await conn.close()


# ── editing ──────────────────────────────────────────────────────────────────


async def insert_row(service: ManagedService, schema: str, table: str, values: dict) -> dict:
    conn = await _connect(service)
    try:
        columns = await _columns(conn, schema, table)
        names = {c.name for c in columns}
        supplied = {k: v for k, v in values.items() if k in names}
        if not supplied:
            raise DatabaseError("no recognised columns in the submitted row")

        cols = ", ".join(_quote(k) for k in supplied)
        placeholders = ", ".join(f"${i + 1}" for i in range(len(supplied)))
        row = await conn.fetchrow(  # noqa: S608 - identifiers validated above
            f"INSERT INTO {_quote(schema)}.{_quote(table)} ({cols}) "
            f"VALUES ({placeholders}) RETURNING *",
            *supplied.values(),
        )
        log.info("row inserted", schema=schema, table=table)
        return {k: _jsonable(v) for k, v in dict(row).items()}
    except asyncpg.PostgresError as exc:
        raise DatabaseError(str(exc)) from exc
    finally:
        await conn.close()


async def update_row(
    service: ManagedService, schema: str, table: str, key: dict, values: dict
) -> dict:
    conn = await _connect(service)
    try:
        columns = await _columns(conn, schema, table)
        names = {c.name for c in columns}
        primary_key = [c.name for c in columns if c.is_primary_key]
        _require_key(primary_key, key, schema, table)

        updates = {k: v for k, v in values.items() if k in names}
        if not updates:
            raise DatabaseError("nothing to update")

        sets = ", ".join(f"{_quote(k)} = ${i + 1}" for i, k in enumerate(updates))
        offset = len(updates)
        conditions = " AND ".join(
            f"{_quote(k)} = ${offset + i + 1}" for i, k in enumerate(primary_key)
        )
        row = await conn.fetchrow(  # noqa: S608 - identifiers validated above
            f"UPDATE {_quote(schema)}.{_quote(table)} SET {sets} WHERE {conditions} RETURNING *",
            *updates.values(),
            *[key[k] for k in primary_key],
        )
        if row is None:
            raise DatabaseError("no row matched that primary key")
        log.info("row updated", schema=schema, table=table)
        return {k: _jsonable(v) for k, v in dict(row).items()}
    except asyncpg.PostgresError as exc:
        raise DatabaseError(str(exc)) from exc
    finally:
        await conn.close()


async def delete_row(service: ManagedService, schema: str, table: str, key: dict) -> int:
    conn = await _connect(service)
    try:
        columns = await _columns(conn, schema, table)
        primary_key = [c.name for c in columns if c.is_primary_key]
        _require_key(primary_key, key, schema, table)

        conditions = " AND ".join(f"{_quote(k)} = ${i + 1}" for i, k in enumerate(primary_key))
        result = await conn.execute(  # noqa: S608 - identifiers validated above
            f"DELETE FROM {_quote(schema)}.{_quote(table)} WHERE {conditions}",
            *[key[k] for k in primary_key],
        )
        deleted = int(result.rsplit(" ", 1)[-1] or 0)
        log.info("row deleted", schema=schema, table=table, rows=deleted)
        return deleted
    except asyncpg.PostgresError as exc:
        raise DatabaseError(str(exc)) from exc
    finally:
        await conn.close()


def _require_key(primary_key: list[str], key: dict, schema: str, table: str) -> None:
    if not primary_key:
        raise DatabaseError(
            f"{schema}.{table} has no primary key, so a single row cannot be "
            f"identified. Use the query console for changes to this table."
        )
    missing = [k for k in primary_key if k not in key]
    if missing:
        raise DatabaseError(f"missing primary key value for: {', '.join(missing)}")


# ── query console ────────────────────────────────────────────────────────────


async def run_query(service: ManagedService, sql: str) -> dict:
    """Run one statement and return either its rows or how many it changed.

    Deliberately unrestricted — it is the operator's own database, and a data
    browser that cannot run DDL is a toy. The guards that matter are the admin
    role, the statement timeout and the row cap.
    """
    statement = sql.strip().rstrip(";")
    if not statement:
        raise DatabaseError("nothing to run")

    conn = await _connect(service)
    started = time.perf_counter()
    try:
        returns_rows = (
            statement.lstrip("( \n\t")
            .lower()
            .startswith(("select", "with", "table", "values", "show", "explain"))
            or " returning " in statement.lower()
        )

        if returns_rows:
            rows = await conn.fetch(statement)
            capped = rows[:MAX_QUERY_ROWS]
            columns = list(capped[0].keys()) if capped else []
            return {
                "kind": "rows",
                "columns": columns,
                "rows": [{k: _jsonable(v) for k, v in dict(r).items()} for r in capped],
                "row_count": len(rows),
                "truncated": len(rows) > len(capped),
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            }

        result = await conn.execute(statement)
        return {
            "kind": "command",
            "command": result,
            "columns": [],
            "rows": [],
            "row_count": _affected(result),
            "truncated": False,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except asyncpg.PostgresError as exc:
        # Postgres' own message is far more useful than anything wrapped around it.
        detail = getattr(exc, "detail", None)
        hint = getattr(exc, "hint", None)
        raise DatabaseError(" — ".join(p for p in (str(exc), detail, hint) if p)) from exc
    finally:
        await conn.close()


def _affected(tag: str) -> int:
    parts = tag.split()
    if parts and parts[-1].isdigit():
        return int(parts[-1])
    return 0


async def overview(service: ManagedService) -> dict:
    """Headline numbers for the top of the database page."""
    conn = await _connect(service)
    try:
        size, tables, connections, version = await conn.fetchrow(
            """
            SELECT pg_database_size(current_database()) AS size,
                   (SELECT count(*) FROM information_schema.tables
                    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')) AS tables,
                   (SELECT count(*) FROM pg_stat_activity
                    WHERE datname = current_database()) AS connections,
                   version() AS version
            """
        )
        return {
            "size_bytes": int(size),
            "tables": int(tables),
            "connections": int(connections),
            "server": str(version).split(" on ")[0],
            "database": (service.config or {}).get("database", "cubicle"),
        }
    finally:
        await conn.close()
