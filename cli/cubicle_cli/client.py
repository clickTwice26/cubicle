"""Transport, configuration and the helpers every command shares.

Standard library only, so `pipx install ./cli` pulls nothing else in and the
CLI works on an air-gapped jump host.

Modules under `commands/` import from here and from nowhere else in the
package. Everything a command is allowed to reach for is named in `__all__`,
and those signatures are fixed: several command modules are written against
them at once, so a change here breaks work that is already in flight.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__

CONFIG_PATH = Path(os.environ.get("CUBICLE_CONFIG", Path.home() / ".cubicle" / "config.toml"))
USER_AGENT = f"cubicle-cli/{__version__}"

#: Long enough for any call the control plane answers out of the database.
DEFAULT_TIMEOUT = 60.0

#: A deploy waits for the image build inside the request rather than handing
#: back a job to poll, and a cold `pip install` is minutes rather than seconds.
#: Timing out here would abandon a build that is going to succeed anyway.
BUILD_TIMEOUT = 900.0

#: Carried by every deploy whatever the language is. The other two files a
#: bundle holds depend on the runtime, hence `runtime_files`.
SHARED_FILES = ("cubicle.toml", "README.md")

#: The file layout of each language, mirroring RuntimeSpec.entry_file and
#: .deps_file in services/api/cubicle/runtimes.py. Keyed on the prefix of the
#: runtime key so that a runtime added upstream needs no change here.
LANGUAGE_FILES = {
    "python": ("handler.py", "requirements.txt"),
    "node": ("handler.js", "package.json"),
}

__all__ = [
    "BUILD_TIMEOUT",
    "CONFIG_PATH",
    "DEFAULT_TIMEOUT",
    "LANGUAGE_FILES",
    "SHARED_FILES",
    "USER_AGENT",
    "Call",
    "CubicleError",
    "Profile",
    "bounded",
    "build_id",
    "confirm",
    "confirmable",
    "deploy_files",
    "ensure_group",
    "env_key",
    "find_function",
    "find_group",
    "installed_commit",
    "list_runtimes",
    "load_profile",
    "paint",
    "poll",
    "record",
    "request",
    "runtime_files",
    "save_profile",
    "set_transport",
    "split_target",
    "stream",
    "table",
    "wait_for_version",
]


class CubicleError(RuntimeError):
    pass


def installed_commit() -> str:
    """The commit this copy was installed from, or "" when that is not knowable.

    There is no separate version for this program. The platform has one version
    string, shared by the API, the console and this, and it does not move
    between releases; what moves is the commit. pip records the resolved commit
    of a VCS install in `direct_url.json`, so an install from GitHub knows
    exactly what it is and can be compared against the branch head that the
    instance is already checking.

    A source checkout has no such record and returns "", because the answer
    there is `git log` and not this.
    """
    try:
        from importlib.metadata import Distribution

        raw = Distribution.from_name("cubicle-cli").read_text("direct_url.json")
        return json.loads(raw or "{}").get("vcs_info", {}).get("commit_id", "")
    except Exception:  # noqa: BLE001 - any failure here just means "not known"
        return ""


def build_id() -> str:
    """The version and the commit, which is what identifies a build."""
    commit = installed_commit()
    return f"{__version__} ({commit[:7]})" if commit else __version__


def normalise_url(url: str) -> str:
    """What someone typed, turned into something urllib will open.

    A bare hostname is what people type, and urllib answers it with
    ``ValueError: unknown url type``, raised from inside the request rather
    than from anything the CLI wrote, so it reaches the terminal as a
    traceback. Assume https, which is what any instance with a domain serves,
    and let a local install say http itself.
    """
    url = url.strip().rstrip("/")
    if not url:
        raise CubicleError("An instance URL is required, for example https://fn.example.com.")
    if "://" not in url:
        # localhost is the one place a missing scheme means http: an install
        # without a domain has no certificate to offer.
        host = url.split("/", 1)[0].split(":", 1)[0]
        scheme = "http" if host in ("localhost", "127.0.0.1", "::1") else "https"
        url = f"{scheme}://{url}"
    if not url.startswith(("http://", "https://")):
        scheme = url.split("://", 1)[0]
        raise CubicleError(f"{scheme}:// is not an instance URL. Use http:// or https://.")
    return url


@dataclass(slots=True)
class Profile:
    url: str
    token: str
    cluster: str | None = None

    @property
    def base(self) -> str:
        return normalise_url(self.url)


def load_profile(
    url: str | None = None, token: str | None = None, cluster: str | None = None
) -> Profile:
    url = url or os.environ.get("CUBICLE_URL")
    token = token or os.environ.get("CUBICLE_TOKEN")
    cluster = cluster or os.environ.get("CUBICLE_CLUSTER")
    if url and token:
        return Profile(url, token, cluster)

    if not CONFIG_PATH.exists():
        raise CubicleError(
            "Not signed in. Run `cubicle login <url>` first, or set CUBICLE_URL and CUBICLE_TOKEN."
        )
    data = tomllib.loads(CONFIG_PATH.read_text())
    profile = data.get("default", {})
    url = url or profile.get("url")
    token = token or profile.get("token")
    cluster = cluster or profile.get("cluster") or None
    if not url or not token:
        raise CubicleError(f"{CONFIG_PATH} is missing a url or token.")
    return Profile(url, token, cluster)


def save_profile(profile: Profile) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Written by `cubicle login`. Treat this file as a credential.",
        "[default]",
        f'url = "{profile.base}"',
        f'token = "{profile.token}"',
    ]
    if profile.cluster:
        lines.append(f'cluster = "{profile.cluster}"')
    CONFIG_PATH.write_text("\n".join(lines) + "\n")
    CONFIG_PATH.chmod(0o600)


# ── transport ────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Call:
    """One outbound call, as the transport sees it.

    Commands never build this themselves; it exists so a test can stand in for
    the network by inspecting a value rather than by patching urllib.
    """

    profile: Profile
    method: str
    path: str
    body: Any = None
    params: dict[str, Any] = field(default_factory=dict)
    raw: bool = False
    timeout: float = DEFAULT_TIMEOUT
    headers: dict[str, str] = field(default_factory=dict)


_send: Callable[[Call], Any] | None = None
_open_stream: Callable[[Call], Iterator[Any]] | None = None


def set_transport(
    send: Callable[[Call], Any] | None = None,
    open_stream: Callable[[Call], Iterator[Any]] | None = None,
) -> None:
    """Put a fake in front of the network, or restore the real one.

    Called with nothing it restores the sockets, so a test fixture tears down
    by calling it again with no arguments.
    """
    global _send, _open_stream
    _send = send
    _open_stream = open_stream


def request(
    profile: Profile,
    method: str,
    path: str,
    *,
    body: Any = None,
    params: dict[str, Any] | None = None,
    raw: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
) -> Any:
    """Perform one API call and return its decoded body.

    A non-2xx answer is raised as a CubicleError carrying the server's own
    message, which is what the top-level handler prints.
    """
    call = Call(
        profile=profile,
        method=method,
        path=path,
        body=body,
        params=params or {},
        raw=raw,
        timeout=timeout,
        headers=headers or {},
    )
    return (_send or _http_send)(call)


def stream(profile: Profile, path: str, *, params: dict[str, Any] | None = None) -> Iterator[Any]:
    """Yield the decoded payload of each server-sent event until interrupted."""
    call = Call(profile=profile, method="GET", path=path, params=params or {})
    return (_open_stream or _http_stream)(call)


def _url(call: Call) -> str:
    url = call.profile.base + call.path
    if call.params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in call.params.items() if v is not None})
    return url


def _headers(call: Call, accept: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {call.profile.token}",
        "Accept": accept,
        "User-Agent": USER_AGENT,
        # Omitted means "the instance default", which is what a single-cluster
        # install always wants.
        **({"X-Cubicle-Cluster": call.profile.cluster} if call.profile.cluster else {}),
        **call.headers,
    }


def _http_send(call: Call) -> Any:
    data = None
    request_headers = _headers(call, "application/json")
    if call.body is not None:
        data = json.dumps(call.body).encode()
        request_headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(  # noqa: S310 - the scheme comes from the saved profile
        _url(call), data=data, method=call.method, headers=request_headers
    )
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(  # noqa: S310
            req, timeout=call.timeout, context=context
        ) as response:
            payload = response.read()
            if call.raw:
                return payload
            if not payload:
                return None
            return json.loads(payload)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        try:
            parsed = json.loads(detail)
            message = parsed.get("detail") or parsed.get("message") or detail
            if isinstance(message, dict):
                message = message.get("message", str(message))
        except json.JSONDecodeError:
            message = detail or error.reason
        raise CubicleError(f"{error.code}: {message}") from None
    except urllib.error.URLError as error:
        raise CubicleError(f"Could not reach {call.profile.base}: {error.reason}") from None
    except (ValueError, OSError) as error:
        # urllib raises a bare ValueError for a URL it cannot parse, and that
        # is not a URLError, so without this it reaches the terminal as a
        # traceback. Nothing this layer can fail at is the user's fault in a
        # way a stack trace helps with.
        raise CubicleError(f"Could not reach {call.profile.base}: {error}") from None


def _http_stream(call: Call) -> Iterator[Any]:
    req = urllib.request.Request(  # noqa: S310 - the scheme comes from the saved profile
        _url(call), headers=_headers(call, "text/event-stream")
    )
    # No timeout: the server holds the connection open and sends a keep-alive
    # comment every fifteen seconds of silence, which is not a payload line.
    with urllib.request.urlopen(req, timeout=None) as response:  # noqa: S310
        for line in response:
            decoded = line.decode(errors="replace").strip()
            if decoded.startswith("data:"):
                try:
                    yield json.loads(decoded[5:].strip())
                except json.JSONDecodeError:
                    continue


# ── output helpers ───────────────────────────────────────────────────────────

TTY = sys.stdout.isatty()


def paint(text: str, colour: str) -> str:
    if not TTY:
        return text
    codes = {
        "green": "\033[38;5;154m",
        "red": "\033[31m",
        "yellow": "\033[33m",
        "blue": "\033[34m",
        "dim": "\033[2m",
        "bold": "\033[1m",
        # Fainter than dim, for rules and separators that should be structure
        # rather than content. 8 is the terminal's own grey, so it stays legible
        # on a light background as well as a dark one.
        "line": "\033[38;5;8m",
    }
    return f"{codes.get(colour, '')}{text}\033[0m"


#: Matches an ANSI escape so a coloured cell can be measured by what it prints
#: rather than by how many bytes it takes. Without this a single painted cell
#: shifts every column to its right by the width of the escape codes.
ANSI = re.compile(r"\033\[[0-9;]*m")

#: A cell is a number if it reads as one once the things people put around
#: numbers are taken off. Numbers belong on the right, where their digits line
#: up and a column can be scanned for the big one.
NUMERIC = re.compile(r"^[+-]?[\d,]+(\.\d+)?\s*(%|ms|s|m|h|d|B|KB|MB|GB|TB|/\S+)?$")


def visible(text: str) -> int:
    """How wide a string prints, ignoring colour."""
    return len(ANSI.sub("", str(text)))


def _pad(cell: str, width: int, *, right: bool) -> str:
    gap = " " * max(0, width - visible(cell))
    return gap + str(cell) if right else str(cell) + gap


def table(headers: list[str], rows: list[list[str]], *, indent: str = "  ") -> str:
    """The CLI's one table.

    Three spaces between columns rather than two: at two, a short value in a
    wide column reads as though it belongs to its neighbour. Numeric columns
    are right-aligned so the digits line up, and the header rule gives the eye
    somewhere to start on a long listing.
    """
    if not rows:
        return paint(f"{indent}(nothing to show)", "dim")

    columns = len(headers)
    widths = [max(visible(headers[i]), *(visible(row[i]) for row in rows)) for i in range(columns)]

    def is_number(cell: str) -> bool | None:
        """True, False, or None for a cell that should not get a vote.

        A column of durations with one dash in it is still a column of
        durations, so the placeholders every command uses for "nothing yet" are
        ignored rather than counted as text.
        """
        text = ANSI.sub("", str(cell)).strip()
        if text in ("", "-", "—", "n/a", "never"):
            return None
        return bool(NUMERIC.match(text))

    right = []
    for i in range(columns):
        votes = [v for v in (is_number(row[i]) for row in rows) if v is not None]
        right.append(bool(votes) and all(votes))

    gutter = "   "
    head = gutter.join(
        paint(_pad(headers[i].upper(), widths[i], right=right[i]), "dim") for i in range(columns)
    )
    rule = gutter.join(paint("─" * widths[i], "line") for i in range(columns))
    lines = [indent + head, indent + rule]
    for row in rows:
        lines.append(
            indent + gutter.join(_pad(row[i], widths[i], right=right[i]) for i in range(columns))
        )
    # Padding the last column leaves trailing spaces on every line, which show
    # up when the output is selected, piped into a diff, or pasted anywhere.
    return "\n".join(line.rstrip() for line in lines)


def record(rows: Sequence[tuple[str, str]], *, label_width: int = 16) -> str:
    """Render one object as the CLI's label/value block.

    This is the shape `cubicle status` has always printed: an upper-case label
    in a fixed column so the values line up down the page. Like `table` it
    returns a string with no surrounding blank lines, because the caller owns
    the frame.
    """
    if not rows:
        return paint("  (nothing to show)", "dim")
    width = max(label_width, *(len(label) for label, _ in rows)) + 2
    return "\n".join(
        f"  {paint(label.upper().ljust(width), 'dim')}{value}" for label, value in rows
    )


# ── shared helpers ───────────────────────────────────────────────────────────


def split_target(target: str) -> tuple[str, str]:
    """Split the `<namespace>/<function>` argument every command accepts."""
    if "/" not in target:
        raise CubicleError("Use <namespace>/<function>, for example payments/create-charge.")
    namespace, name = target.split("/", 1)
    return namespace.strip("/"), name.strip("/")


def env_key(key: str) -> str:
    """A variable or a secret name as the API stores it.

    EnvVarIn and SecretIn upper-case the name and replace everything that is
    not a letter, a digit or an underscore, so `stripe-key` is written down as
    STRIPE_KEY. A delete names the row in the URL path rather than in a body,
    so the same rule has to be applied here or the request goes looking for a
    key nobody wrote: the env endpoint answers that with a 404 and the secrets
    endpoint used to answer it with silence. Normalising here is also what
    keeps the path free of anything that would need escaping.
    """
    return re.sub(r"[^A-Z0-9_]", "_", key.strip().upper())


def bounded(value: int, flag: str, low: int, high: int) -> int:
    """A number the API would accept, refused here when it would not.

    Sending it anyway costs a round trip and comes back as FastAPI's list of
    validation errors, which names the field by its schema name rather than by
    the flag that was typed.
    """
    if not low <= value <= high:
        raise CubicleError(f"{flag} takes {low} to {high}, and {value} is outside that.")
    return value


def find_function(profile: Profile, target: str) -> dict:
    """Resolve `<namespace>/<function>` to the function record.

    The API addresses functions by UUID and people do not, so every command
    that takes a function starts here. The listing is the only endpoint that
    maps a name to an id, and it is cluster-scoped, so this also fails with a
    useful message when the profile is pointed at the wrong cluster.
    """
    namespace, name = split_target(target)
    for fn in request(profile, "GET", "/api/functions"):
        if fn["namespace"] == namespace and fn["name"] == name:
            return fn
    raise CubicleError(f"No function at {namespace}/{name}.")


def find_group(profile: Profile, namespace: str) -> dict:
    """Resolve a namespace slug to the group record, for its id."""
    for group in request(profile, "GET", "/api/groups"):
        if group["ns"] == namespace:
            return group
    raise CubicleError(f"No namespace {namespace} in this cluster.")


def ensure_group(profile: Profile, namespace: str) -> tuple[dict, bool]:
    """The group for a namespace, creating it if this cluster has none.

    Returns the record and whether it had to be created, so the caller can say
    so in its own words rather than have a helper print for it.
    """
    try:
        return find_group(profile, namespace), False
    except CubicleError:
        return request(profile, "POST", "/api/groups", body={"name": namespace}), True


def list_runtimes(profile: Profile) -> list[dict]:
    """Every runtime this instance knows, installed or not.

    The instance is the authority on what can be run here; the CLI hardcoding
    a list is what made `--runtime node22` impossible for a year.
    """
    return request(profile, "GET", "/api/runtimes")


def runtime_files(
    runtime: str, *, catalogue: list[dict] | None = None, profile: Profile | None = None
) -> tuple[str, str]:
    """The entry file and dependency file a runtime reads.

    A key we already understand costs no round trip, which is why `deploy` can
    bundle a Node function without asking. Anything unfamiliar is looked up on
    the instance, which is the only place that truly knows.
    """
    for spec in catalogue or ():
        if spec.get("key") == runtime:
            return spec["entry_file"], spec["deps_file"]
    for prefix, files in LANGUAGE_FILES.items():
        if runtime.startswith(prefix):
            return files
    if profile is not None:
        return runtime_files(runtime, catalogue=list_runtimes(profile))
    raise CubicleError(f"No file layout known for the {runtime} runtime.")


def deploy_files(
    runtime: str, *, catalogue: list[dict] | None = None, profile: Profile | None = None
) -> tuple[str, ...]:
    """The filenames a deploy of this runtime carries, entry file first.

    A deploy merges onto the previous version server-side, so sending the
    wrong language's files does not replace them, it adds them and the build
    then fails on a bundle nobody wrote.
    """
    entry, deps = runtime_files(runtime, catalogue=catalogue, profile=profile)
    return (entry, deps, *SHARED_FILES)


def confirmable() -> argparse.ArgumentParser:
    """A parent parser that gives one command its own --yes.

    --yes is also a global flag, so `cubicle --yes rm ns/fn` has always worked,
    but argparse hands everything after the command name to the subparser and a
    subparser that has never heard of --yes rejects it outright. That is the
    spelling the refusal below tells people to type, so both positions have to
    mean the same thing.

    The default is SUPPRESS rather than False because a subparser copies its
    whole finished namespace over the outer one, and a False default here would
    erase a --yes that was typed before the command name.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Answer this command's confirmation with yes.",
    )
    return parser


def confirm(question: str, *, assume_yes: bool = False) -> bool:
    """Ask before something destructive, unless --yes said not to.

    A pipe has nobody to answer, so rather than block forever or assume the
    dangerous thing, this refuses and names the flag that would have allowed
    it.
    """
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise CubicleError(f"{question} There is no terminal to ask; pass --yes to go ahead.")
    try:
        answer = input(f"  {question} [y/N] ")
    except EOFError:
        # ctrl-d is the end of the input, which is nothing typed, which is the
        # same answer as a bare return. A traceback is not an answer at all.
        return False
    return answer.strip().lower() in {"y", "yes"}


def poll(
    probe: Callable[[], Any],
    *,
    done: Callable[[Any], bool],
    timeout: float = 300.0,
    interval: float = 2.0,
) -> Any:
    """Call `probe` until `done` accepts its result, then return that result.

    Several endpoints answer before the work is finished: creating a function
    and installing from the marketplace both build in the background, and
    applying an update restarts the control plane underneath us. Deliberately
    silent and un-animated, because the output of a command that is waiting
    should be the same whether or not anyone is watching it.
    """
    deadline = time.monotonic() + timeout
    while True:
        result = probe()
        if done(result):
            return result
        if time.monotonic() >= deadline:
            raise CubicleError(f"Still not finished after {timeout:.0f}s. Check the console.")
        time.sleep(interval)


def wait_for_version(
    profile: Profile, function_id: str, *, timeout: float = 300.0, interval: float = 2.0
) -> dict:
    """Wait for a function's current version to stop being pending.

    Returns the function record, whose `version_status` is then `ready` or
    `failed`; the caller decides which of those is bad news.
    """
    return poll(
        lambda: request(profile, "GET", f"/api/functions/{function_id}"),
        done=lambda fn: fn.get("version_status") in {"ready", "failed"},
        timeout=timeout,
        interval=interval,
    )
