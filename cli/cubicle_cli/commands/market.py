"""The community marketplace: reading a registry, reviewing a package, installing one.

Installing runs code somebody else wrote on this operator's cluster, with
whatever env and secrets that namespace can reach. So `show` prints every line
of the source the registry serves, and `install` says what it is about to
create before it asks. The control plane does not take our copy on trust
either: it fetches the package again for itself before it builds anything.
"""

from __future__ import annotations

import argparse
import json

from ..client import (
    CubicleError,
    Profile,
    confirm,
    confirmable,
    ensure_group,
    find_function,
    load_profile,
    paint,
    record,
    request,
    table,
    wait_for_version,
)

ORDER = 30


def register(sub: argparse._SubParsersAction) -> None:
    market = sub.add_parser("market", help="Browse and install published functions.")
    market.add_argument(
        "--registry", default=None, help="Read this registry index rather than the configured one."
    )
    market_sub = market.add_subparsers(dest="market_command")

    # The positional is `package` and not `url`: --url is a global flag, and a
    # positional of that name would quietly overwrite the instance URL with a
    # package one. The metavar keeps the help reading the way people type it.
    show = market_sub.add_parser("show", help="Print a package and the whole of its source.")
    show.add_argument("package", metavar="url", help="The package URL from the listing.")

    install = market_sub.add_parser(
        "install", parents=[confirmable()], help="Create a function from a package."
    )
    install.add_argument("package", metavar="url", help="The package URL from the listing.")
    install.add_argument("--namespace", required=True, help="Namespace to create the function in.")
    install.add_argument("--name", default=None, help="Function name. Defaults to the slug.")

    export = market_sub.add_parser("export", help="Print one of your functions as a package.")
    export.add_argument("target", help="<namespace>/<function>")


# ── commands ─────────────────────────────────────────────────────────────────


def cmd_market(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    if args.market_command == "show":
        return _show(profile, args.package)
    if args.market_command == "install":
        return _install(profile, args)
    if args.market_command == "export":
        return _export(profile, args.target)
    return _browse(profile, args.registry)


def _browse(profile: Profile, registry: str | None) -> int:
    index = request(profile, "GET", "/api/marketplace", params={"url": registry})
    rows = [
        [
            listing["slug"],
            listing["summary"],
            _runtime_cell(listing),
            listing["version"] or "-",
            listing["url"],
        ]
        for listing in index["packages"]
    ]
    print()
    print(table(["package", "summary", "runtime", "version", "url"], rows))
    print(paint(f"\n  registry  {index['registry']}", "dim"))
    print(paint("  review    cubicle market show <url> prints the source it would build", "dim"))
    print()
    return 0


def _show(profile: Profile, url: str) -> int:
    package = request(profile, "GET", "/api/marketplace/package", params={"url": url})
    rows = [
        *_metadata(package),
        ("context", package["ctx_access"]),
        ("license", package["license"] or "not stated"),
        ("tags", ", ".join(package["tags"]) or "none"),
    ]
    if package["homepage"]:
        rows.append(("homepage", package["homepage"]))

    print()
    print(record(rows))

    if package["env"]:
        # Declared, never set: the operator writes these themselves, so the
        # list is the work the install leaves behind rather than a detail.
        print(paint("\n  it expects these in the cluster env, and nothing here sets them", "dim"))
        print(table(["key", "required", "description"], _env_rows(package["env"])))

    # The whole source, because reviewing it is the only thing standing between
    # a stranger's repository and this cluster. A published function is one
    # readable file; that is what makes this practical.
    for filename, body in package["files"].items():
        print(paint(f"\n  {filename}", "dim"))
        print(body)
    if package["readme"] and "README.md" not in package["files"]:
        print(paint("\n  README.md", "dim"))
        print(package["readme"])

    print(paint(f"\n  cubicle market install {url} --namespace <ns>", "dim"))
    print()
    return 0


def _install(profile: Profile, args: argparse.Namespace) -> int:
    package = request(profile, "GET", "/api/marketplace/package", params={"url": args.package})
    if not package["runtime_installed"]:
        raise _missing_runtime(package)

    name = args.name or package["slug"]
    print()
    print(record([*_metadata(package), ("creates", f"{args.namespace}/{name}")]))
    print()
    if not confirm(f"Install {package['name']} and run it on this cluster?", assume_yes=args.yes):
        print(paint("  nothing installed", "dim"))
        return 1

    # Asked for after the confirmation, so declining does not leave a namespace
    # behind that nobody asked for.
    group, created = ensure_group(profile, args.namespace)
    if created:
        print(f"  {paint('created', 'green')} namespace {group['ns']}")

    try:
        fn = request(
            profile,
            "POST",
            "/api/marketplace/install",
            body={"url": args.package, "group_id": group["id"], "name": name},
        )
    except CubicleError as refusal:
        # The control plane re-checks the runtime against its own engine, so a
        # runtime that went away between the review and the install is refused
        # there. Its message points at the console; this one can point at the
        # command that fixes it.
        if "not installed" not in str(refusal):
            raise
        raise _missing_runtime(package) from None

    print(f"  {paint('installed', 'green')}      {group['ns']}/{fn['name']}")
    # The build is an asyncio task the response did not wait for, so the
    # function comes back pending and the interesting answer is still coming.
    built = wait_for_version(profile, fn["id"])
    if built["version_status"] != "ready":
        print(paint("  build failed", "red"))
        print(built.get("build_log", ""))
        return 1

    print(f"  {paint('deployed', 'green')}       {built['url']} (v{built['version']})")
    declared = fn.get("declared_env") or []
    if declared:
        print(paint("\n  it expects these in the cluster env, and nothing here set them", "dim"))
        print(table(["key", "required", "description"], _env_rows(declared)))
        print(paint("\n  cubicle env set KEY=value", "dim"))
    print()
    return 0


def _export(profile: Profile, target: str) -> int:
    fn = find_function(profile, target)
    document = request(profile, "GET", f"/api/marketplace/export/{fn['id']}")
    # Nothing but the document: this is a file on its way to a registry's pull
    # request, so anything friendly printed around it would have to be deleted.
    print(json.dumps(document, indent=2))
    return 0


# ── helpers ──────────────────────────────────────────────────────────────────


def _metadata(package: dict) -> list[tuple[str, str]]:
    """What a package is, in the six lines both `show` and `install` open with."""
    runtime = package["runtime_label"]
    if not package["runtime_installed"]:
        runtime += "  " + paint("not installed on this instance", "yellow")
    return [
        ("package", f"{package['name']} {package['version']}".strip()),
        ("summary", package["summary"] or "none given"),
        ("author", package["author"] or "not stated"),
        ("runtime", runtime),
        ("method", f"{package['method']} · {package['function_type']}"),
        ("resources", f"{package['memory_mb']} MB · {package['timeout_s']}s"),
    ]


def _env_rows(declared: list[dict]) -> list[list[str]]:
    return [
        [item["key"], "required" if item["required"] else "optional", item["description"]]
        for item in declared
    ]


def _runtime_cell(listing: dict) -> str:
    """A listing's runtime, saying so when this instance could not run it."""
    if listing["runtime_installed"]:
        return listing["runtime"]
    return f"{listing['runtime']} (not installed)"


def _missing_runtime(package: dict) -> CubicleError:
    """The refusal, phrased as the command that clears it.

    Both the pre-flight here and the control plane's own 409 end up saying
    this, because either can be the one that notices.
    """
    return CubicleError(
        f"{package['name']} needs {package['runtime_label']}, which this instance does not "
        f"have. Run `cubicle runtimes install {package['runtime']}` first."
    )


COMMANDS = {"market": cmd_market}
