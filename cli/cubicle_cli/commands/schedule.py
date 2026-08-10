"""Schedules: the way a function runs when nobody is asking it to.

A function has been able to run on cron since the scheduler landed, and the CLI
could not see one at all, so the only way to learn that a nightly job had been
failing since Tuesday was to open the console. That is what this leans on: the
plain-language reading of the expression, when it fires next, and what happened
the last time it did.

A trigger is addressed by UUID and nobody types one of those, so every
subcommand that takes one accepts any unambiguous prefix, which is what the
listing prints.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from ..client import (
    DEFAULT_TIMEOUT,
    CubicleError,
    Profile,
    find_function,
    load_profile,
    paint,
    request,
    table,
)

ORDER = 30

#: The preview route parses this as a UUID and then never looks it up: its only
#: dependency is the signed-in principal. So an expression can be read back
#: before there is any function to attach it to, and this is the id that stands
#: in for the one the command does not need.
PREVIEW_FUNCTION = "00000000-0000-0000-0000-000000000000"

#: The only function type a schedule can be attached to, because a schedule has
#: no request body to send one that expects input.
SCHEDULABLE = "independent"


def register(sub: argparse._SubParsersAction) -> None:
    schedule = sub.add_parser("schedule", help="Run a function on a cron schedule.")
    schedule_sub = schedule.add_subparsers(dest="schedule_command", required=True)

    # The function is a flag rather than a positional so it reads the same in
    # every subcommand, and so `preview`, which asks about an expression rather
    # than about a function, does not have to invent one.
    on_a_function = argparse.ArgumentParser(add_help=False)
    on_a_function.add_argument("--function", required=True, help="<namespace>/<function>")

    schedule_sub.add_parser("ls", parents=[on_a_function], help="List a function's schedules.")

    add = schedule_sub.add_parser("add", parents=[on_a_function], help="Schedule a function.")
    add.add_argument("cron", help="Five-field cron, for example '0 9 * * *'.")
    add.add_argument("--tz", default="UTC", help="Timezone the cron is read in. Defaults to UTC.")
    add.add_argument("--disabled", action="store_true", help="Create it without arming it.")

    for name, help_text in (
        ("rm", "Delete a schedule."),
        ("enable", "Arm a schedule."),
        ("disable", "Keep a schedule, but stop it firing."),
        ("run", "Fire a schedule once, now."),
    ):
        parser = schedule_sub.add_parser(name, parents=[on_a_function], help=help_text)
        parser.add_argument("trigger", help="Trigger id, or any unambiguous prefix of one.")

    preview = schedule_sub.add_parser("preview", help="Read a cron expression back, unattached.")
    preview.add_argument("cron", help="Five-field cron, for example '0 9 * * *'.")
    preview.add_argument(
        "--tz", default="UTC", help="Timezone the cron is read in. Defaults to UTC."
    )


# ── commands ─────────────────────────────────────────────────────────────────


def cmd_schedule(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)

    # The one subcommand that is about an expression rather than a function, so
    # it never resolves one.
    if args.schedule_command == "preview":
        return _preview(profile, args.cron, args.tz)

    fn = find_function(profile, args.function)
    if args.schedule_command == "ls":
        return _list(profile, fn)
    if args.schedule_command == "add":
        return _add(profile, fn, args)

    trigger = _find_trigger(profile, fn, args.trigger)
    if args.schedule_command == "rm":
        return _remove(profile, fn, trigger)
    if args.schedule_command == "run":
        return _run(profile, fn, trigger)
    return _set_enabled(profile, fn, trigger, enabled=args.schedule_command == "enable")


def _list(profile: Profile, fn: dict) -> int:
    triggers = request(profile, "GET", f"/api/functions/{fn['id']}/triggers")
    rows = [
        [
            _short(trigger),
            trigger.get("description") or trigger["cron"],
            trigger["cron"],
            trigger.get("timezone") or "UTC",
            "enabled" if trigger.get("enabled") else "paused",
            _when(trigger.get("next_run_at"), "not scheduled"),
            _when(trigger.get("last_run_at"), "never"),
            trigger.get("last_status") or "",
            str(trigger.get("run_count", 0)),
        ]
        for trigger in triggers
    ]
    print()
    print(
        table(
            ["id", "schedule", "cron", "tz", "state", "next run", "last run", "status", "runs"],
            rows,
        )
    )
    notes = _notes(fn, triggers)
    if notes:
        print()
        print("\n".join(notes))
    print()
    return 0


def _add(profile: Profile, fn: dict, args: argparse.Namespace) -> int:
    _require_schedulable(fn)
    trigger = request(
        profile,
        "POST",
        f"/api/functions/{fn['id']}/triggers",
        body={"cron": args.cron, "timezone": args.tz, "enabled": not args.disabled},
    )
    print(f"  {paint('created', 'green')} {_short(trigger)} · {trigger['description']}")
    print(_next_line(trigger))
    return 0


def _remove(profile: Profile, fn: dict, trigger: dict) -> int:
    request(profile, "DELETE", f"/api/functions/{fn['id']}/triggers/{trigger['id']}")
    # The expression is printed because it goes with the trigger: putting a
    # schedule back should not depend on anyone's shell history.
    print(
        f"  {paint('removed', 'green')} {_short(trigger)} · "
        f"{trigger['cron']} ({trigger.get('timezone') or 'UTC'})"
    )
    return 0


def _set_enabled(profile: Profile, fn: dict, trigger: dict, *, enabled: bool) -> int:
    # Only the flag is sent. The PATCH is exclude_unset, so a body carrying the
    # cron it already has would revalidate an expression nobody edited.
    updated = request(
        profile,
        "PATCH",
        f"/api/functions/{fn['id']}/triggers/{trigger['id']}",
        body={"enabled": enabled},
    )
    verb = "enabled" if enabled else "disabled"
    print(f"  {paint(verb, 'green')} {_short(updated)} · {updated['description']}")
    print(_next_line(updated))
    return 0


def _run(profile: Profile, fn: dict, trigger: dict) -> int:
    result = request(
        profile,
        "POST",
        f"/api/functions/{fn['id']}/triggers/{trigger['id']}/run",
        # The invocation happens inside this request and a function may be
        # configured to take up to fifteen minutes, so the client waits for as
        # long as the function itself is allowed to rather than abandon a run
        # that is still going.
        timeout=max(DEFAULT_TIMEOUT, float(fn.get("timeout_s") or 0) + 30),
    )
    # Firing by hand records the outcome but does not move `last_run_at`, which
    # only the scheduler's own claim writes. So the answer to "did it work" is
    # last_status and last_error, not a timestamp that will not have changed.
    failed = result.get("last_status") == "failed"
    verb = paint("failed", "red") if failed else paint("ran", "green")
    print(f"\n  {verb} {_short(result)} · {result.get('run_count', 0)} runs in total")
    if result.get("last_error"):
        print(paint(f"  {result['last_error']}", "red"))
    print(paint(f"  the schedule is untouched · {_next_words(result)}", "dim"))
    print()
    return 1 if failed else 0


def _preview(profile: Profile, cron: str, timezone: str) -> int:
    result = request(
        profile,
        "GET",
        f"/api/functions/{PREVIEW_FUNCTION}/triggers/-/preview",
        params={"cron": cron, "timezone": timezone},
    )
    # An expression the scheduler cannot use comes back as a 200 carrying
    # valid=false, so the status code is not the thing to read here.
    if not result.get("valid"):
        raise CubicleError(result.get("error") or f"'{cron}' is not a schedule that can be run.")
    print()
    print(f"  {result['description']}")
    print(paint("  the next five firings, in UTC", "dim"))
    print()
    for moment in result.get("upcoming", []):
        print(f"  {_when(moment)}")
    print()
    return 0


# ── helpers ──────────────────────────────────────────────────────────────────


def _require_schedulable(fn: dict) -> None:
    """Refuse a schedule the API would refuse, in words that say what to do.

    The API answers this with a 409 naming the rule, and the CLI already holds
    the function's type before it asks. Saying which type it found is the
    difference between a refusal an operator can act on and one they have to go
    and look up.
    """
    kind = fn.get("function_type") or "unknown"
    if kind == SCHEDULABLE:
        return
    raise CubicleError(
        f"{_target(fn)} is a {kind} function: it expects a request body, and a schedule has "
        "none to send. Mark it independent in the console's Settings tab if it does not read "
        "its input, then schedule it."
    )


def _find_trigger(profile: Profile, fn: dict, wanted: str) -> dict:
    """Resolve whatever was typed to exactly one trigger on this function.

    Trigger ids are UUIDs and the listing prints the first eight characters of
    one, so those eight characters have to be enough to act on. An ambiguous
    prefix is refused rather than resolved: guessing which schedule to delete is
    not a thing a command line should do.
    """
    triggers = request(profile, "GET", f"/api/functions/{fn['id']}/triggers")
    matches = [trigger for trigger in triggers if str(trigger["id"]).startswith(wanted)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise CubicleError(f"No schedule on {_target(fn)} has an id starting {wanted}.")
    found = ", ".join(_short(trigger) for trigger in matches)
    raise CubicleError(
        f"{wanted} matches {len(matches)} schedules on {_target(fn)}: {found}. Use more of the id."
    )


def _notes(fn: dict, triggers: list[dict]) -> list[str]:
    """The lines under the listing, which are the reason to have read it.

    A schedule whose last failure you cannot see is not worth listing, and an
    error is a sentence rather than a cell, so it goes here instead of in the
    table.
    """
    notes = [
        paint(f"  {_short(trigger)}  {trigger['last_error']}", "red")
        for trigger in triggers
        if trigger.get("last_error")
    ]

    kind = fn.get("function_type") or "unknown"
    if kind != SCHEDULABLE and triggers:
        # PATCH /api/functions/{id} does not re-check what POST triggers checks,
        # so a function can be made dependent long after it was scheduled. Its
        # schedules stay armed and fire with nothing to send.
        notes.append(
            paint(
                f"  WARN  {_target(fn)} is a {kind} function now, and these still fire "
                "with no body to send.",
                "yellow",
            )
        )
    elif kind != SCHEDULABLE:
        notes.append(paint(f"  {_target(fn)} is a {kind} function and cannot be scheduled.", "dim"))

    if triggers:
        notes.append(
            paint("  times are UTC · the cron is read in the schedule's own timezone", "dim")
        )
    return notes


def _next_line(trigger: dict) -> str:
    """The one fact worth knowing after arming or disarming a schedule."""
    return paint(f"  {_next_words(trigger)}", "dim")


def _next_words(trigger: dict) -> str:
    if trigger.get("next_run_at"):
        return f"next run {_when(trigger['next_run_at'])} UTC"
    return "paused · nothing fires until this schedule is enabled"


def _short(trigger: dict) -> str:
    """The first eight characters of the id, which is what people then type."""
    return str(trigger["id"])[:8]


def _target(fn: dict) -> str:
    return f"{fn['namespace']}/{fn['name']}"


def _when(value: str | None, empty: str = "") -> str:
    """A timestamp as the minute it lands on, in UTC, since cron is no finer."""
    if not value:
        return empty
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        # An instance that serialises a timestamp some other way should still
        # get a listing rather than a traceback.
        return str(value)
    # Converted rather than trusted: everything the scheduler stores is UTC, and
    # a column headed UTC has to be true of whatever offset actually arrived.
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%d %H:%M")


COMMANDS = {"schedule": cmd_schedule}
