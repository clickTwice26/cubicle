"""The managed PostgreSQL and Redis a cluster can have one of each.

A service is a container the control plane owns, so everything here is one API
call and a sentence about what it did. The exception is the connection URL: it
carries the password in plain text, so it is printed by `cubicle services url`
and by nothing else, on its own line, so that a shell can capture it without
capturing anything friendly around it.
"""

from __future__ import annotations

import argparse
import sys

from ..client import (
    BUILD_TIMEOUT,
    CubicleError,
    Profile,
    confirm,
    confirmable,
    load_profile,
    paint,
    record,
    request,
    table,
)

ORDER = 30

#: The whole of `{kind}`. Unlike the runtimes, this is not a property of the
#: instance: services/api/cubicle/routers/data_services.py knows these two and
#: 404s everything else.
KINDS = ("postgres", "redis")

#: The sizes the API has a byte count for. Anything else is silently read as
#: 1 GB rather than refused, which is worth catching before it is provisioned.
MEMORY_SIZES = ("32 MB", "64 MB", "128 MB", "256 MB", "512 MB", "1 GB", "2 GB", "4 GB")

#: Passed straight to `redis-server --maxmemory-policy`, so a typo is a
#: container that never starts rather than a message. These are Redis's, and
#: Redis is not going to grow a ninth one behind the CLI's back.
EVICTION = (
    "noeviction",
    "allkeys-lru",
    "allkeys-lfu",
    "allkeys-random",
    "volatile-lru",
    "volatile-lfu",
    "volatile-random",
    "volatile-ttl",
)


def register(sub: argparse._SubParsersAction) -> None:
    services = sub.add_parser("services", help="Managed PostgreSQL and Redis.")
    services_sub = services.add_subparsers(dest="services_command")

    show = services_sub.add_parser("show", help="Everything one service reports.")
    show.add_argument("kind", choices=KINDS)

    url = services_sub.add_parser(
        "url", help="Print the connection URL, password included. Admins only."
    )
    url.add_argument("kind", choices=KINDS)

    create = services_sub.add_parser("create", help="Provision a service on this cluster.")
    create.add_argument("kind", choices=KINDS)
    create.add_argument(
        "--version", default=None, help="Defaults to the version this instance offers."
    )
    create.add_argument("--memory", default=None, help=f"One of: {', '.join(MEMORY_SIZES)}.")
    create.add_argument(
        "--storage", default=None, help="PostgreSQL only. Recorded, not enforced as a quota."
    )
    create.add_argument("--eviction", default=None, choices=EVICTION, help="Redis only.")
    create.add_argument("--node-pool", default=None, help="Pool to place the container in.")

    start = services_sub.add_parser("start", help="Start a stopped service.")
    start.add_argument("kind", choices=KINDS)

    stop = services_sub.add_parser("stop", help="Stop a running service.")
    stop.add_argument("kind", choices=KINDS)

    recreate = services_sub.add_parser(
        "recreate", parents=[confirmable()], help="Replace the container, keeping the volume."
    )
    recreate.add_argument("kind", choices=KINDS)

    remove = services_sub.add_parser(
        "rm", parents=[confirmable()], help="Delete a service and, by default, its data."
    )
    remove.add_argument("kind", choices=KINDS)
    remove.add_argument(
        "--keep-data",
        action="store_true",
        help="Leave the volume behind. Its password is deleted with the service, "
        "so nothing can read it afterwards.",
    )


# ── commands ─────────────────────────────────────────────────────────────────


def cmd_services(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    command = args.services_command
    if command == "show":
        return _show(profile, args.kind)
    if command == "url":
        return _url(profile, args.kind)
    if command == "create":
        return _create(profile, args)
    if command in {"start", "stop"}:
        return _toggle(profile, args.kind, command)
    if command == "recreate":
        return _recreate(profile, args)
    if command == "rm":
        return _remove(profile, args)
    return _list(profile)


def _list(profile: Profile) -> int:
    rows = [
        [
            service["kind"],
            service["status"].replace("_", " "),
            service["version"],
            (service["config"] or {}).get("memory", "-"),
            service["node"] or "-",
            _usage(service),
        ]
        for service in request(profile, "GET", "/api/services")
    ]
    print()
    print(table(["service", "status", "version", "memory", "node", "usage"], rows))
    # The listing carries a masked URL and this prints none of it. A password
    # belongs in the output of the one command that was asked for it.
    print(paint("\n  cubicle services url <service> prints the URL that carries the", "dim"))
    print(paint("  password, for a function that has to connect", "dim"))
    print()
    return 0


def _show(profile: Profile, kind: str) -> int:
    service = request(profile, "GET", f"/api/services/{kind}")
    print()
    print(record(_detail(service)))
    if not service["created"]:
        print(paint(f"\n  cubicle services create {kind} provisions it", "dim"))
    print()
    return 0


#: What each service listens on inside the cluster's network, for the tunnel
#: hint below. The URL itself carries the port, but a hint has to say it before
#: the operator has read the URL.
SERVICE_PORTS = {"postgres": 5432, "redis": 6379}


def _url(profile: Profile, kind: str) -> int:
    service = request(profile, "GET", f"/api/services/{kind}/connection")
    if not service["connection_url"]:
        state = service["status"].replace("_", " ")
        raise CubicleError(f"There is no connection URL while {kind} is {state}.")

    # On its own, unframed and uncommented, so `$(cubicle services url redis)`
    # is the URL and nothing else.
    print(service["connection_url"])

    # The host in that URL is a container name on the cluster's own Docker
    # network. It resolves for a function and for the control plane, and for
    # nothing on the machine this command just ran on. Saying so on stderr
    # keeps the substitution above clean while still answering the question
    # every operator asks within about ten seconds of seeing the URL.
    if not sys.stdout.isatty():
        return 0
    host = service.get("node") or "your server"
    port = SERVICE_PORTS.get(kind, 5432)
    print(
        paint(
            f"\n  The host in that URL is a container on the cluster network, so it\n"
            f"  resolves from a function and not from here. To reach it from this\n"
            f"  machine, forward the port from {host} and connect to localhost:{port}:\n",
            "dim",
        ),
        file=sys.stderr,
    )
    print(
        paint(f"    ssh -L {port}:{_hostname(service)}:{port} <user>@{host}\n", "dim"),
        file=sys.stderr,
    )
    return 0


def _hostname(service: dict) -> str:
    """The container name out of the connection URL, for the tunnel hint."""
    url = service.get("connection_url") or ""
    after_at = url.rsplit("@", 1)[-1]
    return after_at.split(":", 1)[0] or "<container>"


def _create(profile: Profile, args: argparse.Namespace) -> int:
    if args.kind == "postgres" and args.eviction:
        raise CubicleError("--eviction is a Redis setting; PostgreSQL does not evict.")
    if args.kind == "redis" and args.storage:
        raise CubicleError("--storage is a PostgreSQL setting; Redis is sized by --memory.")

    body = {"version": args.version or _default_version(profile, args.kind)}
    # Only what was asked for. Every one of these has a default in the API, and
    # the API is the one that should be applying it.
    if args.memory:
        body["memory"] = _memory(args.memory)
    if args.storage:
        body["storage"] = args.storage
    if args.eviction:
        body["eviction"] = args.eviction
    if args.node_pool:
        body["node_pool"] = args.node_pool

    service = request(
        profile,
        "POST",
        f"/api/services/{args.kind}",
        body=body,
        # The image is pulled inside this request on a node that has never run
        # this service, which is minutes on a cold engine and a success worth
        # waiting for.
        timeout=BUILD_TIMEOUT,
    )
    print(f"  {paint('created', 'green')} {args.kind} {service['version']} on {service['node']}")
    print(paint(f"  cubicle services url {args.kind} prints its connection URL", "dim"))
    return 0


def _toggle(profile: Profile, kind: str, command: str) -> int:
    service = request(profile, "POST", f"/api/services/{kind}/{command}")
    verb = "started" if command == "start" else "stopped"
    print(f"  {paint(verb, 'green')} {kind} · {service['status']}")
    return 0


def _recreate(profile: Profile, args: argparse.Namespace) -> int:
    if not confirm(
        f"Replace the {args.kind} container? Everything connected to it is cut off "
        "while it restarts; the volume and the password are kept.",
        assume_yes=args.yes,
    ):
        print(paint("  nothing changed", "dim"))
        return 1
    request(profile, "POST", f"/api/services/{args.kind}/recreate", timeout=BUILD_TIMEOUT)
    print(f"  {paint('recreated', 'green')} {args.kind}")
    return 0


def _remove(profile: Profile, args: argparse.Namespace) -> int:
    question = (
        f"Delete {args.kind} and keep its volume?"
        if args.keep_data
        else f"Delete {args.kind} and every byte in it? The volume goes too, and there is no undo."
    )
    if not confirm(question, assume_yes=args.yes):
        print(paint("  nothing removed", "dim"))
        return 1

    # Sent only when it is true, so the default stays the router's default
    # rather than a copy of it here.
    params = {"keep_data": "true"} if args.keep_data else None
    request(profile, "DELETE", f"/api/services/{args.kind}", params=params)
    print(f"  {paint('removed', 'green')} {args.kind}")
    if args.keep_data:
        print(paint("  the volume is still there, and its password was deleted with the", "dim"))
        print(paint("  service, so no future service can read it", "dim"))
    return 0


# ── helpers ──────────────────────────────────────────────────────────────────


def _default_version(profile: Profile, kind: str) -> str:
    """The version this instance offers for a service nobody has created yet.

    ServiceCreate has no default of its own, and the API reports the one it
    would use on the service that does not exist yet. Asking costs a round trip
    and keeps a table that belongs to the API out of this file.
    """
    return request(profile, "GET", f"/api/services/{kind}")["version"]


def _memory(value: str) -> str:
    """One of the labelled sizes, however it was typed.

    An unrecognised label is not refused by the API, it is read as 1 GB, so a
    provisioned service would quietly have four times the memory that was asked
    for. Checking here is the only place that catches it.
    """
    wanted = value.replace(" ", "").upper()
    for label in MEMORY_SIZES:
        if label.replace(" ", "") == wanted:
            return label
    raise CubicleError(f"--memory must be one of: {', '.join(MEMORY_SIZES)}.")


def _detail(service: dict) -> list[tuple[str, str]]:
    """One service as a label and value block."""
    config = service.get("config") or {}
    rows = [
        ("service", service["kind"]),
        ("status", service["status"].replace("_", " ")),
        ("version", service["version"]),
    ]
    if not service["created"]:
        return rows

    rows += [("node", service["node"] or "-"), ("memory", config.get("memory", "-"))]
    if service["kind"] == "postgres":
        rows += [
            ("storage", config.get("storage", "-")),
            ("database", f"{config.get('database', '-')} as {config.get('user', '-')}"),
        ]
    else:
        rows.append(("eviction", config.get("eviction", "-")))
    rows += [
        ("node pool", config.get("node_pool", "-")),
        ("usage", _usage(service)),
        # Masked by the API. It says which host and database a function reaches
        # without saying the one thing that would let this be pasted anywhere.
        ("connection", service["connection_url"] or "none while it is not running"),
    ]
    if service.get("last_error"):
        rows.append(("last error", service["last_error"]))
    return rows


def _usage(service: dict) -> str:
    """Each service's own numbers, which are different numbers for each.

    The probe runs against the container, so it can also come back as a failure
    while everything else about the service still reads fine.
    """
    stats = service.get("stats") or {}
    if "error" in stats:
        return f"unreadable: {stats['error']}"
    if not stats:
        return "-"
    if service["kind"] == "postgres":
        return (
            f"{stats.get('size_label', '?')} · {stats.get('tables', 0)} tables · "
            f"{stats.get('connections', 0)}/{stats.get('max_connections', 0)} connections"
        )
    return f"{stats.get('memory_label', '?')} · {stats.get('keys', 0)} keys"


COMMANDS = {"services": cmd_services}
