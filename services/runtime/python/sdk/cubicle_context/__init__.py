"""The Cubicle runtime SDK.

Available inside every isolate with no installation and no configuration::

    from cubicle_context import Request, Context, env

    def handler(req: Request, ctx: Context):
        return {"ok": True}

``Request`` also behaves like the plain ``event`` mapping documented for the
``handler(event, context)`` form, so either signature works against the same
runtime.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from typing import Any

__all__ = ["Context", "Request", "env", "Env"]

_state = threading.local()


class _MissingService(RuntimeError):
    pass


class Request(Mapping):
    """The incoming invocation."""

    __slots__ = (
        "body",
        "headers",
        "method",
        "query",
        "path",
        "session_id",
        "request_id",
        "namespace",
        "function",
        "trigger",
    )

    def __init__(self, payload: dict[str, Any]) -> None:
        self.body = payload.get("body")
        self.headers = dict(payload.get("headers") or {})
        self.method = payload.get("method", "POST")
        self.query = dict(payload.get("query") or {})
        self.path = payload.get("path", "/")
        self.session_id = payload.get("session_id", "")
        self.request_id = payload.get("request_id", "")
        self.namespace = payload.get("namespace", "")
        self.function = payload.get("function", "")
        self.trigger = payload.get("trigger", "http")

    def json(self, default: Any = None) -> Any:
        """Body as parsed JSON, or ``default`` when there is nothing to parse."""
        if self.body is None or self.body == "":
            return {} if default is None else default
        if isinstance(self.body, (dict, list)):
            return self.body
        try:
            return json.loads(self.body)
        except (TypeError, ValueError):
            return {} if default is None else default

    def text(self) -> str:
        if self.body is None:
            return ""
        if isinstance(self.body, str):
            return self.body
        return json.dumps(self.body)

    def header(self, name: str, default: str | None = None) -> str | None:
        return self.headers.get(name.lower(), default)

    # Mapping protocol — supports the documented `event["body"]` style.
    _KEYS = ("body", "headers", "method", "query", "path", "trigger", "session_id", "request_id")

    def __getitem__(self, key: str) -> Any:
        if key in self._KEYS:
            return getattr(self, key)
        raise KeyError(key)

    def __iter__(self):
        return iter(self._KEYS)

    def __len__(self) -> int:
        return len(self._KEYS)

    def __repr__(self) -> str:
        return f"<Request {self.method} {self.path} session={self.session_id}>"


class Context:
    """Session-scoped state shared by every function in a namespace.

    Keyed by the ``X-Cubicle-Session`` header, held in the cluster for 30
    minutes. What a function may do with it is set per function — a read-only
    function that calls :meth:`set` raises rather than silently dropping data.
    """

    __slots__ = ("_data", "_writes", "_deletes", "_access", "session_id")

    def __init__(self, data: dict[str, Any], access: str, session_id: str) -> None:
        self._data = dict(data or {})
        self._writes: dict[str, Any] = {}
        self._deletes: list[str] = []
        self._access = access or "rw"
        self.session_id = session_id

    @property
    def readable(self) -> bool:
        return "r" in self._access

    @property
    def writable(self) -> bool:
        return "w" in self._access

    def get(self, key: str, default: Any = None) -> Any:
        if not self.readable:
            raise PermissionError(
                f"this function has '{self._access}' context access and cannot read the context"
            )
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        if not self.writable:
            raise PermissionError(
                f"this function has '{self._access}' context access and cannot write the context"
            )
        json.dumps(value)  # fail loudly here rather than at the edge
        self._data[key] = value
        self._writes[key] = value
        if key in self._deletes:
            self._deletes.remove(key)

    def delete(self, key: str) -> None:
        if not self.writable:
            raise PermissionError(
                f"this function has '{self._access}' context access and cannot write the context"
            )
        self._data.pop(key, None)
        self._writes.pop(key, None)
        self._deletes.append(key)

    def all(self) -> dict[str, Any]:
        if not self.readable:
            raise PermissionError("this function cannot read the context")
        return dict(self._data)

    def keys(self):
        return self.all().keys()

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def _drain(self) -> tuple[dict[str, Any], list[str]]:
        return self._writes, self._deletes

    def __repr__(self) -> str:
        return f"<Context session={self.session_id} access={self._access} keys={len(self._data)}>"


class Env:
    """Cluster-wide configuration, resolved at invocation time.

    Values come from the cluster store on every request, so changing one in the
    console takes effect on the next invocation — no redeploy.
    """

    def _values(self) -> dict[str, str]:
        return getattr(_state, "env", {})

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._values().get(key, default)

    def require(self, key: str) -> str:
        value = self._values().get(key)
        if value is None:
            raise KeyError(f"{key} is not set in the cluster env store")
        return value

    def get_int(self, key: str, default: int | None = None) -> int | None:
        raw = self._values().get(key)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        raw = self._values().get(key)
        if raw is None:
            return default
        return raw.strip().lower() in ("1", "true", "yes", "on")

    def get_json(self, key: str, default: Any = None) -> Any:
        raw = self._values().get(key)
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except ValueError:
            return default

    def all(self) -> dict[str, str]:
        return dict(self._values())

    def __contains__(self, key: str) -> bool:
        return key in self._values()

    def __repr__(self) -> str:
        return f"<Env {len(self._values())} keys>"


env = Env()


# ── wiring used by the agent (not part of the public surface) ────────────────


def _bind(*, env_values: dict[str, str], secrets: dict[str, str], services: dict[str, str]) -> None:
    _state.env = {**env_values, **secrets}
    _state.services = services


def _services() -> dict[str, str]:
    return getattr(_state, "services", {})


def _clear() -> None:
    _state.env = {}
    _state.services = {}
