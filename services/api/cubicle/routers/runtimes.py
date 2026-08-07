"""Which languages this instance can run, and installing the ones it cannot yet."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi import status as http
from sqlalchemy import func, select

from .. import runtimes as registry
from ..deps import CurrentPrincipal, DbSession, RequireOwner
from ..models import Function
from ..runtime import images

router = APIRouter(prefix="/api/runtimes", tags=["runtimes"])


@router.get("", response_model=list[dict])
async def list_runtimes(db: DbSession, _: CurrentPrincipal):
    """Every runtime, whether its image is here, and how many functions use it.

    Readable by anyone signed in — the function editor needs it to know which
    options to offer. Installing one is owner-only.
    """
    present = await images.installed()
    rows = await db.execute(
        select(Function.runtime, func.count(Function.id)).group_by(Function.runtime)
    )
    counts = dict(rows.all())
    return [
        images.as_json(spec, is_installed=key in present, in_use=counts.get(key, 0))
        for key, spec in registry.RUNTIMES.items()
    ]


@router.post("/{key}/install", response_model=dict)
async def install(key: str, principal: RequireOwner):
    """Build a runtime's image on this node.

    Synchronous on purpose. It is mostly a base-image download, the console
    shows a spinner for it, and a second press while one is running is refused
    rather than queued.
    """
    try:
        result = await images.install(key)
    except images.InstallError as exc:
        raise HTTPException(http.HTTP_409_CONFLICT, str(exc)) from exc

    if result.get("state") == "failed":
        raise HTTPException(
            http.HTTP_502_BAD_GATEWAY,
            result.get("error") or "The runtime image could not be built.",
        )
    return result


@router.post("/{key}/rebuild", response_model=dict)
async def rebuild(key: str, principal: RequireOwner):
    """Build a runtime's image again even though it is already here.

    The agent lives in the image, so an update that changes it leaves every
    isolate on the old one until this runs. Separate from install rather than a
    flag on it, because install is the safe idempotent one people press twice
    and this deliberately throws away a working image to make another.
    """
    try:
        return await images.install(key, force=True)
    except images.InstallError as exc:
        raise HTTPException(http.HTTP_409_CONFLICT, str(exc)) from exc


@router.delete("/{key}", response_model=dict)
async def uninstall(key: str, db: DbSession, principal: RequireOwner):
    """Remove a runtime's image, unless functions are still written in it."""
    in_use = (
        await db.execute(select(func.count(Function.id)).where(Function.runtime == key))
    ).scalar_one()
    if in_use:
        raise HTTPException(
            http.HTTP_409_CONFLICT,
            f"{in_use} function{'' if in_use == 1 else 's'} still use this runtime. "
            "Move them to another one first.",
        )

    try:
        await images.remove(key)
    except images.InstallError as exc:
        raise HTTPException(http.HTTP_409_CONFLICT, str(exc)) from exc
    return {"key": key, "installed": False}
