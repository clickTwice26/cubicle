"""Host scripts: everything a run needs around it.

:mod:`cubicle.runtime.hostscripts` knows how to get a program onto a node's
host and bring its output back. This module is what sits between that and the
two things that ask for it — the console's run button and the public URL — so
that both get the same node resolution, the same environment, the same record
afterwards and the same answer about what an exit code means.

Kept out of the routers on purpose: a script is the one thing here whose
console path and whose anonymous-webhook path must behave identically, because
the second one is how it will actually be used and the first one is how it will
be tested.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import clusters as cluster_svc
from .crypto import DecryptionError, decrypt, encrypt
from .db import session_scope
from .logging_setup import log
from .models import Cluster, HostScript, HostScriptRun, Node
from .runtime import hostscripts as runtime

#: Runs kept per script. Enough to see a pattern in what a nightly job has been
#: doing; not so many that a script called every minute becomes the largest
#: table in the database.
RUNS_KEPT = 50

#: Additional authenticated data, so a ciphertext lifted from one script's row
#: cannot be pasted into another's and decrypt.
ENV_AAD = "host-script-env"


@dataclass(slots=True)
class Caller:
    """What the script is told about the request that started it."""

    method: str = "CONSOLE"
    path: str = ""
    query: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)


# ── the script's own environment ─────────────────────────────────────────────


def load_env(script: HostScript) -> dict[str, str]:
    """The stored environment, or nothing at all if it cannot be read.

    A row encrypted under a master key that is no longer there is not a reason
    to refuse to show the script: the operator needs to see what they have in
    order to understand what they lost.
    """
    if not script.env_ciphertext:
        return {}
    try:
        loaded = json.loads(decrypt(script.env_ciphertext, aad=ENV_AAD))
    except (DecryptionError, ValueError):
        log.warning("host script environment could not be read", script=script.name)
        return {}
    return {str(k): str(v) for k, v in loaded.items()} if isinstance(loaded, dict) else {}


def dump_env(env: dict[str, str]) -> str | None:
    return encrypt(json.dumps(env), aad=ENV_AAD) if env else None


def invocation_env(
    script: HostScript, cluster: Cluster, *, run_id: str, trigger: str, caller: Caller
) -> dict[str, str]:
    """What the process can read about itself.

    The body arrives on stdin rather than in here — an environment is not the
    place for six megabytes, and reading stdin is what a program run from a
    shell already knows how to do.
    """
    return {
        **load_env(script),
        "CUBICLE_RUN_ID": run_id,
        "CUBICLE_SCRIPT": script.name,
        "CUBICLE_CLUSTER": cluster.slug,
        "CUBICLE_TRIGGER": trigger,
        "CUBICLE_METHOD": caller.method,
        "CUBICLE_PATH": caller.path,
        "CUBICLE_QUERY": json.dumps(caller.query, separators=(",", ":")),
        "CUBICLE_HEADERS": json.dumps(caller.headers, separators=(",", ":")),
    }


# ── where it runs ────────────────────────────────────────────────────────────


async def resolve_node(db: AsyncSession, cluster: Cluster, script: HostScript) -> Node | None:
    """The node whose host this script runs on.

    Not :func:`runtime.nodes.pick_node`: that balances load across a pool,
    which is right for a function and wrong here. A script touches a *machine*
    — its disk, its cron, its packages — so "wherever is least busy" would
    quietly run a backup against the wrong filesystem. A script either names
    its node or means the one the control plane itself is on.
    """
    if script.node_id is not None:
        node = await db.get(Node, script.node_id)
        if node is not None and node.cluster_id == cluster.id:
            return node

    local = (
        await db.execute(select(Node).where(Node.cluster_id == cluster.id, Node.is_local.is_(True)))
    ).scalar_one_or_none()
    if local is not None:
        return local
    return (
        (
            await db.execute(
                select(Node).where(Node.cluster_id == cluster.id).order_by(Node.created_at)
            )
        )
        .scalars()
        .first()
    )


# ── what an exit code means over HTTP ────────────────────────────────────────


def status_for(outcome: runtime.Outcome) -> int:
    """Zero is 200 and everything else is a failure, with two worth naming.

    A script that exits non-zero has said the request failed — there is no
    other channel for it to say so, and treating stdout as success regardless
    would make an exit code decorative.
    """
    if outcome.ok:
        return 200
    if outcome.timed_out:
        return 504
    return 500


def serialize(script: HostScript, cluster: Cluster, *, node_name: str = "") -> dict:
    return {
        "id": script.id,
        "name": script.name,
        "description": script.description,
        "interpreter": script.interpreter,
        "interpreter_label": runtime.INTERPRETERS.get(script.interpreter, script.interpreter),
        "working_dir": script.working_dir,
        "timeout_s": script.timeout_s,
        "method": script.method,
        "output_mode": script.output_mode,
        "auth_required": script.auth_required,
        "status": script.status,
        "node_id": str(script.node_id) if script.node_id else None,
        "node_name": node_name,
        "run_count": script.run_count,
        "last_run_at": script.last_run_at,
        "last_exit_code": script.last_exit_code,
        "cluster": cluster.slug,
        "path": script.path,
        "url": cluster_svc.script_url(cluster, script.name),
        "created_at": script.created_at,
        "updated_at": script.updated_at,
    }


def serialize_run(run: HostScriptRun) -> dict:
    return {
        "id": run.id,
        "ts": run.ts,
        "trigger": run.trigger,
        "exit_code": run.exit_code,
        "duration_ms": run.duration_ms,
        "stdout": run.stdout,
        "stderr": run.stderr,
        "truncated": run.truncated,
        "status_code": run.status_code,
        "request_id": run.request_id,
        "node_name": run.node_name,
    }


# ── running one ──────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Completed:
    outcome: runtime.Outcome
    status_code: int
    run_id: str
    node_name: str


async def execute(
    db: AsyncSession,
    cluster: Cluster,
    script: HostScript,
    *,
    trigger: str,
    caller: Caller,
    stdin: bytes = b"",
) -> Completed:
    """Run the script and record what happened.

    Raises :class:`runtime.ScriptError` only when the run could not be
    attempted — a script that fails is a :class:`Completed` with a non-zero
    exit code, because that is an answer and not a malfunction.
    """
    node = await resolve_node(db, cluster, script)
    if node is None:
        raise runtime.ScriptError("this cluster has no node to run on.")

    run_id = "run_" + uuid.uuid4().hex[:12]
    outcome = await runtime.run(
        node.docker_host,
        source=script.source,
        interpreter=script.interpreter,
        env=invocation_env(script, cluster, run_id=run_id, trigger=trigger, caller=caller),
        working_dir=script.working_dir,
        timeout_s=script.timeout_s,
        stdin=stdin,
    )
    status_code = status_for(outcome)

    log.info(
        "host script run",
        script=script.name,
        cluster=cluster.slug,
        node=node.name,
        trigger=trigger,
        exit_code=outcome.exit_code,
        duration_ms=round(outcome.duration_ms, 1),
    )
    await _record(
        cluster_id=cluster.id,
        script_id=script.id,
        outcome=outcome,
        status_code=status_code,
        run_id=run_id,
        trigger=trigger,
        node_name=node.name,
    )
    return Completed(outcome=outcome, status_code=status_code, run_id=run_id, node_name=node.name)


async def _record(
    *,
    cluster_id: uuid.UUID,
    script_id: uuid.UUID,
    outcome: runtime.Outcome,
    status_code: int,
    run_id: str,
    trigger: str,
    node_name: str,
) -> None:
    """On a session of its own, so keeping the history can never fail the run.

    The script already ran. Whatever it did to the machine, it did — losing the
    record of that would be bad, but refusing to answer the caller because the
    record could not be written would be worse and would not undo anything.
    """
    try:
        async with session_scope() as db:
            db.add(
                HostScriptRun(
                    script_id=script_id,
                    cluster_id=cluster_id,
                    trigger=trigger,
                    exit_code=outcome.exit_code,
                    duration_ms=outcome.duration_ms,
                    stdout=outcome.stdout_text(),
                    stderr=outcome.stderr_text(),
                    truncated=outcome.truncated,
                    status_code=status_code,
                    request_id=run_id,
                    node_name=node_name,
                )
            )

            script = await db.get(HostScript, script_id)
            if script is not None:
                script.run_count += 1
                script.last_run_at = datetime.now(UTC)
                script.last_exit_code = outcome.exit_code

            await db.flush()
            await _trim(db, script_id)
    except Exception:  # noqa: BLE001 - history must not break the response
        log.exception("could not record a host script run", run_id=run_id)


async def _trim(db: AsyncSession, script_id: uuid.UUID) -> None:
    keep = (
        (
            await db.execute(
                select(HostScriptRun.id)
                .where(HostScriptRun.script_id == script_id)
                .order_by(HostScriptRun.ts.desc())
                .limit(RUNS_KEPT)
            )
        )
        .scalars()
        .all()
    )
    if len(keep) < RUNS_KEPT:
        return
    await db.execute(
        delete(HostScriptRun).where(
            HostScriptRun.script_id == script_id, HostScriptRun.id.notin_(keep)
        )
    )
