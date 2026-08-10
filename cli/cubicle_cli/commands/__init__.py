"""The command modules, found by walking this package rather than listing it.

Several people add commands at the same time, and a hand-edited registry is
the one file they would all have to touch. So a module joins the CLI by
existing here and declaring three names:

    ORDER = <int>                    where its commands sit in `cubicle --help`
    def register(sub) -> None        adds its parsers to the subparsers object
    COMMANDS = {"name": handler}     command name to handler(args) -> exit code

Every key in COMMANDS must be a parser added by `register`, because argparse
is the only validation and this dict is the only dispatch. `commands/core.py`
is the worked example.

ORDER is spaced in tens (core is 0) so a module can be slotted between two
others without renumbering anything. Modules whose name begins with an
underscore are skipped, which is where shared fixtures or a private module
would go.
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
from collections.abc import Callable
from types import ModuleType

from ..client import CubicleError

#: A command handler: it is given the parsed argparse namespace and returns
#: the process exit code.
Handler = Callable[[argparse.Namespace], int]

CONTRACT = ("ORDER", "register", "COMMANDS")


def discover() -> list[ModuleType]:
    """Every command module, in the order they should appear in the help."""
    found = []
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        missing = [name for name in CONTRACT if not hasattr(module, name)]
        if missing:
            raise CubicleError(
                f"{module.__name__} is not a command module: it defines no {', '.join(missing)}."
            )
        found.append(module)
    return sorted(found, key=lambda module: (module.ORDER, module.__name__))


def register_all(sub: argparse._SubParsersAction) -> None:
    """Let every module add its own parsers."""
    for module in discover():
        try:
            module.register(sub)
        except argparse.ArgumentError as clash:
            # argparse spots a duplicate command name before the dispatch table
            # does, and its message names only the name. Two modules written in
            # two branches is the likely reason, so say which one arrived second.
            raise CubicleError(f"{module.__name__} could not be registered: {clash}") from None


def handlers() -> dict[str, Handler]:
    """The dispatch table, merged across modules.

    A collision is raised rather than resolved: two modules claiming the same
    command name is a mistake made in two branches that nobody would otherwise
    see until one of them silently stopped working.
    """
    merged: dict[str, Handler] = {}
    owners: dict[str, str] = {}
    for module in discover():
        for name, handler in module.COMMANDS.items():
            if name in merged:
                raise CubicleError(
                    f"Both {owners[name]} and {module.__name__} define the `{name}` command."
                )
            merged[name] = handler
            owners[name] = module.__name__
    return merged
