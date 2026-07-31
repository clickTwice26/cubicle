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
    version_id: str
    version_number: int
    node_name: str = "node-01"
    docker_host: str = LOCAL_HOST
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
    started_at: float = field(default_factory=time.monotonic)
    last_used: float = field(default_factory=time.monotonic)
    invocations: int = 0
    busy: bool = False


def cpu_quota_for(memory_mb: int) -> int:
    """CPU allotted to an isolate, in nanocpus.

    Scaled with the memory setting rather than fixed, so the number the Cluster
    page reports as "allocated" means something: a 512 MB function is allowed
    half a core, a 2 GB function two.
    """
    return int(max(0.25, min(4.0, memory_mb / 1024)) * 1_000_000_000)


class IsolateError(RuntimeError):
    """The isolate could not be started or never became ready."""


class IsolatePool:
    def __init__(self) -> None:
        self._isolates: dict[str, list[Isolate]] = {}
        self._cond = asyncio.Condition()
        self._starting: dict[str, int] = {}
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=920.0))
        self._closed = False

    # ── lifecycle ────────────────────────────────────────────────────────

    async def acquire(self, spec: FunctionSpec) -> tuple[Isolate, bool]:
        """Return a warm isolate, starting one if the pool has room."""
        deadline = time.monotonic() + settings.isolate_start_timeout + spec.timeout_s
        while True:
            async with self._cond:
                pool = self._isolates.setdefault(spec.key, [])
                for isolate in pool:
                    if not isolate.busy:
                        isolate.busy = True
                        isolate.last_used = time.monotonic()
                        return isolate, False

                in_flight = self._starting.get(spec.key, 0)
                if len(pool) + in_flight < settings.isolate_max_per_function:
                    self._starting[spec.key] = in_flight + 1
                    break

                if time.monotonic() > deadline:
                    raise IsolateError("all isolates for this function are busy")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._cond.wait(), timeout=1.0)

        try:
            isolate = await self._start(spec)
        finally:
            async with self._cond:
                self._starting[spec.key] = max(0, self._starting.get(spec.key, 1) - 1)
                self._cond.notify_all()

        async with self._cond:
            isolate.busy = True
            self._isolates.setdefault(spec.key, []).append(isolate)
        return isolate, True

    async def release(self, isolate: Isolate, *, healthy: bool = True) -> None:
        async with self._cond:
            isolate.busy = False
            isolate.last_used = time.monotonic()
            isolate.invocations += 1
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
        )

        try:
            await self._wait_ready(isolate)
        except Exception:
            await self._destroy(isolate, log_output=True)
            raise
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

    async def reap_idle(self, *, min_instances: dict[str, int] | None = None) -> int:
        """Reclaim isolates that have been idle longer than the TTL."""
        keep_alive = min_instances or {}
        now = time.monotonic()
        victims: list[Isolate] = []

        async with self._cond:
            for key, pool in list(self._isolates.items()):
                floor = keep_alive.get(key.split(":", 1)[0], 0)
                idle = [
                    i for i in pool if not i.busy and now - i.last_used > settings.isolate_idle_ttl
                ]
                removable = max(0, len(pool) - floor)
                for isolate in idle[:removable]:
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

    async def adopt(self, *, hosts: list[str], live_versions: set[str]) -> None:
        """Re-attach to isolates that outlived a control-plane restart."""

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
                if version_id not in live_versions or container.status != "running":
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
                    memory_mb=512,
                )
                try:
                    await self._wait_ready(isolate)
                except Exception:
                    await self._destroy(isolate)
                    continue
                async with self._cond:
                    self._isolates.setdefault(isolate.spec_key, []).append(isolate)
                log.info("adopted warm isolate", container=container.name)

    def snapshot(self) -> list[dict]:
        return [
            {
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
