"""Scaffolding, which now offers whatever the instance can actually run.

`--runtime` used to be a two-value list copied from a schema that has since
grown to seven, so node22 was unreachable from the CLI even on an instance
that had it installed.
"""

from __future__ import annotations

CATALOGUE = [
    {
        "key": "python312",
        "label": "Python 3.12",
        "language": "Python",
        "entry_file": "handler.py",
        "deps_file": "requirements.txt",
        "installed": True,
    },
    {
        "key": "node22",
        "label": "Node 22",
        "language": "JavaScript",
        "entry_file": "handler.js",
        "deps_file": "package.json",
        "installed": True,
    },
]

NODE_FILES = {
    "handler.js": "export async function handler() {}\n",
    "package.json": '{"name": "create-charge"}\n',
    "cubicle.toml": '[function]\nname = "create-charge"\n',
    "README.md": "# create-charge\n",
}


def _serve_init(api, api_function, *, runtime: str) -> None:
    api.on("GET", "/api/runtimes", CATALOGUE)
    api.on("GET", "/api/groups", [{"id": "grp-1", "ns": "payments"}])
    api.on("GET", "/api/functions", [])
    api.on("POST", "/api/groups/grp-1/functions", api_function(runtime=runtime))
    api.on("GET", "/api/functions/fn-1", {**api_function(runtime=runtime), "files": NODE_FILES})


def test_a_node_runtime_can_be_scaffolded(api, run, api_function, tmp_path, monkeypatch):
    """The whole point: an operator who installs node22 can use it immediately."""
    monkeypatch.chdir(tmp_path)
    _serve_init(api, api_function, runtime="node22")

    assert run("init", "payments/create-charge", "--runtime", "node22") == 0

    assert api.last("POST", "/api/groups/grp-1/functions").body["runtime"] == "node22"
    assert (tmp_path / "create-charge" / "handler.js").exists()
    assert not (tmp_path / "create-charge" / "handler.py").exists()


def test_the_runtime_is_checked_against_the_instance(api, run, capsys, tmp_path, monkeypatch):
    """And the refusal lists what this instance really has, rather than a guess."""
    monkeypatch.chdir(tmp_path)
    api.on("GET", "/api/runtimes", CATALOGUE)

    assert run("init", "payments/create-charge", "--runtime", "node99") == 1

    err = capsys.readouterr().err
    assert "node99" in err
    assert "python312, node22" in err
    # Nothing was created on the way to finding that out.
    assert api.sent("GET", "/api/groups") == []


def test_a_runtime_with_no_image_yet_is_flagged(
    api, run, api_function, capsys, tmp_path, monkeypatch
):
    """The scaffold still lands; the build it triggers is the part that will not."""
    monkeypatch.chdir(tmp_path)
    api.on("GET", "/api/runtimes", [{**CATALOGUE[1], "installed": False}])
    api.on("GET", "/api/groups", [{"id": "grp-1", "ns": "payments"}])
    api.on("GET", "/api/functions", [])
    api.on("POST", "/api/groups/grp-1/functions", api_function(runtime="node22"))
    api.on("GET", "/api/functions/fn-1", {**api_function(runtime="node22"), "files": NODE_FILES})

    assert run("init", "payments/create-charge", "--runtime", "node22") == 0

    assert "Node 22 is not installed on this instance yet" in capsys.readouterr().out


def test_a_missing_namespace_is_created_first(api, run, api_function, tmp_path, monkeypatch):
    """A namespace is a container for functions, not something to make by hand first."""
    monkeypatch.chdir(tmp_path)
    api.on("GET", "/api/runtimes", CATALOGUE)
    api.on("GET", "/api/groups", [])
    api.on("POST", "/api/groups", {"id": "grp-9", "ns": "billing"})
    api.on("GET", "/api/functions", [])
    api.on("POST", "/api/groups/grp-9/functions", api_function(runtime="python312"))
    api.on("GET", "/api/functions/fn-1", {**api_function(), "files": {"handler.py": "x\n"}})

    assert run("init", "billing/create-charge") == 0

    assert api.last("POST", "/api/groups").body == {"name": "billing"}
    assert (tmp_path / "create-charge" / "handler.py").exists()
