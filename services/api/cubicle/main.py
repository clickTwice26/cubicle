"""Cubicle control plane."""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse, Response
from sqlalchemy import delete, select

from . import metrics
from .config import settings
from .db import engine, get_redis, session_scope
from .logging_setup import configure_logging, log
from .models import Cluster, Function, FunctionVersion, Group, LogEntry, Node
from .routers import ROUTERS
from .runtime.engine import EngineError
from .runtime.nodes import ensure_local_node
from .runtime.pool import pool

LOG_RETENTION_DAYS = 14


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("cubicle control plane starting", version=settings.version, url=settings.public_url)

    settings.data_dir.mkdir(parents=True, exist_ok=True)

    try:
        async with session_scope() as db:
            for cluster in (await db.execute(select(Cluster))).scalars().all():
                await ensure_local_node(db, cluster)
    except EngineError as exc:
        # The console still loads and explains the problem rather than 500ing.
        log.error("docker engine unavailable at boot", error=str(exc))

    await _adopt_isolates()
    task = asyncio.create_task(_reconcile_loop())

    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await pool.close()
        await get_redis().aclose()
        await engine.dispose()
        log.info("cubicle control plane stopped")


app = FastAPI(
    title="Cubicle",
    version=settings.version,
    summary="Self-hosted serverless functions — control plane API",
    description=(
        "Everything the console does is available here. The console is just "
        "another client of this API, and so is the `cubicle` CLI."
    ),
    default_response_class=ORJSONResponse,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

for router in ROUTERS:
    app.include_router(router)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    checks = {"database": False, "redis": False, "docker": False}
    try:
        async with session_scope() as db:
            await db.execute(select(1))
        checks["database"] = True
    except Exception:  # noqa: BLE001, S110 - the check result is the report
        pass
    with contextlib.suppress(Exception):
        checks["redis"] = bool(await get_redis().ping())
    try:
        from .runtime.engine import LOCAL_HOST, engines

        await engines.info(LOCAL_HOST)
        checks["docker"] = True
    except Exception:  # noqa: BLE001, S110 - the check result is the report
        pass

    healthy = checks["database"] and checks["redis"]
    return {
        "status": "ok" if healthy else "degraded",
        "version": settings.version,
        "checks": checks,
        "warm_isolates": pool.count(),
    }


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    metrics.WARM_ISOLATES.set(pool.count())
    return Response(metrics.render(), media_type="text/plain; version=0.0.4; charset=utf-8")


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError) -> ORJSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(p) for p in first.get("loc", ()) if p not in ("body", "query"))
    message = first.get("msg", "Invalid request.")
    message = message.removeprefix("Value error, ")
    return ORJSONResponse(
        {"detail": f"{field}: {message}" if field else message, "errors": exc.errors()},
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )


# ── background maintenance ───────────────────────────────────────────────────


async def _adopt_isolates() -> None:
    """Re-attach to isolates that survived a control-plane restart."""
    try:
        async with session_scope() as db:
            hosts = [n.docker_host for n in (await db.execute(select(Node))).scalars()]
            # Version -> who it belongs to. The container labels say the same
            # thing, but the database is the authority and covers isolates
            # started before a label existed.
            rows = (
                await db.execute(
                    select(Function, Group, Cluster)
                    .join(Group, Group.id == Function.group_id)
                    .join(Cluster, Cluster.id == Group.cluster_id)
                    .where(Function.current_version_id.isnot(None))
                )
            ).all()
            live = {
                str(fn.current_version_id): {
                    "cluster": cluster.slug,
                    "name": fn.name,
                    "namespace": group.ns,
                    "memory_mb": fn.memory_mb,
                }
                for fn, group, cluster in rows
            }
        if hosts:
            await pool.adopt(hosts=hosts, live_versions=live)
    except Exception:  # noqa: BLE001 - never block startup
        log.exception("could not adopt existing isolates")


async def _reconcile_loop() -> None:
    while True:
        try:
            await asyncio.sleep(settings.reconcile_interval)
            async with session_scope() as db:
                limits = {
                    str(fid): (lo, hi, ttl)
                    for fid, lo, hi, ttl in (
                        await db.execute(
                            select(
                                Function.id,
                                Function.min_instances,
                                Function.max_instances,
                                Function.idle_timeout_s,
                            )
                        )
                    ).all()
                }
            await pool.reap_idle(limits=limits)
            metrics.WARM_ISOLATES.set(pool.count())
            await _prune_logs()
            await _prune_versions()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the loop must survive anything
            log.exception("reconcile loop error")


async def _prune_logs() -> None:
    cutoff = datetime.now(UTC) - timedelta(days=LOG_RETENTION_DAYS)
    async with session_scope() as db:
        await db.execute(delete(LogEntry).where(LogEntry.ts < cutoff))


async def _prune_versions(keep: int = 10) -> None:
    """Keep the last few versions per function; older ones lose their volume."""
    from .runtime import builder

    async with session_scope() as db:
        function_ids = (await db.execute(select(Function.id))).scalars().all()
        for fid in function_ids:
            versions = (
                (
                    await db.execute(
                        select(FunctionVersion)
                        .where(FunctionVersion.function_id == fid)
                        .order_by(FunctionVersion.number.desc())
                    )
                )
                .scalars()
                .all()
            )
            for version in versions[keep:]:
                with contextlib.suppress(Exception):
                    await builder.remove_volume(
                        "unix:///var/run/docker.sock", builder.volume_name(str(fid), version.number)
                    )
                await db.delete(version)
