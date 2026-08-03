"""Running functions on a schedule.

A trigger is due when ``next_run_at`` has passed. Claiming one is a single
UPDATE that moves ``next_run_at`` forward and returns the row only if it was
still due — so two control planes looking at the same trigger cannot both take
it, and no lock is held while the function runs. That matters because a run can
take minutes and a lock held across it would stall every other schedule.

Only ``independent`` functions can be scheduled. A schedule has no request body
to send, so a function that expects one would be invoked with nothing and fail
on a timer forever; the label that used to be a note is what makes that
checkable.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import session_scope
from ..logging_setup import log
from ..models import Cluster, Function, Group, Trigger

#: How often the loop looks for due work. A schedule cannot be finer than a
#: minute, so waking twice a minute is enough to fire on time without the loop
#: being a busy one.
TICK_SECONDS = 30

#: A run that was owed while the control plane was down is not replayed. If it
#: was owed more than this long ago, the schedule resumes at its next slot
#: rather than firing a backlog the moment the process returns.
MISSED_GRACE_SECONDS = 300


class ScheduleError(ValueError):
    """The cron expression or timezone cannot be used."""


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ScheduleError(f"'{name}' is not a known timezone.") from exc


def validate(cron: str, timezone: str = "UTC") -> None:
    """Reject an expression at the point someone types it, not at 3am."""
    tz = zone(timezone)
    expression = (cron or "").strip()
    if not expression:
        raise ScheduleError("A schedule needs a cron expression.")
    if len(expression.split()) != 5:
        raise ScheduleError(
            "A schedule is five fields: minute, hour, day of month, month, day of week."
        )
    if not croniter.is_valid(expression):
        raise ScheduleError(f"'{expression}' is not a valid cron expression.")
    # Parsing succeeds on expressions that never produce a time; find out here.
    croniter(expression, datetime.now(tz)).get_next(datetime)


def next_after(cron: str, timezone: str, after: datetime | None = None) -> datetime:
    """The first firing strictly after ``after``, as an aware UTC instant.

    Computed in the trigger's own timezone so "every day at 09:00" stays at
    09:00 across a daylight-saving change, then converted — the database only
    ever holds UTC.
    """
    tz = zone(timezone)
    moment = (after or datetime.now(UTC)).astimezone(tz)
    return croniter(cron, moment).get_next(datetime).astimezone(UTC)


def describe(cron: str, timezone: str) -> str:
    """A plain-language reading of the common shapes, for the console."""
    fields = (cron or "").split()
    if len(fields) != 5:
        return cron
    minute, hour, dom, month, dow = fields
    every = f" ({timezone})" if timezone and timezone != "UTC" else ""

    if cron == "* * * * *":
        return "Every minute"
    if minute.startswith("*/") and (hour, dom, month, dow) == ("*", "*", "*", "*"):
        return f"Every {minute[2:]} minutes"
    if hour.startswith("*/") and (dom, month, dow) == ("*", "*", "*"):
        return f"Every {hour[2:]} hours at :{int(minute):02d}{every}"
    if (hour, dom, month, dow) == ("*", "*", "*", "*"):
        return f"Hourly at :{int(minute):02d}{every}"
    if (dom, month, dow) == ("*", "*", "*"):
        return f"Daily at {int(hour):02d}:{int(minute):02d}{every}"
    if (dom, month) == ("*", "*") and dow != "*":
        days = {
            "0": "Sunday",
            "1": "Monday",
            "2": "Tuesday",
            "3": "Wednesday",
            "4": "Thursday",
            "5": "Friday",
            "6": "Saturday",
            "7": "Sunday",
        }
        named = days.get(dow, dow)
        return f"Every {named} at {int(hour):02d}:{int(minute):02d}{every}"
    return f"{cron}{every}"


async def _claim(db: AsyncSession, trigger_id, was_due: datetime, next_at: datetime) -> bool:
    """Take a due trigger by moving it forward, atomically.

    The WHERE clause carries the value that was read, so the update touches
    nothing if another process already claimed it. That is the whole guard
    against a double fire — no advisory lock, and nothing held while the
    function runs.
    """
    result = await db.execute(
        update(Trigger)
        .where(
            Trigger.id == trigger_id,
            Trigger.enabled.is_(True),
            Trigger.next_run_at == was_due,
        )
        .values(next_run_at=next_at, last_run_at=datetime.now(UTC))
    )
    await db.commit()
    return result.rowcount == 1


async def _due(db: AsyncSession) -> list[tuple]:
    now = datetime.now(UTC)
    rows = (
        await db.execute(
            select(Trigger, Function, Group, Cluster)
            .join(Function, Function.id == Trigger.function_id)
            .join(Group, Group.id == Function.group_id)
            .join(Cluster, Cluster.id == Trigger.cluster_id)
            .where(
                Trigger.enabled.is_(True),
                Trigger.next_run_at.is_not(None),
                Trigger.next_run_at <= now,
            )
            .order_by(Trigger.next_run_at)
            .limit(50)
        )
    ).all()
    return list(rows)


async def fire(trigger: Trigger, fn: Function, group: Group, cluster: Cluster) -> None:
    """Invoke the function the way an HTTP request would, with no body."""
    # Imported here rather than at module level: the invoker pulls in the pool
    # and its whole dependency tree, and the scheduler is started before any of
    # that is needed.
    from ..routers.functions import current_version, load_function
    from . import invoker
    from .nodes import pick_node

    outcome = "ok"
    error = None
    async with session_scope() as db:
        try:
            # Reloaded rather than reused: the rows above came from a session
            # that has since closed, and `invoke` needs the version and the
            # group relationship loaded.
            live = await load_function(db, fn.id, cluster)
            version = await current_version(db, live)
            if version is None or version.status != "ready":
                raise RuntimeError("the function has no deployed version to run")

            node = await pick_node(db, cluster, live.node_pool)
            result = await invoker.invoke(
                db,
                cluster=cluster,
                function=live,
                version=version,
                node=node,
                method=live.method,
                path=f"/{group.ns}/{live.name}",
                headers={"x-cubicle-trigger": "schedule"},
                query={},
                body=None,
                session_id=None,
            )
            if result.status_code >= 400:
                outcome, error = "failed", f"the function answered {result.status_code}"
        except Exception as exc:  # noqa: BLE001 - a schedule must survive its runs
            outcome, error = "failed", str(exc)[:500]

        await db.execute(
            update(Trigger)
            .where(Trigger.id == trigger.id)
            .values(
                last_status=outcome,
                last_error=error,
                run_count=Trigger.run_count + 1,
            )
        )
        await db.commit()

    log.info(
        "schedule fired",
        function=f"{group.ns}/{fn.name}",
        cluster=cluster.slug,
        outcome=outcome,
        error=error,
    )


async def tick() -> int:
    """One pass: claim everything due and run it. Returns how many fired."""
    fired = 0
    async with session_scope() as db:
        rows = await _due(db)

    for trigger, fn, group, cluster in rows:
        was_due = trigger.next_run_at
        try:
            upcoming = next_after(trigger.cron, trigger.timezone)
        except (ScheduleError, Exception) as exc:  # noqa: BLE001
            # An expression that stopped working must not spin the loop. Park
            # the trigger with no future and say why.
            log.warning("disabling an unusable schedule", trigger=str(trigger.id), error=str(exc))
            async with session_scope() as db:
                await db.execute(
                    update(Trigger)
                    .where(Trigger.id == trigger.id)
                    .values(next_run_at=None, last_status="failed", last_error=str(exc)[:500])
                )
                await db.commit()
            continue

        async with session_scope() as db:
            claimed = await _claim(db, trigger.id, was_due, upcoming)
        if not claimed:
            continue

        # Long enough overdue that the moment has passed: the slot is skipped
        # rather than replayed, and the trigger simply resumes.
        if datetime.now(UTC) - was_due > timedelta(seconds=MISSED_GRACE_SECONDS):
            log.info(
                "skipping a missed schedule",
                function=f"{group.ns}/{fn.name}",
                was_due=was_due.isoformat(),
            )
            continue

        fired += 1
        await fire(trigger, fn, group, cluster)

    return fired


async def run_forever() -> None:
    """The scheduler loop, started with the control plane."""
    log.info("scheduler started", tick_seconds=TICK_SECONDS)
    while True:
        try:
            await asyncio.sleep(TICK_SECONDS)
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the loop outlives one bad pass
            log.warning("scheduler pass failed", error=str(exc))
