"""Checking for a newer commit on the deployment branch, and applying it."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi import status as http

from ..deps import RequireOwner
from ..logging_setup import log
from ..runtime import updater
from ..schemas import UpdateProgress, UpdateStatus

router = APIRouter(prefix="/api/update", tags=["update"])


@router.get("", response_model=UpdateStatus)
async def check(principal: RequireOwner, refresh: bool = False):
    """What is deployed against what is on the branch.

    Super admin only, because the button this feeds runs whatever is on that
    branch on the host.
    """
    return await updater.status(force=refresh)


@router.post("/apply", response_model=UpdateProgress)
async def apply(principal: RequireOwner):
    """Start the update and return immediately.

    The work happens in a container of its own, because this one is among the
    things being replaced — the response to this request may well be the last
    thing this process does.
    """
    try:
        await updater.start()
    except updater.UpdateError as exc:
        raise HTTPException(http.HTTP_409_CONFLICT, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator verbatim
        log.warning("could not start the update", error=str(exc))
        raise HTTPException(http.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc

    log.info("update requested", by=principal.user.email)
    return await updater.progress()


@router.get("/progress", response_model=UpdateProgress)
async def progress(principal: RequireOwner):
    """Read the updater's output, including after this process was restarted."""
    return await updater.progress()
