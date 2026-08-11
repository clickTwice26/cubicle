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
    sub = parser.add_subparsers(dest="command", required=True)
    commands.register_all(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        parser = build_parser()
        args = parser.parse_args(argv)
        return commands.handlers()[args.command](args)
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
