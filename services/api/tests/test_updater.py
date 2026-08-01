"""Resolving HEAD out of raw git files, without git and without a checkout.

The parser exists because the API container has no git and no repository — it
reads the host's `.git` through a mount and works out what is deployed. Which
means every shape git stores a ref in has to be handled here.
"""

import pytest

from cubicle.runtime import updater

SHA = "6d6532d74df39fb56c2a5eae21872c0cea656a9f"


def _dump(*, head, refs="", packed="", config=""):
    return f"<<HEAD\n{head}\n" f"<<PACKED\n{packed}\n" f"<<CONFIG\n{config}\n" f"<<REFS\n{refs}\n"


def test_a_loose_ref_resolves():
    parsed = updater._parse_repo(_dump(head="ref: refs/heads/main", refs=f"refs/heads/main {SHA}"))
    assert parsed["sha"] == SHA
    assert parsed["branch"] == "main"


def test_a_packed_ref_resolves():
    """Git packs refs away as a repository ages; the loose file simply vanishes."""
    packed = f"# pack-refs with: peeled\n{SHA} refs/heads/main"
    parsed = updater._parse_repo(_dump(head="ref: refs/heads/main", packed=packed))
    assert parsed["sha"] == SHA


def test_a_loose_ref_wins_over_a_stale_packed_one():
    old = "0" * 40
    parsed = updater._parse_repo(
        _dump(
            head="ref: refs/heads/main",
            refs=f"refs/heads/main {SHA}",
            packed=f"{old} refs/heads/main",
        )
    )
    assert parsed["sha"] == SHA


def test_a_detached_head_is_its_own_sha():
    parsed = updater._parse_repo(_dump(head=SHA))
    assert parsed["sha"] == SHA
    assert parsed["branch"] == "(detached)"


def test_a_branch_with_slashes_keeps_its_full_ref():
    parsed = updater._parse_repo(
        _dump(head="ref: refs/heads/release/2.0", refs=f"refs/heads/release/2.0 {SHA}")
    )
    assert parsed["sha"] == SHA


def test_an_unresolvable_head_yields_no_sha():
    assert updater._parse_repo(_dump(head="ref: refs/heads/main"))["sha"] == ""


def test_only_the_origin_remote_is_read():
    """A fork's `upstream` remote must not be mistaken for where this deploys from."""
    config = (
        '[remote "upstream"]\n'
        "\turl = https://github.com/someone/else.git\n"
        '[remote "origin"]\n'
        "\turl = https://github.com/clickTwice26/cubicle.git\n"
    )
    parsed = updater._parse_repo(_dump(head=SHA, config=config))
    assert parsed["repo"] == "clickTwice26/cubicle"


def test_a_section_after_origin_ends_it():
    config = (
        '[remote "origin"]\n'
        "\turl = https://github.com/clickTwice26/cubicle.git\n"
        '[branch "main"]\n'
        "\turl = https://github.com/wrong/wrong.git\n"
    )
    assert updater._parse_repo(_dump(head=SHA, config=config))["repo"] == "clickTwice26/cubicle"


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/clickTwice26/cubicle.git",
        "https://github.com/clickTwice26/cubicle",
        "git@github.com:clickTwice26/cubicle.git",
        "ssh://git@github.com/clickTwice26/cubicle.git",
        "https://github.com/clickTwice26/cubicle/",
    ],
)
def test_every_github_url_shape_gives_the_same_slug(url):
    assert updater._slug(url) == "clickTwice26/cubicle"


@pytest.mark.parametrize("url", ["", "https://gitlab.com/a/b.git", "/srv/local/repo.git"])
def test_a_non_github_remote_has_no_slug(url):
    """Nothing to check against is reported, not guessed at."""
    assert updater._slug(url) == ""
