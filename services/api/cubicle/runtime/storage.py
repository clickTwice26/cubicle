"""What a cluster's volumes actually occupy.

Memory and CPU are known from what the platform allocated — it decided those
numbers, so it can add them up. Disk is not: a volume grows because a function
wrote to it, and only the engine knows how far. So this asks Docker.

Attribution is by name rather than by label. A cluster's volumes are its data
services' (recorded on the service row) and one per deployed function version
(named deterministically from the function id and version number), and both are
derivable from the database — which means volumes created before any of this
existed are attributed correctly too, rather than only new ones.
"""

from __future__ import annotations

import docker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_setup import log
from ..models import Function, FunctionVersion, Group, ManagedService
from .builder import volume_name
from .engine import LOCAL_HOST, engines


async def cluster_volumes(db: AsyncSession, cluster_id) -> set[str]:
    """Every volume name this cluster owns, from the database."""
    names: set[str] = set()

    services = (
        (
            await db.execute(
                select(ManagedService.volume_name).where(
                    ManagedService.cluster_id == cluster_id,
                    ManagedService.volume_name != "",
                )
            )
        )
        .scalars()
        .all()
    )
    names.update(services)

    versions = (
        await db.execute(
            select(FunctionVersion.function_id, FunctionVersion.number)
            .join(Function, Function.id == FunctionVersion.function_id)
            .join(Group, Group.id == Function.group_id)
            .where(Group.cluster_id == cluster_id)
        )
    ).all()
    for function_id, number in versions:
        names.add(volume_name(function_id, number))

    return names


async def sizes(host: str = LOCAL_HOST) -> dict[str, int]:
    """Every volume on a node and what it occupies, in bytes.

    One `df` for the whole node rather than a call per volume: the engine walks
    the filesystem to answer this, and asking once for everything is the
    difference between a page that loads and one that does not.
    """

    def _run(client: docker.DockerClient) -> dict[str, int]:
        found: dict[str, int] = {}
        for volume in (client.df() or {}).get("Volumes") or []:
            usage = volume.get("UsageData") or {}
            size = usage.get("Size", -1)
            # -1 means the engine did not compute it. Reporting that as zero
            # would read as "empty", which is a different claim entirely.
            if size is not None and size >= 0:
                found[volume.get("Name", "")] = int(size)
        return found

    try:
        return await engines.call(host, _run)
    except Exception as exc:  # noqa: BLE001 - a node that will not answer is not fatal
        log.warning("could not measure volume sizes", host=host, error=str(exc))
        return {}


async def used_bytes(db: AsyncSession, cluster_id, host: str = LOCAL_HOST) -> int:
    """How much disk this cluster's volumes hold right now."""
    owned = await cluster_volumes(db, cluster_id)
    if not owned:
        return 0
    measured = await sizes(host)
    return sum(size for name, size in measured.items() if name in owned)
