"""Removing the CLI from this machine, and nothing else.

The risk this command carries is not that it fails. It is that somebody runs it
believing it removes their Cubicle server, or runs `cubicle rm` believing it
removes the CLI. So the tests below care as much about what it refuses to touch
and what it says it is doing as about whether the uninstall runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from cubicle_cli.__main__ import main
from cubicle_cli.commands import uninstall


@pytest.fixture
def config(tmp_path, monkeypatch):
    """A saved profile, in a directory the test owns."""
    path = tmp_path / ".cubicle" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text('[default]\nurl = "https://fn.example.com"\ntoken = "cbcl_secret"\n')
    monkeypatch.setattr(uninstall, "CONFIG_PATH", path)
    from cubicle_cli import client

    monkeypatch.setattr(client, "CONFIG_PATH", path)
    return path


@pytest.fixture
def ran(monkeypatch):
    """Capture the uninstall command instead of running it."""
    calls = []

    class Result:
        returncode = 0

    monkeypatch.setattr(
        uninstall.subprocess, "run", lambda cmd, **kw: (calls.append(cmd), Result())[1]
    )
    return calls


# ── it removes the client, never the server ──────────────────────────────────


def test_it_makes_no_request_to_the_instance(api, config, ran, monkeypatch):
    """The whole point. An uninstall that called the API could not be trusted."""
    monkeypatch.setattr(
        uninstall, "discover", lambda: uninstall.Install("pipx", "/venvs/cubicle-cli", ["pipx"])
    )
    main(["uninstall", "--yes"])
    assert api.calls == []


def test_it_says_out_loud_that_the_instance_is_untouched(config, ran, capsys, monkeypatch):
    monkeypatch.setattr(
        uninstall, "discover", lambda: uninstall.Install("pipx", "/venvs/cubicle-cli", ["pipx"])
    )
    main(["uninstall", "--yes"])
    out = capsys.readouterr().out
    assert "nothing on any instance" in out
    assert "the instance is untouched" in out


# ── the saved token ──────────────────────────────────────────────────────────


def test_the_profile_goes_with_it(config, ran, monkeypatch):
    """A token in plain text outliving the program that reads it is a hazard."""
    monkeypatch.setattr(
        uninstall, "discover", lambda: uninstall.Install("pipx", "/venvs/x", ["pipx"])
    )
    main(["uninstall", "--yes"])
    assert not config.exists()
    assert not config.parent.exists()


def test_keep_config_leaves_it(config, ran, monkeypatch):
    monkeypatch.setattr(
        uninstall, "discover", lambda: uninstall.Install("pipx", "/venvs/x", ["pipx"])
    )
    main(["uninstall", "--yes", "--keep-config"])
    assert config.exists()


def test_a_directory_with_other_things_in_it_survives(config, ran, monkeypatch):
    """`~/.cubicle` is the operator's, not ours. Only our file is ours."""
    (config.parent / "notes.txt").write_text("mine")
    monkeypatch.setattr(
        uninstall, "discover", lambda: uninstall.Install("pipx", "/venvs/x", ["pipx"])
    )
    main(["uninstall", "--yes"])
    assert not config.exists()
    assert (config.parent / "notes.txt").exists()


def test_config_only_forgets_without_uninstalling(config, ran):
    """Signing out of a machine you keep using is a different thing entirely."""
    assert main(["uninstall", "--config-only", "--yes"]) == 0
    assert not config.exists()
    assert ran == []


# ── it asks first ────────────────────────────────────────────────────────────


def test_it_refuses_without_a_yes_when_nobody_can_answer(config, ran, capsys, monkeypatch):
    """Not a terminal, so there is nobody to ask and nothing is assumed."""
    monkeypatch.setattr(
        uninstall, "discover", lambda: uninstall.Install("pipx", "/venvs/x", ["pipx"])
    )
    assert main(["uninstall"]) == 1
    assert ran == []
    assert config.exists()


# ── how it finds itself ──────────────────────────────────────────────────────


def test_a_pipx_install_is_removed_with_pipx(monkeypatch, tmp_path):
    """pipx puts each program in its own venv under a directory called venvs."""
    venv = tmp_path / "pipx" / "venvs" / "cubicle-cli"
    venv.mkdir(parents=True)
    monkeypatch.setattr(sys, "prefix", str(venv))
    monkeypatch.setattr(uninstall.shutil, "which", lambda _: "/opt/homebrew/bin/pipx")

    found = uninstall.discover()
    assert found.kind == "pipx"
    assert found.command == ["/opt/homebrew/bin/pipx", "uninstall", "cubicle-cli"]


def test_pipx_gone_from_the_path_is_explained_rather_than_guessed_at(monkeypatch, tmp_path):
    venv = tmp_path / "pipx" / "venvs" / "cubicle-cli"
    venv.mkdir(parents=True)
    monkeypatch.setattr(sys, "prefix", str(venv))
    monkeypatch.setattr(uninstall.shutil, "which", lambda _: None)

    found = uninstall.discover()
    assert found.command is None
    assert "by hand" in found.note


def test_a_pip_install_uses_this_interpreter_not_whatever_pip_is_on_the_path(monkeypatch):
    """`pip` on PATH is frequently a different Python from the one running."""
    monkeypatch.setattr(sys, "prefix", "/usr/local")
    found = uninstall.discover()
    assert found.kind in ("pip", "source")
    if found.kind == "pip":
        assert found.command[:3] == [sys.executable, "-m", "pip"]


def test_a_source_checkout_has_nothing_to_uninstall(monkeypatch):
    """Running from a clone: the answer is to delete the directory."""
    monkeypatch.setattr(sys, "prefix", "/usr/local")
    monkeypatch.setattr(
        uninstall, "DIST", "a-package-that-is-definitely-not-installed-anywhere-at-all"
    )
    found = uninstall.discover()
    assert found.kind == "source"
    assert found.command is None
    assert Path(found.location).name == "cli"


# ── a failed uninstall is not a silent one ───────────────────────────────────


def test_a_package_manager_that_fails_is_reported(config, capsys, monkeypatch):
    class Failed:
        returncode = 3

    monkeypatch.setattr(uninstall.subprocess, "run", lambda cmd, **kw: Failed())
    monkeypatch.setattr(
        uninstall, "discover", lambda: uninstall.Install("pipx", "/venvs/x", ["pipx", "uninstall"])
    )
    assert main(["uninstall", "--yes"]) == 1
    assert "exited 3" in capsys.readouterr().err
