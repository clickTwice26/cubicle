"""What the marketplace accepts from a registry, and what it refuses.

Installing runs a stranger's code on your cluster. Nothing here can make that
safe, but the parser is the one place that decides what a registry is allowed
to talk this instance into building — so the refusals matter more than the
happy path.
"""

import json
from pathlib import Path

import pytest

from cubicle import marketplace


def _package(**overrides):
    base = {
        "schema": 1,
        "slug": "webhook-relay",
        "name": "Webhook relay",
        "runtime": "python312",
        "files": {"handler.py": "def handler(req, ctx):\n    return {}\n"},
    }
    return {**base, **overrides}


# ── the index ────────────────────────────────────────────────────────────────


def test_an_index_that_is_not_an_index_is_refused():
    for payload in ({}, [], {"packages": "no"}, "nope"):
        with pytest.raises(marketplace.MarketplaceError):
            marketplace.parse_index(payload, base_url="https://x/index.json")


def test_one_bad_row_does_not_spoil_the_registry():
    """A malformed entry is dropped; a malformed index is an error."""
    listings = marketplace.parse_index(
        {"packages": [{"slug": "Bad Slug!"}, {"slug": "good-one", "name": "Good"}]},
        base_url="https://x/index.json",
    )
    assert [entry.slug for entry in listings] == ["good-one"]


def test_relative_package_urls_resolve_against_the_index():
    """Registries are a directory of files, so relative paths are natural."""
    listings = marketplace.parse_index(
        {"packages": [{"slug": "a", "url": "packages/a.json"}]},
        base_url="https://host/reg/index.json",
    )
    assert listings[0].url == "https://host/reg/packages/a.json"


def test_absolute_package_urls_are_left_alone():
    listings = marketplace.parse_index(
        {"packages": [{"slug": "a", "url": "https://elsewhere/a.json"}]},
        base_url="https://host/reg/index.json",
    )
    assert listings[0].url == "https://elsewhere/a.json"


# ── the package ──────────────────────────────────────────────────────────────


def test_a_well_formed_package_parses():
    package = marketplace.parse_package(_package())
    assert package.slug == "webhook-relay"
    assert package.runtime == "python312"


@pytest.mark.parametrize("slug", ["", "Bad Slug", "-leading", "x" * 80, "../../etc"])
def test_an_unusable_slug_is_refused(slug):
    with pytest.raises(marketplace.MarketplaceError):
        marketplace.parse_package(_package(slug=slug))


def test_a_package_with_no_files_is_refused():
    with pytest.raises(marketplace.MarketplaceError):
        marketplace.parse_package(_package(files={}))


def test_a_file_outside_the_allowed_set_is_refused():
    """Not filtered — refused. A package with files it cannot install is not
    the package its author tested."""
    with pytest.raises(marketplace.MarketplaceError) as exc:
        marketplace.parse_package(
            _package(files={"handler.py": "x", "../../etc/passwd": "root"})
        )
    assert "unexpected file" in str(exc.value)


def test_a_package_missing_its_entry_file_is_refused():
    with pytest.raises(marketplace.MarketplaceError):
        marketplace.parse_package(_package(files={"requirements.txt": "httpx\n"}))


def test_a_javascript_package_must_carry_handler_js():
    with pytest.raises(marketplace.MarketplaceError):
        marketplace.parse_package(
            _package(runtime="node22", files={"handler.py": "def handler(): pass"})
        )
    ok = marketplace.parse_package(
        _package(runtime="node22", files={"handler.js": "export function handler() {}"})
    )
    assert ok.runtime == "node22"


def test_an_unknown_runtime_is_refused():
    with pytest.raises(marketplace.MarketplaceError) as exc:
        marketplace.parse_package(_package(runtime="cobol"))
    assert "cobol" in str(exc.value)


def test_an_oversized_file_is_refused():
    huge = "x" * (marketplace.MAX_FILE_BYTES + 1)
    with pytest.raises(marketplace.MarketplaceError):
        marketplace.parse_package(_package(files={"handler.py": huge}))


def test_a_flood_of_files_is_refused_before_any_are_read():
    """The count check runs before the loop, so a huge package costs nothing.

    With allowed names alone the cap is unreachable — there are fewer permitted
    names than the limit — so this is the guard against a package that is large
    rather than one that is wrong, and it fires first.
    """
    files = {f"file{n}.py": "x" for n in range(marketplace.MAX_FILES + 5)}
    with pytest.raises(marketplace.MarketplaceError) as exc:
        marketplace.parse_package(_package(files=files))
    assert "more than" in str(exc.value)


def test_every_allowed_name_together_is_under_the_cap():
    """If this ever fails, the cap has become reachable by a legitimate package."""
    assert len(marketplace.ALLOWED_FILES) <= marketplace.MAX_FILES


def test_resource_figures_are_clamped_not_trusted():
    """A registry does not get to ask for 64 GB and a one-hour timeout."""
    package = marketplace.parse_package(_package(memory_mb=999999, timeout_s=99999))
    assert package.memory_mb == 8192
    assert package.timeout_s == 900


def test_nonsense_resource_figures_fall_back():
    package = marketplace.parse_package(_package(memory_mb="lots", timeout_s=None))
    assert package.memory_mb == 128
    assert package.timeout_s == 30


def test_declared_env_is_described_never_set():
    """The package says what it needs; it never gets to supply the values."""
    package = marketplace.parse_package(
        _package(env=[{"key": "SECRET", "required": True, "description": "the secret"}])
    )
    assert package.env == [
        {"key": "SECRET", "required": True, "description": "the secret"}
    ]
    assert "value" not in package.env[0]


# ── the registry that ships with the repo ────────────────────────────────────


def _repo_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / "docker-compose.yml").is_file():
            return parent
    return None


REPO = _repo_root()
needs_repo = pytest.mark.skipif(REPO is None, reason="not running from a checkout")


@needs_repo
def test_the_bundled_registry_parses():
    index = json.loads((REPO / "marketplace" / "index.json").read_text())
    listings = marketplace.parse_index(
        index, base_url="https://host/marketplace/index.json"
    )
    assert listings, "the bundled index lists nothing"

    for listing in listings:
        path = REPO / "marketplace" / "packages" / f"{listing.slug}.json"
        assert path.is_file(), f"{listing.slug} is listed but has no package file"
        package = marketplace.parse_package(json.loads(path.read_text()))
        assert package.slug == listing.slug
        assert package.runtime == listing.runtime
