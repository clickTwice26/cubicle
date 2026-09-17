"""What is safe to trust about a tmux session name and a `list-sessions` line.

Nothing here touches Docker: the parts of `runtime.terminal` that do are thin
wrappers around `tmux`/`nsenter` argv construction and docker-py's exec-socket
API, in the same style every other runtime module keeps its Docker calls thin
and its logic pure. What is worth testing without a daemon is the two things
that would otherwise fail silently or unsafely — a name that becomes a tmux
target and nothing else, and turning tmux's own output back into structured
rows.
"""

from cubicle.runtime.terminal import NAME_MAX, parse_sessions, valid_name

# ── session names ────────────────────────────────────────────────────────────


def test_an_ordinary_name_is_valid():
    assert valid_name("staging-box")
    assert valid_name("session_1")
    assert valid_name("a")


def test_blank_is_not_a_name():
    assert not valid_name("")
    assert not valid_name("   ")


def test_a_name_at_the_ceiling_is_valid_one_past_it_is_not():
    assert valid_name("a" * NAME_MAX)
    assert not valid_name("a" * (NAME_MAX + 1))


def test_whitespace_inside_the_name_is_refused():
    """A tmux target is passed as one argv element, never shell text — but a
    space still is not a name anyone meant to type, and it reads like two.
    """
    assert not valid_name("two words")
    assert not valid_name("tab\tinside")


def test_shell_metacharacters_are_refused():
    """Never reaches a shell — every command here is an argv list — but a
    name this suspicious-looking is not one to accept just because it would
    have been harmless anyway.
    """
    for name in ("../etc/passwd", "a;rm -rf /", "$(whoami)", "a`b`", "a|b", "a&b", "a\nb"):
        assert not valid_name(name), name


def test_a_dot_or_a_colon_are_refused():
    """tmux gives `:` and `.` meaning of their own in a target spec
    (`session:window.pane`) — a name that could be read as one is refused
    rather than silently addressing the wrong pane.
    """
    assert not valid_name("session:0")
    assert not valid_name("session.0")


# ── parsing tmux's own listing ───────────────────────────────────────────────

_LINE = "\t".join(["work", "1700000000", "1", "80", "24", "1700000100"])


def test_a_well_formed_line_parses():
    sessions = parse_sessions(_LINE)
    assert len(sessions) == 1
    session = sessions[0]
    assert session.name == "work"
    assert session.attached is True
    assert session.cols == 80
    assert session.rows == 24
    assert session.created_at.startswith("2023-11-14")


def test_an_unattached_session_reads_as_unattached():
    line = "\t".join(["idle", "1700000000", "0", "80", "24", "1700000000"])
    assert parse_sessions(line)[0].attached is False


def test_no_server_running_is_no_sessions_not_an_error():
    assert parse_sessions("") == []


def test_several_sessions_all_parse():
    lines = "\n".join(
        "\t".join([name, "1700000000", "0", "80", "24", "1700000000"]) for name in ("a", "b", "c")
    )
    assert [s.name for s in parse_sessions(lines)] == ["a", "b", "c"]


def test_a_malformed_line_is_skipped_rather_than_raising():
    assert parse_sessions("not\tenough\tfields") == []


def test_a_non_numeric_field_degrades_instead_of_raising():
    line = "\t".join(["work", "not-a-number", "1", "eighty", "24", "1700000000"])
    session = parse_sessions(line)[0]
    assert session.created_at == ""
    assert session.cols == 0
    assert session.rows == 24
