"""The CLI has no version of its own. The commit is the version.

Everything in this repository shares one version string, and it does not move
between releases: the API, the console and this program all say 1.0.0 whatever
has changed. So "am I current" cannot be answered by comparing versions, and is
instead the same question the instance already asks about itself, against the
same branch head.

That means `cubicle update` can answer for both without a second round trip and
without the CLI ever talking to GitHub itself.
"""

from __future__ import annotations

import pytest

from cubicle_cli.client import build_id
from cubicle_cli.commands import ops

HEAD = "cefffc6a1b2c3d4e5f60718293a4b5c6d7e8f900"
OLDER = "9ca018f4950e128f439afd38c4df12a0124018cd"


def _status(**overrides) -> dict:
    base = {
        "current": OLDER,
        "latest": HEAD,
        "branch": "main",
        "repo": "clickTwice26/cubicle",
        "available": True,
        "message": "something changed",
        "author": "Shagato",
        "date": "2026-08-11",
        "error": "",
        "cached": False,
    }
    return {**base, **overrides}


@pytest.fixture
def commit(monkeypatch):
    """Pretend this copy was installed from a particular commit."""

    def _set(value: str) -> None:
        monkeypatch.setattr(ops, "installed_commit", lambda: value)

    return _set


# ── what the commit means ────────────────────────────────────────────────────


def test_a_copy_on_the_branch_head_is_current(api, run, capsys, commit):
    commit(HEAD)
    api.on("GET", "/api/update", _status())

    run("update")

    out = capsys.readouterr().out
    assert "current" in out
    assert "pipx upgrade" not in out


def test_a_copy_behind_the_head_names_both_commits_and_the_fix(api, run, capsys, commit):
    """Behind by any amount is behind. The count would need GitHub, and does not matter."""
    commit(OLDER)
    api.on("GET", "/api/update", _status())

    run("update")

    out = capsys.readouterr().out
    assert OLDER[:7] in out
    assert f"behind {HEAD[:7]}" in out
    assert "pipx upgrade cubicle-cli" in out


def test_the_instance_being_up_to_date_says_nothing_about_the_cli(api, run, capsys, commit):
    """The two move independently: an instance can be current while this is not."""
    commit(OLDER)
    api.on("GET", "/api/update", _status(current=HEAD, available=False))

    run("update")

    out = capsys.readouterr().out
    assert "up to date" in out  # the instance
    assert f"behind {HEAD[:7]}" in out  # and this program, which is not


# ── when the answer is not knowable ──────────────────────────────────────────


def test_a_source_checkout_is_not_guessed_at(api, run, capsys, commit):
    """Running from a clone records no commit, so there is nothing to compare."""
    commit("")
    api.on("GET", "/api/update", _status())

    run("update")

    out = capsys.readouterr().out
    assert "behind" not in out
    assert "updated separately" in out


def test_github_being_unreachable_is_not_reported_as_current(api, run, capsys, commit):
    """No branch head means no comparison. Saying "current" would be a guess."""
    commit(OLDER)
    api.on("GET", "/api/update", _status(latest="", error="", available=False))

    run("update")

    out = capsys.readouterr().out
    assert "not known" in out
    assert "current" not in out


# ── how a build identifies itself ────────────────────────────────────────────


def test_the_build_id_carries_the_commit_when_there_is_one(monkeypatch):
    from cubicle_cli import client

    monkeypatch.setattr(client, "installed_commit", lambda: HEAD)
    assert build_id() == f"1.0.0 ({HEAD[:7]})"


def test_the_build_id_falls_back_to_the_version_alone(monkeypatch):
    from cubicle_cli import client

    monkeypatch.setattr(client, "installed_commit", lambda: "")
    assert build_id() == "1.0.0"


def test_the_version_matches_the_platform():
    """One version across the repository. If this drifts, the premise is broken."""
    from pathlib import Path

    config = Path(__file__).resolve().parents[2] / "services/api/cubicle/config.py"
    if not config.exists():  # installed without the rest of the repository
        pytest.skip("the API is not beside this checkout")
    platform = next(
        line.split('"')[1] for line in config.read_text().splitlines() if "version: str =" in line
    )
    assert build_id().startswith(platform)
