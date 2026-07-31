"""Managed data services, ready to use from any function.

    from cubicle_db import postgres, redis

    with postgres.session() as db:
        db.execute("insert into orders (ref) values (:ref)", ref="ord_1")

Credentials are injected per invocation by the control plane, so there is
nothing to configure and no secret to copy into the function. If the operator
has not created the service — or has stopped it — ``available`` is False and
using it raises a clear error instead of hanging on a connection attempt.
"""

from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from typing import Any

from cubicle_context import _services

__all__ = ["postgres", "redis", "ServiceUnavailable"]

_local = threading.local()

# :name → %(name)s, leaving ::casts and anything inside quotes alone.
_PARAM_RE = re.compile(r"(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)")
_LITERAL_RE = re.compile(r"'[^']*'|\"[^\"]*\"")


class ServiceUnavailable(RuntimeError):
    """The service has not been created on this cluster, or is stopped."""


def _translate(sql: str) -> str:
    """Rewrite named parameters for psycopg, skipping string literals."""
    out: list[str] = []
    last = 0
    for literal in _LITERAL_RE.finditer(sql):
        out.append(_PARAM_RE.sub(r"%(\1)s", sql[last : literal.start()]))
        out.append(literal.group(0))
        last = literal.end()
    out.append(_PARAM_RE.sub(r"%(\1)s", sql[last:]))
    return "".join(out)


class Cursor:
    """A thin, deliberately boring wrapper around a psycopg cursor."""

    def __init__(self, cursor) -> None:
        self._cursor = cursor

    def execute(self, sql: str, **params: Any) -> Cursor:
        self._cursor.execute(_translate(sql), params or None)
        return self

    def fetchone(self) -> dict[str, Any] | None:
        row = self._cursor.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._cursor.fetchall()]

    def scalar(self) -> Any:
        row = self._cursor.fetchone()
        if row is None:
            return None
        return next(iter(row.values()))

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount


class Postgres:
    """The managed PostgreSQL instance for this cluster."""

    @property
    def url(self) -> str | None:
        return _services().get("postgres")

    @property
    def available(self) -> bool:
        return bool(self.url)

    @contextmanager
    def session(self, *, autocommit: bool = True):
        """A connection with a cursor. Commits on success, rolls back on error."""
        import psycopg
        from psycopg.rows import dict_row

        url = self.url
        if not url:
            raise ServiceUnavailable(
                "No PostgreSQL instance on this cluster. Create one in the console "
                "under Data services → PostgreSQL."
            )

        conn = getattr(_local, "pg", None)
        if conn is None or conn.closed or getattr(_local, "pg_url", None) != url:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001 - replacing it anyway
                    pass
            conn = psycopg.connect(url, connect_timeout=5, row_factory=dict_row)
            _local.pg = conn
            _local.pg_url = url

        cursor = conn.cursor()
        try:
            yield Cursor(cursor)
        except Exception:
            conn.rollback()
            raise
        else:
            if autocommit:
                conn.commit()
        finally:
            cursor.close()

    def execute(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        """One-shot query returning every row (empty for statements)."""
        with self.session() as db:
            db.execute(sql, **params)
            try:
                return db.fetchall()
            except Exception:  # noqa: BLE001 - statement produced no result set
                return []


class Redis:
    """The managed Redis instance for this cluster."""

    @property
    def url(self) -> str | None:
        return _services().get("redis")

    @property
    def available(self) -> bool:
        return bool(self.url)

    @property
    def client(self):
        import redis as redis_py

        url = self.url
        if not url:
            raise ServiceUnavailable(
                "No Redis instance on this cluster. Create one in the console "
                "under Data services → Redis."
            )
        client = getattr(_local, "redis", None)
        if client is None or getattr(_local, "redis_url", None) != url:
            client = redis_py.from_url(
                url, decode_responses=True, socket_timeout=5, socket_connect_timeout=5
            )
            _local.redis = client
            _local.redis_url = url
        return client

    # The handful of commands worth having as first-class methods; anything
    # else is reachable through `.client`.
    def get(self, key: str) -> str | None:
        return self.client.get(key)

    def set(self, key: str, value: Any, **kwargs: Any) -> bool:
        return self.client.set(key, value, **kwargs)

    def setex(self, key: str, seconds: int, value: Any) -> bool:
        return self.client.setex(key, seconds, value)

    def delete(self, *keys: str) -> int:
        return self.client.delete(*keys)

    def incr(self, key: str, amount: int = 1) -> int:
        return self.client.incr(key, amount)

    def expire(self, key: str, seconds: int) -> bool:
        return self.client.expire(key, seconds)

    def exists(self, *keys: str) -> int:
        return self.client.exists(*keys)

    def __getattr__(self, name: str):
        return getattr(self.client, name)


postgres = Postgres()
redis = Redis()
