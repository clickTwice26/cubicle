"""The shared helpers in client.py, which several command modules build on.

Their signatures are fixed, so these are as much a description of the contract
as a test of it.
"""

from __future__ import annotations

import pytest

from cubicle_cli.client import (
    CubicleError,
    confirm,
    ensure_group,
    find_function,
    find_group,
    poll,
    record,
    split_target,
    table,
    wait_for_version,
)


class _Stdin:
    """Stands in for a terminal that answers, or for one that is not there."""

    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _ctrl_d(prompt: str = "") -> str:
    """What `input` does when the terminal is closed under it."""
    raise EOFError


def test_a_target_splits_into_namespace_and_function():
    assert split_target("payments/create-charge") == ("payments", "create-charge")


def test_a_target_without_a_slash_says_what_one_looks_like():
    with pytest.raises(CubicleError, match="namespace"):
        split_target("create-charge")


def test_a_function_is_found_by_its_written_name(api, profile, api_function):
    """The API addresses functions by UUID, and nobody types one."""
    api.on("GET", "/api/functions", [api_function(name="refund", id="fn-2"), api_function()])

    assert find_function(profile, "payments/create-charge")["id"] == "fn-1"


def test_a_function_that_is_not_there_names_what_was_looked_for(api, profile):
    api.on("GET", "/api/functions", [])

    with pytest.raises(CubicleError, match="payments/create-charge"):
        find_function(profile, "payments/create-charge")


def test_a_namespace_resolves_to_its_group(api, profile):
    """Creating a function and installing a package both need the group id."""
    api.on("GET", "/api/groups", [{"id": "grp-1", "ns": "payments"}])

    assert find_group(profile, "payments")["id"] == "grp-1"


def test_ensure_group_creates_only_what_is_missing(api, profile):
    api.on("GET", "/api/groups", [{"id": "grp-1", "ns": "payments"}])

    assert ensure_group(profile, "payments") == ({"id": "grp-1", "ns": "payments"}, False)
    assert api.sent("POST", "/api/groups") == []


def test_ensure_group_reports_the_one_it_made(api, profile):
    """The caller says "created", because only it knows how to phrase that."""
    api.on("GET", "/api/groups", [])
    api.on("POST", "/api/groups", {"id": "grp-2", "ns": "billing"})

    group, created = ensure_group(profile, "billing")

    assert (group["ns"], created) == ("billing", True)
    assert api.last("POST", "/api/groups").body == {"name": "billing"}


def test_a_record_lines_the_values_up_where_status_always_had_them():
    assert record([("control plane", "ready")]) == "  CONTROL PLANE     ready"


def test_a_long_label_widens_the_column_rather_than_wrapping():
    label = "a much longer label"
    block = record([(label, "x"), ("cpu", "y")])

    assert block.splitlines()[1] == "  " + "CPU".ljust(len(label) + 2) + "y"


def test_an_empty_record_says_so_like_an_empty_table():
    assert record([]) == table(["anything"], [])


def test_yes_answers_the_question(capsys):
    assert confirm("Delete everything?", assume_yes=True) is True
    assert capsys.readouterr().out == ""


def test_a_pipe_is_not_asked_and_not_assumed(monkeypatch):
    """Blocking forever and guessing yes are both worse than saying which flag."""
    monkeypatch.setattr("sys.stdin", _Stdin(tty=False))

    with pytest.raises(CubicleError, match="--yes"):
        confirm("Delete everything?")


def test_a_terminal_is_asked_and_believed(monkeypatch):
    monkeypatch.setattr("sys.stdin", _Stdin(tty=True))
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    assert confirm("Delete everything?") is True


def test_anything_but_yes_is_no(monkeypatch):
    monkeypatch.setattr("sys.stdin", _Stdin(tty=True))
    monkeypatch.setattr("builtins.input", lambda prompt: "")

    assert confirm("Delete everything?") is False


def test_ctrl_d_is_no_rather_than_a_traceback(monkeypatch):
    """End of input is nothing typed, and nothing typed is already an answer."""
    monkeypatch.setattr("sys.stdin", _Stdin(tty=True))
    monkeypatch.setattr("builtins.input", _ctrl_d)

    assert confirm("Delete everything?") is False


def test_polling_stops_as_soon_as_the_work_is_done():
    answers = iter([{"state": "running"}, {"state": "running"}, {"state": "success"}])

    assert poll(lambda: next(answers), done=lambda r: r["state"] != "running", interval=0) == {
        "state": "success"
    }


def test_polling_gives_up_rather_than_hanging():
    with pytest.raises(CubicleError, match="Still not finished"):
        poll(lambda: "running", done=lambda r: False, timeout=0, interval=0)


def test_waiting_for_a_build_ends_on_ready(api, profile, api_function):
    """Creating a function answers before the build has started."""
    api.on(
        "GET",
        "/api/functions/fn-1",
        api_function(version_status="pending"),
        api_function(version_status="ready"),
    )

    result = wait_for_version(profile, "fn-1", interval=0)

    assert result["version_status"] == "ready"
    assert len(api.sent("GET", "/api/functions/fn-1")) == 2


def test_waiting_for_a_build_ends_on_failed_too(api, profile, api_function):
    """A failed build is finished; whether that is bad news is the caller's call."""
    api.on("GET", "/api/functions/fn-1", api_function(version_status="failed"))

    assert wait_for_version(profile, "fn-1", interval=0)["version_status"] == "failed"
