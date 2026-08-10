"""Whether the pool waits for a busy isolate or starts another one.

Room in the pool is not by itself a reason to spawn. A burst of short requests
makes every isolate momentarily busy, and answering that with a cold start
gives the caller a four hundred millisecond wait for a five millisecond
handler, then leaves the cluster carrying a container it did not need.

These pin down the decision itself, which is pure arithmetic over the pool's
own measurements, so none of them start a container.
"""

import time

from cubicle.runtime.pool import DEFAULT_BOOT_S, Isolate, IsolatePool


def _busy(key: str, *, running_for: float) -> Isolate:
    now = time.monotonic()
    return Isolate(
        container_id="aaaa1111",
        address="http://127.0.0.1:9000",
        spec_key=key,
        function_id="fn",
        version_id="v1",
        node_name="node-01",
        docker_host="unix:///var/run/docker.sock",
        memory_mb=128,
        busy=True,
        busy_since=now - running_for,
    )


def test_nothing_running_means_start_one():
    """The first request has nothing to wait for."""
    assert IsolatePool()._worth_waiting([], "fn:v1", 0.0) is None


def test_an_unmeasured_function_starts_one():
    """Without a service time there is no basis for waiting, so do not guess."""
    isolated = IsolatePool()
    assert isolated._worth_waiting([_busy("fn:v1", running_for=0.0)], "fn:v1", 0.0) is None


def test_a_fast_handler_is_waited_for():
    """A 5 ms handler will be free long before a container could boot."""
    isolated = IsolatePool()
    isolated._service["fn:v1"] = 0.005
    patience = isolated._worth_waiting([_busy("fn:v1", running_for=0.001)], "fn:v1", 0.0)
    assert patience is not None
    assert patience < DEFAULT_BOOT_S


def test_a_slow_handler_is_not_waited_for():
    """A 2 s handler that has just started is further away than a cold start."""
    isolated = IsolatePool()
    isolated._service["fn:v1"] = 2.0
    assert isolated._worth_waiting([_busy("fn:v1", running_for=0.0)], "fn:v1", 0.0) is None


def test_a_slow_handler_almost_done_is_waited_for():
    """The same handler is worth waiting for once it is nearly finished."""
    isolated = IsolatePool()
    isolated._service["fn:v1"] = 2.0
    patience = isolated._worth_waiting([_busy("fn:v1", running_for=1.95)], "fn:v1", 0.0)
    assert patience is not None


def test_the_soonest_isolate_decides():
    """One isolate about to finish is enough, however busy the others are."""
    isolated = IsolatePool()
    isolated._service["fn:v1"] = 1.0
    pool = [_busy("fn:v1", running_for=0.0), _busy("fn:v1", running_for=0.98)]
    assert isolated._worth_waiting(pool, "fn:v1", 0.0) is not None


def test_deferring_is_bounded_by_one_boot():
    """A request that has already waited out a boot stops waiting and spawns.

    Without this a stream of requests against a saturated pool could defer
    each other indefinitely and never grow it.
    """
    isolated = IsolatePool()
    isolated._service["fn:v1"] = 0.005
    pool = [_busy("fn:v1", running_for=0.0)]
    assert isolated._worth_waiting(pool, "fn:v1", DEFAULT_BOOT_S) is None


def test_a_measured_boot_replaces_the_assumed_one():
    """A node whose boots are slow is more patient, and one that is fast less."""
    isolated = IsolatePool()
    isolated._service["fn:v1"] = 0.30
    pool = [_busy("fn:v1", running_for=0.0)]

    isolated._boot["fn:v1"] = 0.10
    assert isolated._worth_waiting(pool, "fn:v1", 0.0) is None

    isolated._boot["fn:v1"] = 1.20
    assert isolated._worth_waiting(pool, "fn:v1", 0.0) is not None


def test_an_idle_pool_is_not_waited_on():
    """Nothing is busy, so there is no release to wait for."""
    isolated = IsolatePool()
    isolated._service["fn:v1"] = 0.005
    idle = _busy("fn:v1", running_for=0.0)
    idle.busy = False
    assert isolated._worth_waiting([idle], "fn:v1", 0.0) is None


def test_the_rolling_mean_tracks_the_newest_sample():
    store: dict[str, float] = {}
    IsolatePool._observe(store, "fn:v1", 1.0)
    assert store["fn:v1"] == 1.0
    IsolatePool._observe(store, "fn:v1", 2.0)
    assert 1.0 < store["fn:v1"] < 2.0
