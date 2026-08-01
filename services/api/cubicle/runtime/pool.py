"""Isolate pool.

An isolate is a container running the Cubicle agent with one function version
mounted read-only. The pool keeps them warm between invocations and reclaims
them after ``CUBICLE_ISOLATE_IDLE_TTL`` seconds of inactivity — that is what
scale-to-zero means here: an idle function costs nothing but a database row.

The first request after an idle period pays a cold start (container create,
start and agent readiness). Every subsequent request reuses the warm isolate
and only pays the HTTP round trip.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from dataclasses import dataclass, field

import docker
import httpx
from docker.errors import DockerException, NotFound

from .. import live
from ..config import settings
from ..logging_setup import log
from .builder import volume_name
from .engine import LOCAL_HOST, engines

AGENT_PORT = 8080
ROLE_LABEL = "cubicle.role"
ISOLATE_ROLE = "isolate"


@dataclass(slots=True)
class FunctionSpec:
    id: str
    name: str
    namespace: str
    runtime: str
    memory_mb: int
    timeout_s: int
    min_instances: int
    max_instances: int
    version_id: str
    version_number: int
    node_name: str = "node-01"
    docker_host: str = LOCAL_HOST
    cluster: str = ""
    #: The cluster's ceilings, and what its data services already hold. Zero
    #: means no ceiling. Carried on the spec because the pool has no database.
    cluster_memory_cap_mb: int = 0
    cluster_cpu_cap: float = 0.0
    cluster_reserved_mb: int = 0
    cluster_reserved_cpu: float = 0.0
    node_is_local: bool = True

    @property
    def key(self) -> str:
        return f"{self.id}:{self.version_id}"


@dataclass
class Isolate:
    container_id: str
    address: str
    spec_key: str
    function_id: str
    version_id: str
    node_name: str
    docker_host: str
    memory_mb: int
    cluster: str = ""
    name: str = ""
    namespace: str = ""
    started_at: float = field(default_factory=time.monotonic)
    last_used: float = field(default_factory=time.monotonic)
    invocations: int = 0
    busy: bool = False


def _announce(kind: str, isolate: Isolate, **fields: object) -> None:
    """Publish an isolate lifecycle event, if we know which cluster owns it.

    Adopted isolates carry no cluster until the reconcile loop matches them to
    a version, so an unattributed event is skipped rather than broadcast to
    every dashboard.
    """
    if not isolate.cluster:
        return
    live.publish(
        kind,
        isolate.cluster,
        isolate=isolate.container_id[:12],
        function_id=isolate.function_id,
        function=isolate.name,
        namespace=isolate.namespace,
        node=isolate.node_name,
        **fields,
    )


def cpu_quota_for(memory_mb: int) -> int:
    """CPU allotted to an isolate, in nanocpus.

    Scaled with the memory setting rather than fixed, so the number the Cluster
    page reports as "allocated" means something: a 512 MB function is allowed
    half a core, a 2 GB function two.
    """
    return int(max(0.25, min(4.0, memory_mb / 1024)) * 1_000_000_000)


class IsolateError(RuntimeError):
    """The isolate could not be started or never became ready."""


class ClusterFullError(IsolateError):
    """The cluster has no room left under its own ceiling."""


class IsolatePool:
    def __init__(self) -> None:
        self._isolates: dict[str, list[Isolate]] = {}
        self._cond = asyncio.Condition()
        self._starting: dict[str, int] = {}
        #: spec key -> (highest concurrent busy count, when it was seen)
        self._peaks: dict[str, tuple[int, float]] = {}
        #: cluster -> memory_mb of isolates being started right now. A pending
        #: start holds its memory as surely as a running one; counting only
        #: what is already in `_isolates` let a burst of concurrent requests
        #: each see an empty pool and all pass the ceiling together.
        self._pending: dict[str, list[int]] = {}
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=920.0))
        self._closed = False

    # ── lifecycle ────────────────────────────────────────────────────────

    async def acquire(self, spec: FunctionSpec) -> tuple[Isolate, bool]:
        """Return a warm isolate, starting one if the pool has room."""
        # A ceiling this function can never fit under, even with the cluster
        # completely idle, is not worth waiting on. Queueing for a minute to
        # deliver the same refusal helps nobody.
        impossible = self._never_fits(spec)
        if impossible is not None:
            raise ClusterFullError(impossible)

        deadline = time.monotonic() + settings.isolate_start_timeout + spec.timeout_s
        while True:
            async with self._cond:
                pool = self._isolates.setdefault(spec.key, [])
                # Least-used wins, so work spreads evenly across the pool
                # instead of piling onto whichever isolate happens to be first
                # in the list. Ties go to the one idle longest, which keeps the
                # rotation stable rather than flapping between two equals.
                idle = [i for i in pool if not i.busy]
                if idle:
                    isolate = min(idle, key=lambda i: (i.invocations, i.last_used))
                    isolate.busy = True
                    isolate.last_used = time.monotonic()
                    self._peak(spec.key, pool)
                    _announce("isolate.busy", isolate)
                    return isolate, False

                # The function's own ceiling, never above the instance-wide
                # one: a per-function setting may restrain the platform, not
                # overrule it.
                ceiling = max(1, min(spec.max_instances, settings.isolate_max_per_function))
                in_flight = self._starting.get(spec.key, 0)
                if len(pool) + in_flight < ceiling:
                    # The cluster's ceiling is checked here, inside the same
                    # lock that decides to start one. Checking it outside would
                    # let two concurrent requests both read "room for one" and
                    # both spawn.
                    full = self._cluster_full(spec)
                    if full is None:
                        self._starting[spec.key] = in_flight + 1
                        if spec.cluster:
                            self._pending.setdefault(spec.cluster, []).append(spec.memory_mb)
                        break
                    if time.monotonic() > deadline:
                        raise ClusterFullError(full)
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(self._cond.wait(), timeout=1.0)
                    continue

                if time.monotonic() > deadline:
                    raise IsolateError(
                        f"all {ceiling} isolates for this function are busy — "
                        "raise its max instances or lower its timeout"
                    )
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._cond.wait(), timeout=1.0)

        try:
            isolate = await self._start(spec)
        finally:
            async with self._cond:
                self._starting[spec.key] = max(0, self._starting.get(spec.key, 1) - 1)
                # Released whether the start succeeded or failed. On success the
                # isolate is appended below and counted from `_isolates`
                # instead; on failure nothing holds the memory and the next
                # request should be able to have it.
                pending = self._pending.get(spec.cluster or "")
                if pending:
                    with contextlib.suppress(ValueError):
                        pending.remove(spec.memory_mb)
                self._cond.notify_all()

        async with self._cond:
            isolate.busy = True
            pool = self._isolates.setdefault(spec.key, [])
            pool.append(isolate)
            self._peak(spec.key, pool)
        _announce("isolate.busy", isolate)
        return isolate, True

    async def release(self, isolate: Isolate, *, healthy: bool = True) -> None:
        async with self._cond:
            isolate.busy = False
            isolate.last_used = time.monotonic()
            isolate.invocations += 1
            _announce("isolate.idle", isolate, invocations=isolate.invocations)
            if not healthy:
                pool = self._isolates.get(isolate.spec_key, [])
                if isolate in pool:
                    pool.remove(isolate)
                asyncio.create_task(self._destroy(isolate))  # noqa: RUF006
            self._cond.notify_all()

    async def invoke(self, isolate: Isolate, payload: dict, timeout: float) -> dict:
        response = await self._client.post(
            f"{isolate.address}/invoke",
            json=payload,
            timeout=httpx.Timeout(5.0, read=timeout + 5.0),
        )
        response.raise_for_status()
        return response.json()

    # ── container management ─────────────────────────────────────────────

    def _never_fits(self, spec: FunctionSpec) -> str | None:
        """Whether this function cannot fit under its cluster's ceiling at all.

        Compares the request against the ceiling minus only what the data
        services permanently hold — no isolate freeing up will change it.
        """
        if not spec.cluster:
            return None

        cap = spec.cluster_memory_cap_mb
        if cap > 0 and spec.cluster_reserved_mb + spec.memory_mb > cap:
            return (
                f"cluster '{spec.cluster}' has a {cap} MB memory ceiling and its data "
                f"services already hold {spec.cluster_reserved_mb} MB, leaving no room for "
                f"a {spec.memory_mb} MB function — raise the quota or shrink the services"
            )

        cpu_cap = spec.cluster_cpu_cap
        wanted = cpu_quota_for(spec.memory_mb) / 1_000_000_000
        if cpu_cap > 0 and spec.cluster_reserved_cpu + wanted > cpu_cap:
            return (
                f"cluster '{spec.cluster}' has a {cpu_cap:.2f} core ceiling and its data "
                f"services already hold {spec.cluster_reserved_cpu:.2f}, leaving no room for "
                f"a function needing {wanted:.2f} — raise the quota"
            )
        return None

    def _cluster_full(self, spec: FunctionSpec) -> str | None:
        """Why this cluster cannot take another isolate, or None if it can.

        Counts every isolate the cluster already has, plus what its managed
        data services hold, plus the one being asked for. Must be called with
        the pool condition held.
        """
        if not spec.cluster:
            return None

        starting = self._pending.get(spec.cluster, [])

        if spec.cluster_memory_cap_mb > 0:
            used = (
                spec.cluster_reserved_mb
                + sum(starting)
                + sum(
                    i.memory_mb
                    for pool in self._isolates.values()
                    for i in pool
                    if i.cluster == spec.cluster
                )
            )
            if used + spec.memory_mb > spec.cluster_memory_cap_mb:
                return (
                    f"cluster '{spec.cluster}' is at its memory ceiling "
                    f"({used} MB of {spec.cluster_memory_cap_mb} MB used, "
                    f"{spec.memory_mb} MB needed)"
                )

        if spec.cluster_cpu_cap > 0:
            wanted = cpu_quota_for(spec.memory_mb) / 1_000_000_000
            used = (
                spec.cluster_reserved_cpu
                + sum(cpu_quota_for(mb) / 1_000_000_000 for mb in starting)
                + sum(
                    cpu_quota_for(i.memory_mb) / 1_000_000_000
                    for pool in self._isolates.values()
                    for i in pool
                    if i.cluster == spec.cluster
                )
            )
            if used + wanted > spec.cluster_cpu_cap:
                return (
                    f"cluster '{spec.cluster}' is at its CPU ceiling "
                    f"({used:.2f} of {spec.cluster_cpu_cap:.2f} cores used, "
                    f"{wanted:.2f} needed)"
                )

        return None

    def _peak(self, key: str, pool: list[Isolate]) -> None:
        """Record how many isolates of this spec are busy at once."""
        busy = sum(1 for i in pool if i.busy)
        seen, at = self._peaks.get(key, (0, 0.0))
        now = time.monotonic()
        # The mark decays quickly. Tying it to the idle TTL instead would make
        # surplus trimming pointless: by the time the peak expired the isolates
        # would be idle-stale anyway and the other rule would already have
        # taken them.
        if now - at > settings.isolate_scaledown_window:
            seen = 0
        if busy >= seen:
            self._peaks[key] = (busy, now)
        elif seen:
            self._peaks[key] = (seen, at)

    def _peak_concurrency(self, key: str, now: float) -> int:
        seen, at = self._peaks.get(key, (0, 0.0))
        return 0 if now - at > settings.isolate_scaledown_window else seen

    async def _start(self, spec: FunctionSpec) -> Isolate:
        image = settings.runtime_image(spec.runtime)
        volume = volume_name(spec.id, spec.version_number)
        name = f"cubicle-iso-{spec.namespace}-{spec.name}-{uuid.uuid4().hex[:8]}"[:60]
        publish = not spec.node_is_local

        if spec.node_is_local:
            await engines.ensure_network(spec.docker_host, settings.function_network)

        def _create(client: docker.DockerClient) -> tuple[str, str]:
            container = client.containers.run(
                image=image,
                name=name,
                detach=True,
                labels={
                    ROLE_LABEL: ISOLATE_ROLE,
                    "cubicle.function": spec.id,
                    "cubicle.version": spec.version_id,
                    "cubicle.version_number": str(spec.version_number),
                    "cubicle.namespace": spec.namespace,
                    "cubicle.name": spec.name,
                    # Read back by adopt(), so an isolate that outlives the
                    # control plane still knows which cluster it belongs to.
                    "cubicle.cluster": spec.cluster,
                },
                environment={
                    "CUBICLE_FUNCTION": spec.name,
                    "CUBICLE_NAMESPACE": spec.namespace,
                    "CUBICLE_TIMEOUT": str(spec.timeout_s),
                    "PYTHONPATH": "/srv/.deps:/srv",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "HOME": "/tmp",
                },
                volumes={volume: {"bind": "/srv", "mode": "ro"}},
                working_dir="/srv",
                network=None if publish else settings.function_network,
                ports={f"{AGENT_PORT}/tcp": None} if publish else None,
                mem_limit=f"{spec.memory_mb}m",
                memswap_limit=f"{spec.memory_mb}m",
                nano_cpus=cpu_quota_for(spec.memory_mb),
                pids_limit=256,
                read_only=True,
                tmpfs={"/tmp": "rw,size=64m,mode=1777"},
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                restart_policy={"Name": "no"},
                user="65532:65532",
            )
            container.reload()
            return container.id, _address_for(container, publish, spec)

        try:
            container_id, address = await engines.call(spec.docker_host, _create)
        except DockerException as exc:
            raise IsolateError(f"could not start isolate: {exc}") from exc

        isolate = Isolate(
            container_id=container_id,
            address=address,
            spec_key=spec.key,
            function_id=spec.id,
            version_id=spec.version_id,
            node_name=spec.node_name,
            docker_host=spec.docker_host,
            memory_mb=spec.memory_mb,
            cluster=spec.cluster,
            name=spec.name,
            namespace=spec.namespace,
        )
        # Announced before the readiness wait, not after: booting is the part
        # worth watching, and it is most of the ~400ms.
        started = time.monotonic()
        _announce("isolate.spawn", isolate, memory_mb=spec.memory_mb)

        try:
            await self._wait_ready(isolate)
        except Exception:
            _announce("isolate.gone", isolate, reason="failed")
            await self._destroy(isolate, log_output=True)
            raise
        _announce("isolate.ready", isolate, boot_ms=round((time.monotonic() - started) * 1000))
        return isolate

    async def _wait_ready(self, isolate: Isolate) -> None:
        deadline = time.monotonic() + settings.isolate_start_timeout
        last_error = "timed out"
        delay = 0.02
        while time.monotonic() < deadline:
            try:
                response = await self._client.get(f"{isolate.address}/healthz", timeout=2.0)
                if response.status_code == 200:
                    payload = response.json()
                    if payload.get("ready"):
                        return
                    last_error = payload.get("error") or "agent not ready"
                    if payload.get("fatal"):
                        raise IsolateError(last_error)
                else:
                    last_error = f"agent returned {response.status_code}"
            except IsolateError:
                raise
            except Exception as exc:  # noqa: BLE001 - the container may still be booting
                last_error = str(exc) or exc.__class__.__name__
            await asyncio.sleep(delay)
            delay = min(delay * 1.6, 0.4)
        raise IsolateError(f"isolate did not become ready: {last_error}")

    async def _destroy(self, isolate: Isolate, *, log_output: bool = False) -> None:
        _announce("isolate.gone", isolate, reason="reclaimed")

        def _remove(client: docker.DockerClient) -> str:
            try:
                container = client.containers.get(isolate.container_id)
            except NotFound:
                return ""
            output = ""
            if log_output:
                with contextlib.suppress(DockerException):
                    output = container.logs(tail=40).decode(errors="replace")
            with contextlib.suppress(DockerException):
                container.remove(force=True)
            return output

        try:
            output = await engines.call(isolate.docker_host, _remove)
        except Exception as exc:  # noqa: BLE001 - reclaiming is best effort
            log.warning("could not remove isolate", container=isolate.container_id, error=str(exc))
            return
        if log_output and output:
            log.warning("isolate failed to start", container=isolate.container_id, logs=output)

    async def container_logs(self, isolate: Isolate, tail: int = 50) -> str:
        def _logs(client: docker.DockerClient) -> str:
            try:
                return (
                    client.containers.get(isolate.container_id)
                    .logs(tail=tail)
                    .decode(errors="replace")
                )
            except DockerException:
                return ""

        return await engines.call(isolate.docker_host, _logs)

    # ── pool maintenance ─────────────────────────────────────────────────

    async def drain(self, *, function_id: str | None = None, version_id: str | None = None) -> int:
        async with self._cond:
            victims: list[Isolate] = []
            for key, pool in list(self._isolates.items()):
                keep: list[Isolate] = []
                for isolate in pool:
                    matches = (function_id is None or isolate.function_id == function_id) and (
                        version_id is None or isolate.version_id == version_id
                    )
                    (victims if matches else keep).append(isolate)
                if keep:
                    self._isolates[key] = keep
                else:
                    self._isolates.pop(key, None)
            self._cond.notify_all()

        for isolate in victims:
            await self._destroy(isolate)
        return len(victims)

    async def reap_idle(self, *, limits: dict[str, tuple[int, int]] | None = None) -> int:
        """Reclaim isolates the pool no longer needs.

        Two reasons to let one go, and both are needed:

        *Idle* — nothing has touched it for the TTL. This is what reclaims a
        function that stopped receiving traffic entirely.

        *Surplus* — the pool is larger than the concurrency seen in the last
        ``isolate_scaledown_window``. Spreading requests evenly keeps every
        isolate's last-used timestamp fresh, so a pool that grew during a burst
        would otherwise stay at its high-water mark for the whole idle TTL:
        eight isolates each taking an eighth of the traffic all look busy
        enough to keep. This is the rule that gives a spike's containers back
        within a couple of minutes; the idle TTL is what eventually takes the
        last one and returns the function to zero.
        """
        bounds = limits or {}
        now = time.monotonic()
        victims: list[Isolate] = []

        async with self._cond:
            for key, pool in list(self._isolates.items()):
                floor, ceiling = bounds.get(
                    key.split(":", 1)[0], (0, settings.isolate_max_per_function)
                )
                stale = [
                    i for i in pool if not i.busy and now - i.last_used > settings.isolate_idle_ttl
                ]
                # Only one surplus isolate per pass, so a pool that is merely
                # between bursts drifts down instead of collapsing and paying
                # for a fresh round of cold starts.
                # Never above the function's ceiling: lowering max instances
                # has to actually shrink a pool that already grew past it.
                wanted = min(max(floor, self._peak_concurrency(key, now), 1), max(ceiling, 1))
                spare = [i for i in pool if not i.busy and i not in stale]
                spare.sort(key=lambda i: i.invocations)
                surplus = spare[:1] if len(pool) > wanted else []

                removable = max(0, len(pool) - floor)
                for isolate in (stale + surplus)[:removable]:
                    pool.remove(isolate)
                    victims.append(isolate)
                if not pool:
                    self._isolates.pop(key, None)
            self._cond.notify_all()

        for isolate in victims:
            await self._destroy(isolate)
        if victims:
            log.info("reclaimed idle isolates", count=len(victims))
        return len(victims)

    async def destroy_isolate(self, container_id: str) -> bool:
        """Reclaim one isolate by id. Returns whether it was found.

        Accepts a busy isolate on purpose: an operator reaching for this is
        usually dealing with one that is wedged mid-request, which is exactly
        the case a "only when idle" rule would refuse. The request it is
        serving fails, and the caller sees a 502.
        """
        victim: Isolate | None = None
        async with self._cond:
            for key, isolates in list(self._isolates.items()):
                for isolate in isolates:
                    if isolate.container_id.startswith(container_id):
                        victim = isolate
                        isolates.remove(isolate)
                        if not isolates:
                            self._isolates.pop(key, None)
                        break
                if victim:
                    break
            self._cond.notify_all()

        if victim is None:
            return False
        await self._destroy(victim)
        log.info(
            "isolate destroyed by operator",
            container=victim.container_id[:12],
            function=victim.name,
            busy=victim.busy,
        )
        return True

    def isolates_for(self, function_id: str, cluster: str) -> list[dict]:
        """This function's isolates, in the shape the snapshot uses."""
        return [
            entry for entry in self.snapshot(cluster=cluster) if entry["function_id"] == function_id
        ]

    async def adopt(self, *, hosts: list[str], live_versions: dict[str, dict]) -> None:
        """Re-attach to isolates that outlived a control-plane restart.

        ``live_versions`` maps a deployed version to the function that owns it,
        so an adopted isolate gets its full identity back — which cluster, which
        function — rather than only what its labels happen to carry.
        """

        def _list(client: docker.DockerClient):
            return client.containers.list(filters={"label": f"{ROLE_LABEL}={ISOLATE_ROLE}"})

        for host in hosts:
            try:
                containers = await engines.call(host, _list)
            except Exception as exc:  # noqa: BLE001 - a node may simply be down
                log.warning("could not list isolates", host=host, error=str(exc))
                continue

            for container in containers:
                labels = container.labels or {}
                version_id = labels.get("cubicle.version", "")
                known = any(
                    i.container_id == container.id for p in self._isolates.values() for i in p
                )
                if known:
                    continue
                owner = live_versions.get(version_id, {})
                if not owner or container.status != "running":
                    log.info("removing stale isolate", container=container.name)
                    with contextlib.suppress(Exception):
                        await engines.call(
                            host,
                            lambda c, cid=container.id: c.containers.get(cid).remove(force=True),
                        )
                    continue

                address = _address_from_attrs(container.attrs, host)
                if not address:
                    continue
                isolate = Isolate(
                    container_id=container.id,
                    address=address,
                    spec_key=f"{labels.get('cubicle.function', '')}:{version_id}",
                    function_id=labels.get("cubicle.function", ""),
                    version_id=version_id,
                    node_name=labels.get("cubicle.node", "node-01"),
                    docker_host=host,
                    memory_mb=owner.get("memory_mb", 512),
                    cluster=owner.get("cluster", "") or labels.get("cubicle.cluster", ""),
                    name=owner.get("name", "") or labels.get("cubicle.name", ""),
                    namespace=owner.get("namespace", "") or labels.get("cubicle.namespace", ""),
                )
                try:
                    await self._wait_ready(isolate)
                except Exception:
                    await self._destroy(isolate)
                    continue
                async with self._cond:
                    self._isolates.setdefault(isolate.spec_key, []).append(isolate)
                log.info("adopted warm isolate", container=container.name)

    def snapshot(self, *, cluster: str | None = None) -> list[dict]:
        return [
            {
                "id": isolate.container_id[:12],
                "cluster": isolate.cluster,
                "function": isolate.name,
                "namespace": isolate.namespace,
                "function_id": isolate.function_id,
                "version_id": isolate.version_id,
                "node": isolate.node_name,
                "busy": isolate.busy,
                "invocations": isolate.invocations,
                "memory_mb": isolate.memory_mb,
                "cpus": cpu_quota_for(isolate.memory_mb) / 1_000_000_000,
                "age_s": round(time.monotonic() - isolate.started_at, 1),
                "idle_s": round(time.monotonic() - isolate.last_used, 1),
            }
            for pool in self._isolates.values()
            for isolate in pool
            if cluster is None or isolate.cluster == cluster
        ]

    def count(self) -> int:
        return sum(len(p) for p in self._isolates.values())

    def warm_functions(self) -> set[str]:
        return {key.split(":", 1)[0] for key, pool in self._isolates.items() if pool}

    async def close(self) -> None:
        """Shut down without tearing the pool down.

        Isolates are deliberately left running so that restarting the control
        plane — a deploy, a config change — does not cost every warm function a
        cold start. ``adopt`` re-attaches to them on the way back up and removes
        any whose version is no longer current. Use ``make clean-isolates`` to
        reclaim them when the control plane is stopped for good.
        """
        self._closed = True
        await self._client.aclose()


def _address_for(container, publish: bool, spec: FunctionSpec) -> str:
    return _address_from_attrs(container.attrs, spec.docker_host, publish=publish)


def _address_from_attrs(attrs: dict, host: str, *, publish: bool | None = None) -> str:
    networks = attrs.get("NetworkSettings", {}) or {}
    if publish is None:
        publish = host not in ("", LOCAL_HOST)

    if not publish:
        nets = networks.get("Networks", {}) or {}
        entry = nets.get(settings.function_network) or next(iter(nets.values()), {})
        ip = (entry or {}).get("IPAddress", "")
        return f"http://{ip}:{AGENT_PORT}" if ip else ""

    ports = networks.get("Ports", {}) or {}
    mapping = ports.get(f"{AGENT_PORT}/tcp") or []
    if not mapping:
        return ""
    hostname = host.split("://", 1)[-1].split(":")[0]
    return f"http://{hostname}:{mapping[0]['HostPort']}"


pool = IsolatePool()
