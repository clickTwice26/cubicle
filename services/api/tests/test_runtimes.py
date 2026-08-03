"""The runtime registry, and the places that have to agree with it.

Two of those are spelled out by hand — the `Runtime` enum in the schemas and
the compose services that bake the built-in images — because both need to be
literal to do their job. These tests are what stop them drifting from the table
that everything else reads.
"""

from pathlib import Path

import pytest

from cubicle import runtimes
from cubicle.config import settings
from cubicle.runtime import images
from cubicle.schemas import Runtime
from cubicle.templates import RUNTIME_LABELS, scaffold


def _repo_root() -> Path | None:
    """The checkout, when these run from one.

    Inside the API image there is no repo — only the application and the
    packaged build contexts — so the two tests that read repository files skip
    rather than fail. Indexing `parents` directly raises there.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "docker-compose.yml").is_file():
            return parent
    return None


REPO = _repo_root()
needs_repo = pytest.mark.skipif(REPO is None, reason="not running from a checkout")


def test_the_schema_enum_matches_the_registry():
    """A runtime you cannot name in the API is a runtime nobody can select."""
    assert set(Runtime.__args__) == set(runtimes.RUNTIMES)


def test_python_and_javascript_both_ship():
    """The two default languages must not need installing."""
    languages = {spec.language for spec in runtimes.builtin()}
    assert languages == {"Python", "JavaScript"}


@needs_repo
def test_compose_builds_exactly_the_builtins():
    """`builtin` is a promise that the image is already there after install."""
    compose = (REPO / "docker-compose.yml").read_text()
    for spec in runtimes.RUNTIMES.values():
        declared = f"image: {spec.repository}:" in compose
        assert declared == spec.builtin, f"{spec.key}: compose={declared} builtin={spec.builtin}"


def test_every_runtime_has_a_build_context_available():
    """Whatever an install would send to the daemon has to actually be there."""
    for spec in runtimes.RUNTIMES.values():
        context = images.CONTEXT_ROOT / spec.context
        assert (context / "Dockerfile").is_file(), f"{spec.key} has no Dockerfile"


def test_an_unknown_runtime_falls_back_rather_than_raising():
    """A function whose runtime was retired still has to render and still run."""
    assert runtimes.get("fortran77").key == runtimes.DEFAULT


def test_image_tags_are_distinct():
    tags = [settings.runtime_image(key) for key in runtimes.RUNTIMES]
    assert len(set(tags)) == len(tags)


@pytest.mark.parametrize("key", list(runtimes.RUNTIMES))
def test_every_runtime_scaffolds_its_own_language(key):
    spec = runtimes.get(key)
    files = scaffold(
        name="charge",
        namespace="payments",
        runtime=key,
        method="POST",
        memory_mb=128,
        timeout_s=30,
        ctx_access="rw",
        base_url="http://localhost/payments/",
    )
    assert spec.entry_file in files, f"{key} scaffolds no {spec.entry_file}"
    assert spec.deps_file in files, f"{key} scaffolds no {spec.deps_file}"
    # The other language's entry file must not come along for the ride.
    other = "handler.js" if spec.entry_file == "handler.py" else "handler.py"
    assert other not in files


def test_javascript_scaffold_exports_a_handler():
    files = scaffold(
        name="charge",
        namespace="payments",
        runtime="node22",
        method="POST",
        memory_mb=128,
        timeout_s=30,
        ctx_access="rw",
        base_url="http://localhost/payments/",
    )
    assert "export async function handler" in files["handler.js"]
    assert '"type": "module"' in files["package.json"]


def test_labels_cover_every_runtime():
    assert set(RUNTIME_LABELS) == set(runtimes.RUNTIMES)


def test_isolate_env_matches_the_language():
    """Each isolate is told where its own language finds installed packages."""
    assert "PYTHONPATH" in runtimes.get("python312").env
    assert "NODE_PATH" in runtimes.get("node22").env
    assert "PYTHONPATH" not in runtimes.get("node22").env
