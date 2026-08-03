"""The reconciler's judgement, without a Docker daemon or a database.

The parts worth pinning down are the ones a live scan cannot reach: the pool is
in-process, so drift between it and Docker only exists inside the API's own
memory, and the grace period that stops a starting container being called an
orphan is invisible unless you control the clock.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from cubicle.models import Cluster, Function, Group, ManagedService, Node
from cubicle.runtime import reconcile
from cubicle.runtime.pool import Isolate, pool

HOST = "unix:///var/run/docker.sock"


def _ago(seconds: float) -> str:
    """A Docker `Created` stamp, in Docker's own nanosecond format."""
    when = datetime.now(UTC) - timedelta(seconds=seconds)
    return when.strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond:06d}000Z"


class FakeContainer:
    def __init__(self, cid, *, role, status="running", age=9999, labels=None, name=None):
        self.id = cid
        self.name = name or f"container-{cid[:6]}"
        self.status = status
        self.labels = {"cubicle.role": role, **(labels or {})}
        self.attrs = {"Created": _ago(age)}


class FakeVolume:
    def __init__(self, name):
        self.name = name


class FakeClient:
    """Answers the same calls the real closures make, so filters are exercised."""

    def __init__(self, containers, volumes):
        self._containers = containers
        self._volumes = volumes
        outer = self

        class _Containers:
            def list(self, all=False, filters=None):  # noqa: A002 - docker's own name
                want = (filters or {}).get("label", "").split("=")[-1]
                return [c for c in outer._containers if c.labels.get("cubicle.role") == want]

        class _Volumes:
            def list(self, filters=None):
                return outer._volumes

        self.containers = _Containers()
        self.volumes = _Volumes()


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeSession:
    """Answers each ``select`` by what it asks for, not by call order."""

    def __init__(self, *, clusters=(), functions=(), services=(), nodes=()):
        self.rows = {
            (Cluster, None): list(clusters),
            (Function, None): list(functions),
            (Function, "id"): [f.id for f in functions],
            (ManagedService, None): list(services),
            (Node, None): list(nodes),
            (Node, "docker_host"): [n.docker_host for n in nodes],
        }

    async def execute(self, stmt):
        description = stmt.column_descriptions[0]
        key = (description["entity"], description["name"])
        if key not in self.rows:
            key = (description["entity"], None)
        return FakeResult(self.rows.get(key, []))


@pytest.fixture
def empty_pool():
    """The pool is a singleton; leave it as it was found."""
    before = dict(pool._isolates)
    pool._isolates.clear()
    yield pool
    pool._isolates.clear()
    pool._isolates.update(before)


@pytest.fixture
def docker(monkeypatch):
    def _install(containers=(), volumes=(), unreachable=()):
        async def _call(host, fn, *args, **kwargs):
            if host in unreachable:
                raise RuntimeError("connection refused")
            return fn(FakeClient(list(containers), list(volumes)))

        monkeypatch.setattr(reconcile.engines, "call", _call)

    return _install


def _isolate(cid, **kwargs):
    kwargs.setdefault("memory_mb", 512)
    return Isolate(
        container_id=cid,
        address="http://127.0.0.1:9000",
        spec_key="fn:v1",
        function_id="fn",
        version_id="v1",
        node_name="node-01",
        docker_host=HOST,
        **kwargs,
    )


def _node():
    node = Node(name="node-01", docker_host=HOST)
    node.cluster_id = None
    return node


# ── the pool believing in containers that are gone ───────────────────────────


async def test_pool_entry_whose_container_vanished_is_an_error(empty_pool, docker):
    empty_pool._isolates["fn:v1"] = [_isolate("aaaa1111", cluster="prod", name="charge")]
    docker(containers=[])

    findings = await reconcile.scan(FakeSession(nodes=[_node()]))

    assert [f.kind for f in findings] == ["stale_pool_entry"]
    assert findings[0].severity == "error"
    assert "no longer exists" in findings[0].summary
    assert findings[0].fix == "Drop it from the pool"


async def test_pool_entry_whose_container_stopped_is_an_error(empty_pool, docker):
    empty_pool._isolates["fn:v1"] = [_isolate("aaaa1111", cluster="prod", name="charge")]
    docker(containers=[FakeContainer("aaaa1111", role="isolate", status="exited")])

    findings = await reconcile.scan(FakeSession(nodes=[_node()]))

    stale = [f for f in findings if f.kind == "stale_pool_entry"]
    assert len(stale) == 1
    assert "has stopped" in stale[0].summary
    assert "remove the container" in stale[0].fix


async def test_a_healthy_isolate_is_not_a_finding(empty_pool, docker):
    empty_pool._isolates["fn:v1"] = [_isolate("aaaa1111", cluster="prod")]
    docker(containers=[FakeContainer("aaaa1111", role="isolate")])

    assert await reconcile.scan(FakeSession(nodes=[_node()])) == []


# ── containers the pool does not know about ──────────────────────────────────


async def test_a_starting_container_is_not_called_an_orphan(empty_pool, docker):
    """The window between `docker run` and joining the pool is not drift."""
    docker(containers=[FakeContainer("bbbb2222", role="isolate", age=5)])

    assert await reconcile.scan(FakeSession(nodes=[_node()])) == []


async def test_a_long_running_untracked_container_is_an_orphan(empty_pool, docker):
    docker(containers=[FakeContainer("bbbb2222", role="isolate", age=6000)])

    findings = await reconcile.scan(FakeSession(nodes=[_node()]))

    assert [f.kind for f in findings] == ["orphan_isolate"]
    assert findings[0].fix == "Remove the container"
    assert not findings[0].destructive


async def test_a_stopped_container_is_an_orphan_however_young(empty_pool, docker):
    """Nothing that has already exited is still starting up."""
    docker(containers=[FakeContainer("bbbb2222", role="isolate", status="exited", age=1)])

    assert [f.kind for f in await reconcile.scan(FakeSession(nodes=[_node()]))] == [
        "orphan_isolate"
    ]


async def test_a_stopped_service_container_is_an_orphan_however_young(empty_pool, docker):
    docker(containers=[FakeContainer("cccc3333", role="service", status="exited", age=1)])

    assert [f.kind for f in await reconcile.scan(FakeSession(nodes=[_node()]))] == [
        "orphan_service_container"
    ]


# ── volumes and unreachable nodes ────────────────────────────────────────────


async def test_an_unclaimed_volume_is_flagged_destructive(empty_pool, docker):
    docker(volumes=[FakeVolume("cubicle-prod-postgres")])

    findings = await reconcile.scan(FakeSession(nodes=[_node()]))

    assert [f.kind for f in findings] == ["orphan_volume"]
    assert findings[0].destructive is True


async def test_a_claimed_volume_is_left_alone(empty_pool, docker):
    service = ManagedService(kind="postgres", volume_name="cubicle-prod-postgres")
    docker(volumes=[FakeVolume("cubicle-prod-postgres")])

    assert await reconcile.scan(FakeSession(nodes=[_node()], services=[service])) == []


async def test_an_unreachable_node_reports_and_offers_no_fix(empty_pool, docker):
    docker(unreachable={HOST})

    findings = await reconcile.scan(FakeSession(nodes=[_node()]))

    assert [f.kind for f in findings] == ["node_unreachable"]
    assert findings[0].fix is None


async def test_an_unreachable_node_does_not_orphan_what_it_holds(empty_pool, docker):
    """A host we cannot see is not evidence that its isolates are gone."""
    empty_pool._isolates["fn:v1"] = [_isolate("aaaa1111", cluster="prod")]
    docker(unreachable={HOST})

    assert [f.kind for f in await reconcile.scan(FakeSession(nodes=[_node()]))] == [
        "node_unreachable"
    ]


# ── the pool's own bookkeeping ───────────────────────────────────────────────


def test_forget_drops_only_the_named_isolate(empty_pool):
    empty_pool._isolates["fn:v1"] = [_isolate("aaaa1111"), _isolate("bbbb2222")]

    assert empty_pool.forget("aaaa1111") is True
    assert [i.container_id for i in empty_pool.tracked()] == ["bbbb2222"]
    assert empty_pool.forget("aaaa1111") is False


def test_tracked_is_a_copy(empty_pool):
    """Callers iterate it across slow engine calls; it must not move underneath."""
    empty_pool._isolates["fn:v1"] = [_isolate("aaaa1111")]
    tracked = empty_pool.tracked()
    empty_pool._isolates["fn:v1"] = []

    assert len(tracked) == 1


# ── timestamp parsing ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "stamp",
    [
        "2024-01-01T00:00:00.123456789Z",  # docker's nanoseconds
        "2024-01-01T00:00:00Z",
        "2024-01-01T00:00:00.123456+00:00",
    ],
)
def test_created_stamps_parse(stamp):
    assert reconcile._created_age({"Created": stamp}) > 0


@pytest.mark.parametrize("attrs", [{}, {"Created": ""}, {"Created": "not a date"}])
def test_unparseable_stamps_read_as_zero_age(attrs):
    """Zero means 'too young to judge', which errs towards leaving things alone."""
    assert reconcile._created_age(attrs) == 0.0


# ── applying ─────────────────────────────────────────────────────────────────


class RecordingSession(FakeSession):
    """A session that remembers commits, and hands back services by id."""

    def __init__(self, services=(), **kwargs):
        super().__init__(services=services, **kwargs)
        self.by_id = {s.id: s for s in services}
        self.commits = 0

    async def get(self, model, pk):
        return self.by_id.get(pk)

    async def commit(self):
        self.commits += 1


@pytest.fixture
def removals(monkeypatch):
    """Capture what apply would have asked Docker to do."""
    seen = []

    class Recorder:
        def __init__(self):
            outer = self

            class _Containers:
                def get(self, cid):
                    seen.append(("container", cid))
                    return _Removable()

            class _Volumes:
                def get(self, name):
                    seen.append(("volume", name))
                    return _Removable()

            class _Removable:
                def remove(self, force=False):
                    return None

            outer.containers = _Containers()
            outer.volumes = _Volumes()

    async def _call(host, fn, *args, **kwargs):
        return fn(Recorder())

    monkeypatch.setattr(reconcile.engines, "call", _call)
    return seen


async def test_applying_a_stale_entry_drops_it_and_removes_the_container(empty_pool, removals):
    empty_pool._isolates["fn:v1"] = [_isolate("aaaa1111")]
    finding = reconcile.Finding(
        id="stale-isolate:aaaa1111",
        kind="stale_pool_entry",
        severity="error",
        cluster="prod",
        summary="",
        detail="",
        fix="Drop it from the pool",
        target={"host": HOST, "container": "aaaa1111"},
    )

    result = await reconcile.apply(RecordingSession(), [finding], {finding.id})

    assert result["applied"] == [finding.id]
    assert empty_pool.tracked() == []
    assert ("container", "aaaa1111") in removals


async def test_applying_an_orphan_volume_removes_that_volume(empty_pool, removals):
    finding = reconcile.Finding(
        id="orphan-volume:v",
        kind="orphan_volume",
        severity="warn",
        cluster="",
        summary="",
        detail="",
        fix="Delete the volume and everything in it",
        destructive=True,
        target={"host": HOST, "volume": "cubicle-old-data"},
    )

    await reconcile.apply(RecordingSession(), [finding], {finding.id})

    assert removals == [("volume", "cubicle-old-data")]


async def test_only_chosen_findings_are_touched(empty_pool, removals):
    findings = [
        reconcile.Finding(
            id=f"orphan-isolate:{cid}",
            kind="orphan_isolate",
            severity="warn",
            cluster="",
            summary="",
            detail="",
            fix="Remove the container",
            target={"host": HOST, "container": cid},
        )
        for cid in ("keep-me", "remove-me")
    ]

    await reconcile.apply(RecordingSession(), findings, {"orphan-isolate:remove-me"})

    assert removals == [("container", "remove-me")]


async def test_an_id_that_no_longer_exists_is_skipped_not_failed(empty_pool, removals):
    """Drift that resolved itself between looking and acting is not an error."""
    result = await reconcile.apply(RecordingSession(), [], {"orphan-isolate:vanished"})

    assert result == {"applied": [], "failed": [], "skipped": ["orphan-isolate:vanished"]}


async def test_a_finding_with_no_fix_is_never_acted_on(empty_pool, removals):
    finding = reconcile.Finding(
        id="node-unreachable:tcp://gone:2376",
        kind="node_unreachable",
        severity="error",
        cluster="",
        summary="",
        detail="",
        fix=None,
        target={"host": "tcp://gone:2376"},
    )

    result = await reconcile.apply(RecordingSession(), [finding], {finding.id})

    assert result["applied"] == []
    assert removals == []


async def test_a_missing_service_is_marked_stopped_and_unlinked(empty_pool, removals):
    # An id is normally assigned on flush; there is no database here.
    service = ManagedService(
        id=uuid.uuid4(), kind="postgres", status="running", container_id="deadbeef"
    )
    session = RecordingSession(services=[service])
    finding = reconcile.Finding(
        id=f"service-missing:{service.id}",
        kind="service_container_missing",
        severity="error",
        cluster="prod",
        summary="",
        detail="",
        fix="Mark it stopped",
        target={"service": str(service.id)},
    )

    await reconcile.apply(session, [finding], {finding.id})

    assert service.status == "stopped"
    assert service.container_id is None
    assert session.commits == 1


async def test_one_failure_does_not_stop_the_others(empty_pool, monkeypatch):
    calls = []

    async def _call(host, fn, *args, **kwargs):
        calls.append(host)
        if host == "tcp://broken:2376":
            raise RuntimeError("engine is down")

    monkeypatch.setattr(reconcile.engines, "call", _call)

    def _orphan(cid, host):
        return reconcile.Finding(
            id=f"orphan-isolate:{cid}",
            kind="orphan_isolate",
            severity="warn",
            cluster="",
            summary="",
            detail="",
            fix="Remove the container",
            target={"host": host, "container": cid},
        )

    findings = [_orphan("a", "tcp://broken:2376"), _orphan("b", HOST)]

    result = await reconcile.apply(RecordingSession(), findings, {f.id for f in findings})

    assert result["applied"] == ["orphan-isolate:b"]
    assert len(result["failed"]) == 1
    assert "engine is down" in result["failed"][0]["error"]


# ── allocation against the ceilings ──────────────────────────────────────────
#
# Admission control refuses anything that would breach a ceiling, so these only
# arise when the ceiling moved after the containers started, or they were
# adopted across a restart without being re-tested. The property worth pinning
# down is that nothing busy is ever proposed for reclaim.


def _cluster(**kwargs):
    cluster = Cluster(name="Prod", slug="prod", **kwargs)
    cluster.id = uuid.uuid4()
    return cluster


def _function(cluster, *, memory_mb=128, max_instances=2, name="charge"):
    group = Group(name="Payments", ns="payments")
    group.id = uuid.uuid4()
    group.cluster_id = cluster.id
    fn = Function(name=name, memory_mb=memory_mb, max_instances=max_instances)
    fn.id = uuid.uuid4()
    fn.group_id = group.id
    fn.group = group
    return fn


def _for(fn, cid, **kwargs):
    """An isolate of the size its function asks for, unless told otherwise."""
    kwargs.setdefault("memory_mb", fn.memory_mb)
    isolate = _isolate(cid, cluster="prod", name=fn.name, **kwargs)
    isolate.function_id = str(fn.id)
    return isolate


async def test_a_cluster_within_its_ceiling_is_not_a_finding(empty_pool, docker):
    cluster = _cluster(max_memory_mb=2048, max_cpu_cores=8)
    fn = _function(cluster)
    empty_pool._isolates["fn:v1"] = [_for(fn, "aaaa1111")]
    docker(containers=[FakeContainer("aaaa1111", role="isolate")])

    findings = await reconcile.scan(
        FakeSession(clusters=[cluster], functions=[fn], nodes=[_node()])
    )
    assert [f.kind for f in findings] == []


async def test_holding_more_than_the_ceiling_is_an_error(empty_pool, docker):
    """A ceiling lowered under running containers."""
    cluster = _cluster(max_memory_mb=512, max_cpu_cores=64)
    fn = _function(cluster, memory_mb=512, max_instances=8)
    empty_pool._isolates["fn:v1"] = [_for(fn, "aaaa1111"), _for(fn, "bbbb2222")]
    docker(
        containers=[
            FakeContainer("aaaa1111", role="isolate"),
            FakeContainer("bbbb2222", role="isolate"),
        ]
    )

    findings = await reconcile.scan(
        FakeSession(clusters=[cluster], functions=[fn], nodes=[_node()])
    )
    over = [f for f in findings if f.kind == "cluster_over_ceiling"]
    assert len(over) == 1
    assert over[0].severity == "error"
    assert over[0].fix == "Reclaim 2 idle instances"
    assert set(over[0].target["containers"]) == {"aaaa1111", "bbbb2222"}


async def test_a_busy_instance_is_never_proposed_for_reclaim(empty_pool, docker):
    """Getting back under a ceiling does not justify failing a live request."""
    cluster = _cluster(max_memory_mb=512, max_cpu_cores=64)
    fn = _function(cluster, memory_mb=512, max_instances=8)
    empty_pool._isolates["fn:v1"] = [
        _for(fn, "aaaa1111", busy=True),
        _for(fn, "bbbb2222"),
    ]
    docker(
        containers=[
            FakeContainer("aaaa1111", role="isolate"),
            FakeContainer("bbbb2222", role="isolate"),
        ]
    )

    findings = await reconcile.scan(
        FakeSession(clusters=[cluster], functions=[fn], nodes=[_node()])
    )
    over = next(f for f in findings if f.kind == "cluster_over_ceiling")
    assert over.target["containers"] == ["bbbb2222"]


async def test_every_instance_busy_offers_no_fix(empty_pool, docker):
    cluster = _cluster(max_memory_mb=512, max_cpu_cores=64)
    fn = _function(cluster, memory_mb=512, max_instances=8)
    empty_pool._isolates["fn:v1"] = [
        _for(fn, "aaaa1111", busy=True),
        _for(fn, "bbbb2222", busy=True),
    ]
    docker(
        containers=[
            FakeContainer("aaaa1111", role="isolate"),
            FakeContainer("bbbb2222", role="isolate"),
        ]
    )

    findings = await reconcile.scan(
        FakeSession(clusters=[cluster], functions=[fn], nodes=[_node()])
    )
    over = next(f for f in findings if f.kind == "cluster_over_ceiling")
    assert over.fix is None
    assert "Every instance is busy" in over.detail


async def test_more_instances_than_the_function_allows(empty_pool, docker):
    cluster = _cluster()
    fn = _function(cluster, max_instances=1)
    empty_pool._isolates["fn:v1"] = [_for(fn, "aaaa1111"), _for(fn, "bbbb2222")]
    docker(
        containers=[
            FakeContainer("aaaa1111", role="isolate"),
            FakeContainer("bbbb2222", role="isolate"),
        ]
    )

    findings = await reconcile.scan(
        FakeSession(clusters=[cluster], functions=[fn], nodes=[_node()])
    )
    over = [f for f in findings if f.kind == "function_over_max_instances"]
    assert len(over) == 1
    # Only the surplus, not every instance: one is allowed to stay.
    assert len(over[0].target["containers"]) == 1


async def test_an_instance_running_at_the_old_size_is_reported(empty_pool, docker):
    """Changing the setting does not resize a container that is already up."""
    cluster = _cluster()
    fn = _function(cluster, memory_mb=128, max_instances=4)
    empty_pool._isolates["fn:v1"] = [_for(fn, "aaaa1111", memory_mb=512)]
    docker(containers=[FakeContainer("aaaa1111", role="isolate")])

    findings = await reconcile.scan(
        FakeSession(clusters=[cluster], functions=[fn], nodes=[_node()])
    )
    wrong = [f for f in findings if f.kind == "isolate_wrong_size"]
    assert len(wrong) == 1
    assert "512 MB" in wrong[0].detail and "128 MB" in wrong[0].detail


async def test_a_function_too_big_for_the_ceiling_is_reported(empty_pool, docker):
    cluster = _cluster(max_memory_mb=256, max_cpu_cores=64)
    fn = _function(cluster, memory_mb=1024, max_instances=1)
    docker(containers=[])

    findings = await reconcile.scan(
        FakeSession(clusters=[cluster], functions=[fn], nodes=[_node()])
    )
    assert any(f.kind == "function_cannot_fit" for f in findings)
    # Nothing to reclaim — this is a configuration decision, not drift.
    assert next(f for f in findings if f.kind == "function_cannot_fit").fix is None


async def test_a_function_that_cannot_reach_its_ceiling_is_only_noted(empty_pool, docker):
    cluster = _cluster(max_memory_mb=1024, max_cpu_cores=64)
    fn = _function(cluster, memory_mb=256, max_instances=8)
    docker(containers=[])

    findings = await reconcile.scan(
        FakeSession(clusters=[cluster], functions=[fn], nodes=[_node()])
    )
    note = next(f for f in findings if f.kind == "function_cannot_reach_max")
    assert note.severity == "info"
    assert note.fix is None


async def test_no_ceiling_means_no_allocation_findings(empty_pool, docker):
    """Unlimited is a real answer, not a very large number to compare against."""
    cluster = _cluster(max_memory_mb=0, max_cpu_cores=0)
    fn = _function(cluster, memory_mb=1024, max_instances=64)
    docker(containers=[])

    findings = await reconcile.scan(
        FakeSession(clusters=[cluster], functions=[fn], nodes=[_node()])
    )
    assert not [f for f in findings if "ceiling" in f.kind or "fit" in f.kind]
