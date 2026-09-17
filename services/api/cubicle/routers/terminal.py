"""A live shell on a node's host — the console's answer to "just SSH in".

Every endpoint here is owner-only, and the feature is off until an owner turns
it on: this is the one thing in the console whose entire purpose is running
arbitrary commands as root on the machine. See ``models.Instance.terminal_enabled``
and ``runtime.terminal`` for why, and how.

Sessions are tmux sessions inside one toolbox container per node, not rows in
this database — asking a node is always asking the truth, and a session
outlives an API restart the same way a running app does. WebSocket
authentication is manual (see ``deps.websocket_principal``) rather than
``Depends``-based, so a rejection is a clean, documented close code instead of
whatever a raised ``HTTPException`` does mid-handshake on a given FastAPI
version.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import secrets
import threading
import uuid

import anyio
from fastapi import APIRouter, HTTPException, Query, WebSocket, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..config import settings
from ..db import session_scope
from ..deps import (
    CurrentCluster,
    DbSession,
    InstanceDep,
    RequireOwner,
    get_instance,
    websocket_cluster,
    websocket_principal,
)
from ..logging_setup import log
from ..models import Node
from ..runtime import terminal as runtime

router = APIRouter(prefix="/api/terminal", tags=["terminal"])

#: A close code a client can branch on without parsing the reason string.
#: 1008 is "policy violation" in the WebSocket spec — the closest fit for
#: every rejection here, auth included, since none of them are protocol errors.
WS_POLICY_VIOLATION = 1008
WS_SERVER_ERROR = 1011


class SettingsUpdate(BaseModel):
    enabled: bool


class SessionCreate(BaseModel):
    #: Blank generates one — most people opening a second shell do not want
    #: to think of a name for it first.
    name: str = Field(default="", max_length=runtime.NAME_MAX)
    node_id: str | None = None


class SessionRename(BaseModel):
    name: str = Field(max_length=runtime.NAME_MAX)


def _new_name() -> str:
    return f"session-{secrets.token_hex(3)}"


def _validated_name(raw: str) -> str:
    name = raw.strip()
    if not runtime.valid_name(name):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A session name is letters, digits, - and _, up to " f"{runtime.NAME_MAX} characters.",
        )
    return name


async def _resolve_node(db, cluster, node_ref: str | None) -> Node | None:
    """A specific node if it is named and belongs to this cluster; otherwise
    the node this control plane itself runs on — "the VPS" is what someone
    means by default, not whichever node happens to be least busy.
    """
    if node_ref:
        node = None
        with contextlib.suppress(ValueError):
            node = await db.get(Node, uuid.UUID(node_ref))
        return node if node is not None and node.cluster_id == cluster.id else None

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


@router.get("/status")
async def terminal_status(instance: InstanceDep, _: RequireOwner):
    """Just the toggle. Visiting Settings should not provision a toolbox
    container on every node — ``GET /sessions`` is the one that does that,
    and only once something actually asks it for a node's sessions.
    """
    return {"enabled": instance.terminal_enabled}


@router.put("/settings")
async def update_settings(
    payload: SettingsUpdate, instance: InstanceDep, db: DbSession, _: RequireOwner
):
    instance.terminal_enabled = payload.enabled
    await db.commit()
    log.info("terminal access setting changed", enabled=payload.enabled)
    return {"enabled": instance.terminal_enabled}


@router.get("/sessions")
async def list_sessions(
    db: DbSession,
    cluster: CurrentCluster,
    instance: InstanceDep,
    _: RequireOwner,
    node: str | None = Query(default=None),
):
    if not instance.terminal_enabled:
        return {"enabled": False, "node_id": None, "node_name": None, "sessions": []}

    target = await _resolve_node(db, cluster, node)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such node on this cluster.")

    sessions = await runtime.list_sessions(target.docker_host, version=settings.version)
    return {
        "enabled": True,
        "node_id": str(target.id),
        "node_name": target.name,
        # `SessionInfo` is a slotted dataclass — no `__dict__` to reach for.
        "sessions": [dataclasses.asdict(s) for s in sessions],
    }


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreate,
    db: DbSession,
    cluster: CurrentCluster,
    instance: InstanceDep,
    _: RequireOwner,
):
    if not instance.terminal_enabled:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Terminal access is off for this instance. Turn it on in Settings first.",
        )

    target = await _resolve_node(db, cluster, payload.node_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such node on this cluster.")

    name = _validated_name(payload.name) if payload.name.strip() else _new_name()
    await runtime.create_session(
        target.docker_host, name, version=settings.version, cols=80, rows=24
    )
    log.info("terminal session created", node=target.name, session=name)
    return {"name": name, "node_id": str(target.id), "node_name": target.name}


@router.delete("/sessions/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    name: str,
    db: DbSession,
    cluster: CurrentCluster,
    principal: RequireOwner,
    node: str | None = Query(default=None),
):
    target = await _resolve_node(db, cluster, node)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such node on this cluster.")
    found = await runtime.kill_session(target.docker_host, name, version=settings.version)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No session named '{name}'.")
    log.info("terminal session ended", node=target.name, session=name, by=principal.user.email)


@router.patch("/sessions/{name}")
async def rename_session(
    name: str,
    payload: SessionRename,
    db: DbSession,
    cluster: CurrentCluster,
    _: RequireOwner,
    node: str | None = Query(default=None),
):
    target = await _resolve_node(db, cluster, node)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such node on this cluster.")
    new_name = _validated_name(payload.name)
    await runtime.rename_session(target.docker_host, name, new_name, version=settings.version)
    return {"name": new_name, "node_id": str(target.id)}


# ── the live attach ──────────────────────────────────────────────────────────


def _query_int(websocket: WebSocket, key: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = websocket.query_params.get(key)
    try:
        value = int(raw) if raw is not None else default
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


@router.websocket("/sessions/{name}/ws")
async def shell_ws(websocket: WebSocket, name: str) -> None:
    """One tmux session, attached live. Binary frames are raw terminal bytes
    in both directions; a text frame from the client is a JSON control message
    — today, only ``{"type": "resize", "cols": ..., "rows": ...}``.
    """
    async with session_scope() as db:
        principal = await websocket_principal(websocket, db)
        if principal is None or not principal.can("owner"):
            await websocket.close(code=WS_POLICY_VIOLATION, reason="owner role required")
            return

        instance = await get_instance(db)
        if not instance.terminal_enabled:
            await websocket.close(code=WS_POLICY_VIOLATION, reason="terminal access is off")
            return

        cluster = await websocket_cluster(websocket, db, principal)
        if cluster is None:
            await websocket.close(code=WS_POLICY_VIOLATION, reason="no such cluster")
            return

        target = await _resolve_node(db, cluster, websocket.query_params.get("node"))
        if target is None:
            await websocket.close(code=WS_POLICY_VIOLATION, reason="no such node")
            return
        host, node_name = target.docker_host, target.name

    if not runtime.valid_name(name):
        await websocket.close(code=WS_POLICY_VIOLATION, reason="invalid session name")
        return

    cols = _query_int(websocket, "cols", 80, minimum=10, maximum=500)
    rows = _query_int(websocket, "rows", 24, minimum=5, maximum=200)

    try:
        shell = await runtime.open_shell(host, name, version=settings.version, cols=cols, rows=rows)
    except runtime.TerminalError as exc:
        await websocket.close(code=WS_SERVER_ERROR, reason=str(exc)[:120])
        return

    await websocket.accept()
    log.info("terminal session attached", node=node_name, session=name)
    stop = threading.Event()

    async def pump_output() -> None:
        def _read_loop() -> None:
            while not stop.is_set():
                chunk = runtime.read_chunk(shell)
                if not chunk:
                    return
                anyio.from_thread.run(websocket.send_bytes, chunk)

        # abandon_on_cancel: a blocking socket read cannot be interrupted from
        # here — closing the exec socket (in the outer ``finally``) is what
        # actually unblocks it. Without this, cancelling this task would just
        # wait for a read that may never come instead of letting the
        # WebSocket close promptly when the other side of the pump finishes.
        await anyio.to_thread.run_sync(_read_loop, abandon_on_cancel=True)

    async def pump_input() -> None:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            data = message.get("bytes")
            if data is not None:
                await anyio.to_thread.run_sync(runtime.write_chunk, shell, data)
                continue
            text = message.get("text")
            if not text:
                continue
            try:
                control = json.loads(text)
            except ValueError:
                continue
            if control.get("type") == "resize":
                new_cols = max(10, min(500, int(control.get("cols") or cols)))
                new_rows = max(5, min(200, int(control.get("rows") or rows)))
                await anyio.to_thread.run_sync(runtime.resize_shell, shell, new_cols, new_rows)

    try:
        async with anyio.create_task_group() as tg:

            async def _run_output() -> None:
                try:
                    await pump_output()
                finally:
                    tg.cancel_scope.cancel()

            async def _run_input() -> None:
                try:
                    await pump_input()
                finally:
                    tg.cancel_scope.cancel()

            tg.start_soon(_run_output)
            tg.start_soon(_run_input)
    finally:
        stop.set()
        runtime.close_shell(shell)
        with contextlib.suppress(Exception):
            await websocket.close()
        log.info("terminal session detached", node=node_name, session=name)
