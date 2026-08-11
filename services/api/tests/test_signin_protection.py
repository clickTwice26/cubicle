"""The sign-in form's two defences, and why each one is shaped as it is.

Signing in is the only unauthenticated endpoint that costs real work: every
attempt runs argon2id at 64 MB whether or not the account exists, deliberately,
so that a missing account and a wrong password take the same time. Two things
stand between that cost and the open internet, and both were wrong or absent
before these tests existed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cubicle import turnstile
from cubicle.config import settings
from cubicle.security import client_ip


def _request(headers: dict[str, str], peer: str = "203.0.113.9"):
    """The smallest thing client_ip actually reads."""
    return SimpleNamespace(
        headers={k.lower(): v for k, v in headers.items()},
        client=SimpleNamespace(host=peer),
    )


# ── which address the throttle counts ────────────────────────────────────────


def test_the_proxys_own_entry_is_used_not_the_callers():
    """X-Forwarded-For grows left to right, so the rightmost entry is ours.

    Reading the leftmost entry is the obvious way to do this and it is wrong:
    Caddy appends rather than replaces, so the left of that list is whatever
    the caller typed. This is the whole of CUB-01.
    """
    request = _request({"X-Forwarded-For": "10.0.0.1, 198.51.100.7"})
    assert client_ip(request) == "198.51.100.7"


def test_a_forged_prefix_cannot_change_the_answer():
    """The counter must land in the same bucket however much the caller invents."""
    real = "198.51.100.7"
    first = client_ip(_request({"X-Forwarded-For": f"1.1.1.1, {real}"}))
    second = client_ip(_request({"X-Forwarded-For": f"2.2.2.2, 3.3.3.3, {real}"}))
    third = client_ip(_request({"X-Forwarded-For": real}))
    assert first == second == third == real


def test_no_header_falls_back_to_the_socket():
    assert client_ip(_request({})) == "203.0.113.9"


def test_a_shorter_chain_than_configured_does_not_index_off_the_start():
    """Fewer hops than expected is misconfiguration, not a reason to raise."""
    assert client_ip(_request({"X-Forwarded-For": "198.51.100.7"})) == "198.51.100.7"


def test_more_proxies_reach_further_left():
    """Two proxies in front means the second entry from the right is ours."""
    original = settings.proxy_hops
    try:
        settings.proxy_hops = 2
        request = _request({"X-Forwarded-For": "1.1.1.1, 198.51.100.7, 10.0.0.9"})
        assert client_ip(request) == "198.51.100.7"
    finally:
        settings.proxy_hops = original


def test_an_untrusted_proxy_setup_ignores_the_header_entirely():
    original = settings.trust_proxy
    try:
        settings.trust_proxy = False
        request = _request({"X-Forwarded-For": "1.1.1.1"})
        assert client_ip(request) == "203.0.113.9"
    finally:
        settings.trust_proxy = original


# ── when a challenge is asked for ────────────────────────────────────────────


def _instance(**kwargs):
    base = {
        "turnstile_enabled": False,
        "turnstile_site_key": "",
        "turnstile_secret_ciphertext": None,
    }
    return SimpleNamespace(**{**base, **kwargs})


def test_turnstile_is_off_until_every_part_is_present():
    """A half-configured widget must not start refusing sign-ins."""
    assert not turnstile.configured(_instance())
    assert not turnstile.configured(_instance(turnstile_enabled=True))
    assert not turnstile.configured(_instance(turnstile_enabled=True, turnstile_site_key="0x4"))
    assert not turnstile.configured(
        _instance(turnstile_site_key="0x4", turnstile_secret_ciphertext="sealed")
    )


def test_turnstile_is_on_when_all_three_are_set():
    assert turnstile.configured(
        _instance(
            turnstile_enabled=True,
            turnstile_site_key="0x4",
            turnstile_secret_ciphertext="sealed",
        )
    )


@pytest.mark.anyio
async def test_an_unconfigured_instance_passes_without_a_network_call():
    """Nothing reaches Cloudflare until an operator turns this on."""
    verdict = await turnstile.verify(_instance(), token=None)
    assert verdict.ok


@pytest.mark.anyio
async def test_a_missing_token_fails_without_a_network_call():
    """An empty token is what a form that skipped the widget sends."""
    instance = _instance(
        turnstile_enabled=True,
        turnstile_site_key="0x4",
        turnstile_secret_ciphertext=turnstile.seal("0xSECRET"),
    )
    verdict = await turnstile.verify(instance, token="")
    assert not verdict.ok
    assert "no Turnstile token" in verdict.reason


# ── the secret at rest ───────────────────────────────────────────────────────


def test_the_secret_round_trips_through_the_envelope():
    sealed = turnstile.seal("0xSECRET")
    assert sealed != "0xSECRET"
    assert turnstile.unseal(_instance(turnstile_secret_ciphertext=sealed)) == "0xSECRET"


def test_an_undecryptable_secret_reads_as_absent_rather_than_raising():
    """A changed master key must not turn every sign-in into a 500."""
    assert turnstile.unseal(_instance(turnstile_secret_ciphertext="not-a-real-envelope")) is None


def test_the_secret_is_bound_to_its_own_purpose():
    """A ciphertext lifted from another field cannot be replayed into this one.

    The additional authenticated data differs per use, so a value sealed as an
    AI key does not open as a Turnstile secret even under the same master key.
    """
    from cubicle.crypto import encrypt

    elsewhere = encrypt("0xSECRET", aad="ai:key")
    assert turnstile.unseal(_instance(turnstile_secret_ciphertext=elsewhere)) is None
