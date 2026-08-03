"""Installing a runtime image onto a node.

Cubicle's runtime images are not published anywhere, because each one has to
carry the agent. So installing a runtime means building it here, from the same
context the compose file uses, sent to the Docker daemon over the API. That
works identically for the local engine and for a node reached over TCP, which
is the reason it is done this way rather than by shelling out to `docker build`.

The build itself is mostly a download: the base image — `node:22-slim`,
`python:3.13-slim` — is the part an operator waits for. Everything on top is a
copy and a syntax check.
"""

from __future__ import annotations

import asyncio
import io
import tarfile
import time
from pathlib import Path

import docker
from docker.errors import DockerException, ImageNotFound

from .. import runtimes
from ..config import settings
from ..logging_setup import log
from .engine import LOCAL_HOST, engines


def _find_context_root() -> Path:
    """Where the runtime build contexts live.

    The API image carries them at a fixed path; a checkout has them beside the
    application. Both are supported so the same code runs either way.
    """
    packaged = Path("/opt/cubicle/runtime")
    if packaged.is_dir():
        return packaged
    # Running from a checkout rather than the image: walk up looking for the
    # sibling directory. Indexing `parents` directly raises inside the
    # container, where the path is only four deep.
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "services" / "runtime"
        if candidate.is_dir():
            return candidate
    return packaged


CONTEXT_ROOT = _find_context_root()

#: One install at a time per image. Two operators pressing the same button
#: should wait on one build, not race two.
_locks: dict[str, asyncio.Lock] = {}
#: image tag -> the build log so far, so progress survives a page reload.
_progress: dict[str, dict] = {}


class InstallError(RuntimeError):
    """The runtime could not be installed, and why."""


def context_root() -> Path:
    return CONTEXT_ROOT


def _tar_context(spec: runtimes.RuntimeSpec) -> bytes:
    """The runtime's build directory, as a tar the daemon can consume."""
    source = CONTEXT_ROOT / spec.context
    if not source.is_dir():
        raise InstallError(
            f"The build context for {spec.label} is missing from this image "
            f"({source}). Update the instance and try again."
        )

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for path in sorted(source.rglob("*")):
            if "__pycache__" in path.parts or path.name.endswith(".pyc"):
                continue
            tar.add(path, arcname=str(path.relative_to(source)))
    return buf.getvalue()


async def installed(host: str = LOCAL_HOST) -> set[str]:
    """Which runtime keys already have their image on this node."""

    def _run(client: docker.DockerClient) -> set[str]:
        found = set()
        for key in runtimes.RUNTIMES:
            tag = settings.runtime_image(key)
            try:
                client.images.get(tag)
                found.add(key)
            except (ImageNotFound, DockerException):
                continue
        return found

    try:
        return await engines.call(host, _run)
    except Exception as exc:  # noqa: BLE001 - an unreachable node knows nothing
        log.warning("could not list runtime images", host=host, error=str(exc))
        return set()


def progress(key: str) -> dict:
    return _progress.get(key, {"state": "idle", "log": "", "error": ""})


async def install(key: str, host: str = LOCAL_HOST) -> dict:
    """Build a runtime's image on a node, and report how it went.

    Idempotent: an image that is already present is reported as installed
    without a rebuild, so pressing the button twice costs nothing.
    """
    if key not in runtimes.RUNTIMES:
        raise InstallError(f"'{key}' is not a runtime this instance knows about.")

    spec = runtimes.RUNTIMES[key]
    tag = settings.runtime_image(key)
    lock = _locks.setdefault(key, asyncio.Lock())

    if lock.locked():
        raise InstallError(f"{spec.label} is already being installed.")

    async with lock:
        if key in await installed(host):
            _progress[key] = {"state": "installed", "log": "already installed", "error": ""}
            return _progress[key]

        context = _tar_context(spec)
        _progress[key] = {"state": "installing", "log": f"pulling {spec.base_image}…", "error": ""}
        started = time.perf_counter()

        def _build(client: docker.DockerClient) -> str:
            lines: list[str] = []
            stream = client.api.build(
                fileobj=io.BytesIO(context),
                custom_context=True,
                tag=tag,
                buildargs=spec.build_args,
                rm=True,
                forcerm=True,
                decode=True,
            )
            for chunk in stream:
                if "stream" in chunk:
                    text = chunk["stream"].strip()
                    if text:
                        lines.append(text)
                elif "error" in chunk:
                    lines.append(chunk["error"].strip())
                    raise InstallError(chunk["error"].strip())
                elif "status" in chunk:
                    lines.append(chunk["status"].strip())
                # The daemon streams a great deal; the tail is what is useful.
                if len(lines) > 400:
                    del lines[:200]
            return "\n".join(lines)

        try:
            output = await engines.call(host, _build)
        except InstallError as exc:
            _progress[key] = {"state": "failed", "log": _progress[key]["log"], "error": str(exc)}
            log.warning("runtime install failed", runtime=key, error=str(exc))
            return _progress[key]
        except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the operator
            _progress[key] = {"state": "failed", "log": "", "error": str(exc)}
            log.warning("runtime install failed", runtime=key, error=str(exc))
            return _progress[key]

        ms = int((time.perf_counter() - started) * 1000)
        _progress[key] = {"state": "installed", "log": output, "error": ""}
        log.info("runtime installed", runtime=key, image=tag, ms=ms)
        return _progress[key]


async def remove(key: str, host: str = LOCAL_HOST) -> None:
    """Drop a runtime's image from a node.

    Refused for a built-in: those come back on the next update anyway, and
    removing one takes every function written in it offline until it does.
    """
    if key not in runtimes.RUNTIMES:
        raise InstallError(f"'{key}' is not a runtime this instance knows about.")
    spec = runtimes.RUNTIMES[key]
    if spec.builtin:
        raise InstallError(
            f"{spec.label} ships with Cubicle and cannot be removed. "
            "It would return on the next update."
        )

    tag = settings.runtime_image(key)

    def _run(client: docker.DockerClient) -> None:
        try:
            client.images.remove(tag, force=False)
        except ImageNotFound:
            return
        except DockerException as exc:
            raise InstallError(str(exc)) from exc

    await engines.call(host, _run)
    _progress.pop(key, None)
    log.info("runtime image removed", runtime=key, image=tag)


def as_json(spec: runtimes.RuntimeSpec, *, is_installed: bool, in_use: int) -> dict:
    return {
        "key": spec.key,
        "label": spec.label,
        "language": spec.language,
        "image": settings.runtime_image(spec.key),
        "base_image": spec.base_image,
        "entry_file": spec.entry_file,
        "deps_file": spec.deps_file,
        "builtin": spec.builtin,
        "summary": spec.summary,
        "installed": is_installed,
        "functions": in_use,
        "state": progress(spec.key).get("state", "idle"),
    }


__all__ = ["InstallError", "as_json", "install", "installed", "progress", "remove"]
