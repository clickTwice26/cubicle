"""The live activity feed behind the animated dashboard.

Two endpoints that describe the same thing at different rates: ``/live/state``
is what the cluster looks like right now, and ``/live/stream`` is everything
that happens to it from the moment you connect.

The stream is the interesting one. It carries the runtime's own events —
requests arriving and finishing, isolates spawning, going busy, going idle,
being reclaimed — as they happen, plus a periodic tick so gauges stay honest
while nothing is going on.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from .. import live
from ..deps import CurrentCluster, CurrentPrincipal, DbSession
from ..models import Function, Group, Invocation, Node
from ..runtime.pool import pool

router = APIRouter(prefix="/api/live", tags=["live"])

#: How often the stream emits aggregate counters when nothing else is
#: happening. Fast enough to feel live, slow enough that an idle dashboard is
#: not a busy loop.
TICK_SECONDS = 2.0


@router.get("/state")
async def state(db: DbSession, cluster: CurrentCluster, _: CurrentPrincipal):
    """Everything the dashboard needs to draw its first frame."""
    return await _state(db, cluster.id, cluster.slug)


@router.get("/stream")
async def stream(
    db: DbSession,
    cluster: CurrentCluster,
    _: CurrentPrincipal,
    since_minutes: int = Query(5, ge=1, le=60),
) -> StreamingResponse:
    """Server-sent events: one full state frame, then the runtime's events.

    EventSource cannot set headers, so the cluster arrives as a query
    parameter — ``get_cluster`` accepts either.
    """
    cluster_id, slug = cluster.id, cluster.slug
    opening = await _state(db, cluster_id, slug, minutes=since_minutes)

    async def events() -> AsyncIterator[str]:
        yield _frame({"kind": "state", **opening})

        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=512)

        async def pump() -> None:
            async for event in live.stream(slug):
                if event.get("kind") == "keepalive":
                    continue
                with contextlib.suppress(asyncio.QueueFull):
                    # A dashboard that cannot keep up loses events rather than
                    # applying backpressure to the runtime that produced them.
                    queue.put_nowait(event)

        pumping = asyncio.create_task(pump())
        try:
            next_tick = time.monotonic() + TICK_SECONDS
            while True:
                timeout = max(0.05, next_tick - time.monotonic())
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=timeout)
                    yield _frame(event)
                except TimeoutError:
                    next_tick = time.monotonic() + TICK_SECONDS
                    yield _frame(
                        {
                            "kind": "tick",
                            "ts": time.time(),
                            "isolates": pool.snapshot(cluster=slug),
                        }
                    )
        except asyncio.CancelledError:
            raise
        finally:
            pumping.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pumping

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _frame(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _state(db, cluster_id, slug: str, *, minutes: int = 5) -> dict:
    """A consistent picture of the cluster: functions, isolates, recent traffic."""
    functions = (
        (
            await db.execute(
                select(Function)
                .options(selectinload(Function.group))
                .join(Group, Group.id == Function.group_id)
                .where(Group.cluster_id == cluster_id)
                .order_by(Function.name)
            )
        )
        .scalars()
        .all()
    )

    nodes = (
        (await db.execute(select(Node).where(Node.cluster_id == cluster_id).order_by(Node.name)))
        .scalars()
        .all()
    )

    since = datetime.now(UTC) - timedelta(minutes=minutes)
    recent = (
        (
            await db.execute(
                select(Invocation)
                .where(Invocation.cluster_id == cluster_id, Invocation.ts >= since)
                .order_by(Invocation.ts.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )

    totals = (
        await db.execute(
            select(
                func.count(Invocation.id),
                func.count(Invocation.id).filter(Invocation.status_code >= 400),
                func.count(Invocation.id).filter(Invocation.cold.is_(True)),
            ).where(Invocation.cluster_id == cluster_id, Invocation.ts >= since)
        )
    ).one()

    isolates = pool.snapshot(cluster=slug)
    warm_by_function = {}
    for isolate in isolates:
        warm_by_function[isolate["function_id"]] = (
            warm_by_function.get(isolate["function_id"], 0) + 1
        )

    return {
        "ts": time.time(),
        "cluster": slug,
        "window_minutes": minutes,
        "functions": [
            {
                "id": str(fn.id),
                "name": fn.name,
                "namespace": fn.group.ns,
                "method": fn.method,
                "status": fn.status,
                "memory_mb": fn.memory_mb,
                "min_instances": fn.min_instances,
                "max_instances": fn.max_instances,
                "warm": warm_by_function.get(str(fn.id), 0),
            }
            for fn in functions
        ],
        "nodes": [{"name": node.name, "status": node.status, "pool": node.pool} for node in nodes],
        "isolates": isolates,
        "recent": [
            {
                "request_id": inv.request_id,
                "function_id": str(inv.function_id),
                "function": inv.function_name,
                "status": inv.status_code,
                "duration_ms": inv.duration_ms,
                "cold": inv.cold,
                "ts": inv.ts.timestamp(),
            }
            for inv in reversed(recent)
        ],
        "totals": {
            "invocations": totals[0] or 0,
            "errors": totals[1] or 0,
            "cold": totals[2] or 0,
        },
    }
