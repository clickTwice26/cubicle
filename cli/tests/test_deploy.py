"""Which files a deploy carries, and how it decides.

The CLI used to bundle a hardcoded four filenames and refuse a directory
without handler.py in it, so a JavaScript function could be scaffolded and
never deployed. The bundle now follows the runtime the function is actually
written in.
"""

from __future__ import annotations

import pytest

from cubicle_cli.client import BUILD_TIMEOUT, CubicleError, deploy_files, runtime_files

PYTHON_BUNDLE = ("handler.py", "requirements.txt", "cubicle.toml", "README.md")
NODE_BUNDLE = ("handler.js", "package.json", "cubicle.toml", "README.md")


def _project(directory, *names: str):
    """A local function directory with the given files in it."""
    (directory / "cubicle.toml").write_text(
        '[function]\nname       = "create-charge"\nnamespace  = "payments"\n'
    )
    for name in names:
        directory.joinpath(name).write_text("// source\n")
    return directory


def test_a_python_runtime_carries_the_python_files():
    """python* reads handler.py and requirements.txt."""
    assert deploy_files("python312") == PYTHON_BUNDLE
    assert deploy_files("python310") == PYTHON_BUNDLE


def test_a_node_runtime_carries_the_node_files():
    """node* reads handler.js and package.json, and never handler.py."""
    assert deploy_files("node22") == NODE_BUNDLE
    assert deploy_files("node18") == NODE_BUNDLE


def test_the_instance_outranks_the_naming_convention():
    """GET /api/runtimes is the real source, so its answer wins."""
    catalogue = [{"key": "node22", "entry_file": "index.mjs", "deps_file": "package.json"}]

    assert runtime_files("node22", catalogue=catalogue) == ("index.mjs", "package.json")


def test_a_runtime_nobody_here_has_heard_of_is_looked_up(api, profile):
    """An unfamiliar key is worth a round trip rather than a guess."""
    api.on(
        "GET",
        "/api/runtimes",
        [{"key": "ruby33", "entry_file": "handler.rb", "deps_file": "Gemfile"}],
    )

    bundle = deploy_files("ruby33", profile=profile)

    assert bundle == ("handler.rb", "Gemfile", "cubicle.toml", "README.md")


def test_an_unknown_runtime_with_nowhere_to_ask_is_an_error():
    """Better to say so than to send a bundle the build cannot use."""
    with pytest.raises(CubicleError):
        deploy_files("ruby33")


def test_a_node_function_sends_only_its_own_files(api, run, api_function, tmp_path):
    """A stray handler.py in the directory is not part of a Node function."""
    project = _project(tmp_path, "handler.js", "package.json", "handler.py")
    api.on("GET", "/api/functions", [api_function(runtime="node22", runtime_label="Node 22")])
    api.on("POST", "/api/functions/fn-1/deploy", api_function(version=4, build_ms=910))

    assert run("deploy", str(project)) == 0

    files = api.last("POST", "/api/functions/fn-1/deploy").body["files"]
    assert sorted(files) == ["cubicle.toml", "handler.js", "package.json"]


def test_a_python_function_sends_only_its_own_files(api, run, api_function, tmp_path):
    """The other half of the same rule."""
    project = _project(tmp_path, "handler.py", "requirements.txt", "handler.js")
    api.on("GET", "/api/functions", [api_function()])
    api.on("POST", "/api/functions/fn-1/deploy", api_function(version=4, build_ms=910))

    assert run("deploy", str(project)) == 0

    files = api.last("POST", "/api/functions/fn-1/deploy").body["files"]
    assert sorted(files) == ["cubicle.toml", "handler.py", "requirements.txt"]


def test_a_node_deploy_needs_no_extra_round_trip(api, run, api_function, tmp_path):
    """node22 is understood without asking, so deploy stays two calls."""
    project = _project(tmp_path, "handler.js", "package.json")
    api.on("GET", "/api/functions", [api_function(runtime="node22", runtime_label="Node 22")])
    api.on("POST", "/api/functions/fn-1/deploy", api_function(version=4, build_ms=910))

    run("deploy", str(project))

    assert api.sent("GET", "/api/runtimes") == []


def test_the_missing_entry_file_is_named_in_the_language_of_the_function(
    api, run, api_function, tmp_path, capsys
):
    """Telling a Node author that handler.py is required is how this started."""
    project = _project(tmp_path)
    api.on("GET", "/api/functions", [api_function(runtime="node22", runtime_label="Node 22")])

    assert run("deploy", str(project)) == 1

    assert "handler.js is required" in capsys.readouterr().err


def test_a_dependency_file_that_is_only_missing_locally_is_called_out(
    api, run, api_function, tmp_path, capsys
):
    """The server merges onto the last version, so deleting a file here keeps it there."""
    project = _project(tmp_path, "handler.py")
    api.on("GET", "/api/functions", [api_function()])
    api.on("POST", "/api/functions/fn-1/deploy", api_function(version=4, build_ms=910))

    assert run("deploy", str(project)) == 0

    assert "no requirements.txt here, the deployed one is kept" in capsys.readouterr().out


def test_the_client_waits_for_the_build(api, run, api_function, tmp_path):
    """The build runs inside the request, and a cold install outlasts a minute."""
    project = _project(tmp_path, "handler.py", "requirements.txt")
    api.on("GET", "/api/functions", [api_function()])
    api.on("POST", "/api/functions/fn-1/deploy", api_function(version=4, build_ms=910))

    run("deploy", str(project))

    assert api.last("POST", "/api/functions/fn-1/deploy").timeout == BUILD_TIMEOUT


def test_a_message_is_sent_with_the_deploy(api, run, api_function, tmp_path):
    """DeployRequest has taken a message all along; there was no flag for it."""
    project = _project(tmp_path, "handler.py", "requirements.txt")
    api.on("GET", "/api/functions", [api_function()])
    api.on("POST", "/api/functions/fn-1/deploy", api_function(version=4, build_ms=910))

    run("deploy", str(project), "-m", "raise the retry ceiling")

    body = api.last("POST", "/api/functions/fn-1/deploy").body
    assert body["message"] == "raise the retry ceiling"


def test_a_failed_build_exits_one_and_prints_the_log(api, run, api_function, tmp_path, capsys):
    """The build log is the only thing worth reading when a deploy fails."""
    project = _project(tmp_path, "handler.py", "requirements.txt")
    api.on("GET", "/api/functions", [api_function()])
    api.on(
        "POST",
        "/api/functions/fn-1/deploy",
        api_function(version_status="failed", build_log="ERROR: no matching distribution"),
    )

    assert run("deploy", str(project)) == 1

    out = capsys.readouterr().out
    assert "build failed" in out
    assert "no matching distribution" in out
