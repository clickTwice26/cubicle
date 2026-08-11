"""One function: what is running, what it costs, and what may be changed.

These pin three things that are easy to get wrong from a terminal. The bounds
FunctionUpdate enforces are checked before a request is built, so a typo is a
sentence rather than a 422. A refusal that only the cluster could have made is
printed in the cluster's own words. And nothing destructive happens without
somebody having said so.
"""

from __future__ import annotations

from conftest import line

from cubicle_cli.client import CubicleError

CATALOGUE = [
    {"key": "python312", "label": "Python 3.12", "installed": True},
    {"key": "node22", "label": "Node 22", "installed": True},
]


class _Stdin:
    """Stands in for a terminal that answers, or for one that is not there."""

    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _ctrl_d(prompt: str = "") -> str:
    """What `input` does when the terminal is closed under it."""
    raise EOFError


def _typed(monkeypatch, answer: str) -> list[str]:
    """Sit somebody at a terminal who types one thing, and keep every prompt."""
    prompts: list[str] = []

    def _input(prompt: str = "") -> str:
        prompts.append(prompt)
        return answer

    monkeypatch.setattr("sys.stdin", _Stdin(tty=True))
    monkeypatch.setattr("builtins.input", _input)
    return prompts


def _isolate(**overrides) -> dict:
    """One entry of the pool snapshot, as GET .../isolates returns them."""
    entry = {
        "id": "a1b2c3d4e5f6",
        "cluster": "prod",
        "function": "create-charge",
        "namespace": "payments",
        "function_id": "fn-1",
        "version_id": "ver-3",
        "node": "node-01",
        "busy": False,
        "invocations": 41,
        "memory_mb": 128,
        "cpus": 0.5,
        "age_s": 903.0,
        "idle_s": 12.0,
    }
    return {**entry, **overrides}


def _pool(*isolates: dict, warm: int = 0, ceiling: int = 1) -> dict:
    return {
        "isolates": list(isolates),
        "min_instances": warm,
        "max_instances": ceiling,
        "memory_mb": 128,
        "version": 3,
    }


def _build(number: int, **overrides) -> dict:
    build = {
        "id": f"ver-{number}",
        "number": number,
        "status": "ready",
        "build_ms": 910,
        "build_log": f"built v{number}\n",
        "created_at": "2026-08-10T14:03:31.412000Z",
        "deployed_at": "2026-08-10T14:03:40.100000Z",
    }
    return {**build, **overrides}


def _metrics(*, invocations, latency, **stats) -> dict:
    return {
        "stats": {
            "invocations": 120,
            "invocations_label": "120",
            "p50": "8ms",
            "p90": "30ms",
            "p95": "40ms",
            "p99": "90ms",
            "error_rate": "2%",
            "cold_rate": "12%",
            "gb_seconds": 0.5,
            "last_invocation": "2026-08-10T14:03:31.412000Z",
            **stats,
        },
        "latency": [
            {"bucket": str(i), "p95": v, "fill": 0.0, "cold": 0, "cold_pct": 0.0}
            for i, v in enumerate(latency)
        ],
        "invocations": [{"bucket": str(i), "ok": v, "err": 0} for i, v in enumerate(invocations)],
    }


# ── instances and kill ───────────────────────────────────────────────────────


def test_the_table_names_the_container_and_says_what_it_is_doing(api, run, api_function, capsys):
    """The id is what `cubicle kill` takes, and busy is why you would think twice."""
    api.on("GET", "/api/functions", [api_function()])
    api.on("GET", "/api/functions/fn-1/isolates", _pool(_isolate(busy=True), ceiling=4))

    assert run("instances", "payments/create-charge") == 0

    out = capsys.readouterr().out
    assert "a1b2c3d4e5f6" in out
    assert "node-01" in out
    assert "busy" in out
    # 903 seconds of uptime, twelve of them idle.
    assert "15m" in out
    assert "12s" in out


def test_an_empty_pool_is_still_counted_against_the_ceiling(api, run, api_function, capsys):
    """Nothing running is the resting state of a function nobody is calling."""
    api.on("GET", "/api/functions", [api_function()])
    api.on("GET", "/api/functions/fn-1/isolates", _pool(ceiling=4, warm=1))

    assert run("instances", "payments/create-charge") == 0

    out = capsys.readouterr().out
    assert "(nothing to show)" in out
    assert "0 running of max 4" in out
    assert "1 kept warm" in out


def test_an_id_this_function_does_not_have_never_reaches_the_api(api, run, api_function, capsys):
    """A mistyped id is a typo, and the API would answer it with a 404 after the prompt."""
    api.on("GET", "/api/functions", [api_function()])
    api.on("GET", "/api/functions/fn-1/isolates", _pool(_isolate()))

    assert run("kill", "payments/create-charge", "deadbeef0000") == 1

    assert "deadbeef0000" in capsys.readouterr().err
    assert api.sent("DELETE", "/api/functions/fn-1/isolates/deadbeef0000") == []


def test_the_question_says_whether_the_container_is_busy(api, run, api_function, monkeypatch):
    """Destroying a busy isolate fails the call it is serving, which is worth being told."""
    api.on("GET", "/api/functions", [api_function()])
    api.on("GET", "/api/functions/fn-1/isolates", _pool(_isolate(busy=True)))
    api.on("DELETE", "/api/functions/fn-1/isolates/a1b2c3d4e5f6", None)
    prompts = _typed(monkeypatch, "y")

    assert run("kill", "payments/create-charge", "a1b2c3d4e5f6") == 0

    assert "serving a request right now" in prompts[0]
    assert "node-01" in prompts[0]


def test_a_declined_kill_destroys_nothing(api, run, api_function, monkeypatch, capsys):
    """Answering anything but yes is answering no."""
    api.on("GET", "/api/functions", [api_function()])
    api.on("GET", "/api/functions/fn-1/isolates", _pool(_isolate()))
    _typed(monkeypatch, "n")

    assert run("kill", "payments/create-charge", "a1b2c3d4e5f6") == 1

    assert "cancelled" in capsys.readouterr().out
    assert api.sent("DELETE", "/api/functions/fn-1/isolates/a1b2c3d4e5f6") == []


def test_a_kill_with_nobody_to_ask_names_the_flag(api, run, api_function, capsys):
    """A pipe cannot be asked, and assuming yes for it is how a script destroys a pool."""
    api.on("GET", "/api/functions", [api_function()])
    api.on("GET", "/api/functions/fn-1/isolates", _pool(_isolate()))

    assert run("kill", "payments/create-charge", "a1b2c3d4e5f6") == 1

    assert "--yes" in capsys.readouterr().err
    assert api.sent("DELETE", "/api/functions/fn-1/isolates/a1b2c3d4e5f6") == []


# ── scale ────────────────────────────────────────────────────────────────────


def test_scale_sends_only_the_knob_that_was_named(api, run, api_function):
    """PATCH is exclude_unset, so an untouched key has to stay out of the body."""
    api.on("GET", "/api/functions", [api_function()])
    api.on("PATCH", "/api/functions/fn-1", api_function(max_instances=4))

    assert run("scale", "payments/create-charge", "--max", "4") == 0

    assert api.last("PATCH", "/api/functions/fn-1").body == {"max_instances": 4}


def test_a_ceiling_the_api_would_refuse_is_refused_here(api, run, capsys, api_function):
    """PATCH stops max_instances at 32 where create allows 64, and 422s read badly."""
    api.on("GET", "/api/functions", [api_function()])

    assert run("scale", "payments/create-charge", "--max", "64") == 1

    assert "--max takes 1 to 32" in capsys.readouterr().err
    assert api.sent("PATCH", "/api/functions/fn-1") == []


def test_a_ceiling_below_the_warm_floor_is_caught_against_the_stored_value(
    api, run, capsys, api_function
):
    """Only one half of the pair was typed; the other half is what the function already has."""
    api.on("GET", "/api/functions", [api_function(min_instances=2, max_instances=8)])

    assert run("scale", "payments/create-charge", "--max", "1") == 1

    assert "below the 2 warm instance(s)" in capsys.readouterr().err
    assert api.sent("PATCH", "/api/functions/fn-1") == []


def test_scale_with_no_flags_changes_nothing(api, run, capsys, api_function):
    """`cubicle scale ns/fn` alone is a question, and PATCH is not how you ask one."""
    api.on("GET", "/api/functions", [api_function()])

    assert run("scale", "payments/create-charge") == 1

    assert "--min, --max or both" in capsys.readouterr().err
    assert api.sent("PATCH", "/api/functions/fn-1") == []


def test_the_ceiling_is_explained_as_a_ceiling(api, run, capsys, api_function):
    """The pool waits for a busy isolate before it spawns, so max is not a target."""
    api.on("GET", "/api/functions", [api_function()])
    api.on("PATCH", "/api/functions/fn-1", api_function(max_instances=6))

    run("scale", "payments/create-charge", "--max", "6")

    out = capsys.readouterr().out
    assert "set payments/create-charge to 0-6 instances" in out
    assert "a ceiling, not a target" in out


def test_a_refusal_from_the_cluster_is_printed_in_its_own_words(api, run, capsys, api_function):
    """Allocation against the cluster ceiling is something only the cluster can decide."""
    api.on("GET", "/api/functions", [api_function(max_instances=8)])
    api.on(
        "PATCH",
        "/api/functions/fn-1",
        CubicleError("409: 4 warm instances at 512 MB would take prod past its 2048 MB ceiling."),
    )

    assert run("scale", "payments/create-charge", "--min", "4") == 1

    assert "would take prod past its 2048 MB ceiling" in capsys.readouterr().err


# ── config ───────────────────────────────────────────────────────────────────


def test_config_with_no_flags_only_reads(api, run, capsys, api_function):
    """It is the settings page of a function, and reading one changes nothing."""
    api.on("GET", "/api/functions", [api_function()])

    assert run("config", "payments/create-charge") == 0

    out = capsys.readouterr().out
    assert line("memory", "128 MB") in out
    assert line("timeout", "30s") in out
    assert line("instances", "0-1") in out
    assert api.sent("PATCH", "/api/functions/fn-1") == []


def test_an_idle_timeout_of_zero_shows_what_it_resolves_to(api, run, capsys, api_function):
    """Zero means "whatever the instance says", and the number it means is the useful one."""
    api.on("GET", "/api/functions", [api_function(idle_timeout_s=0, effective_idle_timeout_s=300)])

    run("config", "payments/create-charge")

    assert "300s (instance default)" in capsys.readouterr().out


def test_config_patches_exactly_what_was_named(api, run, api_function):
    """Anything absent from the body is left as it was, which is the point of PATCH."""
    api.on("GET", "/api/functions", [api_function()])
    api.on("PATCH", "/api/functions/fn-1", api_function(memory_mb=256, auth_required=False))

    assert run("config", "payments/create-charge", "--memory", "256", "--auth", "false") == 0

    assert api.last("PATCH", "/api/functions/fn-1").body == {
        "memory_mb": 256,
        "auth_required": False,
    }


def test_a_memory_size_outside_the_bounds_never_leaves_the_machine(api, run, capsys, api_function):
    """32 to 8192 MB, and a 422 would name memory_mb rather than the flag that was typed."""
    api.on("GET", "/api/functions", [api_function()])

    assert run("config", "payments/create-charge", "--memory", "16") == 1

    assert "--memory takes 32 to 8192" in capsys.readouterr().err
    assert api.sent("PATCH", "/api/functions/fn-1") == []


def test_changing_the_runtime_says_the_files_are_left_alone(api, run, capsys, api_function):
    """A rebuild under a new interpreter reuses the old bundle, and handler.py is not handler.js."""
    api.on("GET", "/api/functions", [api_function()])
    api.on("GET", "/api/runtimes", CATALOGUE)
    api.on("PATCH", "/api/functions/fn-1", api_function(runtime="node22"))

    assert run("config", "payments/create-charge", "--runtime", "node22") == 0

    out = capsys.readouterr().out
    assert api.last("PATCH", "/api/functions/fn-1").body == {"runtime": "node22"}
    assert "rebuilding the current version as Node 22 in the background" in out
    assert "the files are kept as they are" in out


def test_a_runtime_this_instance_lacks_is_named_before_anything_is_sent(
    api, run, capsys, api_function
):
    """`runtime` is a schema enum, so the alternative is a 422 that lists none of the keys."""
    api.on("GET", "/api/functions", [api_function()])
    api.on("GET", "/api/runtimes", CATALOGUE)

    assert run("config", "payments/create-charge", "--runtime", "node99") == 1

    err = capsys.readouterr().err
    assert "python312, node22" in err
    assert api.sent("PATCH", "/api/functions/fn-1") == []


# ── pause, resume, versions and metrics ──────────────────────────────────────


def test_pause_says_that_the_isolates_went_with_it(api, run, capsys, api_function):
    """Pausing drains the pool immediately, so the next call is a cold start at best."""
    api.on("GET", "/api/functions", [api_function()])
    api.on("PATCH", "/api/functions/fn-1", api_function(status="paused"))

    assert run("pause", "payments/create-charge") == 0

    assert api.last("PATCH", "/api/functions/fn-1").body == {"status": "paused"}
    assert "every isolate was drained" in capsys.readouterr().out


def test_resume_puts_it_back_on_the_version_it_had(api, run, capsys, api_function):
    api.on("GET", "/api/functions", [api_function(status="paused")])
    api.on("PATCH", "/api/functions/fn-1", api_function(version=4))

    assert run("resume", "payments/create-charge") == 0

    assert api.last("PATCH", "/api/functions/fn-1").body == {"status": "active"}
    assert "resumed payments/create-charge on v4" in capsys.readouterr().out


def test_versions_marks_the_build_that_is_serving(api, run, capsys, api_function):
    """Twenty-five builds look alike, and only one of them is answering requests."""
    api.on("GET", "/api/functions", [api_function(version=3)])
    api.on(
        "GET",
        "/api/functions/fn-1/versions",
        [_build(4, status="failed", deployed_at=None), _build(3), _build(2)],
    )

    assert run("versions", "payments/create-charge") == 0

    out = capsys.readouterr().out
    assert "* v3" in out
    assert "  v4" in out
    # A build that never deployed has no deploy time to print.
    assert "failed" in out
    assert "never" in out
    assert "2026-08-10 14:03" in out


def test_a_build_log_is_read_out_of_the_listing(api, run, capsys, api_function):
    """The versions payload already carries every log, so reading one costs no second call."""
    api.on("GET", "/api/functions", [api_function()])
    api.on(
        "GET",
        "/api/functions/fn-1/versions",
        [_build(4, status="failed", build_log="ERROR: no matching distribution\n"), _build(3)],
    )

    assert run("versions", "payments/create-charge", "--log", "4") == 0

    assert "no matching distribution" in capsys.readouterr().out
    assert len(api.sent("GET", "/api/functions/fn-1/versions")) == 1


def test_asking_for_a_build_that_is_not_there_says_how_many_are(api, run, capsys, api_function):
    """The API keeps the last 25 and offers no way to page past them."""
    api.on("GET", "/api/functions", [api_function()])
    api.on("GET", "/api/functions/fn-1/versions", [_build(3)])

    assert run("versions", "payments/create-charge", "--log", "99") == 1

    assert "this function has 1" in capsys.readouterr().err


def test_metrics_asks_for_the_window_it_was_given(api, run, api_function):
    """`hours` has no bounds in the API at all, so what is sent is what is honoured."""
    api.on("GET", "/api/functions", [api_function()])
    api.on("GET", "/api/functions/fn-1/metrics", _metrics(invocations=[1], latency=[1.0]))

    assert run("metrics", "payments/create-charge", "--hours", "6") == 0

    assert api.last("GET", "/api/functions/fn-1/metrics").params == {"hours": 6}


def test_a_window_the_api_would_pass_to_sql_is_refused_first(api, run, capsys, api_function):
    """A negative hours reaches the query unvalidated, so it stops here."""
    api.on("GET", "/api/functions", [api_function()])

    assert run("metrics", "payments/create-charge", "--hours", "0") == 1

    assert "--hours takes 1 to 720" in capsys.readouterr().err
    assert api.sent("GET", "/api/functions/fn-1/metrics") == []


def test_metrics_draws_where_in_the_window_the_traffic_was(api, run, capsys, api_function):
    """A percentile says how bad it got; the series says whether it is still happening."""
    api.on("GET", "/api/functions", [api_function()])
    api.on(
        "GET",
        "/api/functions/fn-1/metrics",
        _metrics(invocations=[0, 0, 100], latency=[0.0, 0.0, 250.0]),
    )

    assert run("metrics", "payments/create-charge") == 0

    out = capsys.readouterr().out
    assert "120  ▁▁█" in out
    assert "40ms  ▁▁█" in out
    # The metrics block sets its own label column, wide enough for
    # LAST INVOCATION, so the expectation has to be built the same way.
    assert line("cold starts", "12%", width=18) in out


def test_a_function_nobody_called_says_so_rather_than_drawing_a_flat_line(
    api, run, capsys, api_function
):
    """An empty series and a series of zeroes look identical, and neither is a shape."""
    api.on("GET", "/api/functions", [api_function()])
    api.on(
        "GET",
        "/api/functions/fn-1/metrics",
        _metrics(invocations=[0, 0], latency=[0.0, 0.0], invocations_label="0"),
    )

    run("metrics", "payments/create-charge")

    assert "(no traffic in this window)" in capsys.readouterr().out


# ── rm ───────────────────────────────────────────────────────────────────────


def test_deleting_a_function_wants_its_name_typed_back(api, run, api_function, monkeypatch):
    """y is one keystroke, and this takes the versions, the secrets and the schedules."""
    api.on("GET", "/api/functions", [api_function()])
    api.on("DELETE", "/api/functions/fn-1", None)
    prompts = _typed(monkeypatch, "payments/create-charge")

    assert run("rm", "payments/create-charge") == 0

    assert "Type payments/create-charge to confirm" in prompts[0]
    assert api.sent("DELETE", "/api/functions/fn-1") != []


def test_the_wrong_name_deletes_nothing(api, run, api_function, monkeypatch, capsys):
    """Confirming the wrong function is the mistake the prompt exists to catch."""
    api.on("GET", "/api/functions", [api_function()])
    _typed(monkeypatch, "create-charge")

    assert run("rm", "payments/create-charge") == 1

    assert "cancelled" in capsys.readouterr().out
    assert api.sent("DELETE", "/api/functions/fn-1") == []


def test_rm_with_no_terminal_says_which_flag_would_have_done_it(api, run, capsys, api_function):
    """A pipe has nobody to type the name, and guessing on its behalf is not an option."""
    api.on("GET", "/api/functions", [api_function()])

    assert run("rm", "payments/create-charge") == 1

    err = capsys.readouterr().err
    assert "--yes" in err
    assert "every version, secret and trigger" in err
    assert api.sent("DELETE", "/api/functions/fn-1") == []


def test_yes_deletes_without_asking(api, run, capsys, api_function):
    """A script that has said --yes has already answered the question."""
    api.on("GET", "/api/functions", [api_function()])
    api.on("DELETE", "/api/functions/fn-1", None)

    assert run("--yes", "rm", "payments/create-charge") == 0

    assert "removed payments/create-charge and every version of it" in capsys.readouterr().out


def test_yes_is_taken_after_the_command_too(api, run, capsys, api_function):
    """The spelling the no-terminal refusal asks for, which argparse used to reject."""
    api.on("GET", "/api/functions", [api_function()])
    api.on("DELETE", "/api/functions/fn-1", None)

    assert run("rm", "payments/create-charge", "--yes") == 0

    assert "removed payments/create-charge and every version of it" in capsys.readouterr().out


def test_ctrl_d_at_the_prompt_cancels_rather_than_crashing(
    api, run, capsys, api_function, monkeypatch
):
    """Walking away from the question leaves the function where it was."""
    api.on("GET", "/api/functions", [api_function()])
    monkeypatch.setattr("sys.stdin", _Stdin(tty=True))
    monkeypatch.setattr("builtins.input", _ctrl_d)

    assert run("rm", "payments/create-charge") == 1

    assert "cancelled" in capsys.readouterr().out
    assert api.sent("DELETE", "/api/functions/fn-1") == []
