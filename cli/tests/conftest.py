"""The fake control plane the CLI tests run against.

No test opens a socket. `cubicle_cli.client` performs every call through one
swappable function, so a test installs `FakeAPI` in front of it and then
asserts on what the CLI asked for and what it printed.

Writing a test for a new command looks like this:

    def test_it_asks_for_the_triggers(api, run, capsys):
        api.on("GET", "/api/functions", [api_function()])
        api.on("GET", "/api/functions/fn-1/triggers", [])
        assert run("triggers", "ls", "payments/create-charge") == 0
        assert "(nothing to show)" in capsys.readouterr().out

The three fixtures:

`api`   the fake. `api.on(method, path, *answers)` queues what a path returns.
        Queue several answers and they come back in turn, with the last one
        repeating forever, which is how a polling command is tested. An answer
        that is an exception is raised instead (queue a CubicleError to stand
        in for a 4xx), and an answer that is callable is called with the
        `Call` and its return value used. `api.calls` is every Call in order,
        `api.sent(method, path)` the ones matching a route and `api.last(...)`
        the most recent of those, which is where the body and params are
        asserted on. `api.frames` is the list of SSE payloads a `--follow`
        command will read.

`run`   runs the CLI exactly as a person does, arguments and all, and returns
        the exit code. It supplies --url and --token, so nothing touches
        ~/.cubicle/config.toml.

`api_function`  builds a function record shaped like GET /api/functions
        returns them, with keyword overrides for the fields a test cares
        about.
"""

from __future__ import annotations

from typing import Any

import pytest

from cubicle_cli import client
from cubicle_cli.__main__ import main

URL = "https://cubicle.test"
TOKEN = "cbcl_test"


class FakeAPI:
    """A control plane that answers from a script and remembers the questions."""

    def __init__(self) -> None:
        self.answers: dict[tuple[str, str], list[Any]] = {}
        self.calls: list[client.Call] = []
        self.frames: list[list[dict]] = []

    def on(self, method: str, path: str, *answers: Any) -> None:
        """Queue what one method and path answer with."""
        self.answers.setdefault((method.upper(), path), []).extend(answers)

    def send(self, call: client.Call) -> Any:
        self.calls.append(call)
        queued = self.answers.get((call.method.upper(), call.path))
        if not queued:
            raise AssertionError(
                f"the CLI called {call.method} {call.path}, which this test never set up"
            )
        # The last answer stays put so a route can be asked twice without the
        # test having to know how many times a poll will come round.
        answer = queued.pop(0) if len(queued) > 1 else queued[0]
        if isinstance(answer, Exception):
            raise answer
        return answer(call) if callable(answer) else answer

    def open_stream(self, call: client.Call):
        self.calls.append(call)
        return iter(self.frames)

    def sent(self, method: str, path: str) -> list[client.Call]:
        """Every call made to one route, oldest first."""
        return [c for c in self.calls if c.method.upper() == method.upper() and c.path == path]

    def last(self, method: str, path: str) -> client.Call:
        """The most recent call to one route, for asserting on body and params."""
        matches = self.sent(method, path)
        if not matches:
            raise AssertionError(f"the CLI never called {method} {path}")
        return matches[-1]


@pytest.fixture
def api():
    fake = FakeAPI()
    client.set_transport(fake.send, fake.open_stream)
    yield fake
    client.set_transport()


@pytest.fixture
def profile():
    """The profile a command would have loaded, for testing a helper directly."""
    return client.Profile(URL, TOKEN)


@pytest.fixture
def run(api):
    """Run the CLI as a person would, and return the exit code."""

    def _run(*argv: str) -> int:
        return main(["--url", URL, "--token", TOKEN, *argv])

    return _run


@pytest.fixture
def api_function():
    """Build a function record with the shape GET /api/functions returns."""

    def _make(**overrides: Any) -> dict:
        record = {
            "id": "fn-1",
            "group_id": "grp-1",
            "namespace": "payments",
            "name": "create-charge",
            "method": "POST",
            "runtime": "python312",
            "runtime_label": "Python 3.12",
            "ctx_access": "rw",
            "function_type": "dependent",
            "idle_timeout_s": 0,
            "effective_idle_timeout_s": 300,
            "memory_mb": 128,
            "timeout_s": 30,
            "min_instances": 0,
            "max_instances": 1,
            "node_pool": "general",
            "auth_required": True,
            "status": "active",
            "path": "/payments/create-charge",
            "cluster": "prod",
            "url": "https://fn.example.com/payments/create-charge",
            "version": 3,
            "version_status": "ready",
            "stats": {
                "invocations": 12,
                "invocations_label": "12",
                "p50": "8ms",
                "p95": "21ms",
                "error_rate": "0%",
                "cold_rate": "0%",
                "errors": 0,
            },
        }
        return {**record, **overrides}

    return _make


# ── layout ───────────────────────────────────────────────────────────────────


def line(label: str, value: str, *, width: int = 16) -> str:
    """One rendered line of a `record()` block, padding and all.

    Tests care that a label carries a value, not how wide the gutter happens to
    be this month. Building the expectation with the renderer keeps them
    honest about the first and silent about the second, so the spacing can be
    adjusted in one place without a dozen assertions failing.
    """
    from cubicle_cli.client import record

    return record([(label, value)], label_width=width)


def cells(*values: str) -> str:
    """One rendered row of a `table()`, with whatever gutter it currently uses."""
    from cubicle_cli.client import table

    return table([""] * len(values), [list(values)]).splitlines()[-1]
