"""When the reaper lets an isolate go.

The kill time is per function and zero means "use the instance-wide TTL", so
the cases worth pinning down are the boundary either side of it and the one
rule that overrides everything: a busy isolate is never taken, however long it
has been sitting there.
"""

import time

import pytest

from cubicle.config import settings
from cubicle.runtime.pool import Isolate, pool


@pytest.fixture
def reaper(monkeypatch):
    """The pool with a stubbed destroy, restored afterwards."""

    async def _noop(isolate, **kwargs):
        return None

    monkeypatch.setattr(pool, "_destroy", _noop)
    before = dict(pool._isolates)
    pool._isolates.clear()
    yield pool
    pool._isolates.clear()
    pool._isolates.update(before)


def _idle_for(seconds: float, *, busy: bool = False) -> Isolate:
    isolate = Isolate(
        container_id="aaaa1111",
        address="http://127.0.0.1:9000",
        spec_key="fn:v1",
        function_id="fn",
        version_id="v1",
        node_name="node-01",
        docker_host="unix:///var/run/docker.sock",
        memory_mb=128,
    )
    isolate.last_used = time.monotonic() - seconds
    isolate.busy = busy
    return isolate


async def test_zero_defers_to_the_instance_ttl(reaper):
    """A function nobody set a kill time on behaves as it did before it existed."""
    reaper._isolates["fn:v1"] = [_idle_for(settings.isolate_idle_ttl - 10)]

    assert await reaper.reap_idle(limits={"fn": (0, 4, 0)}) == 0


async def test_past_the_instance_ttl_it_still_goes(reaper):
    reaper._isolates["fn:v1"] = [_idle_for(settings.isolate_idle_ttl + 10)]

    assert await reaper.reap_idle(limits={"fn": (0, 4, 0)}) == 1


async def test_a_shorter_kill_time_reclaims_sooner(reaper):
    reaper._isolates["fn:v1"] = [_idle_for(60)]

    assert await reaper.reap_idle(limits={"fn": (0, 4, 30)}) == 1


async def test_a_longer_kill_time_keeps_it(reaper):
    reaper._isolates["fn:v1"] = [_idle_for(60)]

    assert await reaper.reap_idle(limits={"fn": (0, 4, 300)}) == 0


async def test_exactly_at_the_kill_time_is_kept(reaper):
    """Strictly past it, so a function polled on its own interval is not raced."""
    reaper._isolates["fn:v1"] = [_idle_for(30)]

    assert await reaper.reap_idle(limits={"fn": (0, 4, 31)}) == 0


async def test_a_busy_isolate_is_never_reclaimed(reaper):
    reaper._isolates["fn:v1"] = [_idle_for(9999, busy=True)]

    assert await reaper.reap_idle(limits={"fn": (0, 4, 1)}) == 0


async def test_min_instances_survives_its_own_kill_time(reaper):
    """Warm instances are the point of `min_instances`; the TTL does not win."""
    reaper._isolates["fn:v1"] = [_idle_for(9999)]

    assert await reaper.reap_idle(limits={"fn": (1, 4, 1)}) == 0


async def test_a_function_with_no_entry_uses_the_instance_ttl(reaper):
    """An isolate whose function was deleted still gets reaped, not orphaned."""
    reaper._isolates["fn:v1"] = [_idle_for(settings.isolate_idle_ttl + 10)]

    assert await reaper.reap_idle(limits={}) == 1
