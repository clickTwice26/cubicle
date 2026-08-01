"""Browsing and editing a managed Redis instance.

The Postgres browser next door validates identifiers against the catalog before
quoting them into SQL. Redis has no such problem — keys, fields and members are
always sent as arguments, never as text spliced into a command — so the guards
here are about size instead: a SCAN page is bounded, a value is truncated before
it can flood the console, and the console's command box refuses the handful of
commands that would block the connection or stop the server.

Only the cluster's own managed instance is reachable. The control plane's own
Redis, which holds sessions and rate-limit counters, is never addressable here.
"""

from __future__ import annotations

import contextlib
import shlex
import time
from typing import Any

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from ..logging_setup import log
from ..models import ManagedService
from .services import password_for

# A SCAN page is what the console shows at once; the value cap is what one key
# may contribute to a response. Both are here so a 500 MB string cannot become a
# 500 MB JSON body.
MAX_PAGE = 200
MAX_VALUE_BYTES = 64 * 1024
MAX_COMMAND_ITEMS = 500
SOCKET_TIMEOUT = 5

# Commands that never return on a request/response connection, or that take the
# instance away from under the operator. Everything else is allowed: it is their
# own cache, and a browser that cannot run CONFIG or FLUSHDB is a toy.
BLOCKED_COMMANDS = {
    "blmove",
    "blmpop",
    "blpop",
    "brpop",
    "brpoplpush",
    "bzmpop",
    "bzpopmax",
    "bzpopmin",
    "debug",
    "monitor",
    "psubscribe",
    "psync",
    "shutdown",
    "ssubscribe",
    "subscribe",
    "sync",
    "wait",
}

COLLECTION_TYPES = ("hash", "list", "set", "zset", "stream")


class RedisAdminError(RuntimeError):
    """Something the operator should read: a missing key, or Redis saying no."""


def _client(service: ManagedService) -> aioredis.Redis:
    """A raw-bytes client — values are decoded per field, not per connection.

    ``decode_responses=True`` would raise on the first key holding a protobuf or
    a gzipped blob, which is exactly the key someone is trying to look at when
    something is wrong.
    """
    return aioredis.from_url(
        f"redis://:{password_for(service)}@{service.container_name}:6379/0",
        decode_responses=False,
        socket_timeout=SOCKET_TIMEOUT,
        socket_connect_timeout=SOCKET_TIMEOUT,
    )


def _text(value: Any) -> Any:
    """Coerce a Redis reply into something JSON can carry."""
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, bytes | bytearray | memoryview):
        raw = bytes(value)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            # Binary is shown, not hidden — hex is the honest rendering.
            return f"\\x{raw.hex()}"
    if isinstance(value, str):
        return value
    if isinstance(value, list | tuple | set):
        return [_text(item) for item in value]
    if isinstance(value, dict):
        return {str(_text(k)): _text(v) for k, v in value.items()}
    return str(value)


def _truncate(value: bytes | None) -> tuple[Any, bool]:
    if value is None:
        return None, False
    if len(value) > MAX_VALUE_BYTES:
        return _text(value[:MAX_VALUE_BYTES]), True
    return _text(value), False


async def _run(service: ManagedService, work):
    client = _client(service)
    try:
        return await work(client)
    except RedisError as exc:
        raise RedisAdminError(str(exc)) from exc
    except OSError as exc:
        raise RedisAdminError(f"could not connect to Redis: {exc}") from exc
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()


# ── overview ─────────────────────────────────────────────────────────────────


async def overview(service: ManagedService) -> dict:
    async def work(client: aioredis.Redis) -> dict:
        info = _text(await client.info())
        keys = int(await client.dbsize())
        hits = int(info.get("keyspace_hits", 0) or 0)
        misses = int(info.get("keyspace_misses", 0) or 0)
        looked_up = hits + misses
        return {
            "keys": keys,
            "used_memory": int(info.get("used_memory", 0) or 0),
            "max_memory": int(info.get("maxmemory", 0) or 0),
            "eviction": str(info.get("maxmemory_policy", "noeviction")),
            "server": f"Redis {info.get('redis_version', '?')}",
            "clients": int(info.get("connected_clients", 0) or 0),
            "uptime_seconds": int(info.get("uptime_in_seconds", 0) or 0),
            "hit_rate": round(hits / looked_up, 4) if looked_up else None,
            "expires": int(info.get("expired_keys", 0) or 0),
            "evicted": int(info.get("evicted_keys", 0) or 0),
        }

    return await _run(service, work)


# ── browsing ─────────────────────────────────────────────────────────────────


async def scan_keys(
    service: ManagedService,
    *,
    cursor: int = 0,
    match: str | None = None,
    type_filter: str | None = None,
    limit: int = 50,
) -> dict:
    """One SCAN page, with the type, TTL and size of every key on it.

    SCAN is cursor-based and gives no page numbers — the cursor is handed back
    to the console so "load more" continues exactly where this page stopped.
    """
    limit = max(1, min(limit, MAX_PAGE))
    if type_filter and type_filter not in ("string", *COLLECTION_TYPES):
        raise RedisAdminError(f"unknown key type: {type_filter}")

    async def work(client: aioredis.Redis) -> dict:
        pattern = match.strip() if match and match.strip() else "*"
        if pattern != "*" and not any(ch in pattern for ch in "*?["):
            # A bare word is what people type when they mean "contains".
            pattern = f"*{pattern}*"

        next_cursor, raw_keys = await client.scan(
            cursor=cursor,
            match=pattern,
            count=limit,
            _type=type_filter.upper() if type_filter else None,
        )
        keys = [bytes(k) for k in raw_keys]

        types: list[str] = []
        ttls: list[int] = []
        if keys:
            pipe = client.pipeline(transaction=False)
            for key in keys:
                pipe.type(key)
                pipe.ttl(key)
            replies = await pipe.execute()
            types = [str(_text(replies[i * 2])) for i in range(len(keys))]
            ttls = [int(replies[i * 2 + 1]) for i in range(len(keys))]

        sizes = await _sizes(client, keys, types)
        return {
            "cursor": cursor,
            "next_cursor": int(next_cursor) or None,
            "match": match or "",
            "type": type_filter,
            "total": int(await client.dbsize()),
            "keys": [
                {
                    "key": _text(key),
                    "type": kind,
                    "ttl": ttl,
                    "length": size["length"],
                    "size_bytes": size["bytes"],
                }
                for key, kind, ttl, size in zip(keys, types, ttls, sizes, strict=False)
            ],
        }

    return await _run(service, work)


async def _sizes(client: aioredis.Redis, keys: list[bytes], types: list[str]) -> list[dict]:
    """Element count and memory footprint per key, in one round trip each."""
    if not keys:
        return []
    counters = {
        "string": "strlen",
        "hash": "hlen",
        "list": "llen",
        "set": "scard",
        "zset": "zcard",
        "stream": "xlen",
    }
    pipe = client.pipeline(transaction=False)
    for key, kind in zip(keys, types, strict=False):
        getattr(pipe, counters.get(kind, "strlen"))(key)
    lengths = await pipe.execute()

    pipe = client.pipeline(transaction=False)
    for key in keys:
        pipe.memory_usage(key)
    try:
        footprints = await pipe.execute()
    except RedisError:
        # MEMORY USAGE is missing on some builds; the page is still useful.
        footprints = [None] * len(keys)

    return [
        {
            "length": int(length) if isinstance(length, int) else None,
            "bytes": int(used) if isinstance(used, int) else None,
        }
        for length, used in zip(lengths, footprints, strict=False)
    ]


async def read_key(service: ManagedService, key: str, *, cursor: int = 0, limit: int = 50) -> dict:
    """The value behind one key, paged in the way its own type supports.

    Lists and sorted sets have positions, so they page by offset. Hashes and
    sets do not, so they page by the cursor HSCAN and SSCAN hand back. Both
    arrive at the console as the same shape: a page plus where to go next.
    """
    limit = max(1, min(limit, MAX_PAGE))

    async def work(client: aioredis.Redis) -> dict:
        name = key.encode()
        kind = str(_text(await client.type(name)))
        if kind == "none":
            raise RedisAdminError(f"no key {key!r} in this database")

        ttl = int(await client.ttl(name))
        base = {
            "key": key,
            "type": kind,
            "ttl": ttl,
            "cursor": cursor,
            "next_cursor": None,
            "editable": kind in ("string", *COLLECTION_TYPES) and kind != "stream",
        }

        if kind == "string":
            value, truncated = _truncate(await client.get(name))
            return {
                **base,
                "total": int(await client.strlen(name)),
                "truncated": truncated,
                "value": value,
                "entries": [],
            }

        if kind == "hash":
            next_cursor, items = await client.hscan(name, cursor=cursor, count=limit)
            return {
                **base,
                "total": int(await client.hlen(name)),
                "truncated": False,
                "value": None,
                "next_cursor": int(next_cursor) or None,
                "entries": [
                    {"field": _text(field), "value": _truncate(value)[0]}
                    for field, value in items.items()
                ],
            }

        if kind == "set":
            next_cursor, members = await client.sscan(name, cursor=cursor, count=limit)
            return {
                **base,
                "total": int(await client.scard(name)),
                "truncated": False,
                "value": None,
                "next_cursor": int(next_cursor) or None,
                "entries": [{"field": None, "value": _truncate(m)[0]} for m in members],
            }

        if kind == "list":
            total = int(await client.llen(name))
            items = await client.lrange(name, cursor, cursor + limit - 1)
            return {
                **base,
                "total": total,
                "truncated": False,
                "value": None,
                "next_cursor": cursor + limit if cursor + limit < total else None,
                "entries": [
                    {"field": str(cursor + index), "value": _truncate(item)[0]}
                    for index, item in enumerate(items)
                ],
            }

        if kind == "zset":
            total = int(await client.zcard(name))
            items = await client.zrange(name, cursor, cursor + limit - 1, withscores=True)
            return {
                **base,
                "total": total,
                "truncated": False,
                "value": None,
                "next_cursor": cursor + limit if cursor + limit < total else None,
                "entries": [
                    {"field": _text(member), "value": _text(member), "score": float(score)}
                    for member, score in items
                ],
            }

        if kind == "stream":
            total = int(await client.xlen(name))
            items = await client.xrange(name, count=limit)
            return {
                **base,
                "total": total,
                "truncated": False,
                "value": None,
                "entries": [
                    {"field": _text(entry_id), "value": _text(fields)} for entry_id, fields in items
                ],
            }

        raise RedisAdminError(f"{kind} keys cannot be browsed here — use the command console")

    return await _run(service, work)


# ── editing ──────────────────────────────────────────────────────────────────


async def write_key(
    service: ManagedService,
    key: str,
    *,
    value: str,
    field: str | None = None,
    score: float | None = None,
    ttl: int | None = None,
    type_hint: str | None = None,
) -> dict:
    """Write one value: the whole string, or one field/member/element of a collection.

    The type of an existing key always wins — ``type_hint`` only decides what a
    key that does not exist yet becomes, so nothing here can silently turn
    someone's hash into a string.
    """

    async def work(client: aioredis.Redis) -> dict:
        name = key.encode()
        kind = str(_text(await client.type(name)))
        creating = kind == "none"
        if creating:
            kind = (type_hint or "string").lower()
            if kind not in ("string", "hash", "list", "set", "zset"):
                raise RedisAdminError(f"{kind} keys cannot be created here")

        if kind == "string":
            await client.set(name, value)
        elif kind == "hash":
            if not field:
                raise RedisAdminError("a hash needs a field name")
            await client.hset(name, field.encode(), value.encode())
        elif kind == "set":
            if field is not None and field != value:
                # Renaming a member is a remove and an add; a set has no slots.
                await client.srem(name, field.encode())
            await client.sadd(name, value.encode())
        elif kind == "zset":
            if field is not None and field != value:
                await client.zrem(name, field.encode())
            await client.zadd(name, {value.encode(): float(score or 0)})
        elif kind == "list":
            # No index means appending; an index means replacing that element.
            if field is None or field == "":
                await client.rpush(name, value.encode())
            elif not field.lstrip("-").isdigit():
                raise RedisAdminError("a list element is addressed by its index")
            else:
                await client.lset(name, int(field), value.encode())
        else:
            raise RedisAdminError(f"{kind} keys are read-only here")

        if ttl is not None:
            if ttl > 0:
                await client.expire(name, ttl)
            else:
                await client.persist(name)

        log.info("redis key written", key=key, kind=kind)
        return {"key": key, "type": kind}

    return await _run(service, work)


async def delete_entry(service: ManagedService, key: str, field: str) -> dict:
    """Remove one field, member or element — not the key itself."""

    async def work(client: aioredis.Redis) -> dict:
        name = key.encode()
        kind = str(_text(await client.type(name)))
        if kind == "hash":
            removed = int(await client.hdel(name, field.encode()))
        elif kind == "set":
            removed = int(await client.srem(name, field.encode()))
        elif kind == "zset":
            removed = int(await client.zrem(name, field.encode()))
        elif kind == "list":
            if not field.lstrip("-").isdigit():
                raise RedisAdminError("a list element is addressed by its index")
            # Redis cannot remove by position, so the element is tombstoned and
            # then swept — the sequence Redis' own documentation recommends.
            tombstone = b"__cubicle_deleted__"
            await client.lset(name, int(field), tombstone)
            removed = int(await client.lrem(name, 1, tombstone))
        elif kind == "stream":
            removed = int(await client.xdel(name, field))
        elif kind == "none":
            raise RedisAdminError(f"no key {key!r} in this database")
        else:
            raise RedisAdminError(f"{kind} keys have no removable members")

        log.info("redis entry deleted", key=key, kind=kind, removed=removed)
        return {"deleted": removed}

    return await _run(service, work)


async def delete_key(service: ManagedService, key: str) -> dict:
    async def work(client: aioredis.Redis) -> dict:
        deleted = int(await client.delete(key.encode()))
        log.info("redis key deleted", key=key, deleted=deleted)
        return {"deleted": deleted}

    return await _run(service, work)


async def set_ttl(service: ManagedService, key: str, ttl: int) -> dict:
    async def work(client: aioredis.Redis) -> dict:
        name = key.encode()
        if not await client.exists(name):
            raise RedisAdminError(f"no key {key!r} in this database")
        if ttl > 0:
            await client.expire(name, ttl)
        else:
            await client.persist(name)
        return {"key": key, "ttl": int(await client.ttl(name))}

    return await _run(service, work)


# ── command console ──────────────────────────────────────────────────────────


async def run_command(service: ManagedService, raw: str) -> dict:
    """Run one Redis command and return its reply.

    The same bargain as the SQL console: unrestricted apart from the commands
    that would hang the connection or stop the server, because the guards that
    matter are the admin role and the fact that this is the operator's own cache.
    """
    statement = raw.strip()
    if not statement:
        raise RedisAdminError("nothing to run")
    try:
        parts = shlex.split(statement)
    except ValueError as exc:
        raise RedisAdminError(f"could not parse that command: {exc}") from exc
    if not parts:
        raise RedisAdminError("nothing to run")

    name = parts[0].lower()
    if name in BLOCKED_COMMANDS:
        raise RedisAdminError(
            f"{parts[0].upper()} is not available here — it blocks the connection "
            f"or stops the server."
        )

    async def work(client: aioredis.Redis) -> dict:
        started = time.perf_counter()
        reply = await client.execute_command(*parts)
        value = _text(reply)
        truncated = False
        if isinstance(value, list) and len(value) > MAX_COMMAND_ITEMS:
            value = value[:MAX_COMMAND_ITEMS]
            truncated = True
        log.info("redis command run", command=name)
        return {
            "command": " ".join(parts),
            "kind": "list" if isinstance(value, list) else "value",
            "value": value,
            "truncated": truncated,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    return await _run(service, work)
