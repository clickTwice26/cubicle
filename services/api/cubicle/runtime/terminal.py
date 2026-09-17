"""A live shell on a node's own host.

Every other runtime module in this package manages containers: functions,
apps, managed services. This one is different on purpose — it gives an owner
the machine itself, the way SSH would, but reached through the console and
usable from a phone with nothing installed.

The mechanism is the well-known trick for getting a real host shell out of a
container without installing anything on the host first: one long-lived,
privileged "toolbox" container per node, sharing the host's PID namespace so
``nsenter -t 1`` resolves to the host's own init, and from there re-entering
its mount, UTS, network and IPC namespaces too. What runs inside is the host's
own filesystem, hostname, network stack and init system — ``apt``, ``systemctl``,
``docker``, editing a config file, all exactly as they would be over SSH. The
toolbox's own filesystem (this module's Dockerfile) exists only to hold tmux,
bash and nsenter; nothing of the toolbox is exposed to the shell it opens.

tmux is what makes a session survive a dropped connection: the WebSocket only
ever attaches an already-running (or freshly created) tmux session, so closing
a laptop lid and reopening the console reattaches to the same shell, scrollback
and running command, exactly as it would over a persistent SSH connection with
tmux on the other end. Multiple sessions are just multiple tmux sessions inside
the one toolbox container — nothing here is per-session state that the control
plane has to track, because tmux already tracks it, and tmux already survives
an API restart the same way an app's containers do.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import docker
import docker.utils.socket as docker_socket
from docker.errors import APIError, DockerException, NotFound

from ..logging_setup import log
from .engine import engines

TOOLBOX_NAME = "cubicle-toolbox"
#: Rebuilt whenever the version changes, which is rare and cheap (it is a
#: handful of Alpine packages) — simpler than tracking the Dockerfile's own
#: hash, and it means an upgrade always gets a fresh toolbox.
TOOLBOX_TAG = "cubicle/toolbox:{version}"

#: A session name becomes a tmux target and nothing else — never shell text,
#: never a path. Kept close to what tmux itself accepts, and short enough to
#: read comfortably as a tab label.
NAME_MAX = 40

#: apk needs network access to install these; the image otherwise carries
#: nothing — the shell it opens is the host's own, not this container's.
TOOLBOX_DOCKERFILE = """\
FROM alpine:3.20
RUN apk add --no-cache bash tmux util-linux ncurses-terminfo
CMD ["sleep", "infinity"]
"""

#: The command every session's pane runs. Re-enters the host's mount, UTS,
#: network and IPC namespaces (PID is already shared — see ``ensure_toolbox``);
#: ``-t 1`` only resolves to the host's real init because of that. Tries bash
#: first since that is what almost every real host has, falling back to sh for
#: the rare minimal one that does not.
_NSENTER_SHELL = [
    "nsenter",
    "-t",
    "1",
    "-m",
    "-u",
    "-i",
    "-n",
    "-p",
    "--",
    "sh",
    "-c",
    "exec bash -l 2>/dev/null || exec sh -l",
]

_LIST_FORMAT = "\t".join(
    f"#{{{field}}}"
    for field in (
        "session_name",
        "session_created",
        "session_attached",
        "session_width",
        "session_height",
        "session_activity",
    )
)


class TerminalError(RuntimeError):
    """Something the operator should read, in the console."""


@dataclass(slots=True)
class SessionInfo:
    name: str
    created_at: str
    attached: bool
    cols: int
    rows: int
    activity_at: str


@dataclass(slots=True)
class Shell:
    """One attached exec: the socket the WebSocket handler pumps both ways."""

    client: docker.DockerClient
    exec_id: str
    sock: Any


def valid_name(name: str) -> bool:
    name = name.strip()
    return bool(name) and len(name) <= NAME_MAX and all(c.isalnum() or c in "-_" for c in name)


def _image_tag(version: str) -> str:
    return TOOLBOX_TAG.format(version=version)


def parse_sessions(output: str) -> list[SessionInfo]:
    """Turn ``tmux list-sessions -F ...`` output into structured rows.

    A blank string (no server running yet — nothing has ever been opened) is
    simply no sessions, not an error.
    """
    sessions: list[SessionInfo] = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) != 6:
            continue
        name, created, attached, width, height, activity = parts
        sessions.append(
            SessionInfo(
                name=name,
                created_at=_epoch(created),
                attached=attached != "0",
                cols=int(width) if width.isdigit() else 0,
                rows=int(height) if height.isdigit() else 0,
                activity_at=_epoch(activity),
            )
        )
    return sessions


def _epoch(raw: str) -> str:
    try:
        return datetime.fromtimestamp(int(raw), tz=UTC).isoformat()
    except (ValueError, OverflowError, OSError):
        return ""


# ── the toolbox container ────────────────────────────────────────────────────


async def ensure_toolbox(host: str, *, version: str) -> None:
    """A running, privileged toolbox container on this node. Idempotent.

    ``privileged`` and ``pid_mode="host"`` are the two things Docker itself has
    to grant — ``pid_mode="host"`` is not an optimisation, it is what makes
    ``nsenter -t 1`` inside the container resolve to the *host's* init rather
    than the container's own; every other namespace nsenter re-enters per
    shell instead, so a stopped toolbox never leaves anything of the host
    attached to it.
    """
    tag = _image_tag(version)

    def _ensure(client: docker.DockerClient) -> None:
        try:
            client.images.get(tag)
        except NotFound:
            log.info("building terminal toolbox image", host=host, tag=tag)
            last_error = ""
            for chunk in client.api.build(
                fileobj=io.BytesIO(TOOLBOX_DOCKERFILE.encode()),
                tag=tag,
                rm=True,
                forcerm=True,
                pull=True,
                decode=True,
                labels={"cubicle.role": "toolbox-image"},
            ):
                if "error" in chunk:
                    last_error = str(chunk["error"]).strip()
            if last_error:
                # Not chained: ImageNotFound was the expected reason to be
                # here, not the cause of the build itself failing.
                raise TerminalError(f"could not build the terminal toolbox: {last_error}") from None

        try:
            container = client.containers.get(TOOLBOX_NAME)
        except NotFound:
            container = None

        if container is not None:
            wanted = client.images.get(tag).id
            current = container.image.id if container.image else None
            if current != wanted:
                # An upgrade: tmux sessions inside the old toolbox go with it.
                # There is no way to carry them to a rebuilt image, the same
                # as a control-plane upgrade already does to running isolates.
                log.info("replacing terminal toolbox for a new version", host=host)
                container.remove(force=True)
                container = None
            elif container.status != "running":
                container.start()

        if container is None:
            client.containers.run(
                tag,
                name=TOOLBOX_NAME,
                detach=True,
                privileged=True,
                pid_mode="host",
                restart_policy={"Name": "unless-stopped"},
                labels={"cubicle.role": "toolbox"},
            )
            log.info("terminal toolbox started", host=host)

    try:
        await engines.call(host, _ensure)
    except DockerException as exc:
        raise TerminalError(f"could not prepare the terminal on this node: {exc}") from exc


# ── sessions ─────────────────────────────────────────────────────────────────


async def list_sessions(host: str, *, version: str) -> list[SessionInfo]:
    await ensure_toolbox(host, version=version)

    def _list(client: docker.DockerClient) -> list[SessionInfo]:
        container = client.containers.get(TOOLBOX_NAME)
        exec_id = client.api.exec_create(
            container.id,
            ["tmux", "list-sessions", "-F", _LIST_FORMAT],
            stdout=True,
            stderr=True,
        )["Id"]
        raw = client.api.exec_start(exec_id, tty=False)
        info = client.api.exec_inspect(exec_id)
        if info.get("ExitCode"):
            # No tmux server yet — nothing has ever been opened on this node.
            return []
        return parse_sessions(raw.decode(errors="replace"))

    try:
        return await engines.call(host, _list)
    except DockerException as exc:
        raise TerminalError(f"could not list sessions on this node: {exc}") from exc


async def create_session(host: str, name: str, *, version: str, cols: int, rows: int) -> None:
    """Create the session if it does not already exist. Never attaches.

    Deliberately not ``tmux new-session -A`` here: ``-A`` means "attach to it
    if it exists", which is a request for a live client and needs a real tty —
    this call has none, it is just reserving the name. The interactive attach
    below is the one that reattaches, with an actual terminal for tmux to hand
    the existing session to.
    """
    existing = await list_sessions(host, version=version)
    if any(s.name == name for s in existing):
        return

    def _create(client: docker.DockerClient) -> None:
        container = client.containers.get(TOOLBOX_NAME)
        exec_id = client.api.exec_create(
            container.id,
            ["tmux", "new-session", "-d", "-s", name, "-x", str(cols), "-y", str(rows), "--"]
            + _NSENTER_SHELL,
            stdout=True,
            stderr=True,
        )["Id"]
        client.api.exec_start(exec_id, tty=False)
        info = client.api.exec_inspect(exec_id)
        if info.get("ExitCode"):
            raise TerminalError("tmux could not create the session — see the node's own logs")

    try:
        await engines.call(host, _create)
    except DockerException as exc:
        raise TerminalError(f"could not create the session: {exc}") from exc


async def kill_session(host: str, name: str, *, version: str) -> None:
    def _kill(client: docker.DockerClient) -> bool:
        try:
            container = client.containers.get(TOOLBOX_NAME)
        except NotFound:
            return False
        exec_id = client.api.exec_create(
            container.id, ["tmux", "kill-session", "-t", name], stdout=True, stderr=True
        )["Id"]
        client.api.exec_start(exec_id, tty=False)
        info = client.api.exec_inspect(exec_id)
        return not info.get("ExitCode")

    try:
        return await engines.call(host, _kill)
    except DockerException as exc:
        raise TerminalError(f"could not end the session: {exc}") from exc


async def rename_session(host: str, old: str, new: str, *, version: str) -> None:
    def _rename(client: docker.DockerClient) -> None:
        container = client.containers.get(TOOLBOX_NAME)
        exec_id = client.api.exec_create(
            container.id, ["tmux", "rename-session", "-t", old, new], stdout=True, stderr=True
        )["Id"]
        out = client.api.exec_start(exec_id, tty=False)
        info = client.api.exec_inspect(exec_id)
        if info.get("ExitCode"):
            message = out.decode(errors="replace").strip()
            if "duplicate session" in message:
                raise TerminalError(f"a session named '{new}' already exists")
            raise TerminalError(message or f"could not rename '{old}'")

    await ensure_toolbox(host, version=version)
    try:
        await engines.call(host, _rename)
    except DockerException as exc:
        raise TerminalError(f"could not rename the session: {exc}") from exc


# ── the live attach ──────────────────────────────────────────────────────────


async def open_shell(host: str, name: str, *, version: str, cols: int, rows: int) -> Shell:
    """Attach an interactive exec to ``name``, creating it if it is new.

    Unlike :func:`create_session`, this uses ``-A``: there is now a real
    allocated tty (``tty=True``), so tmux has an actual client to hand an
    existing session to, or to attach freshly if the session is brand new —
    both are well-defined with a live terminal, which is what made the
    detached path above deliberately avoid ``-A``.
    """
    await ensure_toolbox(host, version=version)

    def _open(client: docker.DockerClient) -> Shell:
        container = client.containers.get(TOOLBOX_NAME)
        exec_id = client.api.exec_create(
            container.id,
            ["tmux", "new-session", "-A", "-s", name, "-x", str(cols), "-y", str(rows), "--"]
            + _NSENTER_SHELL,
            stdin=True,
            stdout=True,
            stderr=True,
            tty=True,
        )["Id"]
        sock = client.api.exec_start(exec_id, tty=True, socket=True)
        return Shell(client=client, exec_id=exec_id, sock=sock)

    try:
        return await engines.call(host, _open)
    except DockerException as exc:
        raise TerminalError(f"could not open a shell: {exc}") from exc


def read_chunk(shell: Shell, *, n: int = 4096) -> bytes:
    """Blocking. Call from a worker thread, not the event loop."""
    return docker_socket.read(shell.sock, n)


def write_chunk(shell: Shell, data: bytes) -> None:
    """Blocking, but a terminal write is small — safe to call inline."""
    sock = shell.sock
    if hasattr(sock, "sendall"):
        sock.sendall(data)
    elif hasattr(sock, "send"):
        sock.send(data)
    else:
        os.write(sock.fileno(), data)


def resize_shell(shell: Shell, cols: int, rows: int) -> None:
    """Positional, not keyword-only — called via ``anyio.to_thread.run_sync``,
    which passes a thread's arguments positionally.
    """
    try:
        shell.client.api.exec_resize(shell.exec_id, height=rows, width=cols)
    except APIError as exc:  # noqa: BLE001 - a missed resize is not fatal
        log.debug("terminal resize failed", error=str(exc))


def close_shell(shell: Shell) -> None:
    """Closing the socket is what unblocks a thread stuck in ``read_chunk``."""
    try:
        shell.sock.close()
    except Exception as exc:  # noqa: BLE001 - already going away
        log.debug("terminal socket close failed", error=str(exc))
