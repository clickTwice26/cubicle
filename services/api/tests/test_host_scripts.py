"""What has to be right about a host script before a daemon is involved.

`runtime.hostscripts` is two thin Docker calls around one thing that is not
thin at all: the pair of shell programs that carry a script across a namespace
boundary and run it under a bound. That construction is pure, it is where a
quoting mistake would become a root shell doing something nobody asked for, and
it is the part no integration test would catch — a wrong program that still
runs happily looks exactly like a right one until the day an operator puts a
quote in a working directory.

So: the argv and the two programs, the validation that decides what may reach
them, and the rule that turns what a program printed into an HTTP body.
"""

import json
import shlex
import tarfile
from io import BytesIO

import pytest

from cubicle.runtime.hostscripts import (
    DEFAULT_OUTPUT_KB,
    MAX_OUTPUT_KB,
    MAX_STORED_CHARS,
    MAX_TIMEOUT_S,
    NOT_STARTED,
    PROBED_COMMANDS,
    SHEBANG,
    Outcome,
    ScriptError,
    clean_env,
    for_history,
    inner_program,
    interpret_output,
    outer_program,
    parse_probe,
    payload_tar,
    probe_source,
    valid_interpreter,
    valid_name,
    valid_working_dir,
)

# ── names ────────────────────────────────────────────────────────────────────


def test_an_ordinary_name_is_valid():
    assert valid_name("nightly-backup")
    assert valid_name("b")
    assert valid_name("db2")


def test_a_name_is_a_url_segment_and_nothing_else():
    """The name is the last part of the public URL, so it is held to what a
    path segment may be rather than to what a filename may be.
    """
    for name in ("", "  ", "Upper", "trailing-", "-leading", "has space", "dot.dot", "a/b"):
        assert not valid_name(name), name


def test_shell_metacharacters_are_not_names():
    for name in ("a;rm -rf /", "$(whoami)", "a`b`", "a|b", "a&b", "../etc/passwd"):
        assert not valid_name(name), name


# ── interpreters ─────────────────────────────────────────────────────────────


def test_a_bare_command_or_an_absolute_path_is_an_interpreter():
    assert valid_interpreter("python3")
    assert valid_interpreter("node")
    assert valid_interpreter("/usr/local/bin/python3.11")
    assert valid_interpreter(SHEBANG)


def test_an_interpreter_may_not_carry_arguments():
    """One word, so it is unambiguously a program. Anything needing arguments
    goes in the script's own `#!` line, which is what `shebang` is for.
    """
    for value in ("/usr/bin/env python3", "python3 -u", "sh -c", ""):
        assert not valid_interpreter(value), value


def test_an_interpreter_may_not_be_shell():
    for value in ("python3; rm -rf /", "$(id)", "a|b", "python3\nrm -rf /"):
        assert not valid_interpreter(value), value


# ── working directories ──────────────────────────────────────────────────────


def test_a_working_directory_is_absolute_or_blank():
    assert valid_working_dir("")
    assert valid_working_dir("/srv/app")
    assert not valid_working_dir("relative/path")
    assert not valid_working_dir("~/app")


def test_a_working_directory_may_not_be_shell():
    for value in ("/srv/$(id)", "/srv/`id`", "/srv;id", "/srv\nid"):
        assert not valid_working_dir(value), value


# ── the environment an operator sets ─────────────────────────────────────────


def test_ordinary_variables_pass_through():
    assert clean_env({"TOKEN": "abc", "_x1": "2"}) == {"TOKEN": "abc", "_x1": "2"}


def test_a_name_that_is_not_a_variable_name_is_refused():
    for key in ("1STARTS_WITH_DIGIT", "has space", "has-hyphen", "", "a=b"):
        with pytest.raises(ScriptError):
            clean_env({key: "v"})


def test_the_cubicle_prefix_is_reserved():
    """What a script reads about its own invocation has to have come from
    Cubicle, or it is not worth reading.
    """
    with pytest.raises(ScriptError):
        clean_env({"CUBICLE_TRIGGER": "pretend"})


# ── the program that runs on the host ────────────────────────────────────────


def test_the_host_program_runs_the_script_under_timeout():
    program = inner_program(interpreter="python3", working_dir="", timeout_s=30)
    assert "timeout -s TERM 30 python3" in program
    assert '"$d/script"' in program
    assert '< "$d/stdin"' in program


def test_a_host_without_timeout_refuses_rather_than_running_unbounded():
    """The whole safety story for a root process started by an HTTP request is
    that something ends it. A host that cannot bound it does not get to start
    it.
    """
    program = inner_program(interpreter="python3", working_dir="", timeout_s=30)
    assert "command -v timeout" in program
    assert f"exit {NOT_STARTED}" in program


def test_the_shebang_interpreter_makes_the_script_executable_and_runs_it():
    program = inner_program(interpreter=SHEBANG, working_dir="", timeout_s=5)
    assert 'chmod +x "$d/script"' in program
    assert 'timeout -s TERM 5 "$d/script"' in program
    assert "shebang" not in program


def test_a_working_directory_is_quoted_and_falls_back():
    program = inner_program(interpreter="sh", working_dir="/srv/my app", timeout_s=5)
    assert "cd '/srv/my app' 2>/dev/null || cd \"$d\"" in program


def test_no_working_directory_means_the_run_s_own_directory():
    program = inner_program(interpreter="sh", working_dir="", timeout_s=5)
    assert 'cd "$d"' in program
    assert "2>/dev/null ||" not in program


def test_the_run_directory_is_removed_whatever_the_script_did():
    program = inner_program(interpreter="sh", working_dir="", timeout_s=5)
    # rindex, not index: the early exits clean up after themselves too, and it
    # is the last one — the one after a script that actually ran — that this
    # is about.
    assert program.index("code=$?") < program.rindex('rm -rf "$d"')
    assert program.rstrip().endswith("exit $code")


# ── the program that runs in the toolbox ─────────────────────────────────────


def test_the_toolbox_program_pipes_the_payload_through_nsenter():
    inner = inner_program(interpreter="python3", working_dir="", timeout_s=10)
    program = outer_program(run_dir="/tmp/cubicle-run-abc", inner=inner)
    assert "tar -cf - script stdin | nsenter -t 1 -m -u -i -n -p --" in program
    assert "/bin/sh -c " in program


def test_the_inner_program_survives_being_quoted_into_the_outer_one():
    """The outer program is one argv element containing the inner one as
    shell text. If that nesting were wrong the host would run a fragment of a
    program, which is the failure mode worth a test of its own.
    """
    inner = inner_program(interpreter="python3", working_dir="/srv/it's here", timeout_s=10)
    program = outer_program(run_dir="/tmp/cubicle-run-abc", inner=inner)

    # Tokenise the rest of the outer program the way a shell would. The first
    # token past `-c` is the whole inner program, newlines, quotes and all, or
    # the quoting is wrong.
    rest = program.split("/bin/sh -c ", 1)[1]
    assert shlex.split(rest)[0] == inner


def test_the_exit_code_of_the_pipeline_is_the_script_s_own():
    program = outer_program(run_dir="/tmp/x", inner="true")
    assert program.index("| nsenter") < program.index("code=$?")
    assert program.rstrip().endswith("exit $code")


def test_the_staging_directory_is_cleaned_up_in_the_toolbox_too():
    program = outer_program(run_dir="/tmp/cubicle-run-abc", inner="true")
    assert "rm -rf /tmp/cubicle-run-abc" in program


# ── the payload ──────────────────────────────────────────────────────────────


def test_the_payload_carries_the_script_and_its_stdin():
    archive = payload_tar(source="print('hi')\n", stdin=b'{"a":1}', run_name="run-1")
    with tarfile.open(fileobj=BytesIO(archive)) as tar:
        assert sorted(tar.getnames()) == ["run-1", "run-1/script", "run-1/stdin"]
        assert tar.extractfile("run-1/script").read() == b"print('hi')\n"
        assert tar.extractfile("run-1/stdin").read() == b'{"a":1}'


def test_the_payload_is_not_readable_by_anyone_else_on_the_box():
    archive = payload_tar(source="secret", stdin=b"secret", run_name="run-1")
    with tarfile.open(fileobj=BytesIO(archive)) as tar:
        assert tar.getmember("run-1/script").mode == 0o700
        assert tar.getmember("run-1/stdin").mode == 0o600


def test_a_body_far_past_the_argv_ceiling_still_fits():
    """The reason the payload is a tar at all: Linux caps one argument at
    128 KiB, and a webhook body is routinely larger than that.
    """
    big = b"x" * (4 * 1024 * 1024)
    archive = payload_tar(source="cat", stdin=big, run_name="run-1")
    with tarfile.open(fileobj=BytesIO(archive)) as tar:
        assert tar.extractfile("run-1/stdin").read() == big


# ── turning stdout into a response ───────────────────────────────────────────


def test_auto_gives_json_back_as_json():
    body, media = interpret_output('{"ok": true}\n', "auto")
    assert body == {"ok": True}
    assert media == "application/json"


def test_auto_gives_anything_else_back_as_text():
    body, media = interpret_output("just some output\n", "auto")
    assert body == "just some output\n"
    assert media == "text/plain"


def test_auto_keeps_text_exactly_as_printed():
    """Not stripped: a script that printed trailing whitespace printed it."""
    assert interpret_output("  spaced  \n", "auto")[0] == "  spaced  \n"


def test_text_never_parses_even_when_it_could():
    body, media = interpret_output('{"ok": true}', "text")
    assert body == '{"ok": true}'
    assert media == "text/plain"


def test_json_mode_says_so_instead_of_answering_text():
    """A caller that parses unconditionally must not be handed a plain-text
    surprise with a 200 on it.
    """
    body, media = interpret_output("Traceback (most recent call last):", "json")
    assert body is None
    assert media == "application/json"


def test_a_script_that_printed_nothing_is_not_null():
    assert interpret_output("", "auto") == ("", "text/plain")
    assert interpret_output("   \n", "auto") == ("", "text/plain")
    assert interpret_output("", "json")[0] is None


def test_a_json_scalar_is_still_json():
    assert interpret_output("42", "auto") == (42, "application/json")
    assert interpret_output(json.dumps([1, 2]), "auto")[0] == [1, 2]


# ── bounds ───────────────────────────────────────────────────────────────────


def test_the_timeout_ceiling_is_what_the_console_offers():
    assert MAX_TIMEOUT_S == 900


def test_both_timeout_commands_in_the_world_read_as_a_timeout():
    """GNU coreutils exits 124; busybox — an Alpine host — exits 128+SIGTERM.
    A run that hit its limit has to answer 504 on both, or the status code
    depends on which distribution the node happens to be.
    """
    assert _outcome(124).timed_out
    assert _outcome(143).timed_out
    assert not _outcome(1).timed_out
    assert not _outcome(0).timed_out


def test_only_zero_is_success():
    assert _outcome(0).ok
    assert not _outcome(1).ok
    assert not _outcome(124).ok


def _outcome(exit_code: int) -> Outcome:
    return Outcome(exit_code=exit_code, stdout=b"", stderr=b"", duration_ms=0.0, truncated=False)


# ── asking the machine what it is ────────────────────────────────────────────


def test_the_probe_reads_back_as_facts():
    facts = parse_probe("os=Ubuntu 24.04\nkernel=Linux 6.8.0\ncommands=python3 git jq\n")
    assert facts == {
        "os": "Ubuntu 24.04",
        "kernel": "Linux 6.8.0",
        "commands": "python3 git jq",
    }


def test_a_value_may_contain_the_separator():
    """`python=Python 3.12.3 (main, x=y)` is one fact, not a parse error."""
    assert parse_probe("python=Python 3.12.3 (main, x=y)")["python"] == "Python 3.12.3 (main, x=y)"


def test_empty_and_malformed_probe_lines_are_dropped():
    """A host with no node prints `node=` and one with no /etc/os-release
    prints nothing at all — neither is a fact, and neither should become one.
    """
    facts = parse_probe("os=Debian\nnode=\nnot a line at all\n\n=novalue\n")
    assert facts == {"os": "Debian"}


def test_a_probe_that_said_nothing_is_no_facts_not_an_error():
    assert parse_probe("") == {}


def test_every_probed_command_survives_into_the_program():
    """The probe's command list is interpolated into a shell `for` loop, so a
    name with a space or a quote in it would silently break the loop.
    """
    for command in PROBED_COMMANDS:
        assert command.replace("-", "").replace("_", "").isalnum(), command


def test_the_probe_program_builds_with_its_printf_intact():
    """The template is shell, so it is full of `%s` that printf owns and
    `${...}` that the shell owns. Substituting the command list with either of
    Python's formatting operators would try to claim those — this is the test
    that the substitution leaves them alone.
    """
    program = probe_source()
    assert "@@" not in program
    assert "printf 'commands=%s\\n'" in program
    assert "${PRETTY_NAME:-$NAME}" in program

    # The whole list, in the loop, exactly once each.
    line = next(row for row in program.splitlines() if row.startswith("for c in "))
    assert line.removeprefix("for c in ").removesuffix("; do").split() == list(PROBED_COMMANDS)


# ── the output ceiling ───────────────────────────────────────────────────────


def test_the_default_ceiling_is_a_megabyte():
    """Four times what it was. The old 256 KB was shared by every script and
    mentioned nowhere, which is how a proxy script had its JSON cut mid-value
    and handed back as a 200.
    """
    assert DEFAULT_OUTPUT_KB == 1024
    assert MAX_OUTPUT_KB == 16 * 1024


def test_history_keeps_a_readable_amount_of_a_short_stream_untouched():
    assert for_history("all of it", stream="stdout") == "all of it"


def test_history_trims_a_long_stream_and_says_it_did():
    text = "x" * (MAX_STORED_CHARS + 5000)
    kept = for_history(text, stream="stdout")
    assert kept.startswith("x" * 100)
    assert len(kept) < len(text)
    assert str(len(text)) in kept
    assert "stdout" in kept


def test_the_history_limit_is_not_the_response_limit():
    """Two different questions. What a caller is handed has to be the whole
    answer or an error; what a person reads in the console a week later only
    has to be enough to understand the run.
    """
    assert MAX_STORED_CHARS < DEFAULT_OUTPUT_KB * 1024
