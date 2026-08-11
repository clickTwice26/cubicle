"""What happens before a command runs: the URL, the overview, and near misses.

Every case here came from watching somebody use the CLI for the first time.
None of them is about what a command does; all of them are about whether the
CLI answers a reasonable action with something a person can act on.
"""

from __future__ import annotations

import pytest

from cubicle_cli.__main__ import command_index, main, resolve
from cubicle_cli.client import CubicleError, normalise_url, table, visible

KNOWN = ["login", "status", "ls", "deploy", "logs", "instances", "rm", "market", "schedule"]


# ── the URL somebody types ───────────────────────────────────────────────────


def test_a_bare_hostname_is_assumed_to_be_https():
    """This is what people type, and urllib answers it with a traceback."""
    assert normalise_url("cubicle.shagato.space") == "https://cubicle.shagato.space"


def test_localhost_without_a_scheme_is_http():
    """An install with no domain has no certificate to offer."""
    assert normalise_url("localhost:28080") == "http://localhost:28080"
    assert normalise_url("127.0.0.1:28080") == "http://127.0.0.1:28080"


def test_an_explicit_scheme_is_left_alone():
    assert normalise_url("http://fn.example.com") == "http://fn.example.com"
    assert normalise_url("https://fn.example.com/") == "https://fn.example.com"


def test_a_scheme_urllib_cannot_open_is_refused_by_name():
    with pytest.raises(CubicleError, match="ftp"):
        normalise_url("ftp://fn.example.com")


def test_an_empty_url_says_what_was_wanted():
    with pytest.raises(CubicleError, match="instance URL"):
        normalise_url("   ")


# ── finding the command among the flags ──────────────────────────────────────


def test_a_flags_value_is_not_mistaken_for_the_command():
    """`--url example.com status` names the command last, not first."""
    assert command_index(["--url", "example.com", "status"]) == 2


def test_an_inline_flag_value_does_not_shift_anything():
    assert command_index(["--url=example.com", "status"]) == 1


def test_a_boolean_flag_does_not_swallow_the_command():
    assert command_index(["--yes", "rm"]) == 1


def test_arguments_after_the_command_belong_to_it():
    assert command_index(["logs", "--follow"]) == 0


def test_no_command_at_all_is_reported_as_such():
    assert command_index([]) is None
    assert command_index(["--version"]) is None


# ── near misses ──────────────────────────────────────────────────────────────


def test_a_reasonable_other_word_for_it_is_accepted():
    """`functions` is a perfectly good name for the thing. It is just not ours."""
    assert resolve("functions", KNOWN) == "ls"
    assert resolve("ps", KNOWN) == "instances"
    assert resolve("delete", KNOWN) == "rm"


def test_a_typo_finds_the_command():
    assert resolve("statuss", KNOWN) == "status"
    assert resolve("deply", KNOWN) == "deploy"


def test_something_genuinely_unknown_is_not_guessed_at():
    """Running the wrong command is worse than saying no."""
    assert resolve("zzzzz", KNOWN) is None


def test_an_unknown_command_exits_two_and_says_so(capsys):
    assert main(["zzzzz"]) == 2
    assert "no 'zzzzz' command" in capsys.readouterr().err


# ── the bare command ─────────────────────────────────────────────────────────


def test_running_it_with_nothing_describes_itself(capsys):
    """Somebody typing `cubicle` is asking what it does, not making a mistake."""
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "START HERE" in out
    assert "login" in out and "deploy" in out
    # The old behaviour, which is what this replaces.
    assert "the following arguments are required" not in out


# ── the table ────────────────────────────────────────────────────────────────


def test_a_coloured_cell_does_not_shift_the_columns():
    """Padding has to count what prints, not how many bytes it takes."""
    plain = table(["a", "b"], [["x", "y"], ["xxxx", "z"]])
    coloured = table(["a", "b"], [["\033[31mx\033[0m", "y"], ["xxxx", "z"]])
    assert [visible(row) for row in plain.splitlines()] == [
        visible(row) for row in coloured.splitlines()
    ]


def test_numbers_line_up_on_the_right():
    rendered = table(["name", "count"], [["a", "5"], ["b", "1,200"]])
    rows = rendered.splitlines()[2:]
    assert rows[0].rstrip().endswith("    5")
    assert rows[1].rstrip().endswith("1,200")


def test_a_placeholder_does_not_send_a_number_column_left():
    """One dash in a column of durations is still a column of durations."""
    rendered = table(["p95"], [["142ms"], ["-"], ["8ms"]])
    assert rendered.splitlines()[-1].rstrip().endswith("  8ms")


def test_nothing_is_padded_past_the_end_of_a_line():
    """Trailing spaces show up the moment anyone selects or pipes the output."""
    rendered = table(["a", "b"], [["x", "y"], ["xxxx", "zzzz"]])
    assert all(line == line.rstrip() for line in rendered.splitlines())


def test_an_empty_table_still_says_so():
    assert "(nothing to show)" in table(["a"], [])
