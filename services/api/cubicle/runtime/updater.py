"""Check whether the deployed checkout is behind the repository, and catch it up.

A container cannot rebuild itself: `docker compose up --build` stops the very
process issuing it. So updating happens in a separate one-shot container that
outlives the restart, and the console reads its progress from that container's
logs afterwards.

That container mounts the checkout at *the same absolute path it has on the
host*. Compose resolves relative bind mounts — `./deploy/caddy/Caddyfile` — into
paths it hands to the daemon, and the daemon resolves them on the host. Mounted
anywhere else, every one of those would point at nothing.
"""

from __future__ import annotations

import asyncio
import re
import socket
import time
from dataclasses import dataclass

import docker
import httpx
from docker.errors import DockerException, NotFound

from ..logging_setup import log
from .engine import LOCAL_HOST, engines

#: Kept out of the compose project deliberately: `compose up` must not consider
#: the container running it to be one of the things it is allowed to replace.
UPDATER_NAME = "cubicle-updater"
UPDATER_IMAGE = "alpine:3.20"

#: GitHub allows 60 unauthenticated calls an hour per address, and the console
#: asks on every visit to Settings. One answer for fifteen minutes is plenty to
#: notice a push, and leaves the budget alone.
CACHE_SECONDS = 900

_cache: tuple[float, dict] | None = None
_lock = asyncio.Lock()

# Dumps everything needed to resolve HEAD in one pass, so the parsing happens
# here in Python rather than in a shell script nobody can test.
_READ_SCRIPT = """
cd /repo/.git 2>/dev/null || exit 1
echo "<<HEAD"; cat HEAD 2>/dev/null
echo "<<PACKED"; cat packed-refs 2>/dev/null
echo "<<CONFIG"; cat config 2>/dev/null
echo "<<REFS"
for f in $(find refs/heads -type f 2>/dev/null); do echo "$f $(cat $f)"; done
"""

# `--ff-only` rather than `reset --hard`: an operator who edited a file locally
# gets a loud refusal instead of losing the edit. Untracked files are ignored,
# because .env is untracked and every install has one.
_UPDATE_SCRIPT = """
set -eu
echo "==> preparing"
apk add --no-cache git docker-cli docker-cli-compose >/dev/null 2>&1
git config --global --add safe.directory "$WORKDIR"
cd "$WORKDIR"

echo "==> at $(git rev-parse --short HEAD)"
git fetch --prune origin "$BRANCH"

if [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/$BRANCH)" ]; then
  echo "==> already up to date"
  exit 0
fi

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "!! the checkout has local changes to tracked files."
  echo "!! refusing to overwrite them - commit or discard them first."
  exit 2
fi

echo "==> updating to $(git rev-parse --short origin/$BRANCH)"
git merge --ff-only "origin/$BRANCH"

echo "==> rebuilding and restarting"
docker compose -p "$PROJECT" up -d --build

echo "==> done"
"""


@dataclass
class Deployment:
    """Where this instance was installed from, according to its own container."""

    workdir: str
    project: str


class UpdateError(RuntimeError):
    """The instance cannot be updated from here, and why."""


def _deployment_sync(client: docker.DockerClient) -> Deployment:
    try:
        me = client.containers.get(socket.gethostname())
    except (NotFound, DockerException) as exc:
        raise UpdateError(
            "This container cannot identify itself to Docker, so it cannot find "
            "the checkout it was built from."
        ) from exc

    labels = me.labels or {}
    workdir = labels.get("com.docker.compose.project.working_dir", "")
    project = labels.get("com.docker.compose.project", "")
    if not workdir or not project:
        raise UpdateError(
            "This instance was not started by Docker Compose, so there is no "
            "checkout to update. Update it the way you deployed it."
        )
    return Deployment(workdir=workdir, project=project)


def _parse_repo(dump: str) -> dict:
    """Resolve HEAD and the origin remote out of raw git files."""
    sections: dict[str, str] = {}
    current = ""
    for line in dump.splitlines():
        if line.startswith("<<"):
            current = line[2:]
            sections[current] = ""
        elif current:
            sections[current] += line + "\n"

    head = sections.get("HEAD", "").strip()
    branch, sha = "", ""

    if head.startswith("ref: "):
        ref = head[5:].strip()
        branch = ref.rsplit("/", 1)[-1]
        for line in sections.get("REFS", "").splitlines():
            path, _, value = line.partition(" ")
            if path.strip() == ref:
                sha = value.strip()
        if not sha:  # the ref may have been packed away
            for line in sections.get("PACKED", "").splitlines():
                packed_sha, _, packed_ref = line.partition(" ")
                if packed_ref.strip() == ref:
                    sha = packed_sha.strip()
    elif re.fullmatch(r"[0-9a-f]{40}", head):
        sha, branch = head, "(detached)"

    url = ""
    in_origin = False
    for line in sections.get("CONFIG", "").splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_origin = stripped.replace('"', "").startswith("[remote origin]")
        elif in_origin and stripped.startswith("url"):
            url = stripped.split("=", 1)[-1].strip()

    return {"sha": sha, "branch": branch, "remote_url": url, "repo": _slug(url)}


def _slug(url: str) -> str:
    """`owner/name` for a GitHub remote, in either of the two URL shapes."""
    match = re.search(r"github\.com[:/]+([^/]+)/(.+?)(?:\.git)?/?$", url or "")
    return f"{match.group(1)}/{match.group(2)}" if match else ""


async def _read_repo(deployment: Deployment) -> dict:
    def _run(client: docker.DockerClient) -> str:
        output = client.containers.run(
            UPDATER_IMAGE,
            command=["sh", "-c", _READ_SCRIPT],
            volumes={deployment.workdir: {"bind": "/repo", "mode": "ro"}},
            remove=True,
            network_disabled=True,
        )
        return output.decode(errors="replace")

    return _parse_repo(await engines.call(LOCAL_HOST, _run))


async def _remote_head(repo: str, branch: str) -> dict:
    """The tip of `branch` on GitHub, unauthenticated."""
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"https://api.github.com/repos/{repo}/branches/{branch}",
            headers={"Accept": "application/vnd.github+json"},
        )
    if response.status_code == 404:
        raise UpdateError(
            f"GitHub has no branch '{branch}' in {repo}, or the repository is private."
        )
    if response.status_code == 403:
        raise UpdateError("GitHub is rate-limiting this address. Try again in a few minutes.")
    response.raise_for_status()

    commit = response.json().get("commit", {})
    detail = commit.get("commit", {})
    return {
        "sha": commit.get("sha", ""),
        "message": (detail.get("message") or "").split("\n")[0],
        "author": (detail.get("author") or {}).get("name", ""),
        "date": (detail.get("author") or {}).get("date", ""),
    }


async def status(*, force: bool = False) -> dict:
    """What is deployed, what is on the branch, and whether they differ."""
    global _cache

    async with _lock:
        if not force and _cache and time.monotonic() - _cache[0] < CACHE_SECONDS:
            return {**_cache[1], "cached": True}

        result = await _collect()
        _cache = (time.monotonic(), result)
        return {**result, "cached": False}


async def _collect() -> dict:
    base = {
        "current": "",
        "latest": "",
        "branch": "",
        "repo": "",
        "available": False,
        "message": "",
        "author": "",
        "date": "",
        "error": "",
    }
    try:
        deployment = await engines.call(LOCAL_HOST, _deployment_sync)
        local = await _read_repo(deployment)
    except UpdateError as exc:
        return {**base, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - the console shows this, not a 500
        log.warning("could not read the local checkout", error=str(exc))
        return {**base, "error": f"Could not read the checkout: {exc}"}

    base |= {
        "current": local["sha"],
        "branch": local["branch"],
        "repo": local["repo"],
    }
    if not local["sha"]:
        return {**base, "error": "The checkout has no resolvable HEAD commit."}
    if not local["repo"]:
        return {
            **base,
            "error": (
                "This checkout's origin is not a GitHub repository, so there is "
                "nothing to check against."
            ),
        }

    try:
        remote = await _remote_head(local["repo"], local["branch"])
    except UpdateError as exc:
        return {**base, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - offline is not a server error
        return {**base, "error": f"Could not reach GitHub: {exc}"}

    return {
        **base,
        "latest": remote["sha"],
        "available": bool(remote["sha"]) and remote["sha"] != local["sha"],
        "message": remote["message"],
        "author": remote["author"],
        "date": remote["date"],
    }


async def start() -> None:
    """Launch the one-shot container that pulls and rebuilds."""

    def _run(client: docker.DockerClient) -> None:
        deployment = _deployment_sync(client)

        existing = client.containers.list(all=True, filters={"name": UPDATER_NAME})
        for container in existing:
            if container.status == "running":
                raise UpdateError("An update is already running.")
            container.remove(force=True)

        client.containers.run(
            UPDATER_IMAGE,
            command=["sh", "-c", _UPDATE_SCRIPT],
            name=UPDATER_NAME,
            detach=True,
            environment={
                "WORKDIR": deployment.workdir,
                "PROJECT": deployment.project,
                "BRANCH": "main",
            },
            # The same absolute path as the host, so compose's relative bind
            # mounts resolve to directories that actually exist over there.
            volumes={
                deployment.workdir: {"bind": deployment.workdir, "mode": "rw"},
                "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
            },
            labels={"cubicle.role": "updater"},
        )

    await engines.call(LOCAL_HOST, _run)
    log.info("update started")


async def progress() -> dict:
    """The updater's state and output, readable after this container restarts."""

    def _run(client: docker.DockerClient) -> dict:
        try:
            container = client.containers.get(UPDATER_NAME)
        except NotFound:
            return {"state": "idle", "logs": "", "exit_code": None}

        container.reload()
        exit_code = (container.attrs.get("State") or {}).get("ExitCode")
        running = container.status == "running"
        logs = container.logs(tail=200).decode(errors="replace")

        if running:
            state = "running"
        elif exit_code == 0:
            state = "success"
        else:
            state = "failed"
        return {"state": state, "logs": logs, "exit_code": None if running else exit_code}

    return await engines.call(LOCAL_HOST, _run)
