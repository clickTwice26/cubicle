"""What the control plane refuses to fetch, run, read, and disclose.

Four defects with one shape between them: the control plane sits on every
network Cubicle has, so anything that makes it act on a caller's behalf is a way
to reach the rest of the deployment. These pin the boundaries that were missing.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cubicle import marketplace
from cubicle.config import settings
from cubicle.routers.invoke import MAX_BODY_BYTES, _read_body, _TooLarge
from cubicle.runtime import redisadmin

# ── CUB-10: where a registry may live ────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/index.json",
        "http://localhost:5432/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/index.json",
        "http://0.0.0.0/",
    ],
)
def test_an_address_inside_the_deployment_is_refused(url):
    """The metadata service and the loopback interface are the classic targets."""
    with pytest.raises(marketplace.MarketplaceError):
        marketplace._reachable(url)


def test_a_name_that_resolves_inward_is_refused(monkeypatch):
    """The real attack is a public name with a private answer, not an IP literal.

    An attacker who controls a DNS record points it at 10.x and the URL looks
    ordinary right up until it is resolved.
    """
    monkeypatch.setattr(
        marketplace.socket,
        "getaddrinfo",
        lambda *a, **k: [(marketplace.socket.AF_INET, 1, 6, "", ("10.0.0.5", 80))],
    )
    with pytest.raises(marketplace.BlockedAddress) as caught:
        marketplace._reachable("http://registry.example.com/index.json")

    message = str(caught.value)
    assert "inside this network" in message
    # The address it resolved to is not echoed back: the caller supplied a name,
    # and what that name resolves to on this network is not theirs to learn.
    assert "10.0.0.5" not in message


def test_every_address_a_name_resolves_to_is_checked(monkeypatch):
    """A name answering with one public and one private address is refused.

    Checking only the first answer is checking nothing: the order is the
    resolver's to choose and an attacker can put a decoy in front.
    """
    monkeypatch.setattr(
        marketplace.socket,
        "getaddrinfo",
        lambda *a, **k: [
            (marketplace.socket.AF_INET, 1, 6, "", ("93.184.216.34", 80)),
            (marketplace.socket.AF_INET, 1, 6, "", ("127.0.0.1", 80)),
        ],
    )
    with pytest.raises(marketplace.BlockedAddress):
        marketplace._reachable("http://registry.example.com/index.json")


def test_a_scheme_that_is_not_http_is_refused():
    for url in ("file:///etc/passwd", "gopher://x/", "ftp://x/"):
        with pytest.raises(marketplace.MarketplaceError):
            marketplace._reachable(url)


def test_a_url_with_no_host_is_refused():
    with pytest.raises(marketplace.MarketplaceError):
        marketplace._reachable("http:///index.json")


def test_an_operator_can_allow_their_own_registry_on_the_lan():
    """A private registry is a real deployment, so the door opens by configuration."""
    original = settings.marketplace_allow_private
    try:
        settings.marketplace_allow_private = True
        marketplace._reachable("http://10.0.0.5/index.json")  # no raise
    finally:
        settings.marketplace_allow_private = original


def test_redirects_are_followed_here_and_not_by_the_transport():
    """Checking only the typed URL and then chasing a 302 checks nothing.

    The guard has to run per hop, which means the fetch cannot delegate
    redirect following to httpx.
    """
    import inspect

    source = inspect.getsource(marketplace._fetch)
    assert "follow_redirects=False" in source
    assert "_reachable(url)" in source


# ── CUB-11: what the Redis console may run ───────────────────────────────────


@pytest.mark.parametrize(
    "command",
    ["config", "module", "replicaof", "slaveof", "save", "bgsave", "script", "eval", "acl"],
)
def test_a_command_that_reaches_out_of_redis_is_refused(command):
    """CONFIG SET plus SAVE writes a file. REPLICAOF plus MODULE LOAD runs code."""
    assert command in redisadmin.ESCALATING_COMMANDS


def test_the_two_denylists_are_kept_apart_by_purpose():
    """One is about liveness and one is about reach, and conflating them is how
    the second went missing for as long as it did."""
    assert set() == redisadmin.BLOCKING_COMMANDS & redisadmin.ESCALATING_COMMANDS
    assert "monitor" in redisadmin.BLOCKING_COMMANDS
    assert "module" not in redisadmin.BLOCKING_COMMANDS


def test_reading_and_writing_keys_is_still_free():
    """The console is for the data, and it is still allowed all of the data."""
    for command in ("get", "set", "hgetall", "lrange", "scan", "del", "expire", "flushdb"):
        assert command not in redisadmin.BLOCKED_COMMANDS


# ── CUB-12: how much of a body is read ───────────────────────────────────────


def _request(chunks: list[bytes], headers: dict[str, str] | None = None):
    async def stream():
        for chunk in chunks:
            yield chunk

    return SimpleNamespace(headers=headers or {}, stream=stream)


@pytest.mark.anyio
async def test_a_body_within_the_limit_arrives_whole():
    body = await _read_body(_request([b"hello ", b"world"]))
    assert body == b"hello world"


@pytest.mark.anyio
async def test_a_declared_length_over_the_limit_is_refused_before_anything_arrives():
    """The ordinary case, refused without reading a byte."""
    sent = []

    async def stream():
        sent.append(1)
        yield b"x"

    request = SimpleNamespace(headers={"content-length": str(MAX_BODY_BYTES + 1)}, stream=stream)
    with pytest.raises(_TooLarge):
        await _read_body(request)
    assert sent == [], "the body was read despite a declared length over the limit"


@pytest.mark.anyio
async def test_a_body_that_lies_about_its_length_is_still_bounded():
    """A header is a claim. Chunked encoding does not even make the claim."""
    chunk = b"x" * (1024 * 1024)
    chunks = [chunk] * 10
    with pytest.raises(_TooLarge):
        await _read_body(_request(chunks))


@pytest.mark.anyio
async def test_reading_stops_at_the_limit_rather_than_at_the_end():
    """The point of the fix: what is read is bounded, not just what is accepted."""
    read = 0

    async def stream():
        nonlocal read
        for _ in range(100):
            read += 1
            yield b"y" * (1024 * 1024)

    with pytest.raises(_TooLarge):
        await _read_body(SimpleNamespace(headers={}, stream=stream))
    assert read <= 7, f"read {read} MB before giving up on a 6 MB limit"


# ── CUB-14: what an anonymous caller may learn ───────────────────────────────


def test_the_credential_is_checked_before_existence_is_disclosed():
    """404 for absent and 401 for present is an enumeration oracle.

    The four outcomes below the auth check each say something about a function
    that does exist: paused, wrong method, never built. Whichever of them a
    caller reaches, reaching it at all confirms the name. So the order of these
    two blocks is the whole control, and this pins it.
    """
    import inspect

    from cubicle.routers import invoke

    source = inspect.getsource(invoke._invoke)
    unauthorised = source.index('"error": "unauthorized"')
    not_found = source.index('"error": "not_found"')
    assert unauthorised < not_found, (
        "existence is disclosed before the credential is checked, so an anonymous "
        "caller can tell a real function name from an invented one"
    )


def test_a_missing_function_is_treated_as_though_it_needed_a_key():
    """Otherwise the 401 itself is the signal: only real functions produce it."""
    import inspect

    from cubicle.routers import invoke

    source = inspect.getsource(invoke._invoke)
    assert "fn is None or fn.auth_required" in source
