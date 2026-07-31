"""Creating, listing and retiring clusters.

Creating a cluster is cheap: a row, plus registering the local Docker engine
against it. It costs nothing until something is deployed into it, which is what
makes a throwaway ``staging`` or ``preview`` cluster reasonable.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from slugify import slugify
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .. import clusters as cluster_svc
from ..deps import CurrentPrincipal, DbSession, RequireAdmin, RequireOwner
from ..logging_setup import log
from ..models import Cluster, Function, Group, Node
from ..runtime import services as service_svc
from ..runtime.engine import EngineError
from ..runtime.nodes import ensure_local_node
from ..runtime.pool import pool
from ..schemas import RESERVED_NAMESPACES, ClusterCreate, ClusterOut, ClusterUpdate, validate_slug

router = APIRouter(prefix="/api/clusters", tags=["clusters"])


async def _serialize(db, cluster: Cluster) -> ClusterOut:
    nodes = (
        await db.execute(select(func.count(Node.id)).where(Node.cluster_id == cluster.id))
    ).scalar_one()
    namespaces = (
        await db.execute(select(func.count(Group.id)).where(Group.cluster_id == cluster.id))
    ).scalar_one()
    functions = (
        await db.execute(
            select(func.count(Function.id))
            .join(Group, Group.id == Function.group_id)
            .where(Group.cluster_id == cluster.id)
        )
    ).scalar_one()

    return ClusterOut(
        **{
            column.name: getattr(cluster, column.name)
            for column in cluster.__table__.columns
            if column.name in ClusterOut.model_fields
        },
        base_url=cluster_svc.function_url(cluster),
        node_count=nodes,
        namespace_count=namespaces,
        function_count=functions,
    )


@router.get("", response_model=list[ClusterOut])
async def list_clusters(db: DbSession, _: CurrentPrincipal):
    rows = (
        (await db.execute(select(Cluster).order_by(Cluster.is_default.desc(), Cluster.created_at)))
        .scalars()
        .all()
    )
    return [await _serialize(db, cluster) for cluster in rows]


@router.post("", response_model=ClusterOut, status_code=status.HTTP_201_CREATED)
async def create_cluster(payload: ClusterCreate, db: DbSession, principal: RequireAdmin):
    slug = payload.slug or slugify(payload.name)
    slug = validate_slug(slug, what="Cluster slug")
    if slug in RESERVED_NAMESPACES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"'{slug}' is reserved.")

    if payload.ingress_domain:
        clash = await cluster_svc.by_domain(db, payload.ingress_domain)
        if clash is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{payload.ingress_domain} already routes to '{clash.slug}'.",
            )

    cluster = Cluster(
        name=payload.name.strip(),
        slug=slug,
        ingress_domain=payload.ingress_domain,
        data_dir=payload.data_dir.strip() or "/var/lib/cubicle",
        kms_backend=payload.kms_backend,
        default_node_pool=payload.default_node_pool,
        description=payload.description.strip(),
        is_default=False,
    )
    db.add(cluster)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"'{slug}' is already in use.") from exc
    await db.refresh(cluster)

    # A new cluster is useless without somewhere to schedule, so it gets the
    # local engine registered against it just like the first one did.
    try:
        await ensure_local_node(db, cluster)
    except EngineError as exc:
        log.error("cluster created but the local engine is unreachable", error=str(exc))

    if payload.make_default:
        await _make_default(db, cluster)

    log.info("cluster created", slug=cluster.slug, by=principal.user.email)
    await db.refresh(cluster)
    return await _serialize(db, cluster)


@router.get("/{cluster_ref}", response_model=ClusterOut)
async def get_cluster(cluster_ref: str, db: DbSession, _: CurrentPrincipal):
    cluster = await cluster_svc.by_reference(db, cluster_ref)
    if cluster is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such cluster.")
    return await _serialize(db, cluster)


@router.patch("/{cluster_ref}", response_model=ClusterOut)
async def update_cluster(
    cluster_ref: str, payload: ClusterUpdate, db: DbSession, principal: RequireAdmin
):
    cluster = await cluster_svc.by_reference(db, cluster_ref)
    if cluster is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such cluster.")

    data = payload.model_dump(exclude_unset=True)
    if data.get("ingress_domain"):
        clash = await cluster_svc.by_domain(db, data["ingress_domain"])
        if clash is not None and clash.id != cluster.id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{data['ingress_domain']} already routes to '{clash.slug}'.",
            )

    for key, value in data.items():
        if value is not None:
            setattr(cluster, "name" if key == "name" else key, value)
    await db.commit()
    await db.refresh(cluster)
    log.info("cluster updated", slug=cluster.slug, by=principal.user.email, changed=list(data))
    return await _serialize(db, cluster)


@router.post("/{cluster_ref}/default", response_model=ClusterOut)
async def set_default(cluster_ref: str, db: DbSession, principal: RequireAdmin):
    cluster = await cluster_svc.by_reference(db, cluster_ref)
    if cluster is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such cluster.")
    await _make_default(db, cluster)
    log.info("default cluster changed", slug=cluster.slug, by=principal.user.email)
    return await _serialize(db, cluster)


@router.delete("/{cluster_ref}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cluster(cluster_ref: str, db: DbSession, principal: RequireOwner) -> Response:
    cluster = await cluster_svc.by_reference(db, cluster_ref)
    if cluster is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such cluster.")

    total = await cluster_svc.count(db)
    if total <= 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The instance must keep at least one cluster."
        )
    if cluster.is_default:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Make another cluster the default before deleting this one.",
        )

    # Stop everything this cluster is running before the rows disappear.
    functions = (
        (
            await db.execute(
                select(Function.id)
                .join(Group, Group.id == Function.group_id)
                .where(Group.cluster_id == cluster.id)
            )
        )
        .scalars()
        .all()
    )
    for function_id in functions:
        await pool.drain(function_id=str(function_id))

    for kind in ("postgres", "redis"):
        service = await service_svc.get_service(db, cluster.id, kind)
        if service is not None:
            await service_svc.destroy(db, service)

    await db.delete(cluster)
    await db.commit()
    log.info(
        "cluster deleted", slug=cluster.slug, functions=len(functions), by=principal.user.email
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _make_default(db, cluster: Cluster) -> None:
    rows = (await db.execute(select(Cluster))).scalars().all()
    for row in rows:
        row.is_default = row.id == cluster.id
    await db.commit()
