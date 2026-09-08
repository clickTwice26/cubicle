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
from .deps import CurrentPrincipal
from .logging_setup import configure_logging, log
from .models import Cluster, Function, FunctionVersion, Group, LogEntry, Node
from .routers import ROUTERS
from .runtime import scheduler
from .runtime.engine import EngineError
from .runtime.nodes import ensure_local_node
from .runtime.pool import pool

LOG_RETENTION_DAYS = 14


async def _certificate_loop() -> None:
    """Renew certificates this instance obtained, once a day.

    Only instances behind another web server have any: where Caddy owns the
    ports it renews its own, and this loop finds nothing to do.
    """
    from .routers.certificates import renew_due

    while True:
        await asyncio.sleep(24 * 60 * 60)
        try:
            await renew_due()
        except Exception as exc:  # noqa: BLE001 - a failed renewal is not fatal
            log.warning("certificate renewal pass failed", error=str(exc))


async def _publish_app_routes() -> None:
    """Rebuild the edge's application routing from the database, at every boot.

    The routing files are derived state: the database says which app owns which
    hostname and which token, and the fragments are only a rendering of that.
    Writing them solely when something changes leaves them missing after an
    upgrade that introduced a new one, or after anything that emptied the
    volume — the app is up, the console shows its address, and the edge has
    never heard of it.

    So it is reconciled once on the way up, which is the same reasoning that
    already has isolates adopted here rather than trusted.
    """
    try:
        from .routers.apps import republish_routes

        async with session_scope() as db:
            clusters = (await db.execute(select(Cluster))).scalars().all()
        for cluster in clusters:
            await republish_routes(cluster.id)
    except Exception as exc:  # noqa: BLE001 - the console must still come up
        log.warning("could not publish application routes at boot", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("cubicle control plane starting", version=settings.version, url=settings.public_url)

    # The session cookie is marked Secure from this one value, so an instance
    # serving real traffic with it left at the default hands out cookies a
    # browser will happily send over plain HTTP. Localhost is the exception
    # rather than the oversight, so it is not worth a warning.
    if not settings.secure_cookies and "localhost" not in settings.public_url:
        log.warning(
            "CUBICLE_PUBLIC_URL is not https, so session cookies are not marked Secure",
            public_url=settings.public_url,
        )

    settings.data_dir.mkdir(parents=True, exist_ok=True)

    try:
        async with session_scope() as db:
            for cluster in (await db.execute(select(Cluster))).scalars().all():
                await ensure_local_node(db, cluster)
    except EngineError as exc:
        # The console still loads and explains the problem rather than 500ing.
        log.error("docker engine unavailable at boot", error=str(exc))

    await _adopt_isolates()
    await _publish_app_routes()
    tasks = [
        asyncio.create_task(_reconcile_loop()),
        asyncio.create_task(_certificate_loop()),
        asyncio.create_task(scheduler.run_forever()),
    ]

    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
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
    # Both are unauthenticated by construction, so they are opt-in rather than
    # on: publishing the full administrative surface to anonymous callers is
    # reconnaissance handed over for free. Set CUBICLE_EXPOSE_API_DOCS=1 on an
    # instance that is not reachable from the internet.
    docs_url="/api/docs" if settings.expose_api_docs else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.expose_api_docs else None,
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
async def prometheus_metrics(_: CurrentPrincipal) -> Response:
    """Invocation volumes, error rates and warm isolate counts.

    Authenticated, unlike the convention for a metrics endpoint, because this
    one answers on the same public address as the console. A scraper should be
    given a read-only API key rather than the endpoint being opened up.
    """
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
