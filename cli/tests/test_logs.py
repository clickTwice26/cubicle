"""What `cubicle logs` reads, and in which order it prints it.

GET /api/logs stopped being a list and became a page, and the CLI kept
iterating the response. Iterating the page object walks its keys, so the first
thing handed to the printer was the string "offset" and the command died with
an AttributeError before printing a single line. These pin the page down.
"""

from __future__ import annotations


def _line(message: str, *, function: str = "create-charge", level: str = "INFO") -> dict:
    return {
        "id": f"log-{message}",
        "ts": "2026-08-10T12:00:00Z",
        "time": "12:00:00.001",
        "level": level,
        "function_name": function,
        "message": message,
        "duration": "8ms",
        "request_id": "req-1",
    }


def _page(messages: list[str], *, total: int | None = None, offset: int = 0) -> dict:
    """A LogPage, newest first, the way the endpoint answers."""
    items = [_line(message) for message in messages]
    return {
        "items": items,
        "total": len(items) if total is None else total,
        "limit": 60,
        "offset": offset,
    }


def test_a_page_is_read_from_its_items(api, run, capsys):
    """The rows live under `items`, not at the top level of the response."""
    api.on("GET", "/api/logs", _page(["second", "first"]))

    assert run("logs") == 0

    out = capsys.readouterr().out
    assert "first" in out
    assert "second" in out
    # The old code printed the page's keys, which is how "offset" ended up
    # being treated as a log line.
    assert "offset" not in out


def test_the_newest_line_is_printed_last(api, run, capsys):
    """The endpoint answers newest first; a terminal is read downwards."""
    api.on("GET", "/api/logs", _page(["newest", "oldest"]))

    run("logs")

    out = capsys.readouterr().out
    assert out.index("oldest") < out.index("newest")


def test_an_empty_page_prints_nothing_and_succeeds(api, run, capsys):
    """No logs is not an error, and there is no row to misread."""
    api.on("GET", "/api/logs", _page([]))

    assert run("logs") == 0
    assert capsys.readouterr().out == ""


def test_every_filter_reaches_the_endpoint(api, run):
    """The endpoint grew function, search and offset; the flags pass them on."""
    api.on("GET", "/api/logs", _page([]))

    run(
        "logs",
        "--level",
        "ERROR",
        "--function",
        "create-charge",
        "--search",
        "timeout",
        "--limit",
        "10",
        "--offset",
        "20",
    )

    assert api.last("GET", "/api/logs").params == {
        "level": "ERROR",
        "function": "create-charge",
        "search": "timeout",
        "limit": 10,
        "offset": 20,
    }


def test_a_limit_outside_the_endpoint_s_range_is_refused_here(api, run, capsys):
    """The ceiling used to be a thousand lines, so `--limit 1000` is in scripts.

    Sent anyway it comes back as FastAPI's list of validation error objects,
    which names `limit` as a query field rather than as the flag that was typed.
    """
    assert run("logs", "--limit", "1000") == 1

    assert "--limit takes 1 to 500" in capsys.readouterr().err
    assert api.sent("GET", "/api/logs") == []


def test_a_negative_offset_never_leaves_the_machine(api, run, capsys):
    assert run("logs", "--offset", "-5") == 1

    assert "--offset takes 0 to" in capsys.readouterr().err
    assert api.sent("GET", "/api/logs") == []


def test_a_deeper_page_is_offered_when_the_total_says_there_is_one(api, run, capsys):
    """`total` counts every match, so it is the only way to know more is there."""
    api.on("GET", "/api/logs", _page(["only"], total=61))

    run("logs")

    assert "60 older lines · --offset 1" in capsys.readouterr().out


def test_a_complete_page_advertises_nothing(api, run, capsys):
    """Nothing left to fetch means no footnote to print."""
    api.on("GET", "/api/logs", _page(["only"], total=1))

    run("logs")

    assert "--offset" not in capsys.readouterr().out


def test_the_stream_yields_batches_of_entries(api, run, capsys):
    """Each SSE frame is a list, so --follow iterates the frame, not the page."""
    api.frames = [[_line("from the stream"), _line("and another")]]

    assert run("logs", "--follow") == 0

    out = capsys.readouterr().out
    assert "from the stream" in out
    assert "and another" in out
    assert api.last("GET", "/api/logs/stream").params == {"level": "all"}


def test_follow_applies_the_filters_the_stream_does_not(api, run, capsys):
    """The stream filters by level alone, so the rest is done here or not at all."""
    api.frames = [[_line("kept"), _line("dropped", function="refund")]]

    run("logs", "--follow", "--function", "create-charge")

    out = capsys.readouterr().out
    assert "kept" in out
    assert "dropped" not in out


def test_debug_is_a_level_the_endpoint_accepts(api, run):
    """LEVELS upstream is INFO, WARN, ERROR, DEBUG; the choices used to stop at three."""
    api.on("GET", "/api/logs", _page([]))

    assert run("logs", "--level", "DEBUG") == 0
    assert api.last("GET", "/api/logs").params["level"] == "DEBUG"


def test_a_qualified_function_is_reduced_to_the_name_the_rows_carry(api, run):
    """--function means <namespace>/<function> everywhere else in this CLI.

    A log row stores `function_name` alone, so passing the qualified name the
    rest of the CLI teaches used to match nothing and say nothing about it.
    """
    api.on("GET", "/api/logs", _page([]))

    run("logs", "--function", "payments/create-charge")

    assert api.last("GET", "/api/logs").params["function"] == "create-charge"


def test_follow_reduces_the_qualified_name_too(api, run, capsys):
    """The client-side filter has to agree with the server-side one."""
    api.frames = [[_line("kept"), _line("dropped", function="refund")]]

    run("logs", "--follow", "--function", "payments/create-charge")

    out = capsys.readouterr().out
    assert "kept" in out
    assert "dropped" not in out


def test_a_target_with_no_namespace_is_left_alone(api, run):
    """The bare name is what the endpoint has always taken, and still works."""
    api.on("GET", "/api/logs", _page([]))

    run("logs", "--function", "create-charge")

    assert api.last("GET", "/api/logs").params["function"] == "create-charge"
