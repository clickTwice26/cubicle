"""The runtime catalogue and the operator commands, pinned to how the API behaves.

Both modules exist because of asymmetries that a status code alone hides. A
rebuild reports a failed build with HTTP 200 and a state in the body. An update
check reports "I could not check" with HTTP 200 and an error in the body. A
reconcile apply silently ignores a finding it cannot fix. Each of those reads
as success to a client that only looks at the response code, so each of them
has a test here.
"""

from __future__ import annotations

import re

from conftest import line

from cubicle_cli.__main__ import build_parser
from cubicle_cli.client import BUILD_TIMEOUT, CubicleError
from cubicle_cli.commands import ops

# ── the runtime catalogue ────────────────────────────────────────────────────

PYTHON = {
    "key": "python312",
    "label": "Python 3.12",
    "language": "Python",
    "image": "cubicle/runtime-python312:1.0.0",
    "base_image": "python:3.12-slim",
    "entry_file": "handler.py",
    "deps_file": "requirements.txt",
    "builtin": True,
    "summary": "The default runtime.",
    "installed": True,
    "functions": 4,
    "state": "idle",
}

NODE = {
    "key": "node18",
    "label": "Node 18",
    "language": "JavaScript",
    "image": "cubicle/runtime-node18:1.0.0",
    "base_image": "node:18-slim",
    "entry_file": "handler.js",
    "deps_file": "package.json",
    "builtin": False,
    "summary": "For a function that has not been moved off 18 yet.",
    "installed": False,
    "functions": 0,
    "state": "idle",
}


def _serve_runtimes(api, **node_overrides) -> dict:
    """The catalogue, with the removable Node runtime tweaked per test."""
    node = {**NODE, **node_overrides}
    api.on("GET", "/api/runtimes", [PYTHON, node])
    return node


def test_the_listing_names_the_files_each_runtime_reads(api, run, capsys):
    """This is the fact the CLI used to hardcode, and the reason node was unreachable."""
    _serve_runtimes(api)

    assert run("runtimes") == 0

    out = capsys.readouterr().out
    assert "handler.py + requirements.txt" in out
    assert "handler.js + package.json" in out
    assert "JavaScript" in out


def test_the_listing_marks_what_is_installed_and_what_ships_with_cubicle(api, run, capsys):
    """One of those decides whether a deploy can build; the other decides whether rm works."""
    _serve_runtimes(api)

    run("runtimes")

    out = capsys.readouterr().out
    assert "INSTALLED" in out
    assert "BUILT IN" in out
    # One row, whatever the gutter is this month: the point is that a runtime
    # carries its language, its file layout and its counts on one line.
    row = next(row for row in out.splitlines() if "python312" in l)
    assert re.search(r"python312\s+Python\s+handler\.py \+ requirements\.txt\s+yes\s+yes\s+4", row)
    row = next(row for row in out.splitlines() if "node18" in l)
    assert re.search(r"node18\s+JavaScript\s+handler\.js \+ package\.json\s+no\s+no\s+0", row)


def test_a_build_in_flight_is_reported_instead_of_the_flag(api, run, capsys):
    """`installed` is false all through a build, which is not the same as absent."""
    _serve_runtimes(api, state="installing")

    run("runtimes")

    assert "installing" in capsys.readouterr().out


def test_a_runtime_this_instance_never_heard_of_lists_the_ones_it_has(api, run, capsys):
    """The catalogue is a property of the instance, so the refusal quotes the instance."""
    _serve_runtimes(api)

    assert run("runtimes", "install", "node99") == 1

    err = capsys.readouterr().err
    assert "node99" in err
    assert "python312, node18" in err
    assert api.sent("POST", "/api/runtimes/node99/install") == []


def test_installing_waits_for_the_build_rather_than_the_default_minute(api, run):
    """The image is built inside the request, and a base image download is not sixty seconds."""
    _serve_runtimes(api)
    api.on("POST", "/api/runtimes/node18/install", {"state": "installed", "log": "", "error": ""})

    assert run("runtimes", "install", "node18") == 0

    assert api.last("POST", "/api/runtimes/node18/install").timeout == BUILD_TIMEOUT


def test_an_image_that_was_already_there_says_it_built_nothing(api, run, capsys):
    """Install is idempotent upstream, and a fast success reads as a lie without this."""
    _serve_runtimes(api)
    api.on(
        "POST",
        "/api/runtimes/node18/install",
        {"state": "installed", "log": "already installed", "error": ""},
    )

    assert run("runtimes", "install", "node18") == 0

    assert "it was already here" in capsys.readouterr().out


def test_a_failed_rebuild_is_not_reported_as_a_success(api, run, capsys):
    """Install turns a failed build into a 502; rebuild answers 200 and puts it in the body."""
    _serve_runtimes(api, installed=True)
    api.on(
        "POST",
        "/api/runtimes/node18/rebuild",
        {"state": "failed", "log": "step 3/7", "error": "no space left on device"},
    )

    assert run("runtimes", "rebuild", "node18") == 1

    out = capsys.readouterr().out
    assert "build failed" in out
    assert "no space left on device" in out


def test_a_build_that_outlasts_the_client_says_where_it_carries_on(api, run, capsys):
    """Nothing was cancelled by giving up here, so the message has to point at the catalogue."""
    _serve_runtimes(api)
    api.on("POST", "/api/runtimes/node18/install", TimeoutError("timed out"))

    assert run("runtimes", "install", "node18") == 1

    err = capsys.readouterr().err
    assert "cubicle runtimes" in err
    assert "installing" in err


def test_a_build_already_running_is_not_started_a_second_time(api, run, capsys):
    """The instance would refuse anyway; the catalogue already said so before asking."""
    _serve_runtimes(api, state="installing")

    assert run("runtimes", "install", "node18") == 1

    assert "already being built" in capsys.readouterr().err
    assert api.sent("POST", "/api/runtimes/node18/install") == []


def test_a_built_in_runtime_is_never_removed(api, run, capsys):
    """Python 3.12 comes back on the next update, so removing it only breaks the interim."""
    _serve_runtimes(api)

    assert run("--yes", "runtimes", "rm", "python312") == 1

    assert "ships with Cubicle" in capsys.readouterr().err
    assert api.sent("DELETE", "/api/runtimes/python312") == []


def test_a_runtime_something_is_written_in_is_not_removed(api, run, capsys):
    """The count is instance-wide, and every one of those functions stops building without it."""
    _serve_runtimes(api, functions=2)

    assert run("--yes", "runtimes", "rm", "node18") == 1

    err = capsys.readouterr().err
    assert "2 functions" in err
    assert api.sent("DELETE", "/api/runtimes/node18") == []


def test_removing_an_unused_runtime_asks_first(api, run, capsys):
    """There is no terminal under a test, so the refusal names the flag that would have done it."""
    _serve_runtimes(api, installed=True)

    assert run("runtimes", "rm", "node18") == 1

    assert "--yes" in capsys.readouterr().err
    assert api.sent("DELETE", "/api/runtimes/node18") == []


def test_removing_an_unused_runtime_goes_through_with_yes(api, run, capsys):
    """DELETE answers 200 with a body rather than 204, and either way the image is gone."""
    _serve_runtimes(api, installed=True)
    api.on("DELETE", "/api/runtimes/node18", {"key": "node18", "installed": False})

    assert run("--yes", "runtimes", "rm", "node18") == 0

    assert "removed" in capsys.readouterr().out
    assert api.sent("DELETE", "/api/runtimes/node18") != []


# ── update ───────────────────────────────────────────────────────────────────


def _status(**overrides) -> dict:
    """An UpdateStatus, which always carries every field even when the check failed."""
    base = {
        "current": "2a1b0a6f3c2d1e0987654321abcdef0123456789",
        "latest": "2a1b0a6f3c2d1e0987654321abcdef0123456789",
        "branch": "main",
        "repo": "cubicle/cubicle",
        "available": False,
        "message": "",
        "author": "",
        "date": "",
        "error": "",
        "cached": False,
    }
    return {**base, **overrides}


def test_update_says_what_the_branch_has_that_this_instance_does_not(api, run, capsys):
    """The commit is the thing an operator weighs before restarting a production box."""
    api.on(
        "GET",
        "/api/update",
        _status(
            latest="9f3c1d2aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            available=True,
            message="Let a runtime image be rebuilt from the console",
            author="Shagato",
            date="2026-08-09T11:00:00Z",
        ),
    )

    assert run("update") == 0

    out = capsys.readouterr().out
    assert line("deployed", "2a1b0a6") in out
    assert line("latest", "9f3c1d2") in out
    assert "Let a runtime image be rebuilt from the console" in out
    assert "Shagato, 2026-08-09" in out


def test_an_instance_that_could_not_be_checked_is_not_up_to_date(api, run, capsys):
    """The failure arrives as HTTP 200 with available=false, which is the trap."""
    api.on("GET", "/api/update", _status(error="GitHub is rate-limiting this address."))

    assert run("update") == 1

    out = capsys.readouterr().out
    assert "GitHub is rate-limiting this address." in out
    assert "up to date" not in out


def test_only_refresh_makes_the_instance_ask_github_again(api, run):
    """The answer is cached for fifteen minutes to stay inside an unauthenticated rate limit."""
    api.on("GET", "/api/update", _status(cached=True))

    run("update")
    assert api.last("GET", "/api/update").params == {"refresh": None}

    run("update", "--refresh")
    assert api.last("GET", "/api/update").params == {"refresh": "true"}


def test_applying_an_update_asks_before_restarting_the_instance(api, run, capsys):
    """This rebuilds and restarts everything, including the API being asked to do it."""
    api.on("GET", "/api/update", _status(available=True, latest="9f3c1d2", message="a commit"))

    assert run("update", "apply") == 1

    assert "--yes" in capsys.readouterr().err
    assert api.sent("POST", "/api/update/apply") == []


def test_applying_an_update_reads_the_updater_container_afterwards(api, run, capsys):
    """In-process state does not survive the restart; the updater's own logs do."""
    api.on("GET", "/api/update", _status(available=True, latest="9f3c1d2", message="a commit"))
    api.on("POST", "/api/update/apply", {"state": "running", "logs": "", "exit_code": None})
    api.on(
        "GET",
        "/api/update/progress",
        {"state": "success", "logs": "==> rebuilding and restarting\n==> done", "exit_code": 0},
    )

    assert run("--yes", "update", "apply") == 0

    out = capsys.readouterr().out
    assert "==> done" in out
    assert "updated" in out
    assert "9f3c1d2" in out


def test_an_update_that_refused_to_overwrite_local_changes_explains_itself(api, run, capsys):
    """Exit code 2 is the update declining to discard edits somebody made on the host."""
    api.on("GET", "/api/update", _status(available=True))
    api.on("POST", "/api/update/apply", {"state": "running", "logs": "", "exit_code": None})
    api.on(
        "GET",
        "/api/update/progress",
        {"state": "failed", "logs": "!! refusing to overwrite them", "exit_code": 2},
    )

    assert run("--yes", "update", "apply") == 1

    out = capsys.readouterr().out
    assert "update failed" in out
    assert "local changes to tracked files" in out


def test_a_dropped_connection_during_the_restart_counts_as_still_running(api, profile):
    """The control plane going away is this command working, not this command failing."""
    api.on("GET", "/api/update/progress", CubicleError("Could not reach https://cubicle.test"))

    assert ops._progress(profile)["state"] == "running"


# ── reconcile ────────────────────────────────────────────────────────────────


def _finding(finding_id: str, **overrides) -> dict:
    base = {
        "id": finding_id,
        "kind": "orphan_service_container",
        "severity": "warn",
        "cluster": "prod",
        "summary": "Data service cubicle-pg-prod belongs to nothing on record",
        "detail": "No database row points at it.",
        "fix": "Remove the container",
        "destructive": False,
        "target": {"container": "abc123"},
    }
    return {**base, **overrides}


def _report(*findings: dict) -> dict:
    return {
        "findings": list(findings),
        "errors": sum(1 for f in findings if f["severity"] == "error"),
        "warnings": sum(1 for f in findings if f["severity"] == "warn"),
        "fixable": sum(1 for f in findings if f["fix"] and not f["destructive"]),
    }


DRIFT = (
    _finding("orphan-service:abc123"),
    _finding(
        "orphan-volume:local:pgdata",
        kind="orphan_volume",
        cluster="",
        summary="Volume pgdata is held by no service",
        fix="Delete the volume and everything in it",
        destructive=True,
    ),
    _finding(
        "node-unreachable:tcp://10.0.0.4:2375",
        kind="node_unreachable",
        severity="error",
        summary="Node worker-02 is not answering",
        fix=None,
    ),
)


def test_reconcile_prints_the_id_that_apply_takes(api, run, capsys):
    """A finding is only actionable if the operator can name it on the next line they type."""
    api.on("GET", "/api/reconcile", _report(*DRIFT))

    assert run("reconcile") == 0

    out = capsys.readouterr().out
    assert "orphan-service:abc123" in out
    assert "Remove the container" in out
    assert "no automatic fix" in out
    assert "1 fixable" in out


def test_an_instance_with_no_drift_says_so(api, run, capsys):
    """An empty report is the good outcome and should read like one."""
    api.on("GET", "/api/reconcile", _report())

    assert run("reconcile") == 0

    assert "in sync" in capsys.readouterr().out


def test_apply_with_no_ids_leaves_the_destructive_findings_where_they_are(api, run):
    """Deleting the only copy of somebody's data is not a default."""
    api.on("GET", "/api/reconcile", _report(*DRIFT))
    api.on(
        "POST",
        "/api/reconcile/apply",
        {"applied": ["orphan-service:abc123"], "failed": [], "skipped": [], "report": _report()},
    )

    assert run("--yes", "reconcile", "apply") == 0

    assert api.last("POST", "/api/reconcile/apply").body == {"ids": ["orphan-service:abc123"]}


def test_a_destructive_finding_is_applied_when_it_is_named(api, run, capsys):
    """Naming the id is the operator saying they meant this one in particular."""
    api.on("GET", "/api/reconcile", _report(*DRIFT))
    api.on(
        "POST",
        "/api/reconcile/apply",
        {
            "applied": ["orphan-volume:local:pgdata"],
            "failed": [],
            "skipped": [],
            "report": _report(),
        },
    )

    assert run("--yes", "reconcile", "apply", "orphan-volume:local:pgdata") == 0

    out = capsys.readouterr().out
    assert "destroys data" in out
    assert api.last("POST", "/api/reconcile/apply").body == {"ids": ["orphan-volume:local:pgdata"]}


def test_a_finding_with_no_fix_is_refused_rather_than_sent(api, run, capsys):
    """The API ignores those silently, and a silent no-op is the worst possible answer."""
    api.on("GET", "/api/reconcile", _report(*DRIFT))

    assert run("--yes", "reconcile", "apply", "node-unreachable:tcp://10.0.0.4:2375") == 1

    assert "no automatic fix" in capsys.readouterr().err
    assert api.sent("POST", "/api/reconcile/apply") == []


def test_an_id_that_is_not_in_the_report_names_itself(api, run, capsys):
    """Findings are re-scanned on every call, so a stale id is a thing people will type."""
    api.on("GET", "/api/reconcile", _report(*DRIFT))

    assert run("--yes", "reconcile", "apply", "orphan-volume:local:gone") == 1

    assert "orphan-volume:local:gone" in capsys.readouterr().err


def test_what_each_fix_actually_did_is_printed(api, run, capsys):
    """Applied, failed and resolved-in-between are three different outcomes in one response."""
    api.on("GET", "/api/reconcile", _report(*DRIFT))
    api.on(
        "POST",
        "/api/reconcile/apply",
        {
            "applied": ["orphan-service:abc123"],
            "failed": [{"id": "orphan-volume:local:pgdata", "error": "volume is in use"}],
            "skipped": ["node-unreachable:tcp://10.0.0.4:2375"],
            "report": _report(DRIFT[2]),
        },
    )

    assert (
        run(
            "--yes",
            "reconcile",
            "apply",
            "orphan-service:abc123",
            "orphan-volume:local:pgdata",
        )
        == 1
    )

    out = capsys.readouterr().out
    assert "fixed          Data service cubicle-pg-prod belongs to nothing on record" in out
    assert "volume is in use" in out
    assert "resolved itself" in out
    assert "1 breaking" in out


def test_applying_a_reconcile_is_given_longer_than_a_read(api, run):
    """One request is three full scans of every node, and a slow node is what it is fixing."""
    api.on("GET", "/api/reconcile", _report(*DRIFT))
    api.on(
        "POST",
        "/api/reconcile/apply",
        {"applied": [], "failed": [], "skipped": [], "report": _report()},
    )

    run("--yes", "reconcile", "apply")

    assert api.last("POST", "/api/reconcile/apply").timeout == BUILD_TIMEOUT


# ── metering ─────────────────────────────────────────────────────────────────

USAGE = {
    "cluster": "prod",
    "window_start": "2026-08-01T00:00:00Z",
    "window_end": "2026-09-01T00:00:00Z",
    "window_progress": 32.0,
    "invocations": 12345,
    "invocations_label": "12,345",
    "gb_seconds": 1234.5,
    "gb_seconds_label": "1,234.5",
    "egress_bytes": 1288490188,
    "egress_label": "1.2 GB",
    "storage_bytes": 4831838208,
    "storage_label": "4.5 GB",
    "namespaces": [
        {
            "name": "payments",
            "invocations": 9000,
            "invocations_label": "9,000",
            "gb_seconds": 800.1,
            "gb_seconds_label": "800.1",
        }
    ],
    "warm_isolates": 3,
    "cost": {
        "rows": [],
        "self_hosted_total": 0.12,
        "avoided_vs_aws": 41.2,
        "rates_as_of": "2026-07",
        "kwh_price": 0.11,
    },
}


def test_metering_shows_the_month_and_where_it_went(api, run, capsys):
    """The window is a calendar month, and the namespaces are who spent it."""
    api.on("GET", "/api/cluster/metering", USAGE)

    assert run("metering") == 0

    out = capsys.readouterr().out
    assert line("window", "2026-08-01 to 2026-09-01 (32% through)") in out
    assert line("invocations", "12,345") in out
    row = next(row for row in out.splitlines() if "payments" in l)
    assert re.search(r"payments\s+9,000\s+800\.1", row)
    assert "$0.12 of electricity" in out


def test_the_csv_export_is_passed_through_rather_than_decoded(api, run, capsys):
    """It is text/csv, and json.loads on a CSV file is how that endpoint breaks a client."""
    api.on(
        "GET",
        "/api/cluster/metering/export.csv",
        b"cluster,namespace,invocations\nprod,payments,9000\n",
    )

    assert run("metering", "--csv") == 0

    assert api.last("GET", "/api/cluster/metering/export.csv").raw is True
    assert capsys.readouterr().out == "cluster,namespace,invocations\nprod,payments,9000\n"


# ── parsing ──────────────────────────────────────────────────────────────────


def test_the_question_needs_no_sub_verb():
    """`cubicle runtimes` and `cubicle update` are questions; the verbs hang off them."""
    for argv in (["runtimes"], ["update"], ["reconcile"], ["metering"]):
        assert build_parser().parse_args(argv).command == argv[0]
