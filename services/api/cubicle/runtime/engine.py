"""Docker engine access.

A Cubicle "node" is a Docker engine: the local one by default, plus any
additional engines registered in Settings (``tcp://host:2376`` with client
certificates). Every runtime operation goes through this module so that adding
a node is the only thing multi-node scheduling needs.

docker-py is synchronous, so every call is pushed to a worker thread.
"""

from __future__ import annotations

import contextlib
import threading
from dataclasses import dataclass
from typing import Any

import anyio
import docker
from docker.errors import DockerException

from ..config import settings
from ..logging_setup import log

LOCAL_HOST = "unix:///var/run/docker.sock"

# What Docker reports vs what everyone actually calls the architecture.
ARCH_NAMES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}


@dataclass(slots=True)
class EngineInfo:
    name: str
    cpus: int
    memory_bytes: int
    arch: str
    engine_version: str
    os: str


class EngineError(RuntimeError):
    pass


class EnginePool:
    """Caches one docker-py client per node, keyed by its Docker host URL."""

    def __init__(self) -> None:
        self._clients: dict[str, docker.DockerClient] = {}
        self._lock = threading.Lock()

    def _client_sync(self, host: str) -> docker.DockerClient:
        with self._lock:
            client = self._clients.get(host)
            if client is not None:
                return client
            try:
                if host in ("", LOCAL_HOST):
                    client = docker.DockerClient(base_url=LOCAL_HOST, timeout=60)
                else:
                    tls = host.startswith("tcp://") and settings.data_dir.joinpath("certs").exists()
                    kwargs: dict[str, Any] = {"base_url": host, "timeout": 60}
                    if tls:
                        certs = settings.data_dir / "certs"
                        kwargs["tls"] = docker.tls.TLSConfig(
                            client_cert=(str(certs / "cert.pem"), str(certs / "key.pem")),
                            ca_cert=str(certs / "ca.pem"),
                            verify=True,
                        )
                    client = docker.DockerClient(**kwargs)
                client.ping()
            except DockerException as exc:
                raise EngineError(
                    f"cannot reach Docker engine at {host or 'local socket'}: {exc}"
                ) from exc
            self._clients[host] = client
            return client

    async def client(self, host: str = LOCAL_HOST) -> docker.DockerClient:
        return await anyio.to_thread.run_sync(self._client_sync, host)

    async def call(self, host: str, fn, *args, **kwargs):
        client = await self.client(host)

        def _run():
            return fn(client, *args, **kwargs)

        return await anyio.to_thread.run_sync(_run)

    def forget(self, host: str) -> None:
        with self._lock:
            client = self._clients.pop(host, None)
        if client is not None:
            with contextlib.suppress(Exception):  # closing is best effort
                client.close()

    async def info(self, host: str = LOCAL_HOST) -> EngineInfo:
        def _info(client: docker.DockerClient) -> EngineInfo:
            data = client.info()
            version = client.version()
            return EngineInfo(
                name=str(data.get("Name", "node-01")),
                cpus=int(data.get("NCPU", 0) or 0),
                memory_bytes=int(data.get("MemTotal", 0) or 0),
                arch=ARCH_NAMES.get(
                    str(data.get("Architecture", "")), str(data.get("Architecture", "unknown"))
                ),
                engine_version=str(version.get("Version", "")),
                os=str(data.get("OperatingSystem", "")),
            )

        return await self.call(host, _info)

    async def ensure_network(self, host: str, name: str) -> None:
        def _ensure(client: docker.DockerClient) -> None:
            try:
                client.networks.get(name)
            except docker.errors.NotFound:
                log.info("creating function network", network=name, host=host)
                client.networks.create(name, driver="bridge", check_duplicate=True)

        await self.call(host, _ensure)

    async def image_present(self, host: str, image: str) -> bool:
        def _check(client: docker.DockerClient) -> bool:
            try:
                client.images.get(image)
            except docker.errors.ImageNotFound:
                return False
            return True

        return await self.call(host, _check)


engines = EnginePool()
