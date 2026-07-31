"""The live event bus behind the activity dashboard.

Every interesting thing the runtime does — a request arriving, an isolate
being started, one going busy or idle, one being reaped — is published here as
a small JSON event. The console subscribes over SSE and animates it.

Redis pub/sub rather than an in-process queue: an install can run more than one
API worker, and a dashboard connected to worker A has to see the isolate worker
B just started. It also means publishing is fire-and-forget — the runtime never
waits on, or fails because of, a dashboard.

Events are advisory. They are dropped when nothing is listening and never
replayed, so nothing in the platform may depend on one being delivered; the
database remains the record of what happened.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator
from typing import Any

from .db import get_redis
from .logging_setup import log

CHANNEL = "cubicle:live"

#: A slow consumer must not be able to stall the runtime, so publishing runs
#: detached and these are the only two ways it can end: delivered, or dropped.
_tasks: set[asyncio.Task[None]] = set()


def publish(kind: str, cluster: str, **fields: Any) -> None:
    """Fire an event at whoever is watching. Never raises, never blocks."""
    event = {"kind": kind, "cluster": cluster, "ts": time.time(), **fields}
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # called from a thread with no loop — not worth caring about
    task = loop.create_task(_send(event))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _send(event: dict[str, Any]) -> None:
    try:
        await get_redis().publish(CHANNEL, json.dumps(event))
    except Exception as exc:  # noqa: BLE001 - telemetry must not break a request
        log.debug("live event dropped", kind=event.get("kind"), error=str(exc))


async def stream(cluster: str) -> AsyncIterator[dict[str, Any]]:
    """Yield events for one cluster until the caller goes away."""
    redis = get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(CHANNEL)
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5.0)
            if message is None:
                yield {"kind": "keepalive"}
                continue
            try:
                event = json.loads(message["data"])
            except (json.JSONDecodeError, TypeError):
                continue
            if event.get("cluster") == cluster:
                yield event
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(CHANNEL)
            await pubsub.aclose()
