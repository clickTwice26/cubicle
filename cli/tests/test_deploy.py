"""Which files a deploy carries, how it decides, and how it reports the build.

The CLI used to bundle a hardcoded four filenames and refuse a directory
without handler.py in it, so a JavaScript function could be scaffolded and
never deployed. The bundle now follows the runtime the function is actually
written in.

The other half of these is the answer a deploy gives back. The endpoint
answers with the function, and a function's version is the one serving
traffic, which after a failed build is still the previous one. So the outcome
is read off the versions listing, where the version that was just built is the
newest row.
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


def _build(number: int, **overrides) -> dict:
    """One row of GET /api/functions/{id}/versions, which is a VersionOut."""
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
    api.on("POST", "/api/functions/fn-1/deploy", api_function(version=4))
    api.on("GET", "/api/functions/fn-1/versions", [_build(4)])

    assert run("deploy", str(project)) == 0

    files = api.last("POST", "/api/functions/fn-1/deploy").body["files"]
    assert sorted(files) == ["cubicle.toml", "handler.js", "package.json"]


def test_a_python_function_sends_only_its_own_files(api, run, api_function, tmp_path):
    """The other half of the same rule."""
    project = _project(tmp_path, "handler.py", "requirements.txt", "handler.js")
    api.on("GET", "/api/functions", [api_function()])
    api.on("POST", "/api/functions/fn-1/deploy", api_function(version=4))
    api.on("GET", "/api/functions/fn-1/versions", [_build(4)])

    assert run("deploy", str(project)) == 0

    files = api.last("POST", "/api/functions/fn-1/deploy").body["files"]
    assert sorted(files) == ["cubicle.toml", "handler.py", "requirements.txt"]


def test_a_node_deploy_asks_the_instance_nothing_about_its_files(api, run, api_function, tmp_path):
    """node22 is understood here, so no runtime lookup goes out to find that."""
    project = _project(tmp_path, "handler.js", "package.json")
    api.on("GET", "/api/functions", [api_function(runtime="node22", runtime_label="Node 22")])
    api.on("POST", "/api/functions/fn-1/deploy", api_function(version=4))
    api.on("GET", "/api/functions/fn-1/versions", [_build(4)])

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
    api.on("POST", "/api/functions/fn-1/deploy", api_function(version=4))
    api.on("GET", "/api/functions/fn-1/versions", [_build(4)])

    assert run("deploy", str(project)) == 0

    assert "no requirements.txt here, the deployed one is kept" in capsys.readouterr().out


def test_the_client_waits_for_the_build(api, run, api_function, tmp_path):
    """The build runs inside the request, and a cold install outlasts a minute."""
    project = _project(tmp_path, "handler.py", "requirements.txt")
    api.on("GET", "/api/functions", [api_function()])
    api.on("POST", "/api/functions/fn-1/deploy", api_function(version=4))
    api.on("GET", "/api/functions/fn-1/versions", [_build(4)])

    run("deploy", str(project))

    assert api.last("POST", "/api/functions/fn-1/deploy").timeout == BUILD_TIMEOUT


def test_the_deploy_body_is_the_bundle_and_nothing_else(api, run, api_function, tmp_path):
    """DeployRequest also declares a `message`, which no endpoint reads or stores.

    There was a --message flag for it. Nothing persists the text, FunctionVersion
    has no column for it and VersionOut has no field, so it could never be read
    back; a flag that reads as an audit trail and is not one is worse than none.
    """
    project = _project(tmp_path, "handler.py", "requirements.txt")
    api.on("GET", "/api/functions", [api_function()])
    api.on("POST", "/api/functions/fn-1/deploy", api_function(version=4))
    api.on("GET", "/api/functions/fn-1/versions", [_build(4)])

    run("deploy", str(project))

    assert set(api.last("POST", "/api/functions/fn-1/deploy").body) == {"files"}


# ── what the build did ───────────────────────────────────────────────────────


def test_the_version_just_built_is_the_one_reported(api, run, api_function, tmp_path, capsys):
    """v4 built and serves, so that is the number printed rather than the response's."""
    project = _project(tmp_path, "handler.py", "requirements.txt")
    api.on("GET", "/api/functions", [api_function()])
    api.on("POST", "/api/functions/fn-1/deploy", api_function(version=4))
    api.on("GET", "/api/functions/fn-1/versions", [_build(4, build_ms=1421), _build(3)])

    assert run("deploy", str(project)) == 0

    out = capsys.readouterr().out
    assert "building       1421ms" in out
    assert "deployed" in out
    assert "(v4)" in out


def test_a_failed_build_exits_one_and_prints_the_log(api, run, api_function, tmp_path, capsys):
    """The build log is the only thing worth reading when a deploy fails.

    The deploy answers with the function, and the function is still serving the
    version it was serving before, ready and green. Reading the outcome there is
    how a broken deploy came to print "deployed" and exit 0.
    """
    project = _project(tmp_path, "handler.py", "requirements.txt")
    api.on("GET", "/api/functions", [api_function()])
    api.on("POST", "/api/functions/fn-1/deploy", api_function(version=3, version_status="ready"))
    api.on(
        "GET",
        "/api/functions/fn-1/versions",
        [
            _build(
                4,
                status="failed",
                build_log="ERROR: no matching distribution",
                deployed_at=None,
            ),
            _build(3),
        ],
    )

    assert run("deploy", str(project)) == 1

    out = capsys.readouterr().out
    assert "build failed   v4 was not deployed" in out
    assert "no matching distribution" in out
    # The success line is the one that prints the URL, and it is not printed.
    assert "fn.example.com" not in out


def test_a_failed_build_says_what_is_still_serving(api, run, api_function, tmp_path, capsys):
    """A failed build takes nothing out of service, and the exit code cannot say so."""
    project = _project(tmp_path, "handler.py", "requirements.txt")
    api.on("GET", "/api/functions", [api_function()])
    api.on("POST", "/api/functions/fn-1/deploy", api_function(version=3, version_status="ready"))
    api.on(
        "GET",
        "/api/functions/fn-1/versions",
        [_build(4, status="failed", deployed_at=None), _build(3)],
    )

    run("deploy", str(project))

    assert "v3 is still serving" in capsys.readouterr().out


def test_a_first_build_that_fails_has_nothing_to_fall_back_to(
    api, run, api_function, tmp_path, capsys
):
    """A function whose only version failed serves nothing, so nothing is claimed."""
    project = _project(tmp_path, "handler.py", "requirements.txt")
    api.on("GET", "/api/functions", [api_function(version=1, version_status="failed")])
    api.on(
        "POST",
        "/api/functions/fn-1/deploy",
        api_function(version=1, version_status="failed"),
    )
    api.on(
        "GET",
        "/api/functions/fn-1/versions",
        [_build(1, status="failed", build_log="ERROR: no matching distribution", deployed_at=None)],
    )

    assert run("deploy", str(project)) == 1

    out = capsys.readouterr().out
    assert "build failed   v1 was not deployed" in out
    assert "still serving" not in out
