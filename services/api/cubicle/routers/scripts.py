"""Host scripts: the console's side of them.

Every endpoint here is owner-only, and the feature is off until an owner turns
it on. A script is a root process on the machine, started by a URL — writing
one is exactly as consequential as opening the terminal and typing it, so it
asks for exactly the same role, and gets its own instance-wide switch because
turning on a shell for a person at a keyboard is not the same decision as
turning on a URL anyone may be given.

The public endpoint that actually receives those URLs is
:mod:`cubicle.routers.run`; both go through :mod:`cubicle.scripts` so that what
the run button does and what a webhook does cannot drift apart.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .. import scripts as script_svc
from ..deps import CurrentCluster, DbSession, InstanceDep, RequireOwner
from ..logging_setup import log
from ..models import Cluster, HostScript, HostScriptRun, Node
from ..runtime import hostscripts as runtime

router = APIRouter(prefix="/api/scripts", tags=["scripts"])

METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
OUTPUT_MODES = {"auto", "json", "text"}


class SettingsUpdate(BaseModel):
    enabled: bool


class ScriptIn(BaseModel):
    """Everything about a script. Every field is optional on a PATCH, and the
    absent ones are left alone rather than reset — an editor that saves the
    source should not silently clear an environment it never showed.
    """

    name: str | None = Field(default=None, max_length=runtime.NAME_MAX)
    description: str | None = Field(default=None, max_length=200)
    interpreter: str | None = Field(default=None, max_length=120)
    source: str | None = None
    working_dir: str | None = Field(default=None, max_length=255)
    timeout_s: int | None = Field(default=None, ge=runtime.MIN_TIMEOUT_S, le=runtime.MAX_TIMEOUT_S)
    method: str | None = None
    output_mode: str | None = None
    node_id: str | None = None
    auth_required: bool | None = None
    status: str | None = None
    env: dict[str, str] | None = None


class RunRequest(BaseModel):
    """What the console's run button sends — the same two things a request
    would have carried, so testing a script from here tests the real path.
    """

    body: str = ""
    query: dict[str, str] = Field(default_factory=dict)


def _bad(message: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, message)


async def _load(db, cluster: Cluster, script_id: uuid.UUID) -> HostScript:
    script = (
        await db.execute(
            select(HostScript).where(
                HostScript.id == script_id, HostScript.cluster_id == cluster.id
            )
        )
    ).scalar_one_or_none()
    if script is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such script.")
    return script


async def _node_name(db, script: HostScript) -> str:
    if script.node_id is None:
        return ""
    node = await db.get(Node, script.node_id)
    return node.name if node is not None else ""


async def _apply(db, cluster: Cluster, script: HostScript, payload: ScriptIn) -> None:
    """Validate and copy over whatever was sent. Nothing is half-applied: every
    check happens before the first assignment.
    """
    if payload.name is not None:
        name = payload.name.strip().lower()
        if not runtime.valid_name(name):
            raise _bad(
                "A script name is lower-case letters, digits and hyphens, "
                f"up to {runtime.NAME_MAX} characters."
            )
    if payload.interpreter is not None and not runtime.valid_interpreter(
        payload.interpreter.strip()
    ):
        raise _bad(
            "An interpreter is one command name on the host's PATH, one absolute "
            "path, or 'shebang' to let the script's own #! line decide."
        )
    if payload.working_dir is not None and not runtime.valid_working_dir(
        payload.working_dir.strip()
    ):
        raise _bad("A working directory must be an absolute path on the host, or blank.")
    if payload.method is not None and payload.method.upper() not in METHODS:
        raise _bad(f"A method is one of {', '.join(sorted(METHODS))}.")
    if payload.output_mode is not None and payload.output_mode not in OUTPUT_MODES:
        raise _bad(f"An output mode is one of {', '.join(sorted(OUTPUT_MODES))}.")
    if payload.status is not None and payload.status not in ("active", "paused"):
        raise _bad("A script is either active or paused.")
    if payload.source is not None and len(payload.source.encode()) > runtime.MAX_SOURCE_BYTES:
        raise _bad(f"A script may be at most {runtime.MAX_SOURCE_BYTES // 1024} KB.")

    node_id: uuid.UUID | None = None
    if payload.node_id:
        try:
            node_id = uuid.UUID(payload.node_id)
        except ValueError:
            raise _bad("That is not a node id.") from None
        node = await db.get(Node, node_id)
        if node is None or node.cluster_id != cluster.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such node on this cluster.")

    env_ciphertext = None
    if payload.env is not None:
        try:
            env_ciphertext = script_svc.dump_env(runtime.clean_env(payload.env))
        except runtime.ScriptError as exc:
            raise _bad(str(exc)) from exc

    if payload.name is not None:
        script.name = payload.name.strip().lower()
    if payload.description is not None:
        script.description = payload.description.strip()
    if payload.interpreter is not None:
        script.interpreter = payload.interpreter.strip()
    if payload.source is not None:
        script.source = payload.source
    if payload.working_dir is not None:
        script.working_dir = payload.working_dir.strip()
    if payload.timeout_s is not None:
        script.timeout_s = payload.timeout_s
    if payload.method is not None:
        script.method = payload.method.upper()
    if payload.output_mode is not None:
        script.output_mode = payload.output_mode
    if payload.auth_required is not None:
        script.auth_required = payload.auth_required
    if payload.status is not None:
        script.status = payload.status
    if payload.node_id is not None:
        script.node_id = node_id
    if payload.env is not None:
        script.env_ciphertext = env_ciphertext


# ── the switch ───────────────────────────────────────────────────────────────


@router.get("/status")
async def scripts_status(instance: InstanceDep, _: RequireOwner):
    """Just the toggle, and the interpreters the console offers. Touches no
    node: provisioning happens when something actually asks for a run.
    """
    return {
        "enabled": instance.host_scripts_enabled,
        "interpreters": [
            {"value": value, "label": label} for value, label in runtime.INTERPRETERS.items()
        ],
        "max_timeout_s": runtime.MAX_TIMEOUT_S,
    }


@router.put("/settings")
async def update_settings(
    payload: SettingsUpdate, instance: InstanceDep, db: DbSession, _: RequireOwner
):
    instance.host_scripts_enabled = payload.enabled
    await db.commit()
    log.info("host scripts setting changed", enabled=payload.enabled)
    return {"enabled": instance.host_scripts_enabled}


# ── the scripts themselves ───────────────────────────────────────────────────


@router.get("")
async def list_scripts(
    db: DbSession, cluster: CurrentCluster, instance: InstanceDep, _: RequireOwner
):
    rows = (
        (
            await db.execute(
                select(HostScript)
                .where(HostScript.cluster_id == cluster.id)
                .order_by(HostScript.name)
            )
        )
        .scalars()
        .all()
    )
    names = {
        node.id: node.name
        for node in (await db.execute(select(Node).where(Node.cluster_id == cluster.id))).scalars()
    }
    return {
        "enabled": instance.host_scripts_enabled,
        "scripts": [
            script_svc.serialize(s, cluster, node_name=names.get(s.node_id, "")) for s in rows
        ],
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_script(
    payload: ScriptIn,
    db: DbSession,
    cluster: CurrentCluster,
    instance: InstanceDep,
    _: RequireOwner,
):
    if not instance.host_scripts_enabled:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Host scripts are off for this instance. Turn them on in Settings first.",
        )
    if not payload.name:
        raise _bad("A script needs a name.")

    script = HostScript(cluster_id=cluster.id, name="")
    await _apply(db, cluster, script, payload)
    db.add(script)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"This cluster already has a script called '{payload.name}'."
        ) from None
    await db.refresh(script)
    log.info("host script created", script=script.name, cluster=cluster.slug)
    return script_svc.serialize(script, cluster, node_name=await _node_name(db, script))


@router.get("/{script_id}")
async def get_script(script_id: uuid.UUID, db: DbSession, cluster: CurrentCluster, _: RequireOwner):
    script = await _load(db, cluster, script_id)
    return {
        **script_svc.serialize(script, cluster, node_name=await _node_name(db, script)),
        "source": script.source,
        # Values, not hints: an owner who may open a root shell on this machine
        # can already read anything the script could. Masking them here would
        # protect nothing and make the editor unusable.
        "env": script_svc.load_env(script),
    }


@router.patch("/{script_id}")
async def update_script(
    script_id: uuid.UUID,
    payload: ScriptIn,
    db: DbSession,
    cluster: CurrentCluster,
    _: RequireOwner,
):
    script = await _load(db, cluster, script_id)
    await _apply(db, cluster, script, payload)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This cluster already has a script with that name."
        ) from None
    await db.refresh(script)
    return script_svc.serialize(script, cluster, node_name=await _node_name(db, script))


@router.delete("/{script_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_script(
    script_id: uuid.UUID, db: DbSession, cluster: CurrentCluster, principal: RequireOwner
):
    script = await _load(db, cluster, script_id)
    name = script.name
    await db.delete(script)
    await db.commit()
    log.info("host script deleted", script=name, by=principal.user.email)


# ── running and history ──────────────────────────────────────────────────────


@router.post("/{script_id}/run")
async def run_script(
    script_id: uuid.UUID,
    payload: RunRequest,
    db: DbSession,
    cluster: CurrentCluster,
    instance: InstanceDep,
    principal: RequireOwner,
):
    """Run it now, from the console, and hand back everything it printed.

    Unlike the public endpoint this never shapes the output into a response
    body — the point of pressing the button is to see stdout, stderr and the
    exit code as they were, which is exactly what the URL will not show you.
    """
    if not instance.host_scripts_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Host scripts are off for this instance.")
    script = await _load(db, cluster, script_id)

    try:
        done = await script_svc.execute(
            db,
            cluster,
            script,
            trigger="console",
            caller=script_svc.Caller(method="CONSOLE", path=script.path, query=payload.query),
            stdin=payload.body.encode(),
        )
    except runtime.ScriptError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    log.info("host script run from the console", script=script.name, by=principal.user.email)
    return {
        "run_id": done.run_id,
        "node_name": done.node_name,
        "exit_code": done.outcome.exit_code,
        "status_code": done.status_code,
        "duration_ms": done.outcome.duration_ms,
        "stdout": done.outcome.stdout_text(),
        "stderr": done.outcome.stderr_text(),
        "truncated": done.outcome.truncated,
        "timed_out": done.outcome.timed_out,
    }


@router.get("/{script_id}/runs")
async def list_runs(
    script_id: uuid.UUID,
    db: DbSession,
    cluster: CurrentCluster,
    _: RequireOwner,
    limit: int = Query(default=20, ge=1, le=script_svc.RUNS_KEPT),
):
    await _load(db, cluster, script_id)
    rows = (
        (
            await db.execute(
                select(HostScriptRun)
                .where(HostScriptRun.script_id == script_id)
                .order_by(HostScriptRun.ts.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [script_svc.serialize_run(run) for run in rows]
