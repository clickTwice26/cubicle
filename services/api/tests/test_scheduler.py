"""Reading a schedule, and describing it back.

The claim-by-update that stops two control planes taking the same run needs a
database and is exercised live; what is pinned down here is everything that
decides *when* a run is owed — the part that is wrong at 3am on the last Sunday
in October if nobody checked it.
"""

from datetime import UTC, datetime, timedelta

import pytest

from cubicle.runtime import scheduler

# ── validation ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "cron",
    ["* * * * *", "*/5 * * * *", "0 9 * * *", "30 3 * * 1", "0 0 1 * *", "15,45 * * * *"],
)
def test_ordinary_expressions_are_accepted(cron):
    scheduler.validate(cron)


@pytest.mark.parametrize(
    "cron",
    [
        "",
        "   ",
        "* * * *",  # four fields
        "* * * * * *",  # six — a seconds field cubicle does not offer
        "not a cron",
        "99 * * * *",
    ],
)
def test_unusable_expressions_are_refused(cron):
    with pytest.raises(scheduler.ScheduleError):
        scheduler.validate(cron)


def test_the_field_count_is_named_in_the_error():
    """Five-versus-six is the mistake people actually make."""
    with pytest.raises(scheduler.ScheduleError) as exc:
        scheduler.validate("0 0 9 * * *")
    assert "five fields" in str(exc.value)


def test_an_unknown_timezone_is_refused():
    with pytest.raises(scheduler.ScheduleError) as exc:
        scheduler.validate("0 9 * * *", "Mars/Olympus_Mons")
    assert "timezone" in str(exc.value)


# ── when it next fires ───────────────────────────────────────────────────────


def test_the_next_run_is_in_the_future_and_utc():
    upcoming = scheduler.next_after("*/5 * * * *", "UTC")
    assert upcoming > datetime.now(UTC)
    assert upcoming.tzinfo is not None
    assert upcoming.utcoffset() == timedelta(0)


def test_a_daily_schedule_is_read_in_its_own_timezone():
    """09:00 in Dhaka is 03:00 UTC, and the stored instant is the UTC one."""
    after = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
    upcoming = scheduler.next_after("0 9 * * *", "Asia/Dhaka", after)
    assert upcoming.hour == 3
    assert upcoming.date() == after.date()


def test_a_daily_schedule_holds_its_local_hour_across_a_dst_change():
    """The point of storing a timezone rather than an offset.

    London is UTC+1 in July and UTC+0 in January, so a 09:00 local schedule is
    08:00 UTC in summer and 09:00 UTC in winter. An offset stored once would
    drift by an hour twice a year.
    """
    summer = scheduler.next_after("0 9 * * *", "Europe/London", datetime(2026, 7, 1, tzinfo=UTC))
    winter = scheduler.next_after("0 9 * * *", "Europe/London", datetime(2026, 1, 5, tzinfo=UTC))
    assert summer.hour == 8
    assert winter.hour == 9


def test_successive_calls_walk_forward():
    """Each call is strictly after the last, so a loop cannot stall on one slot."""
    moment = datetime(2026, 6, 1, tzinfo=UTC)
    seen = []
    for _ in range(4):
        moment = scheduler.next_after("*/15 * * * *", "UTC", moment)
        seen.append(moment)
    assert seen == sorted(seen)
    assert len(set(seen)) == 4
    assert seen[1] - seen[0] == timedelta(minutes=15)


# ── describing it back ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("cron", "expected"),
    [
        ("* * * * *", "Every minute"),
        ("*/5 * * * *", "Every 5 minutes"),
        ("0 * * * *", "Hourly at :00"),
        ("30 * * * *", "Hourly at :30"),
        ("0 9 * * *", "Daily at 09:00"),
        ("45 23 * * *", "Daily at 23:45"),
        ("0 9 * * 1", "Every Monday at 09:00"),
    ],
)
def test_common_shapes_read_as_english(cron, expected):
    assert scheduler.describe(cron, "UTC") == expected


def test_a_non_utc_timezone_is_named():
    """Otherwise "Daily at 09:00" is ambiguous in exactly the wrong way."""
    assert scheduler.describe("0 9 * * *", "Asia/Dhaka") == "Daily at 09:00 (Asia/Dhaka)"


def test_an_expression_with_no_plain_reading_is_shown_as_written():
    """Better the cron than a wrong sentence about it."""
    assert scheduler.describe("0 9 1,15 * *", "UTC") == "0 9 1,15 * *"


def test_describe_does_not_raise_on_rubbish():
    """It runs on stored values, so it must never be the thing that 500s."""
    for cron in ("", "nonsense", "* * *"):
        assert isinstance(scheduler.describe(cron, "UTC"), str)
