"""Cluster and metering: nodes, resource usage, chargeback and cost comparison."""

from __future__ import annotations

import csv
import io
import uuid

import docker
from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, select

from .. import analytics, pricing
from ..deps import CurrentCluster, CurrentPrincipal, DbSession, RequireAdmin
from ..logging_setup import log
from ..models import Invocation, Node
from ..runtime.engine import LOCAL_HOST, EngineError, engines
from ..runtime.nodes import allocation_by_node, format_spec, refresh_nodes, register_node
from ..runtime.pool import pool
from ..schemas import NodeCreate, NodeOut

router = APIRouter(prefix="/api/cluster", tags=["cluster"])


async def _node(db, node_id: uuid.UUID, cluster) -> Node:
    """A node lookup that cannot reach into another cluster."""
    node = (
        await db.execute(select(Node).where(Node.id == node_id, Node.cluster_id == cluster.id))
    ).scalar_one_or_none()
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such node in this cluster.")
    return node


@router.get("/nodes", response_model=list[NodeOut])
async def list_nodes(db: DbSession, cluster: CurrentCluster, _: CurrentPrincipal):
    nodes = await refresh_nodes(db, cluster)
    load = allocation_by_node()
    result = []
    for node in nodes:
        placed = load.get(node.name, {})
        memory_mb = placed.get("memory_mb", 0.0)
        total_mb = (node.memory_bytes or 0) / 1024**2 or 1
        result.append(
            NodeOut(
                **{
                    c.name: getattr(node, c.name)
                    for c in node.__table__.columns
                    if c.name in NodeOut.model_fields
                },
                spec=format_spec(node),
                cpu_allocated_pct=round(
                    min(100.0, (placed.get("cpus", 0.0) / (node.cpus or 1)) * 100), 1
                ),
                memory_allocated_pct=round(min(100.0, memory_mb / total_mb * 100), 1),
                memory_label=f"{memory_mb / 1024:.1f} / {total_mb / 1024:.0f} GB",
                isolates=int(placed.get("isolates", 0)),
            )
        )
    return result


@router.post("/nodes", response_model=NodeOut, status_code=status.HTTP_201_CREATED)
async def add_node(payload: NodeCreate, db: DbSession, cluster: CurrentCluster, _: RequireAdmin):
    existing = (
        await db.execute(
            select(Node).where(Node.cluster_id == cluster.id, Node.name == payload.name)
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{cluster.name} already has a node called that."
        )
    try:
        node = await register_node(
            db,
            cluster,
            name=payload.name,
            docker_host=payload.docker_host,
            pool_name=payload.pool,
        )
    except EngineError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return NodeOut(
        **{
            c.name: getattr(node, c.name)
            for c in node.__table__.columns
            if c.name in NodeOut.model_fields
        },
        spec=format_spec(node),
        memory_label=f"0.0 / {(node.memory_bytes or 0) / 1024**3:.0f} GB",
    )


@router.post("/nodes/{node_id}/drain")
async def drain_node(node_id: uuid.UUID, db: DbSession, cluster: CurrentCluster, _: RequireAdmin):
    node = await _node(db, node_id, cluster)
    node.schedulable = False
    node.status = "draining"
    await db.commit()
    log.info("node draining", node=node.name)
    return {"name": node.name, "status": node.status}


@router.post("/nodes/{node_id}/resume")
async def resume_node(node_id: uuid.UUID, db: DbSession, cluster: CurrentCluster, _: RequireAdmin):
    node = await _node(db, node_id, cluster)
    node.schedulable = True
    node.status = "ready"
    await db.commit()
    return {"name": node.name, "status": node.status}


@router.delete("/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_node(
    node_id: uuid.UUID, db: DbSession, cluster: CurrentCluster, _: RequireAdmin
) -> Response:
    node = await _node(db, node_id, cluster)
    if node.is_local:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "The local engine cannot be removed from the cluster."
        )
    engines.forget(node.docker_host)
    await db.delete(node)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/isolates")
async def list_isolates(_: CurrentPrincipal):
    return {"count": pool.count(), "isolates": pool.snapshot()}


# ── metering ─────────────────────────────────────────────────────────────────


@router.get("/metering")
async def metering(db: DbSession, cluster: CurrentCluster, _: CurrentPrincipal):
    start, end, progress = analytics.month_window()

    totals = (
        await db.execute(
            select(
                func.count(Invocation.id),
                func.sum(Invocation.gb_seconds),
                func.sum(Invocation.egress_bytes),
            ).where(
                Invocation.cluster_id == cluster.id,
                Invocation.ts >= start,
                Invocation.ts < end,
            )
        )
    ).one()
    invocations = int(totals[0] or 0)
    gb_seconds = float(totals[1] or 0.0)
    egress_bytes = int(totals[2] or 0)

    namespaces = await analytics.namespace_usage(db, start, end, cluster.id)
    storage = await _storage_bytes()

    return {
        "cluster": cluster.slug,
        "window_start": start,
        "window_end": end,
        "window_progress": round(progress * 100, 1),
        "invocations": invocations,
        "invocations_label": f"{invocations:,}",
        "gb_seconds": round(gb_seconds, 2),
        "gb_seconds_label": f"{gb_seconds:,.1f}",
        "egress_bytes": egress_bytes,
        "egress_label": analytics.fmt_bytes(egress_bytes),
        "storage_bytes": storage,
        "storage_label": analytics.fmt_bytes(storage),
        "namespaces": namespaces,
        "warm_isolates": pool.count(),
        "cost": pricing.comparison(
            requests=invocations, gb_seconds=gb_seconds, egress_bytes=egress_bytes
        ),
    }


@router.get("/metering/export.csv")
async def export_metering(db: DbSession, cluster: CurrentCluster, _: CurrentPrincipal) -> Response:
    start, end, _progress = analytics.month_window()
    namespaces = await analytics.namespace_usage(db, start, end, cluster.id)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["cluster", "namespace", "invocations", "gb_seconds", "window_start", "window_end"]
    )
    for row in namespaces:
        writer.writerow(
            [
                cluster.slug,
                row["name"],
                row["invocations"],
                f"{row['gb_seconds']:.4f}",
                start.date().isoformat(),
                end.date().isoformat(),
            ]
        )
    filename = f"cubicle-{cluster.slug}-metering-{start:%Y-%m}.csv"
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _storage_bytes() -> int:
    """Disk used by function version volumes and managed service volumes."""

    def _df(client: docker.DockerClient) -> int:
        try:
            data = client.df()
        except docker.errors.APIError:
            return 0
        total = 0
        for volume in data.get("Volumes") or []:
            name = volume.get("Name", "")
            if not name.startswith("cubicle-"):
                continue
            total += int((volume.get("UsageData") or {}).get("Size", 0) or 0)
        return max(total, 0)

    try:
        return await engines.call(LOCAL_HOST, _df)
    except Exception:  # noqa: BLE001 - storage is informational
        return 0
