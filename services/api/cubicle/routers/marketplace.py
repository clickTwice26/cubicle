"""Browsing the community marketplace, and installing from it."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Query
from fastapi import status as http
from sqlalchemy.exc import IntegrityError

from .. import marketplace, runtimes
from ..config import settings
from ..deps import CurrentCluster, CurrentPrincipal, DbSession, RequireDeveloper
from ..logging_setup import log
from ..models import Function, FunctionVersion
from ..runtime import images
from ..schemas import MarketplaceInstall, validate_slug
from .functions import _build_and_activate, _detail, _load_group

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])


@router.get("", response_model=dict)
async def browse(_: CurrentPrincipal, url: str | None = Query(default=None)):
    """Everything a registry lists, plus which runtimes are here to run it.

    The registry is read live rather than cached: it is one small file, and an
    operator who just published something should see it on the next visit
    rather than in fifteen minutes.
    """
    try:
        source, listings = await marketplace.index(url)
    except marketplace.MarketplaceError as exc:
        raise HTTPException(http.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    present = await images.installed()
    return {
        "registry": source,
        "is_default": (url or settings.marketplace_url) == settings.marketplace_url,
        "packages": [
            {**listing.as_json(), "runtime_installed": listing.runtime in present}
            for listing in listings
        ],
    }


@router.get("/package", response_model=dict)
async def show(_: CurrentPrincipal, url: str = Query(...)):
    """One package in full, including its source, before anything is created.

    Installing runs this code on your cluster, so the console shows every line
    of it first. That is the whole reason this endpoint returns the files.
    """
    try:
        package = await marketplace.package(url)
    except marketplace.MarketplaceError as exc:
        raise HTTPException(http.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    present = await images.installed()
    return {
        **package.as_json(),
        "runtime_installed": package.runtime in present,
        "source_url": url,
    }


@router.post("/install", response_model=dict, status_code=http.HTTP_201_CREATED)
async def install(
    payload: MarketplaceInstall,
    db: DbSession,
    cluster: CurrentCluster,
    _: RequireDeveloper,
):
    """Create a function in one of your namespaces from a published package.

    The package is fetched again here rather than taken from the browser: what
    was shown for review is not necessarily what a request body claims it was,
    and the source that gets built should be the source the registry serves.
    """
    group = await _load_group(db, payload.group_id, cluster)
    if group is None:
        raise HTTPException(http.HTTP_404_NOT_FOUND, "No such namespace.")

    try:
        package = await marketplace.package(payload.url)
    except marketplace.MarketplaceError as exc:
        raise HTTPException(http.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    if package.runtime not in await images.installed():
        spec = runtimes.get(package.runtime)
        raise HTTPException(
            http.HTTP_409_CONFLICT,
            f"This function needs {spec.label}, which is not installed on this "
            "instance. Install it in Settings → Runtimes first.",
        )

    name = payload.name or package.slug
    try:
        name = validate_slug(name, what="Function name")
    except ValueError as exc:
        raise HTTPException(http.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    fn = Function(
        group_id=group.id,
        name=name,
        method=package.method,
        runtime=package.runtime,
        ctx_access=package.ctx_access,
        function_type=package.function_type,
        memory_mb=package.memory_mb,
        timeout_s=package.timeout_s,
        # Installed functions start at the smallest ceiling, like any other new
        # one. Someone else's idea of a sensible instance count is not binding.
        min_instances=0,
        max_instances=1,
    )
    namespace = group.ns
    db.add(fn)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            http.HTTP_409_CONFLICT,
            f"'{name}' already exists in {namespace}. Choose another name.",
        ) from exc
    await db.refresh(fn)

    files = dict(package.files)
    files.setdefault("README.md", package.readme or f"# {package.name}\n")
    version = FunctionVersion(function_id=fn.id, number=1, files=files, status="pending")
    db.add(version)
    await db.commit()
    await db.refresh(version)

    asyncio.create_task(  # noqa: RUF006
        _build_and_activate(str(fn.id), str(version.id), str(cluster.id))
    )
    log.info(
        "installed from marketplace",
        slug=package.slug,
        ns=namespace,
        name=name,
        author=package.author,
        url=payload.url,
    )
    return {
        **(await _detail(db, fn, cluster)),
        "declared_env": package.env,
    }


@router.get("/export/{function_id}", response_model=dict)
async def export(
    function_id: uuid.UUID,
    db: DbSession,
    cluster: CurrentCluster,
    _: RequireDeveloper,
):
    """The package document for one of your own functions.

    Publishing has no endpoint because there is no service to publish to yet.
    This produces exactly what a registry entry needs, to be submitted however
    that registry accepts submissions.
    """
    from .functions import current_version, load_function

    fn = await load_function(db, function_id, cluster)
    version = await current_version(db, fn)
    if version is None:
        raise HTTPException(http.HTTP_409_CONFLICT, "Deploy this function before exporting it.")

    return marketplace.publish_bundle(
        slug=fn.name,
        name=fn.name.replace("-", " ").title(),
        summary="",
        author="",
        fn=fn,
        files=version.files or {},
    )
