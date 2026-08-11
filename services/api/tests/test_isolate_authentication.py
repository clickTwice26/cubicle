"""What stops one tenant's function invoking another's isolate directly.

Every isolate on the instance shares one Docker network, so an agent's
``/invoke`` port is reachable by any function anyone has deployed. Nothing
about that changes here: the network is still flat. What changes is that the
port now needs a credential, so reaching it is not the same as being allowed to
use it, and the API's cluster access control stops being something a handler
can simply route around.
"""

from __future__ import annotations

from cubicle.config import settings
from cubicle.runtime.pool import agent_token


def test_each_function_version_gets_its_own_token():
    """A token lifted from one isolate is useless against another."""
    a = agent_token("fn-a", "v1")
    b = agent_token("fn-b", "v1")
    assert a != b


def test_a_new_version_gets_a_new_token():
    """Redeploying rotates it, so a token read out of an old container expires."""
    assert agent_token("fn-a", "v1") != agent_token("fn-a", "v2")


def test_the_token_is_stable_for_one_version():
    """This is what lets adopt() re-attach after the control plane restarts.

    A random token would have been lost with the process that generated it, and
    every warm isolate would have to be destroyed on the way back up.
    """
    assert agent_token("fn-a", "v1") == agent_token("fn-a", "v1")


def test_the_token_depends_on_the_instance_secret():
    """Two instances cannot invoke each other's isolates, even with the same ids."""
    original = settings.secret_key
    try:
        settings.secret_key = "instance-one-secret-key-value"
        first = agent_token("fn-a", "v1")
        settings.secret_key = "instance-two-secret-key-value"
        second = agent_token("fn-a", "v1")
        assert first != second
    finally:
        settings.secret_key = original


def test_the_token_does_not_leak_the_secret():
    """It is a digest, not the key itself, in case a handler reads its own env."""
    token = agent_token("fn-a", "v1")
    assert settings.secret_key not in token
    assert len(token) == 64
    assert set(token) <= set("0123456789abcdef")
