"""The runtime catalogue, and the images behind it.

A runtime image is built on the instance rather than pulled from a registry,
because each one carries the invocation agent. So installing a language means
waiting out a build, removing one is refused while any function is still
written in it, and the three that ship with Cubicle cannot be removed at all.

This listing is also the answer to the question that kept the CLI Python-only:
which files a function of a given runtime is made of. Those names come from the
instance, so a runtime added upstream is usable here the day it lands.
"""

from __future__ import annotations

import argparse

from ..client import (
    BUILD_TIMEOUT,
    CubicleError,
    Profile,
    confirm,
    list_runtimes,
    load_profile,
    paint,
    request,
    table,
)

ORDER = 30


def register(sub: argparse._SubParsersAction) -> None:
    runtimes = sub.add_parser("runtimes", help="Runtimes this instance can run.")
    # Not required, unlike `env`: the bare command is the listing, which is the
    # only runtime question most people ever have.
    runtimes_sub = runtimes.add_subparsers(dest="runtimes_command")

    install = runtimes_sub.add_parser("install", help="Build a runtime's image on this instance.")
    install.add_argument("key", help="Runtime key, e.g. node22.")

    rebuild = runtimes_sub.add_parser("rebuild", help="Build the image again, stale agent and all.")
    rebuild.add_argument("key", help="Runtime key, e.g. node22.")

    remove = runtimes_sub.add_parser("rm", help="Remove a runtime's image from this instance.")
    remove.add_argument("key", help="Runtime key, e.g. node22.")


# ── commands ─────────────────────────────────────────────────────────────────


def cmd_runtimes(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    # One listing serves all four verbs: it is how a key is checked against the
    # instance, and it carries every precondition the writes have.
    catalogue = list_runtimes(profile)

    if args.runtimes_command is None:
        rows = [
            [
                spec["key"],
                spec["language"],
                f"{spec['entry_file']} + {spec['deps_file']}",
                _presence(spec),
                "yes" if spec["builtin"] else "no",
                str(spec["functions"]),
            ]
            for spec in catalogue
        ]
        print()
        print(table(["runtime", "language", "files", "installed", "built in", "functions"], rows))
        print(paint("\n  a built in runtime ships with Cubicle and cannot be removed", "dim"))
        print()
        return 0

    spec = _spec(catalogue, args.key)
    if args.runtimes_command == "rm":
        return _remove(profile, spec, assume_yes=args.yes)
    return _build(profile, spec, force=args.runtimes_command == "rebuild")


# ── helpers ──────────────────────────────────────────────────────────────────


def _spec(catalogue: list[dict], key: str) -> dict:
    """The instance's record for a runtime key, or a message listing the real ones."""
    for spec in catalogue:
        if spec["key"] == key:
            return spec
    known = ", ".join(spec["key"] for spec in catalogue)
    raise CubicleError(f"No {key} runtime on this instance. It has: {known}.")


def _presence(spec: dict) -> str:
    """Whether the image is here, in the one word that matters.

    `state` is what the last attempt at this image did, and it says more than
    the flag only in two cases: a build running right now, and one that failed.
    A runtime that is absent because its build broke is a different problem
    from one nobody ever asked for, and the flag alone reads the same for both.
    """
    if spec.get("state") in {"installing", "failed"}:
        return spec["state"]
    return "yes" if spec["installed"] else "no"


def _build(profile: Profile, spec: dict, *, force: bool) -> int:
    """Install or rebuild one image, and wait for the build to finish.

    The endpoint builds inside the request rather than handing back a job, and
    the only progress the API publishes is the `state` on the listing, which
    this process cannot read while it is the one holding the build open. So the
    wait is silent by necessity, and a client that runs out of patience first
    says where the answer will appear.
    """
    if spec["state"] == "installing":
        raise CubicleError(
            f"{spec['label']} is already being built on the instance. "
            "`cubicle runtimes` shows it as installing until that finishes."
        )

    verb = "rebuild" if force else "install"
    print(f"  building       {spec['label']} from {spec['base_image']}")
    try:
        result = request(
            profile, "POST", f"/api/runtimes/{spec['key']}/{verb}", timeout=BUILD_TIMEOUT
        )
    except TimeoutError:
        raise CubicleError(
            f"Gave up waiting after {BUILD_TIMEOUT:.0f}s. The build carries on inside the "
            f"control plane; `cubicle runtimes` reports {spec['key']} as installing until "
            "it lands, and as failed if it does not."
        ) from None

    # Install turns a failed build into a 502, which `request` has already
    # raised by the time we are here. Rebuild answers 200 with the failure in
    # the body, so the state decides this rather than the status code.
    if result.get("state") == "failed":
        print(paint("  build failed", "red"))
        print(result.get("error") or result.get("log", ""))
        return 1

    # The idempotent path: install of an image that is already here is reported
    # rather than done, and saying so is the difference between a fast command
    # and one the operator believes rebuilt something.
    already = "  (it was already here)" if result.get("log") == "already installed" else ""
    print(f"  {paint('installed', 'green')}      {spec['image']}{already}")
    return 0


def _remove(profile: Profile, spec: dict, *, assume_yes: bool) -> int:
    """Drop an image, having ruled out the two refusals the API would give.

    Both are answered by the listing already in hand, and asking a person to
    confirm something the server is about to refuse is a worse experience than
    telling them now.
    """
    if spec["builtin"]:
        raise CubicleError(
            f"{spec['label']} ships with Cubicle and cannot be removed. "
            "It would come back on the next update."
        )
    if spec["functions"]:
        count = spec["functions"]
        raise CubicleError(
            f"{count} function{'' if count == 1 else 's'} on this instance still use "
            f"{spec['label']}. Move them to another runtime first."
        )
    if not confirm(f"Remove the {spec['label']} image?", assume_yes=assume_yes):
        print(paint("  nothing removed", "dim"))
        return 1

    request(profile, "DELETE", f"/api/runtimes/{spec['key']}")
    print(f"  {paint('removed', 'green')}        {spec['image']}")
    return 0


COMMANDS = {"runtimes": cmd_runtimes}
