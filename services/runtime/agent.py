"""Isolate agent.

One of these runs inside every isolate. It imports the function once, then
answers invocation requests from the control plane over the function network.
Standard library only — the less this has to import, the shorter the cold start.

Protocol
    GET  /healthz  -> {"ready": bool, "error": str|null, "fatal": bool}
    POST /invoke   -> {"status_code", "body", "headers", "logs",
                       "context_writes", "context_deletes", "error"}
"""

from __future__ import annotations

import importlib.util
import inspect
import io
import json
import os
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cubicle_context
from cubicle_context import Context, Request

PORT = int(os.environ.get("CUBICLE_AGENT_PORT", "8080"))
SOURCE = os.environ.get("CUBICLE_HANDLER_PATH", "/srv/handler.py")
ENTRYPOINT = os.environ.get("CUBICLE_ENTRYPOINT", "handler")
MAX_LOG_LINES = 200

_handler = None
_load_error: str | None = None
_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="invoke")


# ── per-invocation stdout capture ────────────────────────────────────────────


class _StreamRouter(io.TextIOBase):
    """Routes writes to the current invocation's buffer, else to the real stream."""

    def __init__(self, real, level: str) -> None:
        self._real = real
        self._level = level
        self._local = threading.local()

    def begin(self) -> list[dict]:
        buffer: list[dict] = []
        self._local.buffer = buffer
        return buffer

    def end(self) -> None:
        self._local.buffer = None

    def write(self, text: str) -> int:
        buffer = getattr(self._local, "buffer", None)
        if buffer is None:
            return self._real.write(text)
        for line in text.splitlines():
            if line and len(buffer) < MAX_LOG_LINES:
                buffer.append({"level": self._level, "message": line[:4000]})
        return len(text)

    def flush(self) -> None:
        self._real.flush()


_stdout = _StreamRouter(sys.stdout, "INFO")
_stderr = _StreamRouter(sys.stderr, "ERROR")
sys.stdout = _stdout
sys.stderr = _stderr


# ── function loading ─────────────────────────────────────────────────────────


def load_function() -> None:
    global _handler, _load_error
    try:
        if not os.path.exists(SOURCE):
            raise FileNotFoundError(f"{SOURCE} is missing from the deployed bundle")

        spec = importlib.util.spec_from_file_location("cubicle_function", SOURCE)
        if spec is None or spec.loader is None:
            raise ImportError(f"could not load {SOURCE}")
        module = importlib.util.module_from_spec(spec)
        sys.modules["cubicle_function"] = module
        spec.loader.exec_module(module)

        fn = getattr(module, ENTRYPOINT, None)
        if fn is None or not callable(fn):
            raise AttributeError(f"{SOURCE} defines no callable named '{ENTRYPOINT}'")
        _handler = fn
        _load_error = None
    except Exception:
        _load_error = traceback.format_exc(limit=6)
        _handler = None


# ── invocation ───────────────────────────────────────────────────────────────


def normalise(result) -> tuple[int, object, dict]:
    """Accept every documented return shape and produce one response."""
    if isinstance(result, tuple) and len(result) == 2:
        body, status = result
        return int(status), body, {}
    if isinstance(result, dict):
        status = result.get("statusCode", result.get("status_code"))
        if status is not None:
            headers = result.get("headers") or {}
            body = result.get("body")
            if isinstance(body, str):
                try:
                    body = json.loads(body)
                except (TypeError, ValueError):
                    pass
            return int(status), body, {str(k): str(v) for k, v in headers.items()}
    return 200, result, {}


def run_invocation(payload: dict) -> dict:
    if _handler is None:
        return {
            "status_code": 500,
            "body": {"error": "handler_not_loaded", "message": _load_error or "unknown"},
            "headers": {},
            "logs": [{"level": "ERROR", "message": (_load_error or "").strip()[:4000]}],
            "error": "handler failed to import",
            "context_writes": {},
            "context_deletes": [],
        }

    request = Request(payload)
    context = Context(
        payload.get("context") or {},
        payload.get("ctx_access", "rw"),
        payload.get("session_id", ""),
    )
    cubicle_context._bind(
        env_values=payload.get("env") or {},
        secrets=payload.get("secrets") or {},
        services=payload.get("services") or {},
    )

    logs = _stdout.begin()
    _stderr._local.buffer = logs
    started = time.perf_counter()
    error = None
    try:
        parameters = len(inspect.signature(_handler).parameters)
        result = _handler(request, context) if parameters >= 2 else _handler(request)
        status_code, body, headers = normalise(result)
    except Exception as exc:
        trace = traceback.format_exc(limit=8)
        error = f"{exc.__class__.__name__}: {exc}"
        status_code, body, headers = 500, {"error": "handler_error", "message": str(exc)}, {}
        for line in trace.strip().splitlines():
            if len(logs) < MAX_LOG_LINES:
                logs.append({"level": "ERROR", "message": line[:4000]})
    finally:
        _stdout.end()
        _stderr.end()
        cubicle_context._clear()

    writes, deletes = context._drain()
    return {
        "status_code": status_code,
        "body": body,
        "headers": headers,
        "logs": logs,
        "error": error,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "context_writes": writes,
        "context_deletes": deletes,
    }


# ── HTTP ─────────────────────────────────────────────────────────────────────


class Agent(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "cubicle-agent/1.0"

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.startswith("/healthz"):
            self._send(
                200,
                {
                    "ready": _handler is not None,
                    "error": _load_error,
                    "fatal": _handler is None and _load_error is not None,
                    "function": os.environ.get("CUBICLE_FUNCTION", ""),
                },
            )
        else:
            self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self.path.startswith("/invoke"):
            self._send(404, {"error": "not_found"})
            return

        length = int(self.headers.get("Content-Length", "0") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._send(400, {"error": "bad_request", "message": "payload is not valid JSON"})
            return

        timeout = float(payload.get("timeout_s") or os.environ.get("CUBICLE_TIMEOUT", "30"))
        future = _executor.submit(run_invocation, payload)
        try:
            self._send(200, future.result(timeout=timeout))
        except FutureTimeout:
            # The handler is still running. The control plane recycles this
            # isolate on a 504, which is the only way to reclaim the thread.
            self._send(
                200,
                {
                    "status_code": 504,
                    "body": {
                        "error": "timeout",
                        "message": f"handler exceeded its {timeout:g}s timeout",
                    },
                    "headers": {},
                    "logs": [{"level": "ERROR", "message": f"timed out after {timeout:g}s"}],
                    "error": "timeout",
                    "context_writes": {},
                    "context_deletes": [],
                },
            )

    def log_message(self, *args) -> None:  # noqa: A003 - silence the default access log
        return


def main() -> None:
    load_function()
    if _load_error:
        # Reported through /healthz; the control plane surfaces it in the console.
        print(f"cubicle-agent: function failed to load\n{_load_error}", file=sys.__stderr__)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Agent)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
