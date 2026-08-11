"""cubicle — command line client for a self-hosted Cubicle cluster.

Everything here goes through the same HTTP API the console uses; there is no
privileged back channel.

This file owns the global flags, the dispatch and the one place an error is
turned into a message and an exit code. The commands themselves live in
`commands/`, which is walked rather than listed, so adding one means adding a
file and nothing else.
"""

from __future__ import annotations

import argparse
import difflib
import sys

from . import __version__, commands
from .client import CubicleError, paint


def build_parser() -> argparse.ArgumentParser:
    """The whole command line, global flags first and then every module's."""
    parser = argparse.ArgumentParser(
        prog="cubicle", description="Self-hosted serverless functions.", allow_abbrev=False
    )
    parser.add_argument("--url", help="Override the configured instance URL.")
    parser.add_argument("--token", help="Override the configured API token.")
    parser.add_argument(
        "--cluster",
        help="Cluster slug to act on. Defaults to the instance's default cluster.",
    )
    # Global as well as per-command: a script that has decided it is not being
    # supervised has decided it for the whole invocation, and a person typing
    # one command puts the flag after it. `client.confirmable()` is the other
    # half of that, and every command that asks a question carries it.
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Answer every confirmation with yes. Required when there is no terminal.",
    )
    parser.add_argument("--version", action="version", version=f"cubicle {__version__}")
    # Not required: a bare `cubicle` should say what it can do, not print an
    # argparse error at somebody who is trying to find out.
    sub = parser.add_subparsers(dest="command")
    commands.register_all(sub)
    return parser


#: Words people reasonably reach for, and what this CLI calls them. Typos are
#: caught by difflib below; these are the cases where the guess is a perfectly
#: good name for the thing and simply is not the one that was chosen.
ALIASES = {
    "functions": "ls",
    "fn": "ls",
    "fns": "ls",
    "list": "ls",
    "ps": "instances",
    "top": "instances",
    "delete": "rm",
    "destroy": "rm",
    "remove": "rm",
    "log": "logs",
    "tail": "logs",
    "secret": "secrets",
    "cluster": "clusters",
    "runtime": "runtimes",
    "service": "services",
    "db": "services",
    "cron": "schedule",
    "schedules": "schedule",
    "triggers": "schedule",
    "trigger": "schedule",
    "marketplace": "market",
    "install": "market",
    "whoami": "status",
    "health": "status",
    "info": "status",
    "usage": "metering",
    "billing": "metering",
    "upgrade": "update",
    "publish": "deploy",
    "push": "deploy",
    "run": "invoke",
    "call": "invoke",
    "new": "init",
    "create": "init",
}


def overview(known: list[str]) -> str:
    """What a bare `cubicle` prints.

    Somebody typing the bare command is asking what this thing does. The full
    `--help` answers that with a wall of every flag of every subcommand, which
    is the right reference and the wrong greeting.
    """
    groups = [
        ("Start here", ["login", "status", "ls"]),
        ("Ship a function", ["init", "deploy", "invoke", "logs"]),
        ("Run it", ["instances", "scale", "config", "schedule", "versions", "metrics"]),
        ("Configure", ["env", "secrets", "runtimes", "services", "market"]),
        ("Operate", ["clusters", "update", "reconcile", "metering"]),
    ]
    lines = [
        "",
        f"  {paint('cubicle', 'bold')} {paint(__version__, 'dim')}"
        f"  {paint('· self-hosted serverless functions', 'dim')}",
        "",
    ]
    for title, names in groups:
        shown = [name for name in names if name in known]
        if not shown:
            continue
        lines.append(f"  {paint(title.upper(), 'dim')}")
        lines.append(f"    {'  '.join(shown)}")
        lines.append("")
    lines += [
        f"  {paint('cubicle <command> --help', 'dim')}  what one command takes",
        f"  {paint('cubicle --help', 'dim')}            everything at once",
        "",
    ]
    return "\n".join(lines)


#: The global flags that consume the token after them. Getting this list wrong
#: is how `cubicle --url example.com status` decides the command is
#: "example.com", so it is spelled out rather than inferred.
VALUE_FLAGS = {"--url", "--token", "--cluster"}


def command_index(argv: list[str]) -> int | None:
    """Where the subcommand is, skipping global flags and their values.

    Anything after the subcommand belongs to the subcommand, so this stops at
    the first token that is neither a flag nor a flag's value.
    """
    skip = False
    for i, word in enumerate(argv):
        if skip:
            skip = False
            continue
        if word == "--":
            return i + 1 if i + 1 < len(argv) else None
        if word.startswith("-"):
            # `--url=x` carries its value; `--url x` takes the next token.
            skip = word in VALUE_FLAGS
            continue
        return i
    return None


def resolve(name: str, known: list[str]) -> str | None:
    """The command someone meant, when it is obvious which one that is."""
    if name in ALIASES and ALIASES[name] in known:
        return ALIASES[name]
    close = difflib.get_close_matches(name, known, n=1, cutoff=0.7)
    return close[0] if close else None


def main(argv: list[str] | None = None) -> int:
    try:
        parser = build_parser()
        table = commands.handlers()

        # Rewrite a near miss before argparse sees it, so `cubicle functions`
        # runs `cubicle ls` and says that it did, rather than printing the list
        # of valid choices and leaving the reader to spot the difference.
        argv = list(sys.argv[1:] if argv is None else argv)
        index = command_index(argv)
        first = argv[index] if index is not None else None
        if first is not None and first not in table:
            meant = resolve(first, list(table))
            if meant is not None:
                print(paint(f"  {first} is not a command. Running {meant}.", "dim"))
                argv[index] = meant
            else:
                # argparse's own answer here is the full list of choices on one
                # line, which is the least readable form of the only thing it
                # has to say. The overview says the same thing in groups.
                print(paint(f"✗ There is no {first!r} command.", "red"), file=sys.stderr)
                print(overview(list(table)), file=sys.stderr)
                return 2

        args = parser.parse_args(argv)
        if args.command is None:
            print(overview(list(table)))
            return 0
        return table[args.command](args)
    except CubicleError as error:
        print(paint(f"✗ {error}", "red"), file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        # ctrl-c and ctrl-d are the two ways a person walks away from a prompt,
        # and a traceback is not the right answer to either. The confirmations
        # read ctrl-d as "no" themselves; this is for the ones that read a
        # value, `login` and `secrets set`, where there is nothing to assume.
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
