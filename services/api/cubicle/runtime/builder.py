"""Deploy-time build.

A deploy writes the source into a fresh Docker volume, installs the function's
dependencies into ``/srv/.deps`` inside it, and marks the version ready. The
volume is then mounted read-only by every isolate for that version, which
means:

* isolates never see another function's code,
* a rebuilt version is atomic — old isolates keep serving until the swap,
* a remote node can run the same version by building on that node.

Nothing here touches the host filesystem, so the same code path works for the
local engine and for a Docker engine reached over TCP.
"""

from __future__ import annotations

import contextlib
import io
import json
import tarfile
import time
from dataclasses import dataclass

import docker
from docker.errors import DockerException, NotFound

from .. import runtimes
from ..config import settings
from ..logging_setup import log
from .engine import engines

BUILD_LABEL = "cubicle.role"
SRV = "/srv"


@dataclass(slots=True)
class BuildResult:
    ok: bool
    log: str
    duration_ms: int
    volume: str


def volume_name(function_id: str, version_number: int) -> str:
    return f"cubicle-fn-{str(function_id).replace('-', '')[:12]}-v{version_number}"


def _tar_bytes(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mode = 0o644
            info.mtime = int(time.time())
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _install_command(spec, files: dict[str, str]) -> str | None:
    """How this runtime installs dependencies, or None if there are none.

    Both land in ``/srv/.deps``: Python because that is what the isolate puts on
    PYTHONPATH, JavaScript because npm resolves upwards from the handler and
    finds ``/srv/node_modules`` — which is a symlink into .deps, so one rule
    about where a build writes covers both.
    """
    body = files.get(spec.deps_file, "")
    if not body.strip():
        return None

    if spec.deps_file == "requirements.txt":
        if not any(line.strip() and not line.strip().startswith("#") for line in body.splitlines()):
            return None
        return (
            f"python -m pip install --no-cache-dir --disable-pip-version-check "
            f"-r {SRV}/requirements.txt -t {SRV}/.deps 2>&1"
        )

    if spec.deps_file == "package.json":
        try:
            declared = json.loads(body).get("dependencies") or {}
        except (TypeError, ValueError):
            # A package.json that will not parse is a build error worth showing,
            # not a reason to silently skip the install.
            return "echo 'package.json is not valid JSON' >&2; exit 1"
        if not declared:
            return None
        return (
            f"cd {SRV} && npm install --omit=dev --no-audit --no-fund --loglevel=error 2>&1 "
            f"&& mkdir -p {SRV}/.deps && ln -sfn {SRV}/node_modules {SRV}/.deps/node_modules"
        )

    return None


def _build_sync(
    client: docker.DockerClient,
    *,
    image: str,
    volume: str,
    files: dict[str, str],
    install: str | None,
    label: str,
    timeout: int,
) -> BuildResult:
    started = time.perf_counter()
    output: list[str] = []
    container = None

    try:
        with contextlib.suppress(NotFound):
            client.volumes.get(volume).remove(force=True)
        client.volumes.create(name=volume, labels={BUILD_LABEL: "function-volume"})

        container = client.containers.create(
            image=image,
            command=["sleep", str(timeout)],
            entrypoint=[""],
            user="root",
            labels={BUILD_LABEL: "build"},
            volumes={volume: {"bind": SRV, "mode": "rw"}},
            working_dir=SRV,
            network_disabled=not install,
            network=settings.function_network if install else None,
            mem_limit="1g",
            detach=True,
        )
        container.start()

        # Copying into a *running* container lands inside the mounted volume.
        container.put_archive(SRV, _tar_bytes(files))
        output.append(
            f"bundled        {len(files)} files · {sum(len(f) for f in files.values())} B"
        )

        code, out = container.exec_run(
            ["sh", "-lc", f"mkdir -p {SRV}/.deps && chmod -R a+rX {SRV}"], user="root"
        )
        if code != 0:
            output.append(out.decode(errors="replace"))
            return BuildResult(False, "\n".join(output), _ms(started), volume)

        if install:
            output.append(f"installing     {label}")
            code, out = container.exec_run(["sh", "-lc", install], user="root")
            text = out.decode(errors="replace").strip()
            output.append(_tail(text, 120))
            if code != 0:
                output.append(f"\nbuild failed   install exited {code}")
                return BuildResult(False, "\n".join(output), _ms(started), volume)
        else:
            output.append("installing     no dependencies declared, skipped")

        container.exec_run(["sh", "-lc", f"chmod -R a+rX {SRV}"], user="root")
        output.append("ready          volume " + volume)
        return BuildResult(True, "\n".join(output), _ms(started), volume)

    except DockerException as exc:
        output.append(f"build failed   {exc}")
        return BuildResult(False, "\n".join(output), _ms(started), volume)
    finally:
        if container is not None:
            with contextlib.suppress(DockerException):
                container.remove(force=True)


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _tail(text: str, lines: int) -> str:
    parts = text.splitlines()
    if len(parts) <= lines:
        return text
    return "…\n" + "\n".join(parts[-lines:])


async def build_version(
    *,
    host: str,
    runtime: str,
    function_id: str,
    version_number: int,
    files: dict[str, str],
) -> BuildResult:
    spec = runtimes.get(runtime)
    image = settings.runtime_image(runtime)
    volume = volume_name(function_id, version_number)
    install = _install_command(spec, files)
    verb = "pip install -r" if spec.deps_file == "requirements.txt" else "npm install from"
    label = f"{verb} {spec.deps_file}"

    if install:
        await engines.ensure_network(host, settings.function_network)

    log.info(
        "building function version",
        function=function_id,
        version=version_number,
        runtime=runtime,
        install=bool(install),
        image=image,
    )
    result = await engines.call(
        host,
        _build_sync,
        image=image,
        volume=volume,
        files=files,
        install=install,
        label=label,
        timeout=settings.build_timeout,
    )
    log.info(
        "build finished",
        function=function_id,
        version=version_number,
        ok=result.ok,
        ms=result.duration_ms,
    )
    return result


async def remove_volume(host: str, volume: str) -> None:
    def _remove(client: docker.DockerClient) -> None:
        try:
            client.volumes.get(volume).remove(force=True)
        except NotFound:
            return
        except DockerException as exc:
            log.warning("could not remove volume", volume=volume, error=str(exc))

    await engines.call(host, _remove)
