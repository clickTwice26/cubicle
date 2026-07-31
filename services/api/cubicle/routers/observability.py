"""Dashboard, logs and the live tail."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from .. import analytics
from ..db import get_redis
from ..deps import CurrentCluster, CurrentPrincipal, DbSession
from ..models import Function, Group, LogEntry, Node
from ..runtime.invoker import LOG_CHANNEL
from ..runtime.pool import pool
from ..schemas import LogPage
from .functions import _log_out, current_version, serialize_function

router = APIRouter(prefix="/api", tags=["observability"])

LEVELS = ("INFO", "WARN", "ERROR", "DEBUG")


@router.get("/dashboard")
async def dashboard(
    db: DbSession,
    cluster: CurrentCluster,
    _: CurrentPrincipal,
    hours: int = Query(24, ge=1, le=720),
):
    functions = (
        (
            await db.execute(
                select(Function)
                .options(selectinload(Function.group))
                .join(Group, Group.id == Function.group_id)
                .where(Group.cluster_id == cluster.id)
                .order_by(Function.created_at)
            )
        )
        .scalars()
        .all()
    )
    stats = await analytics.bulk_function_stats(db, hours=hours, cluster_id=cluster.id)
    warm = pool.warm_functions()

    rows = []
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
        payload["warm"] = str(fn.id) in warm
        rows.append(payload)

    node_count = (
        await db.execute(
            select(func.count(Node.id)).where(
                Node.cluster_id == cluster.id, Node.schedulable.is_(True)
            )
        )
    ).scalar_one()

    return {
        "kpis": await analytics.cluster_kpis(db, hours=hours, cluster_id=cluster.id),
        "chart": await analytics.invocation_series(
            db, hours=hours, buckets=28, cluster_id=cluster.id
        ),
        "functions": rows,
        "function_count": len(rows),
        "node_count": node_count,
        "warm_isolates": pool.count(),
        "window_hours": hours,
        "cluster": cluster.slug,
    }


@router.get("/logs", response_model=LogPage)
async def list_logs(
    db: DbSession,
    cluster: CurrentCluster,
    _: CurrentPrincipal,
    level: str = Query("all"),
    function: str | None = None,
    search: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """A page of recorded log lines, newest first.

    Filtering happens here rather than in the console so the total is the count
    of what matches, not the count of what happened to be fetched.
    """
    filters = [LogEntry.cluster_id == cluster.id]
    if level.upper() in LEVELS:
        filters.append(LogEntry.level == level.upper())
    if function:
        filters.append(LogEntry.function_name == function)
    if search:
        filters.append(LogEntry.message.ilike(f"%{search}%"))

    total = (await db.execute(select(func.count(LogEntry.id)).where(*filters))).scalar_one()
    rows = (
        (
            await db.execute(
                select(LogEntry)
                .where(*filters)
                .order_by(LogEntry.ts.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return LogPage(
        items=[_log_out(row) for row in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.get("/logs/functions", response_model=list[str])
async def log_function_names(db: DbSession, cluster: CurrentCluster, _: CurrentPrincipal):
    """Function names that appear in this cluster's logs, for the filter."""
    rows = (
        (
            await db.execute(
                select(LogEntry.function_name)
                .where(LogEntry.cluster_id == cluster.id, LogEntry.function_name != "")
                .distinct()
                .order_by(LogEntry.function_name)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@router.get("/logs/stream")
async def stream_logs(
    cluster: CurrentCluster, _: CurrentPrincipal, level: str = Query("all")
) -> StreamingResponse:
    """Server-sent events carrying every log line as it is written.

    EventSource cannot set headers, so the console passes the cluster as a
    query parameter; ``get_cluster`` accepts either.
    """
    wanted = level.upper()
    slug = cluster.slug

    async def events() -> AsyncIterator[str]:
        redis = get_redis()
        pubsub = redis.pubsub()
        await pubsub.subscribe(LOG_CHANNEL)
        try:
            yield ": connected\n\n"
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
                if message is None:
                    yield ": keep-alive\n\n"
                    continue
                try:
                    entries = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    continue
                entries = [e for e in entries if e.get("cluster") in (slug, None)]
                if wanted in LEVELS:
                    entries = [e for e in entries if e.get("level") == wanted]
                if entries:
                    yield f"data: {json.dumps(entries)}\n\n"
        except asyncio.CancelledError:
            raise
        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(LOG_CHANNEL)
                await pubsub.aclose()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
