"""What `cubicle schedule` asks for, and what it says back.

The CLI could not see a schedule at all, so these pin the three things that
made it worth adding: that the listing carries the last failure, that a trigger
can be named by the short id the listing prints, and that a schedule is refused
on a function that could never run one, in words that name the type it found.
"""

from __future__ import annotations

TRIGGERS = "/api/functions/fn-1/triggers"
PREVIEW = "/api/functions/00000000-0000-0000-0000-000000000000/triggers/-/preview"


def _trigger(**overrides: object) -> dict:
    """A TriggerOut, as GET /api/functions/{id}/triggers answers with one."""
    record = {
        "id": "8f2a1c3d-1111-4111-8111-111111111111",
        "function_id": "fn-1",
        "kind": "schedule",
        "enabled": True,
        "cron": "0 9 * * *",
        "timezone": "UTC",
        "description": "Daily at 09:00",
        "next_run_at": "2026-08-11T09:00:00+00:00",
        "last_run_at": "2026-08-10T09:00:00+00:00",
        "last_status": "ok",
        "last_error": None,
        "run_count": 41,
        "created_at": "2026-07-01T00:00:00+00:00",
    }
    return {**record, **overrides}


def _independent(api_function, **overrides: object) -> dict:
    return api_function(function_type="independent", **overrides)


# ── ls ───────────────────────────────────────────────────────────────────────


def test_ls_shows_when_it_next_fires_and_how_the_last_run_went(api, run, capsys, api_function):
    """The reading of the expression, the next slot and the outcome are the listing."""
    api.on("GET", "/api/functions", [_independent(api_function)])
    api.on("GET", TRIGGERS, [_trigger()])

    assert run("schedule", "ls", "--function", "payments/create-charge") == 0

    out = capsys.readouterr().out
    assert "8f2a1c3d" in out
    assert "Daily at 09:00" in out
    assert "0 9 * * *" in out
    assert "2026-08-11 09:00" in out
    assert "2026-08-10 09:00" in out
    assert "41" in out


def test_ls_prints_the_last_failure_under_the_table(api, run, capsys, api_function):
    """A schedule whose last failure you cannot see is not worth listing."""
    api.on("GET", "/api/functions", [_independent(api_function)])
    api.on(
        "GET",
        TRIGGERS,
        [_trigger(last_status="failed", last_error="the function answered 500")],
    )

    run("schedule", "ls", "--function", "payments/create-charge")

    out = capsys.readouterr().out
    assert "failed" in out
    assert "8f2a1c3d  the function answered 500" in out


def test_ls_says_a_paused_schedule_has_no_next_slot(api, run, capsys, api_function):
    """next_run_at is null exactly when nothing is going to happen, so it says so."""
    api.on("GET", "/api/functions", [_independent(api_function)])
    api.on("GET", TRIGGERS, [_trigger(enabled=False, next_run_at=None)])

    run("schedule", "ls", "--function", "payments/create-charge")

    out = capsys.readouterr().out
    assert "paused" in out
    assert "not scheduled" in out


def test_ls_explains_why_a_dependent_function_has_no_schedules(api, run, capsys, api_function):
    """An empty listing on a function that could never have one should say which it is."""
    api.on("GET", "/api/functions", [api_function(function_type="dependent")])
    api.on("GET", TRIGGERS, [])

    assert run("schedule", "ls", "--function", "payments/create-charge") == 0

    out = capsys.readouterr().out
    assert "(nothing to show)" in out
    assert "payments/create-charge is a dependent function and cannot be scheduled." in out


def test_ls_warns_when_a_scheduled_function_was_made_dependent(api, run, capsys, api_function):
    """PATCH does not re-check what POST checked, so armed triggers can outlive the type."""
    api.on("GET", "/api/functions", [api_function(function_type="dependent")])
    api.on("GET", TRIGGERS, [_trigger()])

    run("schedule", "ls", "--function", "payments/create-charge")

    assert "WARN" in capsys.readouterr().out


# ── add ──────────────────────────────────────────────────────────────────────


def test_add_sends_the_expression_the_timezone_and_an_armed_trigger(api, run, api_function):
    """The three fields TriggerCreate takes, with enabled defaulting to armed."""
    api.on("GET", "/api/functions", [_independent(api_function)])
    api.on("POST", TRIGGERS, _trigger(timezone="Europe/London"))

    assert run("schedule", "add", "--function", "payments/create-charge", "0 9 * * *") == 0

    assert api.last("POST", TRIGGERS).body == {
        "cron": "0 9 * * *",
        "timezone": "UTC",
        "enabled": True,
    }


def test_add_can_create_a_schedule_without_arming_it(api, run, capsys, api_function):
    """--disabled writes the expression down and fires nothing until it is enabled."""
    api.on("GET", "/api/functions", [_independent(api_function)])
    api.on("POST", TRIGGERS, _trigger(enabled=False, next_run_at=None))

    run(
        "schedule",
        "add",
        "--function",
        "payments/create-charge",
        "*/15 * * * *",
        "--tz",
        "Europe/London",
        "--disabled",
    )

    assert api.last("POST", TRIGGERS).body == {
        "cron": "*/15 * * * *",
        "timezone": "Europe/London",
        "enabled": False,
    }
    assert "nothing fires until this schedule is enabled" in capsys.readouterr().out


def test_add_reports_the_reading_of_the_cron_and_the_next_slot(api, run, capsys, api_function):
    """The server describes the expression it stored, which is the confirmation."""
    api.on("GET", "/api/functions", [_independent(api_function)])
    api.on("POST", TRIGGERS, _trigger())

    run("schedule", "add", "--function", "payments/create-charge", "0 9 * * *")

    out = capsys.readouterr().out
    assert "created 8f2a1c3d · Daily at 09:00" in out
    assert "next run 2026-08-11 09:00 UTC" in out


def test_a_dependent_function_is_refused_before_anything_is_posted(api, run, capsys, api_function):
    """The API 409s on this; the CLI knows the type already and can name it."""
    api.on("GET", "/api/functions", [api_function(function_type="dependent")])

    assert run("schedule", "add", "--function", "payments/create-charge", "0 9 * * *") == 1

    assert api.sent("POST", TRIGGERS) == []
    err = capsys.readouterr().err
    assert "is a dependent function" in err
    assert "Mark it independent" in err


# ── addressing a trigger ─────────────────────────────────────────────────────


def test_a_trigger_is_named_by_the_short_id_the_listing_prints(api, run, api_function):
    """Nobody types a UUID, so eight characters have to be enough to act on."""
    api.on("GET", "/api/functions", [_independent(api_function)])
    api.on("GET", TRIGGERS, [_trigger()])
    api.on("DELETE", f"{TRIGGERS}/8f2a1c3d-1111-4111-8111-111111111111", None)

    assert run("schedule", "rm", "--function", "payments/create-charge", "8f2a1c3d") == 0

    assert api.sent("DELETE", f"{TRIGGERS}/8f2a1c3d-1111-4111-8111-111111111111")


def test_an_ambiguous_prefix_is_refused_rather_than_guessed(api, run, capsys, api_function):
    """Choosing which of two schedules to delete is not the CLI's decision to make."""
    api.on("GET", "/api/functions", [_independent(api_function)])
    api.on(
        "GET",
        TRIGGERS,
        [_trigger(), _trigger(id="8f2a1c3d-2222-4222-8222-222222222222")],
    )

    assert run("schedule", "rm", "--function", "payments/create-charge", "8f2a") == 1

    assert api.sent("DELETE", f"{TRIGGERS}/8f2a1c3d-1111-4111-8111-111111111111") == []
    assert "matches 2 schedules" in capsys.readouterr().err


def test_a_prefix_that_matches_nothing_names_the_function(api, run, capsys, api_function):
    """The likely mistake is the wrong function or the wrong cluster, not the wrong id."""
    api.on("GET", "/api/functions", [_independent(api_function)])
    api.on("GET", TRIGGERS, [_trigger()])

    assert run("schedule", "rm", "--function", "payments/create-charge", "deadbeef") == 1

    assert "No schedule on payments/create-charge has an id starting deadbeef." in (
        capsys.readouterr().err
    )


def test_removing_a_schedule_prints_the_expression_it_removed(api, run, capsys, api_function):
    """The cron goes with the trigger, so putting it back should not need shell history."""
    api.on("GET", "/api/functions", [_independent(api_function)])
    api.on("GET", TRIGGERS, [_trigger(timezone="Europe/London")])
    api.on("DELETE", f"{TRIGGERS}/8f2a1c3d-1111-4111-8111-111111111111", None)

    run("schedule", "rm", "--function", "payments/create-charge", "8f2a1c3d")

    assert "removed 8f2a1c3d · 0 9 * * * (Europe/London)" in capsys.readouterr().out


# ── enable, disable and run ──────────────────────────────────────────────────


def test_disable_patches_the_flag_and_nothing_else(api, run, capsys, api_function):
    """The PATCH is exclude_unset, so sending the cron back would revalidate it for nothing."""
    api.on("GET", "/api/functions", [_independent(api_function)])
    api.on("GET", TRIGGERS, [_trigger()])
    api.on(
        "PATCH",
        f"{TRIGGERS}/8f2a1c3d-1111-4111-8111-111111111111",
        _trigger(enabled=False, next_run_at=None),
    )

    assert run("schedule", "disable", "--function", "payments/create-charge", "8f2a1c3d") == 0

    patch = api.last("PATCH", f"{TRIGGERS}/8f2a1c3d-1111-4111-8111-111111111111")
    assert patch.body == {"enabled": False}
    assert "disabled 8f2a1c3d" in capsys.readouterr().out


def test_enable_reports_when_the_schedule_will_next_fire(api, run, capsys, api_function):
    """Arming one is only useful if it says what it just armed it to do."""
    api.on("GET", "/api/functions", [_independent(api_function)])
    api.on("GET", TRIGGERS, [_trigger(enabled=False, next_run_at=None)])
    api.on("PATCH", f"{TRIGGERS}/8f2a1c3d-1111-4111-8111-111111111111", _trigger())

    run("schedule", "enable", "--function", "payments/create-charge", "8f2a1c3d")

    out = capsys.readouterr().out
    assert api.last("PATCH", f"{TRIGGERS}/8f2a1c3d-1111-4111-8111-111111111111").body == {
        "enabled": True
    }
    assert "enabled 8f2a1c3d · Daily at 09:00" in out
    assert "next run 2026-08-11 09:00 UTC" in out


def test_run_reads_the_outcome_from_the_status_not_from_the_timestamp(
    api, run, capsys, api_function
):
    """Firing by hand records last_status and run_count; only the scheduler moves last_run_at."""
    api.on("GET", "/api/functions", [_independent(api_function)])
    api.on("GET", TRIGGERS, [_trigger()])
    api.on(
        "POST",
        f"{TRIGGERS}/8f2a1c3d-1111-4111-8111-111111111111/run",
        _trigger(last_status="ok", run_count=42),
    )

    assert run("schedule", "run", "--function", "payments/create-charge", "8f2a1c3d") == 0

    out = capsys.readouterr().out
    assert "ran 8f2a1c3d · 42 runs in total" in out
    assert "the schedule is untouched · next run 2026-08-11 09:00 UTC" in out


def test_a_run_that_failed_is_a_failed_command(api, run, capsys, api_function):
    """Firing one by hand is how you find out it is broken, so the exit code has to say."""
    api.on("GET", "/api/functions", [_independent(api_function)])
    api.on("GET", TRIGGERS, [_trigger()])
    api.on(
        "POST",
        f"{TRIGGERS}/8f2a1c3d-1111-4111-8111-111111111111/run",
        _trigger(last_status="failed", last_error="the function answered 500", run_count=42),
    )

    assert run("schedule", "run", "--function", "payments/create-charge", "8f2a1c3d") == 1

    assert "the function answered 500" in capsys.readouterr().out


def test_run_waits_as_long_as_the_function_is_allowed_to_take(api, run, api_function):
    """The invocation happens inside the request, so the default minute is not enough."""
    api.on("GET", "/api/functions", [_independent(api_function, timeout_s=900)])
    api.on("GET", TRIGGERS, [_trigger()])
    api.on("POST", f"{TRIGGERS}/8f2a1c3d-1111-4111-8111-111111111111/run", _trigger())

    run("schedule", "run", "--function", "payments/create-charge", "8f2a1c3d")

    assert api.last("POST", f"{TRIGGERS}/8f2a1c3d-1111-4111-8111-111111111111/run").timeout == 930


# ── preview ──────────────────────────────────────────────────────────────────


def test_preview_asks_about_the_expression_without_resolving_a_function(api, run, capsys):
    """The route parses its function id and never looks it up, so none is needed."""
    api.on(
        "GET",
        PREVIEW,
        {
            "valid": True,
            "error": "",
            "description": "Daily at 09:00",
            "upcoming": ["2026-08-11T09:00:00+00:00", "2026-08-12T09:00:00+00:00"],
        },
    )

    assert run("schedule", "preview", "0 9 * * *") == 0

    assert api.sent("GET", "/api/functions") == []
    assert api.last("GET", PREVIEW).params == {"cron": "0 9 * * *", "timezone": "UTC"}
    out = capsys.readouterr().out
    assert "Daily at 09:00" in out
    assert "2026-08-11 09:00" in out
    assert "2026-08-12 09:00" in out


def test_preview_passes_the_timezone_the_cron_is_read_in(api, run):
    """Nine in the morning is a different instant in every zone, which is the point of --tz."""
    api.on(
        "GET",
        PREVIEW,
        {
            "valid": True,
            "error": "",
            "description": "Daily at 09:00 (Europe/London)",
            # 09:00 in London is 08:00 UTC, and the API answers in UTC.
            "upcoming": ["2026-08-11T08:00:00+00:00"],
        },
    )

    assert run("schedule", "preview", "0 9 * * *", "--tz", "Europe/London") == 0

    assert api.last("GET", PREVIEW).params == {"cron": "0 9 * * *", "timezone": "Europe/London"}


def test_an_unusable_expression_is_an_error_even_though_the_call_succeeded(api, run, capsys):
    """A cron the scheduler cannot run comes back 200 with valid=false, not as a 4xx."""
    api.on(
        "GET",
        PREVIEW,
        {
            "valid": False,
            "error": "'0 99 * * *' is not a valid cron expression.",
            "description": "",
            "upcoming": [],
        },
    )

    assert run("schedule", "preview", "0 99 * * *") == 1

    assert "is not a valid cron expression." in capsys.readouterr().err
