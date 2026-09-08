"""Building and running applications.

An app is a container the cluster keeps up, in contrast to a function, which is
an isolate the cluster keeps warm. The lifecycle here is deliberately the same
one a deploy has anywhere else: fetch the source, resolve a definition, build an
image, start the new containers, wait for them to answer, move the traffic, and
only then remove what was serving before. A deploy that fails at any step leaves
the previous release running and untouched.

The definition is ``cubicle.json`` at the root of the repository. A CapRover
``captain-definition`` is read too, because the two files say the same things
and a project that already has one should not need a second. When there is
neither, the tree is inspected: a Dockerfile is used as-is, and the common
JavaScript and static layouts are recognised well enough to build without one.
"""

from __future__ import annotations

import contextlib
import json
import re
import secrets
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio
import docker
from docker.errors import DockerException, NotFound

from ..config import settings
from ..db import get_redis
from ..logging_setup import log
from .engine import engines

BUILD_ROOT = settings.data_dir / "builds"
CLONE_TIMEOUT = 300
BUILD_LOG_TTL = 60 * 60 * 24 * 7
#: A build log is for reading, not for archiving a compiler's opinion of the
#: universe. Long ones are kept whole in Redis while they stream and trimmed
#: to this before they are written to the database.
MAX_LOG_CHARS = 200_000

DEFINITION_FILES = ("cubicle.json", "captain-definition")


class AppError(RuntimeError):
    """Something the operator should read, on the deploy page."""


@dataclass(slots=True)
class Source:
    path: Path
    commit_sha: str = ""
    commit_message: str = ""


@dataclass(slots=True)
class Definition:
    """The resolved build plan for one deploy."""

    dockerfile: str | None = None
    #: Set when the definition supplied the Dockerfile rather than the repo.
    dockerfile_body: str | None = None
    image: str = ""
    port: int = 3000
    env: dict[str, str] = field(default_factory=dict)
    build_args: dict[str, str] = field(default_factory=dict)
    health_path: str = ""
    detected: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


# ── naming ───────────────────────────────────────────────────────────────────


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", value.lower()).strip("-")[:40] or "app"


def container_name(cluster_slug: str, app_name: str, deployment: int, replica: int) -> str:
    return f"cubicle-app-{_slug(cluster_slug)}-{_slug(app_name)}-{deployment}-{replica}"


def container_prefix(cluster_slug: str, app_name: str) -> str:
    return f"cubicle-app-{_slug(cluster_slug)}-{_slug(app_name)}-"


def image_tag(cluster_slug: str, app_name: str, deployment: int) -> str:
    return f"cubicle/app-{_slug(cluster_slug)}-{_slug(app_name)}:{deployment}"


def volume_name(cluster_slug: str, app_name: str, path: str) -> str:
    leaf = _slug(path.strip("/").replace("/", "-")) or "data"
    return f"cubicle-appvol-{_slug(cluster_slug)}-{_slug(app_name)}-{leaf}"


# ── build log, streamed and kept ─────────────────────────────────────────────


def log_key(deployment_id: str) -> str:
    return f"cubicle:build:{deployment_id}"


async def append_log(deployment_id: str, *lines: str) -> None:
    """Push lines where the console can read them while the build runs."""
    clean = [line.rstrip() for line in lines if line and line.strip()]
    if not clean:
        return
    try:
        redis = get_redis()
        key = log_key(deployment_id)
        await redis.rpush(key, *clean)
        await redis.expire(key, BUILD_LOG_TTL)
    except Exception as exc:  # noqa: BLE001 - a log line must not fail a build
        log.debug("build log line dropped", error=str(exc))


async def read_log(deployment_id: str, start: int = 0) -> list[str]:
    try:
        raw = await get_redis().lrange(log_key(deployment_id), start, -1)
    except Exception:  # noqa: BLE001 - the database copy is the fallback
        return []
    return [item.decode() if isinstance(item, bytes) else str(item) for item in raw]


# ── the definition ───────────────────────────────────────────────────────────


def _read_definition_file(root: Path) -> dict[str, Any] | None:
    for name in DEFINITION_FILES:
        candidate = root / name
        if not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text())
        except (OSError, ValueError) as exc:
            raise AppError(f"{name} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise AppError(f"{name} must contain a JSON object")
        data["_source"] = name
        return data
    return None


def resolve_definition(root: Path, *, fallback_port: int = 3000) -> Definition:
    """What to build, from the repository's own definition or from its shape."""
    raw = _read_definition_file(root)
    if raw is not None:
        return _from_file(root, raw, fallback_port)

    detected = detect(root)
    if detected is None:
        raise AppError(
            "Could not work out how to build this repository. Add a Dockerfile, "
            "or a cubicle.json saying how to build it."
        )
    return detected


def _from_file(root: Path, raw: dict[str, Any], fallback_port: int) -> Definition:
    # captain-definition spells these the same way, which is the point.
    lines = raw.get("dockerfileLines")
    path = raw.get("dockerfilePath") or raw.get("dockerfile")
    image = raw.get("imageName") or raw.get("image") or ""

    supplied = [bool(lines), bool(path), bool(image)]
    if sum(supplied) > 1:
        raise AppError(
            "A definition sets exactly one of dockerfileLines, dockerfilePath or imageName."
        )

    definition = Definition(
        image=str(image),
        port=int(raw.get("port") or raw.get("containerHttpPort") or fallback_port),
        env={str(k): str(v) for k, v in (raw.get("env") or {}).items()},
        build_args={str(k): str(v) for k, v in (raw.get("buildArgs") or {}).items()},
        health_path=str(raw.get("healthCheckPath") or raw.get("healthPath") or ""),
        detected=str(raw.get("_source", "cubicle.json")),
        raw=raw,
    )

    if lines:
        if not isinstance(lines, list):
            raise AppError("dockerfileLines must be a list of strings")
        definition.dockerfile_body = "\n".join(str(line) for line in lines) + "\n"
        return definition

    if path:
        relative = str(path).lstrip("./")
        if ".." in Path(relative).parts:
            raise AppError("dockerfilePath must stay inside the repository")
        if not (root / relative).is_file():
            raise AppError(f"dockerfilePath points at {relative}, which is not in the repository")
        definition.dockerfile = relative
        return definition

    if image:
        return definition

    if (root / "Dockerfile").is_file():
        definition.dockerfile = "Dockerfile"
        return definition

    detected = detect(root)
    if detected is None:
        raise AppError(
            "The definition says neither how to build nor what image to run, and the "
            "repository has no Dockerfile."
        )
    detected.env = {**detected.env, **definition.env}
    detected.port = definition.port or detected.port
    detected.health_path = definition.health_path or detected.health_path
    detected.raw = raw
    return detected


def _package_json(root: Path) -> dict[str, Any]:
    try:
        return json.loads((root / "package.json").read_text())
    except (OSError, ValueError):
        return {}


def detect(root: Path) -> Definition | None:
    """Recognise the layouts that do not need a Dockerfile written by hand."""
    if (root / "Dockerfile").is_file():
        return Definition(dockerfile="Dockerfile", detected="Dockerfile")

    if (root / "package.json").is_file():
        package = _package_json(root)
        deps = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
        scripts = package.get("scripts", {})
        install = "npm ci" if (root / "package-lock.json").is_file() else "npm install"

        if "next" in deps:
            return Definition(
                dockerfile_body=_NEXT_DOCKERFILE.format(install=install),
                port=3000,
                detected="Next.js",
            )

        static_builders = {"vite", "react-scripts", "@angular/cli", "parcel", "webpack"}
        if "build" in scripts and deps.keys() & static_builders:
            out = next(
                (d for d in ("dist", "build", "out", "public") if (root / d).is_dir()), "dist"
            )
            return Definition(
                dockerfile_body=_STATIC_BUILD_DOCKERFILE.format(install=install, out=out),
                port=80,
                detected="static build (nginx)",
            )

        if "start" in scripts:
            return Definition(
                dockerfile_body=_NODE_DOCKERFILE.format(install=install),
                port=3000,
                detected="Node",
            )

    if (root / "index.html").is_file():
        return Definition(
            dockerfile_body=_STATIC_DOCKERFILE, port=80, detected="static site (nginx)"
        )

    if (root / "requirements.txt").is_file() and (root / "Procfile").is_file():
        command = _procfile_web(root)
        if command:
            return Definition(
                dockerfile_body=_PYTHON_DOCKERFILE.format(command=json.dumps(command.split())),
                port=8000,
                detected="Python (Procfile)",
            )
    return None


def _procfile_web(root: Path) -> str:
    for line in (root / "Procfile").read_text().splitlines():
        if line.strip().startswith("web:"):
            return line.split(":", 1)[1].strip()
    return ""


_NEXT_DOCKERFILE = """\
# Generated by Cubicle — Next.js
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN {install}

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000
COPY --from=build /app ./
EXPOSE 3000
CMD ["npm", "start"]
"""

_NODE_DOCKERFILE = """\
# Generated by Cubicle — Node
FROM node:22-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN {install}
COPY . .
ENV NODE_ENV=production PORT=3000
EXPOSE 3000
CMD ["npm", "start"]
"""

_STATIC_BUILD_DOCKERFILE = """\
# Generated by Cubicle — build, then serve the output
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN {install}
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/{out} /usr/share/nginx/html
EXPOSE 80
"""

_STATIC_DOCKERFILE = """\
# Generated by Cubicle — static site
FROM nginx:1.27-alpine
COPY . /usr/share/nginx/html
EXPOSE 80
"""

_PYTHON_DOCKERFILE = """\
# Generated by Cubicle — Python, command from the Procfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8000
EXPOSE 8000
CMD {command}
"""


# ── fetching source ──────────────────────────────────────────────────────────


def authenticated_url(repo_url: str, username: str, token: str) -> str:
    """Put credentials in the clone URL. Never logged, never persisted."""
    if not token or not repo_url.startswith("https://"):
        return repo_url
    return repo_url.replace("https://", f"https://{username or 'x-access-token'}:{token}@", 1)


def redact(text: str, *secrets: str) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "•••")
    return text


async def fetch_source(
    *, repo_url: str, branch: str, username: str, token: str, deployment_id: str
) -> Source:
    """Shallow-clone the branch into this deploy's own directory."""
    target = BUILD_ROOT / deployment_id
    await anyio.to_thread.run_sync(lambda: shutil.rmtree(target, ignore_errors=True))
    target.parent.mkdir(parents=True, exist_ok=True)

    url = authenticated_url(repo_url, username, token)

    def _clone() -> Source:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [
                "/usr/bin/git",
                "clone",
                "--depth",
                "1",
                "--single-branch",
                "--branch",
                branch,
                url,
                str(target),
            ],
            capture_output=True,
            text=True,
            timeout=CLONE_TIMEOUT,
            check=False,
        )
        if result.returncode != 0:
            raise AppError(redact(result.stderr.strip()[-800:] or "git clone failed", token, url))
        described = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["/usr/bin/git", "-C", str(target), "log", "-1", "--format=%H%n%s"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        sha, _, message = described.stdout.partition("\n")
        return Source(
            path=target,
            commit_sha=sha.strip()[:40],
            commit_message=message.strip()[:400],
        )

    try:
        return await anyio.to_thread.run_sync(_clone)
    except subprocess.TimeoutExpired as exc:
        raise AppError(f"git clone timed out after {CLONE_TIMEOUT}s") from exc


async def discard_source(deployment_id: str) -> None:
    target = BUILD_ROOT / deployment_id
    await anyio.to_thread.run_sync(lambda: shutil.rmtree(target, ignore_errors=True))


# ── building ─────────────────────────────────────────────────────────────────


async def build_image(
    *,
    host: str,
    source: Source,
    definition: Definition,
    tag: str,
    deployment_id: str,
) -> None:
    """Build the image, streaming the transcript as it goes."""
    dockerfile = definition.dockerfile or "Dockerfile.cubicle"
    if definition.dockerfile_body:
        (source.path / "Dockerfile.cubicle").write_text(definition.dockerfile_body)
        await append_log(
            deployment_id,
            f"$ using a generated Dockerfile ({definition.detected})",
            *[f"  {line}" for line in definition.dockerfile_body.strip().splitlines()],
        )
    else:
        await append_log(deployment_id, f"$ using {dockerfile} from the repository")

    await append_log(deployment_id, f"$ docker build -t {tag} .")

    def _build(client: docker.DockerClient) -> None:
        stream = client.api.build(
            path=str(source.path),
            dockerfile=dockerfile,
            tag=tag,
            rm=True,
            forcerm=True,
            pull=True,
            decode=True,
            buildargs=definition.build_args or None,
            labels={"cubicle.role": "app-image"},
        )
        pending: list[str] = []
        for chunk in stream:
            if "stream" in chunk:
                for line in str(chunk["stream"]).splitlines():
                    if line.strip():
                        pending.append(line.rstrip())
            elif "status" in chunk:
                pending.append(str(chunk["status"]))
            elif "error" in chunk:
                message = str(chunk["error"]).strip()
                if pending:
                    anyio.from_thread.run(append_log, deployment_id, *pending)
                anyio.from_thread.run(append_log, deployment_id, message)
                raise AppError(message[-1000:])
            # Flushing in batches keeps a chatty build from making one Redis
            # round trip per line without letting the console fall behind.
            if len(pending) >= 20:
                anyio.from_thread.run(append_log, deployment_id, *pending)
                pending = []
        if pending:
            anyio.from_thread.run(append_log, deployment_id, *pending)

    try:
        await engines.call(host, _build)
    except DockerException as exc:
        raise AppError(f"docker build failed: {exc}") from exc


async def pull_image(*, host: str, image: str, deployment_id: str) -> None:
    await append_log(deployment_id, f"$ docker pull {image}")

    def _pull(client: docker.DockerClient) -> None:
        client.images.pull(image)

    try:
        await engines.call(host, _pull)
    except DockerException as exc:
        raise AppError(f"could not pull {image}: {exc}") from exc


# ── running ──────────────────────────────────────────────────────────────────


async def start_replicas(
    *,
    host: str,
    cluster_slug: str,
    app_name: str,
    deployment: int,
    image: str,
    replicas: int,
    port: int,
    env: dict[str, str],
    memory_mb: int,
    cpus: float,
    volumes: list[dict],
    deployment_id: str,
) -> list[str]:
    """Start this release's containers. Returns their names."""
    await engines.ensure_network(host, settings.function_network)
    await engines.ensure_network(host, settings.edge_network)

    names = [container_name(cluster_slug, app_name, deployment, index) for index in range(replicas)]
    mounts = {
        volume_name(cluster_slug, app_name, entry.get("path", "/data")): {
            "bind": entry.get("path", "/data"),
            "mode": "rw",
        }
        for entry in volumes or []
    }

    def _start(client: docker.DockerClient) -> None:
        for name in names:
            _remove(client, name)
            for volume in mounts:
                try:
                    client.volumes.get(volume)
                except NotFound:
                    client.volumes.create(
                        name=volume, labels={"cubicle.role": "app-volume", "cubicle.app": app_name}
                    )
            container = client.containers.run(
                image,
                name=name,
                detach=True,
                environment={**env, "PORT": str(port)},
                labels={
                    "cubicle.role": "app",
                    "cubicle.app": app_name,
                    "cubicle.cluster": cluster_slug,
                    "cubicle.deployment": str(deployment),
                },
                network=settings.function_network,
                volumes=mounts or None,
                mem_limit=memory_mb * 1024**2,
                nano_cpus=int(max(0.1, cpus) * 1_000_000_000),
                restart_policy={"Name": "unless-stopped"},
            )
            # A stable alias on both networks: the edge reaches the container by
            # its unique name, while other apps reach the app by its own name
            # and keep working across deploys.
            client.networks.get(settings.function_network).disconnect(container)
            client.networks.get(settings.function_network).connect(
                container, aliases=[_slug(app_name)]
            )
            client.networks.get(settings.edge_network).connect(container, aliases=[_slug(app_name)])

    await append_log(
        deployment_id,
        f"$ starting {replicas} container{'' if replicas == 1 else 's'} on port {port}",
    )
    try:
        await engines.call(host, _start)
    except DockerException as exc:
        raise AppError(f"could not start the container: {exc}") from exc
    return names


async def wait_healthy(
    *,
    host: str,
    names: list[str],
    port: int,
    health_path: str,
    deployment_id: str,
    timeout: int = 90,  # noqa: ASYNC109 - a deploy step, not a cancellation scope
) -> None:
    """Give the release a chance to answer before it is given any traffic."""
    import httpx

    deadline = time.monotonic() + timeout
    target = names[0]
    probe = f"http://{target}:{port}{health_path or '/'}"
    await append_log(deployment_id, f"$ waiting for {target} to answer on {port}")

    last: str = ""
    while time.monotonic() < deadline:
        state = await _container_state(host, target)
        if state == "exited":
            tail = await tail_logs(host, target, lines=40)
            await append_log(deployment_id, "the container exited during startup:", *tail)
            raise AppError("the container exited during startup — see the build log")
        if state == "running":
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.get(probe)
                # Any answer proves the process is listening. Which status it
                # chose for "/" is the app's business, not a health signal —
                # unless a health path was configured, which is a promise.
                if not health_path or response.status_code < 400:
                    await append_log(
                        deployment_id, f"$ healthy ({response.status_code} from {probe})"
                    )
                    return
                last = f"{response.status_code} from {probe}"
            except Exception as exc:  # noqa: BLE001 - still starting up
                last = str(exc)
        await anyio.sleep(2)

    if health_path:
        raise AppError(f"the app did not become healthy within {timeout}s — last: {last}")
    # Without a health path a listening socket was never promised. A container
    # that is up and has not crashed is as much as can honestly be checked.
    if await _container_state(host, target) == "running":
        await append_log(deployment_id, "$ running (no health path set, nothing to probe)")
        return
    raise AppError(f"the app did not start within {timeout}s")


async def _container_state(host: str, name: str) -> str:
    def _state(client: docker.DockerClient) -> str:
        try:
            return str(client.containers.get(name).status)
        except NotFound:
            return "missing"

    try:
        return await engines.call(host, _state)
    except DockerException:
        return "unknown"


async def tail_logs(host: str, name: str, *, lines: int = 200) -> list[str]:
    def _logs(client: docker.DockerClient) -> list[str]:
        try:
            raw = client.containers.get(name).logs(tail=lines)
        except NotFound:
            return []
        return raw.decode("utf-8", "replace").splitlines()

    try:
        return await engines.call(host, _logs)
    except DockerException as exc:
        return [f"could not read logs: {exc}"]


async def logs_since(host: str, names: list[str], since: float, *, lines: int = 200) -> list[dict]:
    """Log lines from every replica, newest last, for the live tail."""

    def _read(client: docker.DockerClient) -> list[dict]:
        out: list[dict] = []
        for name in names:
            try:
                container = client.containers.get(name)
            except NotFound:
                continue
            raw = (
                container.logs(since=since, timestamps=True)
                if since
                else container.logs(tail=lines, timestamps=True)
            )
            replica = name.rsplit("-", 1)[-1]
            for line in raw.decode("utf-8", "replace").splitlines():
                stamp, _, text = line.partition(" ")
                out.append({"time": stamp, "replica": replica, "text": text})
        return out[-1000:]

    try:
        return await engines.call(host, _read)
    except DockerException as exc:
        return [{"time": "", "replica": "", "text": f"could not read logs: {exc}"}]


def _remove(client: docker.DockerClient, name: str) -> None:
    try:
        container = client.containers.get(name)
    except NotFound:
        return
    with contextlib.suppress(DockerException):  # already going away
        container.remove(force=True)


async def stop_containers(host: str, names: list[str]) -> None:
    def _stop(client: docker.DockerClient) -> None:
        for name in names:
            _remove(client, name)

    try:
        await engines.call(host, _stop)
    except DockerException as exc:
        log.warning("could not remove app containers", error=str(exc))


async def remove_other_deployments(
    host: str, cluster_slug: str, app_name: str, keep_deployment: int | None
) -> None:
    """Remove containers from every release except the one now serving."""
    prefix = container_prefix(cluster_slug, app_name)

    def _sweep(client: docker.DockerClient) -> list[str]:
        removed = []
        for container in client.containers.list(all=True, filters={"label": "cubicle.role=app"}):
            name = container.name
            if not name.startswith(prefix):
                continue
            number = container.labels.get("cubicle.deployment")
            if keep_deployment is not None and number == str(keep_deployment):
                continue
            try:
                container.remove(force=True)
                removed.append(name)
            except DockerException:
                pass
        return removed

    try:
        removed = await engines.call(host, _sweep)
        if removed:
            log.info("removed superseded app containers", app=app_name, count=len(removed))
    except DockerException as exc:
        log.warning("could not sweep old app containers", error=str(exc))


async def running_containers(host: str, cluster_slug: str, app_name: str) -> list[dict]:
    prefix = container_prefix(cluster_slug, app_name)

    def _list(client: docker.DockerClient) -> list[dict]:
        found = []
        for container in client.containers.list(all=True, filters={"label": "cubicle.role=app"}):
            if not container.name.startswith(prefix):
                continue
            found.append(
                {
                    "name": container.name,
                    "status": container.status,
                    "deployment": container.labels.get("cubicle.deployment", ""),
                    "started_at": container.attrs.get("State", {}).get("StartedAt", ""),
                }
            )
        return sorted(found, key=lambda row: row["name"])

    try:
        return await engines.call(host, _list)
    except DockerException:
        return []


async def destroy(host: str, cluster_slug: str, app_name: str, *, keep_volumes: bool) -> None:
    await remove_other_deployments(host, cluster_slug, app_name, keep_deployment=None)
    if keep_volumes:
        return

    def _volumes(client: docker.DockerClient) -> None:
        prefix = f"cubicle-appvol-{_slug(cluster_slug)}-{_slug(app_name)}-"
        for volume in client.volumes.list():
            if volume.name.startswith(prefix):
                with contextlib.suppress(DockerException):
                    volume.remove(force=True)

    try:
        await engines.call(host, _volumes)
    except DockerException as exc:
        log.warning("could not remove app volumes", error=str(exc))


def new_secret() -> str:
    return uuid.uuid4().hex


#: Unambiguous in a URL read aloud or copied out of a terminal: no look-alikes
#: and nothing that needs escaping.
TOKEN_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # noqa: S105 - an alphabet, not a secret


def new_path_token(length: int = 16) -> str:
    """The permanent path an app answers on. Assigned once, never rotated."""
    return "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(length))
