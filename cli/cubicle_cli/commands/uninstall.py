"""Remove this program from this machine.

Nothing here touches the instance. No request is made, no cluster is contacted,
and a Cubicle server carries on exactly as it was: this removes the client, the
saved profile, and nothing else. The distinction is worth being loud about,
because `cubicle rm` deletes a function on the server and the two words are
close enough to be reached for by mistake.

The saved profile is the part only this command knows about. It holds an API
token in plain text, so leaving it behind after the program that reads it has
gone is worse than useless: it is a credential in a file nobody will think to
look at again.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ..client import CONFIG_PATH, CubicleError, confirm, confirmable, load_profile, paint, record

ORDER = 90

#: The package name, which is not the module name and is what a package
#: manager is asked about.
DIST = "cubicle-cli"

#: Printed after a successful removal, because the commonest reason to
#: uninstall something is to install it again cleanly.
REINSTALL = 'pipx install "git+https://github.com/clickTwice26/cubicle.git#subdirectory=cli"'


def register(sub: argparse._SubParsersAction) -> None:
    remove = sub.add_parser(
        "uninstall",
        parents=[confirmable()],
        help="Remove the CLI and the saved profile from this machine.",
        description=(
            "Removes this program and the saved profile from this computer. "
            "The instance, its clusters and its functions are untouched: nothing "
            "here makes a single request."
        ),
    )
    remove.add_argument(
        "--keep-config",
        action="store_true",
        help="Leave ~/.cubicle in place. It holds an API token in plain text.",
    )
    remove.add_argument(
        "--config-only",
        action="store_true",
        help="Forget the saved instance and token, but leave the program installed.",
    )


# ── how this copy got here ───────────────────────────────────────────────────


@dataclass(slots=True)
class Install:
    """Where this program lives and what would remove it."""

    #: pipx | pip | source
    kind: str
    #: Somewhere a person can look, for the summary.
    location: str
    #: What to run, or None when there is nothing a package manager owns.
    command: list[str] | None
    #: Why, when there is nothing to run.
    note: str = ""


def discover() -> Install:
    """Work out how this copy was installed, from the running interpreter.

    Reading the environment rather than a record of the install, because the
    record is inside the thing being removed and a person may well have moved
    it since.
    """
    prefix = Path(sys.prefix)

    # pipx gives each program its own virtual environment under a directory
    # called `venvs`, named for the package. That shape is the signal; the
    # location of pipx's home varies with the platform and with PIPX_HOME.
    if prefix.parent.name == "venvs":
        pipx = shutil.which("pipx")
        if pipx:
            return Install("pipx", str(prefix), [pipx, "uninstall", prefix.name])
        return Install(
            "pipx",
            str(prefix),
            None,
            "pipx installed it and pipx is no longer on PATH. "
            f"Reinstall pipx, or delete {prefix} by hand.",
        )

    try:
        from importlib.metadata import Distribution

        Distribution.from_name(DIST)
    except Exception:  # noqa: BLE001 - not installed as a package is the answer
        return Install(
            "source",
            str(Path(__file__).resolve().parents[2]),
            None,
            "This is a source checkout, so there is no installed copy to remove. "
            "Delete the directory when you are done with it.",
        )

    # A plain pip install, into a venv or into the user's site-packages. Use
    # this interpreter rather than whatever `pip` resolves to on PATH, which is
    # frequently a different Python entirely.
    return Install("pip", str(prefix), [sys.executable, "-m", "pip", "uninstall", "-y", DIST])


# ── the command ──────────────────────────────────────────────────────────────


def cmd_uninstall(args: argparse.Namespace) -> int:
    install = discover()
    config = Path(CONFIG_PATH)
    removing_config = config.exists() and not args.keep_config

    rows = [("removes", "the CLI on this machine, and nothing on any instance")]
    if not args.config_only:
        rows.append((install.kind, install.location))
    if removing_config:
        rows.append(("profile", str(config.parent)))
        # Worth naming, because it is the reason not to skip this half.
        rows.append(("", paint("holds an API token in plain text", "dim")))

    print()
    print(record(rows))

    # Which instance, when there is one, so a person with several does not have
    # to remember which profile this machine is holding.
    with_instance = _instance_hint()
    if with_instance:
        print(paint(f"\n  signed in to {with_instance}. That instance is not affected.", "dim"))

    if args.config_only:
        return _forget(config, assume_yes=args.yes)

    if install.command is None:
        print(f"\n  {paint('note', 'yellow')} {install.note}")
        if removing_config:
            _forget(config, assume_yes=args.yes)
        return 0

    print()
    if not confirm("Remove the CLI from this machine?", assume_yes=args.yes):
        return 1

    if removing_config:
        _delete_config(config)

    print(paint(f"  running {' '.join(install.command)}", "dim"))
    try:
        # Output goes straight to the terminal: this is the last thing this
        # program does, and a package manager's own report of what it removed
        # is better than a summary of it.
        result = subprocess.run(install.command, check=False)  # noqa: S603
    except OSError as error:
        raise CubicleError(f"Could not run the uninstaller: {error}") from None

    if result.returncode != 0:
        raise CubicleError(
            f"{install.command[0]} exited {result.returncode}. Nothing else was changed."
        )

    print(f"\n  {paint('removed', 'green')}  the CLI is gone from this machine")
    print(paint("  the instance is untouched. To install it again:", "dim"))
    print(paint(f"    {REINSTALL}", "dim"))
    print()
    return 0


def _instance_hint() -> str:
    """The instance this machine is signed in to, if it is signed in at all."""
    try:
        return load_profile().base
    except CubicleError:
        return ""


def _forget(config: Path, *, assume_yes: bool) -> int:
    """Drop the saved profile and leave the program installed."""
    if not config.exists():
        print(f"\n  {paint('nothing to forget', 'dim')}  there is no saved profile\n")
        return 0
    print()
    if not confirm("Forget the saved instance and token?", assume_yes=assume_yes):
        return 1
    _delete_config(config)
    print(f"\n  {paint('forgotten', 'green')}  run `cubicle login <url>` to sign in again\n")
    return 0


def _delete_config(config: Path) -> None:
    """Remove the profile, and the directory when this was the only thing in it.

    Anything else a person put in `~/.cubicle` is theirs, so the directory goes
    only when it is empty.
    """
    config.unlink(missing_ok=True)
    parent = config.parent
    try:
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        # A directory that will not go is not worth failing the uninstall over.
        pass


COMMANDS = {"uninstall": cmd_uninstall}
