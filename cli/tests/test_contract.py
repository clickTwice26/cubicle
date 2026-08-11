"""The seam a new command module plugs into.

Adding a command means adding a file under `cubicle_cli/commands/`, and these
are what that file has to satisfy. A module that fails one of them would
otherwise fail at the moment somebody typed its command.
"""

from __future__ import annotations

import argparse

import pytest

from cubicle_cli import commands
from cubicle_cli.__main__ import build_parser

# One canonical invocation of every command that existed before the package
# was split up, so a restructure cannot quietly drop a flag.
CANONICAL = [
    ["login", "https://cubicle.test"],
    ["clusters"],
    ["status"],
    ["ls"],
    ["init", "payments/create-charge"],
    ["init", "payments/create-charge", "--runtime", "node22", "--method", "PATCH"],
    ["deploy"],
    ["deploy", "./service"],
    ["invoke", "payments/create-charge", "-d", '{"amount": 4200}', "--session", "sess_1"],
    ["logs"],
    ["logs", "--follow", "--level", "DEBUG"],
    ["logs", "--limit", "5", "--offset", "5", "--function", "create-charge", "--search", "boom"],
    ["env", "ls"],
    ["env", "set", "STRIPE_MODE=live", "--secret"],
    ["env", "rm", "STRIPE_MODE"],
    ["secrets", "--function", "payments/create-charge", "ls"],
    ["secrets", "--function", "payments/create-charge", "set", "STRIPE_KEY"],
    ["secrets", "--function", "payments/create-charge", "rm", "STRIPE_KEY"],
]


def _subcommands(parser: argparse.ArgumentParser) -> dict:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices
    raise AssertionError("the parser has no subcommands")


def test_every_module_declares_the_contract():
    """ORDER, register and COMMANDS, or the module is not a command module."""
    for module in commands.discover():
        assert isinstance(module.ORDER, int), module.__name__
        assert callable(module.register), module.__name__
        assert isinstance(module.COMMANDS, dict), module.__name__
        assert module.COMMANDS, f"{module.__name__} registers no commands"


def test_every_handler_answers_to_a_parser():
    """The parser is the only validation and the dict is the only dispatch."""
    assert set(commands.handlers()) == set(_subcommands(build_parser()))


def test_every_handler_is_callable():
    for name, handler in commands.handlers().items():
        assert callable(handler), name


def test_modules_come_back_in_help_order():
    """Sorted by ORDER then by name, so two modules added at once cannot race."""
    order = [(module.ORDER, module.__name__) for module in commands.discover()]
    assert order == sorted(order)


def test_the_original_commands_are_all_still_here():
    """The restructure moved these; it did not get to lose any."""
    expected = {
        "login",
        "clusters",
        "status",
        "ls",
        "init",
        "deploy",
        "invoke",
        "logs",
        "env",
        "secrets",
    }
    assert expected <= set(commands.handlers())


def test_help_lists_every_command(capsys):
    with pytest.raises(SystemExit) as exit_code:
        build_parser().parse_args(["--help"])

    assert exit_code.value.code == 0
    out = capsys.readouterr().out
    for name in commands.handlers():
        assert name in out


@pytest.mark.parametrize("argv", CANONICAL, ids=" ".join)
def test_every_command_still_parses_its_arguments(argv):
    assert build_parser().parse_args(argv).command == argv[0]


def test_the_global_flags_reach_every_command():
    """--cluster, --url, --token and --yes are the parser's, not a command's."""
    args = build_parser().parse_args(
        ["--cluster", "staging", "--url", "https://x", "--token", "t", "--yes", "ls"]
    )

    assert (args.cluster, args.url, args.token, args.yes) == ("staging", "https://x", "t", True)


# Every command that asks a question before doing something, and the shortest
# invocation of each. The refusals all say "pass --yes to go ahead", so --yes
# has to be accepted where a person types it, which is at the end.
CONFIRMS = [
    ["kill", "payments/create-charge", "a1b2c3d4e5f6"],
    ["rm", "payments/create-charge"],
    ["runtimes", "rm", "node18"],
    ["services", "rm", "postgres"],
    ["services", "recreate", "redis"],
    ["market", "install", "https://example.com/p.json", "--namespace", "payments"],
    ["update", "apply"],
    ["reconcile", "apply"],
]


@pytest.mark.parametrize("argv", CONFIRMS, ids=" ".join)
def test_yes_is_taken_after_the_command_as_well(argv):
    """`cubicle rm ns/fn --yes` is the spelling the error message asks for."""
    assert build_parser().parse_args([*argv, "--yes"]).yes is True
    assert build_parser().parse_args([*argv, "-y"]).yes is True


@pytest.mark.parametrize("argv", CONFIRMS, ids=" ".join)
def test_the_global_yes_still_survives_the_subparser(argv):
    """A subparser copies its namespace outwards, so its default must not exist.

    This is what SUPPRESS buys: without it the per-command flag would default to
    False on every run and overwrite a --yes given before the command name,
    breaking the one spelling that used to work.
    """
    assert build_parser().parse_args(["--yes", *argv]).yes is True
    assert build_parser().parse_args(argv).yes is False
