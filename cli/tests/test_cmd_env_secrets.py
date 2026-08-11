"""Cluster variables and per-function secrets, and the name they are filed under.

The write path normalises: EnvVarIn and SecretIn upper-case the key and replace
anything that is not a letter, a digit or an underscore, so `stripe-key` is
stored as STRIPE_KEY. The delete path names the key in the URL rather than in a
body, so it has to apply the same rule. It did not, which made `secrets rm
stripe_key` delete nothing while printing that it had, and made `env rm` a 404
one line after `env set` reported success.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def typed_value(monkeypatch):
    """Somebody at a terminal typing a secret's value at the getpass prompt."""
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "sk_live_4f21")


def _ctrl_d(prompt: str = "") -> str:
    """What a prompt does when the terminal is closed under it."""
    raise EOFError


# ── cluster variables ────────────────────────────────────────────────────────


def test_a_variable_is_removed_under_the_name_the_api_stored(api, run):
    """`env rm stripe_mode` has to address STRIPE_MODE or it removes nothing."""
    api.on("DELETE", "/api/env/STRIPE_MODE", None)

    assert run("env", "rm", "stripe_mode") == 0


def test_a_variable_name_is_normalised_rather_than_upper_cased(api, run, capsys):
    """A hyphen is not a legal character in a key, so it is not simply raised."""
    api.on("DELETE", "/api/env/STRIPE_MODE", None)

    assert run("env", "rm", "stripe-mode") == 0
    assert "removed STRIPE_MODE" in capsys.readouterr().out


def test_setting_a_variable_echoes_the_name_it_was_stored_under(api, run, capsys):
    """The value is written by the name the API chose, and that is the name to print."""
    api.on("POST", "/api/env", {"key": "STRIPE_MODE", "value": "live", "is_secret": False})

    assert run("env", "set", "stripe-mode=live") == 0

    assert "set STRIPE_MODE" in capsys.readouterr().out
    # The body is sent as typed: the API owns the rule, and this only mirrors it.
    assert api.last("POST", "/api/env").body["key"] == "stripe-mode"


# ── per-function secrets ─────────────────────────────────────────────────────


def test_a_secret_is_removed_under_the_name_the_api_stored(api, run, api_function):
    """The endpoint answers 204 for a key it never had, so a miss is silent."""
    api.on("GET", "/api/functions", [api_function()])
    api.on("DELETE", "/api/functions/fn-1/secrets/STRIPE_KEY", None)

    assert run("secrets", "--function", "payments/create-charge", "rm", "stripe_key") == 0


def test_a_secret_name_is_normalised_rather_than_upper_cased(api, run, api_function, capsys):
    api.on("GET", "/api/functions", [api_function()])
    api.on("DELETE", "/api/functions/fn-1/secrets/STRIPE_KEY", None)

    assert run("secrets", "--function", "payments/create-charge", "rm", "stripe-key") == 0
    assert "removed STRIPE_KEY" in capsys.readouterr().out


def test_sealing_a_secret_echoes_the_name_it_was_stored_under(
    api, run, api_function, typed_value, capsys
):
    """Printing STRIPE-KEY teaches a name that would remove nothing tomorrow."""
    api.on("GET", "/api/functions", [api_function()])
    api.on(
        "POST",
        "/api/functions/fn-1/secrets",
        {"key": "STRIPE_KEY", "value": "sk_…4f21", "updated_at": "2026-08-10T14:03:31Z"},
    )

    assert run("secrets", "--function", "payments/create-charge", "set", "stripe-key") == 0

    assert "sealed STRIPE_KEY" in capsys.readouterr().out


def test_ctrl_d_at_the_value_prompt_ends_the_command(api, run, api_function, monkeypatch):
    """A value has no safe default the way a y/N question does, so nothing is sent."""
    api.on("GET", "/api/functions", [api_function()])
    monkeypatch.setattr("getpass.getpass", _ctrl_d)

    assert run("secrets", "--function", "payments/create-charge", "set", "stripe_key") == 130

    assert api.sent("POST", "/api/functions/fn-1/secrets") == []


def test_a_secret_listing_shows_the_masked_value(api, run, api_function, capsys):
    """`ls` is the only place a secret is readable, and only as its last four."""
    api.on("GET", "/api/functions", [api_function()])
    api.on(
        "GET",
        "/api/functions/fn-1/secrets",
        [{"key": "STRIPE_KEY", "value": "sk_…4f21", "updated_at": "2026-08-10T14:03:31Z"}],
    )

    assert run("secrets", "--function", "payments/create-charge", "ls") == 0

    out = capsys.readouterr().out
    assert "STRIPE_KEY" in out
    assert "sk_…4f21" in out
