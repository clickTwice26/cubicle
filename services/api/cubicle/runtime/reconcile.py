"""Compare what we believe against what Docker actually has.

Three things claim to know what is running: the pool holds isolates in memory,
the database holds managed services and nodes, and Docker holds the truth. They
drift — a container dies without the pool noticing, a control plane is killed
mid-start and leaves a container nothing owns, a cluster is deleted and its
volume stays behind holding disk forever.

Scanning never changes anything. It reports, and each report says what applying
would do, because the fix for drift is sometimes to delete data and that is not
a decision to make on the operator's behalf.
"""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import docker
from docker.errors import DockerException, NotFound
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..logging_setup import log
from ..models import Cluster, Function, Group, ManagedService, Node
from .engine import LOCAL_HOST, engines
from .invoker import quota_for
from .pool import ISOLATE_ROLE, ROLE_LABEL, cpu_quota_for, pool

#: A container started moments ago may not be in the pool yet — it is registered
#: only once it answers readiness. Calling that an orphan and removing it would
#: destroy a healthy isolate mid-start, so nothing younger than this is judged.
ORPHAN_GRACE_SECONDS = 180

SERVICE_ROLE = "service"
VOLUME_ROLE = "service-volume"


@dataclass
class Finding:
    """One disagreement, and what resolving it would cost."""

    id: str
    kind: str
    #: ``error`` is already breaking something, ``warn`` is waste, ``info`` is
    #: worth knowing and not worth acting on.
    severity: str
    cluster: str
    summary: str
    detail: str
    #: What applying does, in plain words. ``None`` means nothing safe exists and
    #: the operator has to decide — an unreachable node is not fixed from here.
    fix: str | None = None
    #: Applying this destroys data that is not recoverable. The console demands a
    #: separate confirmation for these and never includes them in "fix all".
    destructive: bool = False
    target: dict = field(default_factory=dict)


def _created_age(attrs: dict) -> float:
    """Seconds since the container was created, or 0 if Docker did not say."""
    raw = (attrs or {}).get("Created", "")
    if not raw:
        return 0.0
    with contextlib.suppress(ValueError):
        # Docker sends more sub-second digits than fromisoformat accepts.
        head, _, tail = raw.partition(".")
        cleaned = f"{head}+00:00" if tail else raw.replace("Z", "+00:00")
        created = datetime.fromisoformat(cleaned)
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        return (datetime.now(UTC) - created).total_seconds()
    return 0.0


async def _hosts(db: AsyncSession) -> list[str]:
    rows = (await db.execute(select(Node.docker_host).distinct())).scalars().all()
    return list(rows) or [LOCAL_HOST]


def _list_by_role(role: str):
    def _run(client: docker.DockerClient):
        return client.containers.list(all=True, filters={"label": f"{ROLE_LABEL}={role}"})

    return _run


def _list_volumes(client: docker.DockerClient):
    return client.volumes.list(filters={"label": f"{ROLE_LABEL}={VOLUME_ROLE}"})


async def scan(db: AsyncSession) -> list[Finding]:
    """Read everything, change nothing, and report where the three disagree."""
    findings: list[Finding] = []

    clusters = (await db.execute(select(Cluster))).scalars().all()
    by_slug = {c.slug: c for c in clusters}
    function_rows = (
        (await db.execute(select(Function).options(selectinload(Function.group)).join(Group)))
        .scalars()
        .all()
    )
    functions = {str(f.id) for f in function_rows}
    services = (await db.execute(select(ManagedService))).scalars().all()
    nodes = (await db.execute(select(Node))).scalars().all()

    hosts = await _hosts(db)
    tracked = pool.tracked()

    # What Docker actually holds, per host. A host we cannot reach is a finding
    # in itself, and everything below simply skips it rather than guessing.
    isolates_seen: dict[str, list] = {}
    services_seen: dict[str, list] = {}
    volumes_seen: dict[str, list] = {}
    reachable: set[str] = set()

    for host in hosts:
        try:
            isolates_seen[host] = await engines.call(host, _list_by_role(ISOLATE_ROLE))
            services_seen[host] = await engines.call(host, _list_by_role(SERVICE_ROLE))
            volumes_seen[host] = await engines.call(host, _list_volumes)
            reachable.add(host)
        except Exception as exc:  # noqa: BLE001 - an unreachable node is the finding
            node = next((n for n in nodes if n.docker_host == host), None)
            findings.append(
                Finding(
                    id=f"node-unreachable:{host}",
                    kind="node_unreachable",
                    severity="error",
                    cluster=next(
                        (c.slug for c in clusters if node and c.id == node.cluster_id), ""
                    ),
                    summary=f"Node {node.name if node else host} is not answering",
                    detail=(
                        f"{host} could not be reached: {exc}. Nothing on it can be checked, so "
                        "isolates and services there are absent from this report rather than "
                        "confirmed healthy."
                    ),
                    fix=None,
                    target={"host": host},
                )
            )

    live_ids = {c.id for host in reachable for c in isolates_seen.get(host, [])}
    running_ids = {
        c.id for host in reachable for c in isolates_seen.get(host, []) if c.status == "running"
    }

    # ── the pool believes in containers that are gone ────────────────────────
    for isolate in tracked:
        if isolate.docker_host not in reachable:
            continue
        if isolate.container_id in running_ids:
            continue
        gone = isolate.container_id not in live_ids
        findings.append(
            Finding(
                id=f"stale-isolate:{isolate.container_id}",
                kind="stale_pool_entry",
                severity="error",
                cluster=isolate.cluster,
                summary=(
                    f"{isolate.name or 'a function'} has a warm instance that "
                    + ("no longer exists" if gone else "has stopped")
                ),
                detail=(
                    f"The pool routes requests to {isolate.container_id[:12]}, which Docker "
                    + ("does not have" if gone else "reports as not running")
                    + ". Requests sent to it time out rather than failing over."
                ),
                fix="Drop it from the pool" + ("" if gone else " and remove the container"),
                target={"host": isolate.docker_host, "container": isolate.container_id},
            )
        )

    # ── Docker holds isolates the pool does not know about ───────────────────
    pooled = {i.container_id for i in tracked}
    for host in reachable:
        for container in isolates_seen.get(host, []):
            if container.id in pooled:
                continue
            labels = container.labels or {}
            cluster = labels.get("cubicle.cluster", "")
            age = _created_age(container.attrs)
            if container.status == "running" and age < ORPHAN_GRACE_SECONDS:
                continue  # too young to judge — it may still be starting up
            unknown_fn = labels.get("cubicle.function", "") not in functions
            findings.append(
                Finding(
                    id=f"orphan-isolate:{container.id}",
                    kind="orphan_isolate",
                    severity="warn",
                    cluster=cluster,
                    summary=(
                        f"Container {container.name} is running with nothing tracking it"
                        if container.status == "running"
                        else f"Container {container.name} is stopped and left behind"
                    ),
                    detail=(
                        (
                            "Its function no longer exists. "
                            if unknown_fn
                            else "It carries our labels but is in no pool. "
                        )
                        + (
                            "It holds memory that counts against nothing and serves no requests."
                            if container.status == "running"
                            else "It serves nothing and holds its writable layer on disk."
                        )
                    ),
                    fix="Remove the container",
                    target={"host": host, "container": container.id},
                )
            )

    # ── managed services ─────────────────────────────────────────────────────
    by_service_container = {(s.container_id or ""): s for s in services if s.container_id}
    for service in services:
        cluster = next((c for c in clusters if c.id == service.cluster_id), None)
        slug = cluster.slug if cluster else ""
        host = next((n.docker_host for n in nodes if n.name == service.node_name), LOCAL_HOST)
        if host not in reachable or not service.container_id:
            continue
        found = next((c for c in services_seen.get(host, []) if c.id == service.container_id), None)
        if found is None:
            findings.append(
                Finding(
                    id=f"service-missing:{service.id}",
                    kind="service_container_missing",
                    severity="error" if service.status == "running" else "warn",
                    cluster=slug,
                    summary=f"{service.kind} for {slug} is recorded but its container is gone",
                    detail=(
                        f"The database points at {service.container_id[:12]}, which Docker does "
                        f"not have. Anything connecting to this {service.kind} fails. Its volume "
                        "is untouched, so recreating the service keeps the data."
                    ),
                    fix="Mark it stopped, so the console offers to recreate it",
                    target={"service": str(service.id)},
                )
            )
        elif found.status != "running" and service.status == "running":
            findings.append(
                Finding(
                    id=f"service-down:{service.id}",
                    kind="service_not_running",
                    severity="error",
                    cluster=slug,
                    summary=f"{service.kind} for {slug} is recorded as running but has stopped",
                    detail=(
                        f"Docker reports {found.name} as {found.status}. The console shows it "
                        "healthy while every connection to it fails."
                    ),
                    fix="Mark it stopped, so the console shows what is true",
                    target={"service": str(service.id)},
                )
            )

    for host in reachable:
        for container in services_seen.get(host, []):
            if container.id in by_service_container:
                continue
            # Only a running container can still be mid-provision; a stopped one
            # that nothing points at is left over however recently it was made.
            young = _created_age(container.attrs) < ORPHAN_GRACE_SECONDS
            if container.status == "running" and young:
                continue
            labels = container.labels or {}
            slug = labels.get("cubicle.cluster", "")
            findings.append(
                Finding(
                    id=f"orphan-service:{container.id}",
                    kind="orphan_service_container",
                    severity="warn",
                    cluster=slug,
                    summary=f"Data service {container.name} belongs to nothing on record",
                    detail=(
                        f"A {labels.get('cubicle.service', 'service')} container labelled for "
                        + (f"cluster '{slug}'" if slug in by_slug else "a cluster that is gone")
                        + ". No database row points at it, so the console cannot manage or stop it."
                    ),
                    fix="Remove the container",
                    target={"host": host, "container": container.id},
                )
            )

    # ── volumes outliving whatever wrote them ────────────────────────────────
    claimed = {s.volume_name for s in services if s.volume_name}
    for host in reachable:
        for volume in volumes_seen.get(host, []):
            if volume.name in claimed:
                continue
            findings.append(
                Finding(
                    id=f"orphan-volume:{host}:{volume.name}",
                    kind="orphan_volume",
                    severity="warn",
                    cluster="",
                    summary=f"Volume {volume.name} is held by no service",
                    detail=(
                        "Its service was deleted and the data was kept. It occupies disk "
                        "indefinitely, and is the only copy of whatever that service held."
                    ),
                    fix="Delete the volume and everything in it",
                    destructive=True,
                    target={"host": host, "volume": volume.name},
                )
            )

    findings.extend(await _allocation(db, clusters, function_rows, by_slug))

    order = {"error": 0, "warn": 1, "info": 2}
    findings.sort(key=lambda f: (order.get(f.severity, 3), f.kind, f.id))
    return findings


async def apply(db: AsyncSession, findings: list[Finding], ids: set[str]) -> dict:
    """Act on the findings named by ``ids``, and report what actually happened.

    Findings are re-scanned by the caller rather than trusted from the browser,
    so an id that no longer exists is simply skipped: drift that resolved itself
    between looking and acting is not an error.
    """
    applied: list[str] = []
    failed: list[dict] = []
    chosen = [f for f in findings if f.id in ids]

    for finding in chosen:
        if finding.fix is None:
            continue
        try:
            await _apply_one(db, finding)
            applied.append(finding.id)
            log.info(
                "reconciled", kind=finding.kind, target=finding.target, summary=finding.summary
            )
        except Exception as exc:  # noqa: BLE001 - one failure must not stop the rest
            failed.append({"id": finding.id, "error": str(exc)})
            log.warning("could not reconcile", kind=finding.kind, error=str(exc))

    await db.commit()
    return {
        "applied": applied,
        "failed": failed,
        "skipped": sorted(ids - {f.id for f in chosen}),
    }


async def _apply_one(db: AsyncSession, finding: Finding) -> None:
    host = finding.target.get("host", LOCAL_HOST)

    if finding.kind == "stale_pool_entry":
        container = finding.target["container"]
        pool.forget(container)
        with contextlib.suppress(Exception):
            await engines.call(host, _remove_container(container))
        return

    if finding.kind in {"orphan_isolate", "orphan_service_container"}:
        await engines.call(host, _remove_container(finding.target["container"]))
        return

    if finding.kind in {
        "cluster_over_ceiling",
        "function_over_max_instances",
        "isolate_wrong_size",
    }:
        # One finding covers several containers, and any of them may have gone
        # busy since the scan proposed it. Each is re-checked under the pool's
        # lock and skipped if it is now serving a request — getting back under
        # a ceiling never justifies failing one in flight.
        skipped = 0
        for container in finding.target.get("containers", []):
            if await pool.reclaim_if_idle(container) == "busy":
                skipped += 1
        if skipped:
            raise RuntimeError(
                f"{skipped} instance{'' if skipped == 1 else 's'} went busy and "
                "were left alone. Scan again once they are idle."
            )
        return

    if finding.kind in {"service_container_missing", "service_not_running"}:
        service = await db.get(ManagedService, uuid.UUID(finding.target["service"]))
        if service is None:
            return
        service.status = "stopped"
        if finding.kind == "service_container_missing":
            service.container_id = None
        service.last_error = "Marked stopped by resource sync: the container was not running."
        return

    if finding.kind == "orphan_volume":

        def _remove(client: docker.DockerClient) -> None:
            with contextlib.suppress(NotFound):
                client.volumes.get(finding.target["volume"]).remove(force=True)

        await engines.call(host, _remove)
        return

    raise ValueError(f"{finding.kind} has no automatic fix")


def _remove_container(container_id: str):
    def _run(client: docker.DockerClient) -> None:
        # NotFound is a DockerException, so this covers "already gone" too.
        with contextlib.suppress(DockerException):
            client.containers.get(container_id).remove(force=True)

    return _run


# ── allocation against the ceilings ──────────────────────────────────────────


async def _allocation(
    db: AsyncSession,
    clusters: list,
    functions: list,
    by_slug: dict,
) -> list[Finding]:
    """Whether what is running still fits the limits that were configured.

    Admission control refuses anything that would breach a ceiling, so a breach
    here does not mean the check failed — it means the ceiling moved after the
    containers started, or they were adopted across a control-plane restart,
    which re-attaches to whatever was running without re-testing it against a
    limit that may have changed since.

    Nothing busy is ever proposed for reclaim. Getting back under a ceiling is
    not worth failing a request that is mid-flight.
    """
    findings: list[Finding] = []
    tracked = pool.tracked()

    for cluster in clusters:
        mine = [i for i in tracked if i.cluster == cluster.slug]
        quota = await quota_for(db, cluster)

        # ── the cluster's own ceilings ───────────────────────────────────────
        if quota:
            used_mb = sum(i.memory_mb for i in mine)
            used_cpu = sum(cpu_quota_for(i.memory_mb) / 1_000_000_000 for i in mine)
            for label, held, reserved, cap, unit in (
                ("memory", used_mb, quota.reserved_mb, quota.memory_cap_mb, "MB"),
                ("CPU", used_cpu, quota.reserved_cpu, quota.cpu_cap, "cores"),
            ):
                total = held + reserved
                if not cap or total <= cap:
                    continue
                idle = sorted(
                    (i for i in mine if not i.busy), key=lambda i: (i.invocations, i.last_used)
                )
                findings.append(
                    Finding(
                        id=f"over-ceiling:{cluster.slug}:{label}",
                        kind="cluster_over_ceiling",
                        severity="error",
                        cluster=cluster.slug,
                        summary=(
                            f"{cluster.name} holds {_num(total)} {unit} against a "
                            f"{_num(cap)} {unit} ceiling"
                        ),
                        detail=(
                            f"{len(mine)} warm instance{'' if len(mine) == 1 else 's'} hold "
                            f"{_num(held)} {unit} and the cluster's own Postgres and Redis hold "
                            f"{_num(reserved)} {unit}. Admission control refuses anything that "
                            "would breach the ceiling, so this means the ceiling was lowered "
                            "while these were already running, or they were adopted after a "
                            "restart. New requests are already being refused."
                            + (
                                ""
                                if idle
                                else " Every instance is busy, so nothing can be "
                                "reclaimed without failing a live request."
                            )
                        ),
                        fix=(
                            f"Reclaim {len(idle)} idle instance{'' if len(idle) == 1 else 's'}"
                            if idle
                            else None
                        ),
                        target={"containers": [i.container_id for i in idle]},
                    )
                )

        # ── each function against its own ceiling ────────────────────────────
        for fn in functions:
            if fn.group.cluster_id != cluster.id:
                continue
            running = [i for i in mine if i.function_id == str(fn.id)]

            if len(running) > fn.max_instances:
                idle = sorted(
                    (i for i in running if not i.busy),
                    key=lambda i: (i.invocations, i.last_used),
                )
                surplus = idle[: len(running) - fn.max_instances]
                findings.append(
                    Finding(
                        id=f"over-max-instances:{fn.id}",
                        kind="function_over_max_instances",
                        severity="error",
                        cluster=cluster.slug,
                        summary=(
                            f"{fn.group.ns}/{fn.name} has {len(running)} warm instances "
                            f"but allows {fn.max_instances}"
                        ),
                        detail=(
                            "The ceiling was lowered while these were running, or they were "
                            "adopted after a restart. They hold memory the function is no "
                            f"longer configured to use — {_num(sum(i.memory_mb for i in running))}"
                            f" MB against {_num(fn.max_instances * fn.memory_mb)} MB allowed."
                        ),
                        fix=(
                            f"Reclaim {len(surplus)} idle instance"
                            f"{'' if len(surplus) == 1 else 's'}"
                            if surplus
                            else None
                        ),
                        target={"containers": [i.container_id for i in surplus]},
                    )
                )

            # An isolate keeps the size it started with; changing the setting
            # does not resize a running container.
            wrong = [i for i in running if i.memory_mb != fn.memory_mb and not i.busy]
            if wrong:
                findings.append(
                    Finding(
                        id=f"wrong-size:{fn.id}",
                        kind="isolate_wrong_size",
                        severity="warn",
                        cluster=cluster.slug,
                        summary=(
                            f"{fn.group.ns}/{fn.name} has {len(wrong)} instance"
                            f"{'' if len(wrong) == 1 else 's'} running at the wrong size"
                        ),
                        detail=(
                            f"They hold {', '.join(sorted({f'{i.memory_mb} MB' for i in wrong}))} "
                            f"while the function is set to {fn.memory_mb} MB. A container keeps "
                            "the size it started with, so the setting only takes effect on the "
                            "next one — and the cluster is charged for what they actually hold."
                        ),
                        fix=f"Reclaim {len(wrong)} instance{'' if len(wrong) == 1 else 's'}",
                        target={"containers": [i.container_id for i in wrong]},
                    )
                )

            # ── configuration that can never be satisfied ────────────────────
            if quota:
                room = quota.memory_cap_mb - quota.reserved_mb
                if fn.memory_mb > room:
                    findings.append(
                        Finding(
                            id=f"never-fits:{fn.id}",
                            kind="function_cannot_fit",
                            severity="warn",
                            cluster=cluster.slug,
                            summary=(
                                f"{fn.group.ns}/{fn.name} can never start under "
                                f"{cluster.name}'s ceiling"
                            ),
                            detail=(
                                f"It asks for {fn.memory_mb} MB, and the cluster's "
                                f"{quota.memory_cap_mb} MB ceiling has only {_num(room)} MB left "
                                "once its Postgres and Redis are counted. Every request to it is "
                                "refused immediately rather than queued."
                            ),
                            fix=None,
                            target={"function": str(fn.id)},
                        )
                    )
                elif fn.max_instances * fn.memory_mb > room:
                    fits = int(room // fn.memory_mb)
                    findings.append(
                        Finding(
                            id=f"cannot-reach-max:{fn.id}",
                            kind="function_cannot_reach_max",
                            severity="info",
                            cluster=cluster.slug,
                            summary=(
                                f"{fn.group.ns}/{fn.name} cannot reach its "
                                f"{fn.max_instances}-instance ceiling"
                            ),
                            detail=(
                                f"{fn.max_instances} × {fn.memory_mb} MB exceeds the "
                                f"{_num(room)} MB {cluster.name} has left under its ceiling. It "
                                f"will stop at {fits} and queue the rest, which is a working "
                                "arrangement — just not the one the setting describes."
                            ),
                            fix=None,
                            target={"function": str(fn.id)},
                        )
                    )

    return findings


def _num(value: float) -> str:
    """Whole numbers without a trailing .0, fractions to two places."""
    return f"{value:.2f}".rstrip("0").rstrip(".") if value % 1 else f"{value:.0f}"
