"""Triggers: the ways a function runs other than someone calling it."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response
from fastapi import status as http
from sqlalchemy import select

from ..deps import CurrentCluster, CurrentPrincipal, DbSession, RequireDeveloper
from ..logging_setup import log
from ..models import Trigger
from ..runtime import scheduler
from ..schemas import TriggerCreate, TriggerOut, TriggerUpdate
from .functions import load_function

router = APIRouter(prefix="/api/functions/{function_id}/triggers", tags=["triggers"])


def _out(trigger: Trigger) -> dict:
    return {
        "id": trigger.id,
        "function_id": trigger.function_id,
        "kind": trigger.kind,
        "enabled": trigger.enabled,
        "cron": trigger.cron,
        "timezone": trigger.timezone,
        "description": scheduler.describe(trigger.cron, trigger.timezone),
        "next_run_at": trigger.next_run_at,
        "last_run_at": trigger.last_run_at,
        "last_status": trigger.last_status,
        "last_error": trigger.last_error,
        "run_count": trigger.run_count,
        "created_at": trigger.created_at,
    }


async def _require_independent(fn) -> None:
    """A schedule has no body to send, so only an independent function can take one.

    This is the one place the dependent/independent label decides something. It
    is still not a runtime contract — a dependent function invoked over HTTP is
    unaffected — but a scheduler cannot invent a request body, so scheduling one
    that expects input would fail on a timer forever.
    """
    if fn.function_type != "independent":
        raise HTTPException(
            http.HTTP_409_CONFLICT,
            f"'{fn.name}' is a dependent function: it expects a request body, and a "
            "schedule has none to send. Mark it independent in Settings if it does "
            "not read its input.",
        )


@router.get("", response_model=list[TriggerOut])
async def list_triggers(
    function_id: uuid.UUID, db: DbSession, cluster: CurrentCluster, _: CurrentPrincipal
):
    fn = await load_function(db, function_id, cluster)
    rows = (
        (
            await db.execute(
                select(Trigger).where(Trigger.function_id == fn.id).order_by(Trigger.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [_out(row) for row in rows]


@router.post("", response_model=TriggerOut, status_code=http.HTTP_201_CREATED)
async def create_trigger(
    function_id: uuid.UUID,
    payload: TriggerCreate,
    db: DbSession,
    cluster: CurrentCluster,
    _: RequireDeveloper,
):
    fn = await load_function(db, function_id, cluster)
    await _require_independent(fn)

    try:
        scheduler.validate(payload.cron, payload.timezone)
    except scheduler.ScheduleError as exc:
        raise HTTPException(http.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    trigger = Trigger(
        function_id=fn.id,
        cluster_id=cluster.id,
        kind="schedule",
        enabled=payload.enabled,
        cron=payload.cron.strip(),
        timezone=payload.timezone,
        next_run_at=(
            scheduler.next_after(payload.cron, payload.timezone) if payload.enabled else None
        ),
    )
    db.add(trigger)
    await db.commit()
    await db.refresh(trigger)
    log.info(
        "trigger created",
        function=fn.name,
        cron=trigger.cron,
        timezone=trigger.timezone,
        next_run_at=trigger.next_run_at.isoformat() if trigger.next_run_at else None,
    )
    return _out(trigger)


async def _load(db, function_id: uuid.UUID, trigger_id: uuid.UUID, cluster) -> Trigger:
    """A trigger lookup that cannot reach into another cluster or function."""
    await load_function(db, function_id, cluster)
    trigger = (
        await db.execute(
            select(Trigger).where(
                Trigger.id == trigger_id,
                Trigger.function_id == function_id,
                Trigger.cluster_id == cluster.id,
            )
        )
    ).scalar_one_or_none()
    if trigger is None:
        raise HTTPException(http.HTTP_404_NOT_FOUND, "No such trigger.")
    return trigger


@router.patch("/{trigger_id}", response_model=TriggerOut)
async def update_trigger(
    function_id: uuid.UUID,
    trigger_id: uuid.UUID,
    payload: TriggerUpdate,
    db: DbSession,
    cluster: CurrentCluster,
    _: RequireDeveloper,
):
    trigger = await _load(db, function_id, trigger_id, cluster)
    data = payload.model_dump(exclude_unset=True)

    cron = data.get("cron", trigger.cron)
    timezone = data.get("timezone", trigger.timezone)
    if "cron" in data or "timezone" in data:
        try:
            scheduler.validate(cron, timezone)
        except scheduler.ScheduleError as exc:
            raise HTTPException(http.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    for key, value in data.items():
        setattr(trigger, key, value)

    # Recomputed from now rather than advanced from the old slot: changing a
    # schedule should take effect at its next occurrence, not fire immediately
    # because the previous expression was already overdue.
    trigger.next_run_at = (
        scheduler.next_after(trigger.cron, trigger.timezone) if trigger.enabled else None
    )
    await db.commit()
    await db.refresh(trigger)
    return _out(trigger)


@router.post("/{trigger_id}/run", response_model=TriggerOut)
async def run_now(
    function_id: uuid.UUID,
    trigger_id: uuid.UUID,
    db: DbSession,
    cluster: CurrentCluster,
    _: RequireDeveloper,
):
    """Fire it once, immediately, without disturbing the schedule.

    For finding out whether a schedule works at all, rather than waiting until
    the small hours to discover it does not.
    """
    trigger = await _load(db, function_id, trigger_id, cluster)
    fn = await load_function(db, function_id, cluster)
    group = fn.group

    await scheduler.fire(trigger, fn, group, cluster)
    await db.refresh(trigger)
    return _out(trigger)


@router.delete("/{trigger_id}", status_code=http.HTTP_204_NO_CONTENT)
async def delete_trigger(
    function_id: uuid.UUID,
    trigger_id: uuid.UUID,
    db: DbSession,
    cluster: CurrentCluster,
    _: RequireDeveloper,
) -> Response:
    trigger = await _load(db, function_id, trigger_id, cluster)
    await db.delete(trigger)
    await db.commit()
    return Response(status_code=http.HTTP_204_NO_CONTENT)


@router.get("/-/preview", response_model=dict)
async def preview(
    function_id: uuid.UUID,
    cron: str,
    timezone: str = "UTC",
    _: CurrentPrincipal = None,  # noqa: RUF013 - dependency, not a default
):
    """What an expression means and when it would next fire, as it is typed."""
    try:
        scheduler.validate(cron, timezone)
    except scheduler.ScheduleError as exc:
        return {"valid": False, "error": str(exc), "description": "", "upcoming": []}

    upcoming: list[str] = []
    moment = datetime.now(UTC)
    for _ in range(5):
        moment = scheduler.next_after(cron, timezone, moment)
        upcoming.append(moment.isoformat())

    return {
        "valid": True,
        "error": "",
        "description": scheduler.describe(cron, timezone),
        "upcoming": upcoming,
    }
