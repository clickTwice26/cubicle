"""Cluster resolution and addressing.

A request has to be attributed to exactly one cluster before anything else can
happen, and the answer must be the same whether it arrives from the console,
the CLI, or a caller invoking a function. Everything that decides "which
cluster" lives here so there is one rule rather than several.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Cluster

CLUSTER_HEADER = "x-cubicle-cluster"


class NoClusterError(RuntimeError):
    """The instance has no cluster yet — setup has not run."""


async def default_cluster(db: AsyncSession) -> Cluster:
    cluster = (
        await db.execute(select(Cluster).where(Cluster.is_default.is_(True)).limit(1))
    ).scalar_one_or_none()
    if cluster is None:
        cluster = (
            await db.execute(select(Cluster).order_by(Cluster.created_at).limit(1))
        ).scalar_one_or_none()
    if cluster is None:
        raise NoClusterError("this instance has no cluster")
    return cluster


async def by_reference(db: AsyncSession, ref: str) -> Cluster | None:
    """Look a cluster up by id or by slug — the console uses ids, humans slugs."""
    ref = ref.strip()
    if not ref:
        return None
    try:
        return await db.get(Cluster, uuid.UUID(ref))
    except ValueError:
        return (
            await db.execute(select(Cluster).where(Cluster.slug == ref.lower()))
        ).scalar_one_or_none()


async def by_domain(db: AsyncSession, host: str) -> Cluster | None:
    """Match the request's Host header against a cluster's own ingress domain."""
    hostname = host.split(":")[0].strip().lower()
    if not hostname:
        return None
    return (
        await db.execute(
            select(Cluster).where(Cluster.ingress_domain != "", Cluster.ingress_domain == hostname)
        )
    ).scalar_one_or_none()


async def count(db: AsyncSession) -> int:
    return len((await db.execute(select(Cluster.id))).scalars().all())


# ── addressing ───────────────────────────────────────────────────────────────


def _scheme() -> str:
    return "https" if settings.public_url.startswith("https://") else "http"


def cluster_root(cluster: Cluster) -> str:
    """The URL prefix every function in this cluster hangs off.

    A cluster with its own ingress domain owns that hostname outright, and the
    host already says which cluster it is — repeating the slug in the path
    would be noise.

    Otherwise the slug is always in the path, including for the default
    cluster. Letting the default one answer on a bare ``/<ns>/<fn>`` would mean
    the shape of a URL depended on which cluster happened to be default, so
    changing the default would quietly change what an existing URL addressed.
    """
    if cluster.ingress_domain:
        return f"{_scheme()}://{cluster.ingress_domain}"
    return f"{settings.public_url.rstrip('/')}/{cluster.slug}"


def function_url(cluster: Cluster, ns: str = "", name: str = "") -> str:
    root = cluster_root(cluster)
    if ns and name:
        return f"{root}/{ns}/{name}"
    if ns:
        return f"{root}/{ns}/"
    return root + "/"


def resource_suffix(cluster: Cluster) -> str:
    """Suffix for Docker names, so two clusters never fight over a container.

    Existing services keep whatever name is recorded on their row, so an
    install that predates multi-cluster is untouched by this.
    """
    return cluster.slug[:24]
