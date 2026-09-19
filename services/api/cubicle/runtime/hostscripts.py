"""Running a program on the node's own host, triggered by a URL.

A function is a container: an image built from its source, started on demand,
handed a request. This is the other thing an operator keeps wanting — the
script they would otherwise have run over SSH, given a URL. Nothing here is
built, no image exists, and what runs is a host process: the host's own
``python3``, the host's site-packages, the host's filesystem, the host's
network, the host's ``docker`` and ``systemctl``. ``ps`` on the machine shows
it exactly as it would show the same command typed into a shell there.

Getting out of a container to do that is the same problem the terminal solves,
and it is solved the same way, through the same single privileged toolbox
container per node — see :mod:`cubicle.runtime.terminal`, which owns it. The
difference is only what is on the far side of ``nsenter``: there, an
interactive tmux session that outlives the request; here, one short-lived
program whose output and exit code become an HTTP response.

Three things are worth knowing about how a run is put together.

*The script never passes through a shell as text.* It goes into a tar archive,
over the Docker API into the toolbox, and through the namespace boundary into a
temporary directory on the host. Linux caps a single command-line argument at
128 KiB, so embedding the source — or a request body — in one would have put a
size limit on both and an escaping question on every byte of them. A tar has
neither.

*The timeout is the host's own.* ``timeout`` runs the program, so the bound is
enforced by the kernel on the machine the program runs on, rather than by this
process hoping to interrupt a blocking read it cannot cancel. A host with no
``timeout`` command refuses the run instead of starting something nothing can
stop. The deadline here is only a backstop for a daemon that never answers.

*Output is read over the exec's socket rather than waited for.* docker-py gives
its clients a sixty-second HTTP timeout, which is the right default for every
other call in this package and would be a hard ceiling on a script's runtime.
Reading the socket directly — the same way the terminal reads a shell — has no
such ceiling.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import re
import shlex
import tarfile
import time
import uuid
from dataclasses import dataclass
from functools import partial
from typing import Any

import anyio
import docker
import docker.utils.socket as docker_socket
from docker.errors import DockerException

from ..logging_setup import log
from .engine import engines
from .terminal import TOOLBOX_NAME, TerminalError, ensure_toolbox

# ── what a script may be ─────────────────────────────────────────────────────

NAME_MAX = 63

#: The interpreter value meaning "the script says so itself" — the file is made
#: executable and run directly, so its ``#!`` line decides. The only way to
#: reach an interpreter that needs arguments (``/usr/bin/env -S deno run``),
#: since the field itself deliberately holds one bare word or path.
SHEBANG = "shebang"

#: Offered in the console. Anything else that is a bare command name or an
#: absolute path is accepted too — this is the host's ``PATH``, not a runtime
#: catalogue Cubicle has to build images for.
INTERPRETERS: dict[str, str] = {
    "python3": "Python 3",
    "bash": "Bash",
    "sh": "POSIX shell",
    "node": "Node.js",
    "ruby": "Ruby",
    "perl": "Perl",
    "php": "PHP",
    SHEBANG: "Whatever the script's #! line says",
}

#: A script is source code an operator typed, not an upload — this is a
#: sanity ceiling, not a budget.
MAX_SOURCE_BYTES = 512 * 1024

#: How much of each stream a run may return, when the script does not say.
#:
#: Everything past the limit is still *read* — a program must never block
#: writing to a pipe because this stopped listening — but it is not returned,
#: and a run that hits it is reported as truncated rather than as success. A
#: script used as a proxy for somebody else's API is the case that makes this
#: worth configuring: the size of the answer is not its author's to choose.
DEFAULT_OUTPUT_KB = 1024

#: The highest a script may be set to. Output is held in memory while it is
#: read, so this multiplied by MAX_CONCURRENT_RUNS is the worst case a node can
#: be asked to hold at once.
MAX_OUTPUT_KB = 16 * 1024
MIN_OUTPUT_KB = 1

#: How much of each stream the *run history* keeps, which is a different
#: question from what the caller is handed. History exists to be read by a
#: person debugging at two in the morning; the first 64 KB answers that, and
#: keeping megabytes per run of a script called every minute would make this
#: table the largest thing in the database.
MAX_STORED_CHARS = 64 * 1024

MIN_TIMEOUT_S = 1
MAX_TIMEOUT_S = 900

#: Slack between the host's own ``timeout`` and the deadline here. This one
#: only fires if the Docker daemon itself stops answering, since the host
#: enforces the real bound.
_GRACE_S = 20

#: Concurrent host runs across this control plane. A URL that starts a root
#: process is a URL that can be asked to start a thousand of them; this is what
#: makes that slow rather than fatal. Runs past it wait for a slot.
MAX_CONCURRENT_RUNS = 8

#: Where the payload lands *inside the toolbox container*, on its way through.
#: Not a temporary file on this machine and not one on the host either — the
#: toolbox is a scratch container whose filesystem holds nothing else, and the
#: run's directory is removed on the way out.
TOOLBOX_STAGING = "/tmp"  # noqa: S108

#: What ``timeout`` reports when it had to kill the program, and what this
#: answers 504 for.
#:
#: Two numbers because there are two ``timeout`` commands in the world. GNU
#: coreutils — the one on a Debian, Ubuntu or RHEL host — exits 124. busybox,
#: which is what an Alpine host has, exits 128+SIGTERM, so 143. A run that hit
#: its limit is the same event either way, and reporting it as "the script
#: failed for some reason" on half of all hosts would be a worse answer than
#: the small risk on the other side: a script that chooses to exit 143 on its
#: own is read as a timeout. Nothing but ``timeout`` signals this process.
TIMED_OUT = 124
TIMEOUT_CODES = frozenset({124, 143})

#: Used here for "the run never started" — mktemp failed, the payload did not
#: arrive, the host has no ``timeout``. Distinct from any exit code a script
#: chooses for itself only by convention, which is why the stderr that comes
#: with it is what the console actually shows.
NOT_STARTED = 127

_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
#: One bare command name resolved on the host's PATH, or one absolute path.
#: No spaces, so it is unambiguously a program and never a fragment of shell.
_INTERPRETER_RE = re.compile(r"^(?:[a-z][a-z0-9_.+-]{0,39}|/[A-Za-z0-9_./+-]{1,120})$")
_WORKING_DIR_RE = re.compile(r"^/[A-Za-z0-9_./+-]{0,255}$")
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

#: Set for every run, and refused as a name an operator may set, so that what a
#: script reads about its own invocation always came from Cubicle.
ENV_PREFIX = "CUBICLE_"


class ScriptError(RuntimeError):
    """Something the operator should read, in the console."""


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.match(name.strip())) and len(name.strip()) <= NAME_MAX


def valid_interpreter(value: str) -> bool:
    value = value.strip()
    return value == SHEBANG or bool(_INTERPRETER_RE.match(value))


def valid_working_dir(value: str) -> bool:
    """Blank means the run's own temporary directory, which always exists."""
    value = value.strip()
    return not value or bool(_WORKING_DIR_RE.match(value))


def clean_env(raw: dict[str, str]) -> dict[str, str]:
    """The operator's own variables, checked to be variables.

    A name that is not a name would either be dropped silently by the shell or
    change what the assignment means, and ``CUBICLE_`` is reserved so that a
    script can trust what it reads about its own invocation.
    """
    cleaned: dict[str, str] = {}
    for key, value in raw.items():
        name = key.strip()
        if not _ENV_KEY_RE.match(name):
            raise ScriptError(
                f"'{key}' is not an environment variable name — letters, digits "
                "and underscore, not starting with a digit."
            )
        if name.startswith(ENV_PREFIX):
            raise ScriptError(f"'{name}' is reserved: Cubicle sets the {ENV_PREFIX}* variables.")
        cleaned[name] = str(value)
    return cleaned


# ── the result of a run ──────────────────────────────────────────────────────


@dataclass(slots=True)
class Outcome:
    exit_code: int
    stdout: bytes
    stderr: bytes
    duration_ms: float
    truncated: bool
    #: The ceiling this run was given, so an error can name the number that
    #: has to change rather than saying "too big".
    limit_bytes: int = DEFAULT_OUTPUT_KB * 1024

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def timed_out(self) -> bool:
        return self.exit_code in TIMEOUT_CODES

    def stdout_text(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")

    def stderr_text(self) -> str:
        return self.stderr.decode("utf-8", errors="replace")


def interpret_output(text: str, mode: str) -> tuple[Any, str]:
    """What a program's stdout should be handed back as.

    ``auto`` is the useful default and the one that makes a script feel like a
    function: print JSON and the caller gets JSON, print anything else and the
    caller gets exactly the bytes that were printed. ``json`` is for a caller
    that must not be handed a plain-text surprise when the script fails halfway
    through printing, and says so by failing instead.

    Returns the decoded body and the media type to answer with; a body of
    ``None`` with ``application/json`` is the JSON-mode failure case, which the
    caller turns into an error rather than an empty document.
    """
    if mode == "text":
        return text, "text/plain"

    stripped = text.strip()
    if not stripped:
        # An empty document is not JSON, and a script that printed nothing
        # almost certainly meant "nothing", not "null".
        if mode == "auto":
            return "", "text/plain"
        return None, "application/json"

    try:
        return json.loads(stripped), "application/json"
    except ValueError:
        if mode == "json":
            return None, "application/json"
        return text, "text/plain"


# ── building the two programs ────────────────────────────────────────────────
#
# Two shells, one pipe. The outer one runs inside the toolbox container, where
# the payload was just unpacked; the inner one runs on the host, having entered
# its namespaces. `tar` across the pipe is what carries the script over that
# boundary, because a pipe is the one thing that crosses it unchanged.


def inner_program(*, interpreter: str, working_dir: str, timeout_s: int) -> str:
    """What the host's own shell runs, with the payload arriving on stdin."""
    if interpreter == SHEBANG:
        launch = [
            'chmod +x "$d/script" || exit 127',
            f'timeout -s TERM {timeout_s} "$d/script" < "$d/stdin"',
        ]
    else:
        launch = [
            f"timeout -s TERM {timeout_s} {shlex.quote(interpreter)} " '"$d/script" < "$d/stdin"'
        ]

    # A working directory that no longer exists is not worth failing a run
    # over: the run's own directory is always there, and the script is free to
    # notice where it is.
    where = f'cd {shlex.quote(working_dir)} 2>/dev/null || cd "$d"' if working_dir else 'cd "$d"'

    return "\n".join(
        [
            "set -u",
            f"d=$(mktemp -d /tmp/cubicle-run.XXXXXXXX) || exit {NOT_STARTED}",
            f'tar -C "$d" -xf - || {{ rm -rf "$d"; exit {NOT_STARTED}; }}',
            # Refused rather than run unbounded: this is a root process started
            # by an HTTP request, and the whole safety story is that something
            # ends it.
            "command -v timeout >/dev/null 2>&1 || {",
            '  echo "cubicle: this host has no timeout command, so a run cannot be'
            ' bounded — install coreutils" >&2',
            f'  rm -rf "$d"; exit {NOT_STARTED}',
            "}",
            where,
            *launch,
            "code=$?",
            'rm -rf "$d"',
            "exit $code",
        ]
    )


def outer_program(*, run_dir: str, inner: str) -> str:
    """What the toolbox container runs: feed the payload through ``nsenter``.

    The exit status of a pipeline in POSIX sh is the exit status of its last
    command — here ``nsenter``, which is the inner shell's, which is the
    script's. That is the whole reason this is a pipeline and not two steps.
    """
    quoted = shlex.quote(run_dir)
    return "\n".join(
        [
            f"cd {quoted} 2>/dev/null || exit {NOT_STARTED}",
            f"tar -cf - script stdin | nsenter -t 1 -m -u -i -n -p -- "
            f"/bin/sh -c {shlex.quote(inner)}",
            "code=$?",
            f"rm -rf {quoted}",
            "exit $code",
        ]
    )


def payload_tar(*, source: str, stdin: bytes, run_name: str) -> bytes:
    """The script and its stdin, as one archive to unpack in the toolbox.

    Mode 0700 on the script and 0600 on the body: both land in a directory on
    the host that only root can have put there, and neither is anybody else's
    to read while the run is in flight.
    """
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        directory = tarfile.TarInfo(run_name)
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o700
        tar.addfile(directory)

        for member_name, data, mode in (
            ("script", source.encode(), 0o700),
            ("stdin", stdin, 0o600),
        ):
            info = tarfile.TarInfo(f"{run_name}/{member_name}")
            info.size = len(data)
            info.mode = mode
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


# ── running one ──────────────────────────────────────────────────────────────

_slots: asyncio.Semaphore | None = None


def _limiter() -> asyncio.Semaphore:
    """Created on first use rather than at import: a semaphore made before
    there is a loop to run on is a subtle way to break under a test runner
    that makes its own.
    """
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(MAX_CONCURRENT_RUNS)
    return _slots


def _drain(sock: Any, limit: int) -> tuple[bytes, bytes, bool]:
    """Read the exec to EOF, keeping at most ``limit`` bytes of each stream.

    Reading continues past the ceiling on purpose. A program whose output is
    not being consumed blocks on the pipe, so abandoning the read early would
    turn a chatty script into a hung one that only the timeout ends.
    """
    streams: dict[int, bytearray] = {
        docker_socket.STDOUT: bytearray(),
        docker_socket.STDERR: bytearray(),
    }
    truncated = False

    for stream_id, chunk in docker_socket.frames_iter(sock, tty=False):
        kept = streams.get(stream_id)
        if kept is None:
            continue
        room = limit - len(kept)
        if room <= 0:
            truncated = True
            continue
        if len(chunk) > room:
            kept += chunk[:room]
            truncated = True
        else:
            kept += chunk

    return (
        bytes(streams[docker_socket.STDOUT]),
        bytes(streams[docker_socket.STDERR]),
        truncated,
    )


def _exit_code(client: docker.DockerClient, exec_id: str) -> int:
    """The exec's status once it has actually settled.

    EOF on the socket and the daemon recording an exit code are two different
    moments, usually microseconds apart and occasionally not.
    """
    for _ in range(50):
        info = client.api.exec_inspect(exec_id)
        if not info.get("Running"):
            code = info.get("ExitCode")
            return int(code) if code is not None else NOT_STARTED
        time.sleep(0.1)
    return NOT_STARTED


async def run(
    host: str,
    *,
    source: str,
    interpreter: str,
    env: dict[str, str],
    working_dir: str,
    timeout_s: int,
    stdin: bytes = b"",
    max_output_kb: int = DEFAULT_OUTPUT_KB,
) -> Outcome:
    """Run ``source`` on ``host`` and come back with what it printed.

    Never raises for a script that fails — a non-zero exit is an outcome, not
    an error. :class:`ScriptError` means the run could not be attempted at all.
    """
    if len(source.encode()) > MAX_SOURCE_BYTES:
        raise ScriptError(f"a script may be at most {MAX_SOURCE_BYTES // 1024} KB.")
    if not valid_interpreter(interpreter):
        raise ScriptError(f"'{interpreter}' is not an interpreter — one command name or path.")
    if not valid_working_dir(working_dir):
        raise ScriptError("a working directory must be an absolute path.")

    timeout_s = max(MIN_TIMEOUT_S, min(MAX_TIMEOUT_S, timeout_s))
    limit = max(MIN_OUTPUT_KB, min(MAX_OUTPUT_KB, max_output_kb)) * 1024

    try:
        await ensure_toolbox(host)
    except TerminalError as exc:
        raise ScriptError(str(exc)) from exc

    run_name = f"cubicle-run-{uuid.uuid4().hex[:12]}"
    archive = payload_tar(source=source, stdin=stdin, run_name=run_name)
    program = outer_program(
        run_dir=f"{TOOLBOX_STAGING}/{run_name}",
        inner=inner_program(interpreter=interpreter, working_dir=working_dir, timeout_s=timeout_s),
    )

    def _execute(client: docker.DockerClient) -> tuple[int, bytes, bytes, bool]:
        container = client.containers.get(TOOLBOX_NAME)
        if not client.api.put_archive(container.id, TOOLBOX_STAGING, archive):
            raise ScriptError("could not place the script on the node.")

        exec_id = client.api.exec_create(
            container.id,
            ["/bin/sh", "-c", program],
            stdin=False,
            stdout=True,
            stderr=True,
            tty=False,
            # nsenter does not scrub the environment it was given, so what is
            # set here is what the host process reads.
            environment=env,
        )["Id"]
        sock = client.api.exec_start(exec_id, tty=False, socket=True)
        try:
            stdout, stderr, truncated = _drain(sock, limit)
        finally:
            with contextlib.suppress(Exception):
                sock.close()
        return _exit_code(client, exec_id), stdout, stderr, truncated

    started = time.perf_counter()
    async with _limiter():
        try:
            client = await engines.client(host)
        except Exception as exc:  # noqa: BLE001 - surfaced to the operator as-is
            raise ScriptError(f"could not reach the node: {exc}") from exc

        try:
            with anyio.fail_after(timeout_s + _GRACE_S):
                # abandon_on_cancel: the thread is blocked on a socket read
                # that only the daemon can end. Waiting for it would mean the
                # deadline that exists for an unresponsive daemon is enforced
                # by asking that daemon to respond.
                code, stdout, stderr, truncated = await anyio.to_thread.run_sync(
                    partial(_execute, client), abandon_on_cancel=True
                )
        except TimeoutError:
            log.warning("host script run gave up on the engine", host=host, timeout_s=timeout_s)
            return Outcome(
                exit_code=TIMED_OUT,
                stdout=b"",
                stderr=b"cubicle: the node stopped answering while the script was running",
                duration_ms=(time.perf_counter() - started) * 1000,
                truncated=False,
                limit_bytes=limit,
            )
        except ScriptError:
            raise
        except DockerException as exc:
            raise ScriptError(f"could not run the script on this node: {exc}") from exc

    if truncated:
        log.warning(
            "host script output hit its limit and was cut",
            host=host,
            limit_kb=limit // 1024,
        )

    return Outcome(
        exit_code=code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=(time.perf_counter() - started) * 1000,
        truncated=truncated,
        limit_bytes=limit,
    )


# ── what is actually on the machine ──────────────────────────────────────────
#
# Only the assistant uses this, and only to stop guessing. A model asked to
# write a host script without it will reach for `apt-get` on an Alpine box,
# `python3.12` syntax on a host with 3.9, or `jq` on a machine that has never
# had it. Asking the machine costs one exec and removes a whole class of
# confidently wrong answers.

#: Commands worth knowing about before writing a script for this host. Short
#: on purpose: a roll call of everything in /usr/bin would cost more context
#: than it is worth, and these are the ones a script actually reaches for.
PROBED_COMMANDS = (
    "python3",
    "python",
    "bash",
    "node",
    "npm",
    "ruby",
    "perl",
    "php",
    "go",
    "docker",
    "systemctl",
    "service",
    "psql",
    "mysql",
    "redis-cli",
    "sqlite3",
    "git",
    "curl",
    "wget",
    "jq",
    "rsync",
    "tar",
    "zip",
    "openssl",
    "ffmpeg",
    "apt-get",
    "dnf",
    "yum",
    "apk",
    "pacman",
    "pip3",
    "crontab",
    "nginx",
)

#: Substituted by :func:`probe_source` rather than by ``%`` or ``str.format``:
#: this is shell, so it is full of ``%s`` that printf owns and ``${...}`` that
#: the shell owns, and both of Python's formatting operators would try to claim
#: them. A marker nothing else uses cannot be misread by either.
_COMMANDS_MARKER = "@@COMMANDS@@"

PROBE_TEMPLATE = """\
printf 'kernel=%s\\n' "$(uname -sr 2>/dev/null)"
printf 'arch=%s\\n' "$(uname -m 2>/dev/null)"
if [ -r /etc/os-release ]; then
  . /etc/os-release 2>/dev/null
  printf 'os=%s\\n' "${PRETTY_NAME:-$NAME}"
fi
printf 'shell=%s\\n' "$(readlink -f /bin/sh 2>/dev/null || echo /bin/sh)"
python3 -V 2>&1 | head -1 | sed 's/^/python=/'
node -v 2>/dev/null | head -1 | sed 's/^/node=/'
found=
for c in @@COMMANDS@@; do
  if command -v "$c" >/dev/null 2>&1; then found="$found $c"; fi
done
printf 'commands=%s\\n' "${found# }"
"""


def probe_source() -> str:
    return PROBE_TEMPLATE.replace(_COMMANDS_MARKER, " ".join(PROBED_COMMANDS))


#: How long a probe is reused. The answer changes when somebody installs
#: something, which is rare, and a stale answer for a few minutes is a far
#: smaller cost than an exec on every keystroke-driven request.
PROBE_TTL_S = 300.0

_probes: dict[str, tuple[float, dict[str, str]]] = {}


def parse_probe(text: str) -> dict[str, str]:
    """``key=value`` lines into a dict, ignoring anything that is not one."""
    facts: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if sep and key and value:
            facts[key] = value
    return facts


async def probe_host(host: str) -> dict[str, str]:
    """What this machine is and what it has, cached. Never raises.

    Best effort by design: the assistant is better off with a brief that says
    nothing about the host than with no answer at all, so a node that will not
    answer simply contributes nothing here.
    """
    cached = _probes.get(host)
    now = time.monotonic()
    if cached is not None and now - cached[0] < PROBE_TTL_S:
        return cached[1]

    try:
        outcome = await run(
            host,
            source=probe_source(),
            interpreter="sh",
            env={},
            working_dir="",
            timeout_s=15,
            max_output_kb=64,
        )
    except Exception as exc:  # noqa: BLE001 - "never raises" is the contract
        # Deliberately every exception, not just ScriptError. This exists to
        # enrich a prompt; there is no failure here worth turning into a failed
        # request, and a brief without host facts still produces an answer.
        log.warning("host probe failed", host=host, error=str(exc))
        return {}

    facts = parse_probe(outcome.stdout_text()) if outcome.ok else {}
    _probes[host] = (now, facts)
    return facts


def for_history(text: str, *, stream: str) -> str:
    """The part of a stream worth keeping in the database.

    Separate from the response limit on purpose. What a caller is handed has
    to be the whole answer or an error; what the console shows a person a week
    later only has to be enough to understand the run, and a megabyte of it
    per run would cost far more than it explains.
    """
    if len(text) <= MAX_STORED_CHARS:
        return text
    return (
        text[:MAX_STORED_CHARS]
        + f"\n\n… [{len(text)} characters of {stream}; the first "
        + f"{MAX_STORED_CHARS} are kept here]"
    )
