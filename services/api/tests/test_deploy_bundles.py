"""What a deploy is allowed to carry, and for which language.

A deploy is checked in two places, and they answer different questions. The
request body is validated before the function it targets has been read, so all
it can say is whether these file names belong to any runtime at all and whether
the bundle is small enough. The endpoint then loads the function and asks
`check_bundle`, which knows the language and can tell a JavaScript author that
handler.py is not their file.

Both layers matter. The first is what keeps a path out of the tar the builder
writes; the second is what stopped JavaScript being deployable at all, because
it used to be a hand-written set of Python file names and nobody added
handler.js to it when the Node runtimes arrived.

None of these touch a database: `check_bundle` takes a runtime key and a dict,
which is the whole reason it is a plain function rather than endpoint code.
"""

import pytest
from pydantic import ValidationError

from cubicle import runtimes
from cubicle.runtime import builder
from cubicle.schemas import DeployRequest, bundle_files, check_bundle

PY = {"handler.py": "def handler(req, ctx):\n    return {}\n", "requirements.txt": "httpx\n"}
JS = {"handler.js": "export function handler() {}\n", "package.json": "{}\n"}

PYTHONS = [key for key, spec in runtimes.RUNTIMES.items() if spec.language == "Python"]
NODES = [key for key, spec in runtimes.RUNTIMES.items() if spec.language == "JavaScript"]


# ── the bundle a runtime accepts ─────────────────────────────────────────────


@pytest.mark.parametrize("runtime", PYTHONS)
def test_a_python_bundle_deploys(runtime):
    """The behaviour that already worked, on every Python the registry lists."""
    DeployRequest(files=PY)
    check_bundle(runtime, PY)


@pytest.mark.parametrize("runtime", NODES)
def test_a_javascript_bundle_deploys(runtime):
    """The defect. Until this passed, no JavaScript function could be deployed."""
    DeployRequest(files=JS)
    check_bundle(runtime, JS)


@pytest.mark.parametrize("runtime", list(runtimes.RUNTIMES))
def test_every_runtime_takes_its_own_scaffold(runtime):
    """Whatever a new function is created with must be deployable unchanged."""
    spec = runtimes.get(runtime)
    files = {spec.entry_file: "", spec.deps_file: "", "cubicle.toml": "", "README.md": ""}
    DeployRequest(files=files)
    check_bundle(runtime, files)


# ── the wrong language ───────────────────────────────────────────────────────


def test_a_python_function_refuses_handler_js():
    """The file names its language, so the author can see which of the two is wrong."""
    with pytest.raises(ValueError) as caught:
        check_bundle("python312", {"handler.py": "", "handler.js": ""})

    message = str(caught.value)
    assert "handler.js" in message
    assert "Python 3.12" in message
    assert "handler.py" in message


def test_a_node_function_refuses_handler_py():
    """The same in the other direction, which is the case the console hits."""
    with pytest.raises(ValueError) as caught:
        check_bundle("node22", {"handler.js": "", "handler.py": ""})

    message = str(caught.value)
    assert "handler.py is not part of a Node 22 function" in message
    assert "Deploy handler.js instead" in message


def test_a_node_function_refuses_requirements_txt():
    """Dependency manifests belong to a language too, not just the entry file."""
    with pytest.raises(ValueError):
        check_bundle("node22", {"handler.js": "", "requirements.txt": "httpx\n"})


def test_a_python_function_refuses_package_json():
    with pytest.raises(ValueError):
        check_bundle("python311", {"handler.py": "", "package.json": "{}"})


# ── the entry file ───────────────────────────────────────────────────────────


def test_a_bundle_with_no_entry_file_is_refused():
    """Source-less versions build green and then fail every invocation."""
    with pytest.raises(ValueError) as caught:
        check_bundle("python312", {"requirements.txt": "httpx\n"})
    assert "handler.py" in str(caught.value)

    with pytest.raises(ValueError) as caught:
        check_bundle("node22", {"package.json": "{}"})
    assert "handler.js" in str(caught.value)


def test_the_manifest_alone_is_not_a_bundle():
    """Nothing carries over in `check_bundle`; the endpoint merges before calling it."""
    with pytest.raises(ValueError):
        check_bundle("node22", {"cubicle.toml": "", "README.md": ""})


@pytest.mark.parametrize("runtime", list(runtimes.RUNTIMES))
def test_the_entry_file_alone_is_enough(runtime):
    """Dependencies are optional. A handler with no imports is a whole function."""
    spec = runtimes.get(runtime)
    check_bundle(runtime, {spec.entry_file: ""})


# ── the files every language shares ──────────────────────────────────────────


@pytest.mark.parametrize("runtime", list(runtimes.RUNTIMES))
def test_the_manifest_and_readme_are_taken_by_every_runtime(runtime):
    """They are the function's configuration and its documentation, not its source."""
    spec = runtimes.get(runtime)
    assert {"cubicle.toml", "README.md"} <= bundle_files(runtime)
    check_bundle(runtime, {spec.entry_file: "", "cubicle.toml": "", "README.md": ""})


# ── files that belong to nothing ─────────────────────────────────────────────


@pytest.mark.parametrize("runtime", ["python312", "node22"])
def test_an_unknown_file_is_refused_whatever_the_language(runtime):
    """A deploy writes a tar into the version volume, so the names are the gate."""
    spec = runtimes.get(runtime)
    with pytest.raises(ValidationError):
        DeployRequest(files={spec.entry_file: "", "evil.sh": "rm -rf /"})
    with pytest.raises(ValueError):
        check_bundle(runtime, {spec.entry_file: "", "evil.sh": "rm -rf /"})


@pytest.mark.parametrize("name", ["../escape.py", "/etc/passwd", "src/handler.py"])
def test_paths_are_still_refused(name):
    """A name is a name. Nothing a bundle carries is allowed to be a path."""
    with pytest.raises(ValidationError):
        DeployRequest(files={"handler.py": "", name: "x"})


# ── size ─────────────────────────────────────────────────────────────────────


def test_the_two_megabyte_ceiling_still_trips():
    """Measured over the whole bundle, in bytes, whichever files it is made of."""
    with pytest.raises(ValidationError):
        DeployRequest(files={"handler.js": "x" * 1_000_001, "package.json": "y" * 1_000_001})


def test_a_bundle_just_under_the_ceiling_is_accepted():
    """The limit is a ceiling on the encoded bytes, not a rounded-down guess."""
    assert DeployRequest(files={"handler.js": "x" * 2_000_000}).files


# ── the build's own last word ────────────────────────────────────────────────


async def test_a_build_without_the_entry_file_fails_rather_than_going_green():
    """The deploy endpoint is not the only way a version is built.

    Changing a function's runtime rebuilds the version it already has, with the
    files it already has, so a Python function switched to Node arrives at the
    builder carrying handler.py. The build has nothing to object to, since it
    copies whatever it is handed, so the version would be marked ready while
    every invocation failed to import. This refuses before any engine is
    contacted, which is also why it runs here without a Docker daemon.
    """
    result = await builder.build_version(
        host="unix:///nowhere.sock",
        runtime="node22",
        function_id="0000",
        version_number=3,
        files={"handler.py": "def handler(req, ctx): pass\n"},
    )

    assert result.ok is False
    assert "handler.js" in result.log
    assert "Node 22" in result.log
