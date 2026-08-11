"""Removing a secret, and the difference between doing it and saying so.

A secret is written under a name the API chooses: SecretIn upper-cases it and
replaces anything that is not a letter, a digit or an underscore, so
`stripe_key` is stored as STRIPE_KEY. A delete names that key in the URL
instead, and the endpoint deleted whatever matched and answered 204 either way.
So a caller that sent the name as it was typed was told a secret had been
removed while it stayed in the store and stayed in every invocation's
environment. Deleting an env var has answered a miss with a 404 all along; this
is the same rule in the place that was missing it.

No database here. The endpoint is handed a session that reports what the DELETE
matched, which is the only thing the decision rests on.
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from cubicle.routers.functions import delete_secret
from cubicle.runtime import invoker


class Session:
    """A session whose DELETE matched a given number of rows."""

    def __init__(self, matched: int) -> None:
        self.matched = matched
        self.committed = False

    async def execute(self, statement):
        return SimpleNamespace(rowcount=self.matched)

    async def commit(self) -> None:
        self.committed = True


@pytest.fixture
def quiet_cache(monkeypatch):
    """The cache bump goes to Redis, which this decision has nothing to do with."""

    async def _bump() -> None:
        return None

    monkeypatch.setattr(invoker, "bump_env_revision", _bump)


async def test_removing_a_secret_that_is_not_there_says_so(quiet_cache):
    """The 204 it used to answer is indistinguishable from having deleted one."""
    db = Session(matched=0)

    with pytest.raises(HTTPException) as caught:
        await delete_secret(uuid.uuid4(), "stripe_key", db, None)

    assert caught.value.status_code == 404
    assert db.committed is False


async def test_removing_a_secret_that_is_there_still_answers_204(quiet_cache):
    """The behaviour that already worked, which the check must not have cost."""
    db = Session(matched=1)

    response = await delete_secret(uuid.uuid4(), "STRIPE_KEY", db, None)

    assert response.status_code == 204
    assert db.committed is True
