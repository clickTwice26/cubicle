"""The commands the CLI has always had, brought back into line with the API.

This module is also the worked example of the contract described in
`commands/__init__.py`: it declares ORDER, a `register` that adds its own
parsers, and a COMMANDS dict whose keys are exactly the parser names it added.
A new module copies that shape and needs to touch nothing else.

Everything a handler needs comes from `..client`, which is the only import a
command module should need from the package.
"""

from __future__ import annotations

import argparse
import getpass
import json
import tomllib
from pathlib import Path

from ..client import (
    BUILD_TIMEOUT,
    CubicleError,
    Profile,
    bounded,
    deploy_files,
    ensure_group,
    env_key,
    find_function,
    list_runtimes,
    load_profile,
    paint,
    record,
    request,
    save_profile,
    split_target,
    stream,
    table,
)

ORDER = 0


def register(sub: argparse._SubParsersAction) -> None:
    login = sub.add_parser("login", help="Authenticate against an instance.")
    login.add_argument("instance_url", help="https://cubicle.example.com")

    sub.add_parser("clusters", help="List the clusters on this instance.")

    sub.add_parser("status", help="Show control plane, node and isolate health.")
    sub.add_parser("ls", help="List namespaces and functions.")

    init = sub.add_parser("init", help="Scaffold a function directory locally.")
    init.add_argument("target", help="<namespace>/<function>")
    # No choices=[...] here on purpose. Which runtimes exist is a property of
    # the instance, not of this file, and the last hardcoded list outlived the
    # platform by five runtimes.
    init.add_argument("--runtime", default="python312", help="Runtime key, e.g. node22.")
    init.add_argument(
        "--method",
        default="POST",
        choices=["GET", "POST", "PUT", "PATCH", "DELETE"],
        help="HTTP method the function answers on.",
    )

    # No --message here. DeployRequest has a `message` field, but the endpoint
    # never reads it and FunctionVersion has no column to keep it in, so a note
    # typed here would be accepted and dropped, and `cubicle versions` could
    # never show it back. A flag that reads as an audit trail and is not one is
    # worse than no flag.
    deploy = sub.add_parser("deploy", help="Deploy the function in a directory.")
    deploy.add_argument("directory", nargs="?", default=".", help="Defaults to the current one.")

    invoke = sub.add_parser("invoke", help="Invoke a function and print the response.")
    invoke.add_argument("target", help="<namespace>/<function>")
    invoke.add_argument("--data", "-d", default=None, help="JSON body, or @file.json")
    invoke.add_argument("--session", default=None, help="Reuse one isolate across calls.")

    logs = sub.add_parser("logs", help="Show or follow logs.")
    logs.add_argument("--follow", "-f", action="store_true", help="Tail new lines as they arrive.")
    logs.add_argument(
        "--level",
        default="all",
        choices=["all", "INFO", "WARN", "ERROR", "DEBUG"],
        help="Only lines at this level.",
    )
    logs.add_argument("--limit", type=int, default=60, help="How many lines to show, 1 to 500.")
    logs.add_argument("--offset", type=int, default=0, help="Skip this many of the newest lines.")
    logs.add_argument(
        "--function",
        default=None,
        help="Only this function. Takes a bare name or <namespace>/<function>.",
    )
    logs.add_argument("--search", default=None, help="Only lines containing this text.")

    env = sub.add_parser("env", help="Cluster-wide configuration.")
    env_sub = env.add_subparsers(dest="env_command", required=True)
    env_sub.add_parser("ls", help="List the cluster's variables.")
    env_set = env_sub.add_parser("set", help="Set one variable.")
    env_set.add_argument("assignment", help="KEY=value")
    env_set.add_argument("--secret", action="store_true", help="Store the value write-only.")
    env_rm = env_sub.add_parser("rm", help="Remove one variable.")
    env_rm.add_argument("key", help="The variable to remove.")

    secrets = sub.add_parser("secrets", help="Per-function secrets.")
    secrets.add_argument("--function", required=True, help="<namespace>/<function>")
    secrets_sub = secrets.add_subparsers(dest="secrets_command", required=True)
    secrets_sub.add_parser("ls", help="List the function's secret names.")
    secrets_set = secrets_sub.add_parser("set", help="Set one secret, read from the terminal.")
    secrets_set.add_argument("key", help="The secret's name.")
    secrets_rm = secrets_sub.add_parser("rm", help="Remove one secret.")
    secrets_rm.add_argument("key", help="The secret to remove.")


# ── commands ─────────────────────────────────────────────────────────────────


def cmd_login(args: argparse.Namespace) -> int:
    url = args.instance_url.rstrip("/")
    token = args.token or getpass.getpass("token: ")
    profile = Profile(url, token.strip(), args.cluster)
    me = request(profile, "GET", "/api/auth/me")
    instance = request(profile, "GET", "/api/settings/instance")
    save_profile(profile)
    print(
        f"  {paint('authenticated', 'green')} as {me['email']} · {me['role']} · "
        f"{instance['cluster_name']}\n"
        f"  {paint('cluster', 'dim')} {instance['cluster_slug']}"
        f"{'' if args.cluster else paint('  (default — override with --cluster)', 'dim')}\n"
        f"  {paint('saved to', 'dim')} ~/.cubicle/config.toml"
    )
    return 0


def cmd_clusters(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    rows = [
        [
            ("* " if c["is_default"] else "  ") + c["slug"],
            c["name"],
            c["base_url"],
            str(c["namespace_count"]),
            str(c["function_count"]),
            str(c["node_count"]),
        ]
        for c in request(profile, "GET", "/api/clusters")
    ]
    print()
    print(table(["cluster", "name", "base url", "ns", "fns", "nodes"], rows))
    print(paint("\n  * default — used when --cluster is not given", "dim"))
    print()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    health = request(profile, "GET", "/healthz")
    instance = request(profile, "GET", "/api/settings/instance")
    nodes = request(profile, "GET", "/api/cluster/nodes")
    # /api/cluster/resources rather than /api/cluster/isolates: the isolate
    # listing counts the whole instance, so on a multi-cluster install it
    # answered a question nobody asked and disagreed with every line above it.
    resources = request(profile, "GET", "/api/cluster/resources")

    def ok(flag: bool) -> str:
        return paint("ready", "green") if flag else paint("down", "red")

    # A drained node is up and unusable, and counting it as ready is how a
    # cluster with one working node reads as 2/2.
    ready = sum(1 for node in nodes if node["status"] == "ready" and node.get("schedulable", True))
    names = ", ".join(node["name"] for node in nodes)

    rows = [
        ("control plane", f"{ok(health['status'] == 'ok')}    v{instance['version']}"),
        ("database", ok(health["checks"]["database"])),
        # Redis decides `status` alongside the database, so leaving it out made
        # a degraded control plane look like it had nothing wrong with it.
        ("redis", ok(health["checks"]["redis"])),
        ("docker", ok(health["checks"]["docker"])),
        ("nodes", f"{paint(f'{ready}/{len(nodes)}', 'green')}      {names}"),
        ("isolates", f"{resources['isolates']} warm"),
        *_ceilings(resources),
        ("ingress", instance["base_url"]),
        ("cluster", f"{instance['cluster_slug']} ({instance['cluster_count']} on this instance)"),
    ]
    print()
    print(record(rows))
    print()
    return 0


def cmd_ls(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    functions = request(profile, "GET", "/api/functions")
    rows = [
        [
            f"{fn['namespace']}/{fn['name']}",
            fn["method"],
            fn["runtime_label"],
            fn["function_type"],
            f"{fn['min_instances']}-{fn['max_instances']}",
            _version_cell(fn),
            fn["stats"]["invocations_label"],
            fn["stats"]["p95"],
        ]
        for fn in functions
    ]
    print()
    print(
        table(
            ["function", "method", "runtime", "type", "scale", "version", "invocations", "p95"],
            rows,
        )
    )
    print()
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    namespace, name = split_target(args.target)
    spec = _runtime(profile, args.runtime)

    group, created = ensure_group(profile, namespace)
    if created:
        print(f"  {paint('created', 'green')} namespace {group['ns']}")

    existing = request(profile, "GET", "/api/functions", params={"group_id": group["id"]})
    fn = next((f for f in existing if f["name"] == name), None)
    if fn is None:
        fn = request(
            profile,
            "POST",
            f"/api/groups/{group['id']}/functions",
            body={"name": name, "runtime": spec["key"], "method": args.method},
        )
        print(f"  {paint('created', 'green')} {namespace}/{name}")
    if not spec["installed"]:
        print(f"  {paint('note', 'dim')}    {spec['label']} is not installed on this instance yet")

    detail = request(profile, "GET", f"/api/functions/{fn['id']}")
    directory = Path(name)
    directory.mkdir(exist_ok=True)
    # Whatever the scaffold wrote is what belongs on disk: handler.js and
    # package.json for a Node runtime, handler.py and requirements.txt for a
    # Python one.
    for filename, content in detail["files"].items():
        (directory / filename).write_text(content)
        print(f"  {paint('wrote', 'dim')}   {directory / filename}")
    print(f"\n  cd {name} && cubicle deploy\n")
    return 0


def cmd_deploy(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    directory = Path(args.directory).resolve()
    config_path = directory / "cubicle.toml"
    if not config_path.exists():
        raise CubicleError(f"No cubicle.toml in {directory}. Run `cubicle init` first.")

    config = tomllib.loads(config_path.read_text()).get("function", {})
    namespace, name = config.get("namespace"), config.get("name")
    if not namespace or not name:
        raise CubicleError("cubicle.toml is missing function.namespace or function.name.")

    fn = find_function(profile, f"{namespace}/{name}")
    # The bundle is the one the function's own runtime reads. cubicle.toml
    # records a runtime too, but the deployed function is the authority on
    # what it is, and the API validates the bundle against exactly that.
    wanted = deploy_files(fn["runtime"], profile=profile)
    entry, deps = wanted[0], wanted[1]
    files = {
        filename: (directory / filename).read_text()
        for filename in wanted
        if (directory / filename).exists()
    }
    if entry not in files:
        raise CubicleError(f"{entry} is required for a {fn['runtime_label']} function.")

    print(f"  bundling       {len(files)} files · {sum(len(f) for f in files.values())} B")
    if deps not in files:
        # A deploy merges onto the previous version rather than replacing it,
        # so a file deleted locally is still deployed.
        print(paint(f"  note           no {deps} here, the deployed one is kept", "dim"))

    result = request(
        profile,
        "POST",
        f"/api/functions/{fn['id']}/deploy",
        body={"files": files},
        # The build runs inside this request, so the client has to be willing
        # to wait for a cold dependency install rather than abandon a build
        # that is going to succeed without it.
        timeout=BUILD_TIMEOUT,
    )

    # The deploy answers with the function, and a function's version is the one
    # currently serving traffic: a build that fails leaves the previous version
    # in place and untouched. So reading the outcome off this response reports
    # the last good build as though it were the one just pushed, and a broken
    # deploy exits 0. The version that was just built is the newest row of the
    # listing, which is ordered newest first.
    built = request(profile, "GET", f"/api/functions/{fn['id']}/versions")[0]

    if built["status"] == "ready":
        print(f"  building       {built['build_ms']}ms")
        print(f"  {paint('deployed', 'green')}       {result['url']} (v{built['number']})")
        return 0

    print(paint(f"  build failed   v{built['number']} was not deployed", "red"))
    print(built["build_log"] or paint("  (this build wrote no log)", "dim"))
    # Nothing went out of service, which is the second thing worth knowing when
    # a deploy fails and the reason the exit code is the only sign of it.
    if result["version_status"] == "ready":
        print(paint(f"  v{result['version']} is still serving", "dim"))
    return 1


def cmd_invoke(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    fn = find_function(profile, args.target)

    body = None
    if args.data:
        raw = Path(args.data[1:]).read_text() if args.data.startswith("@") else args.data
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as error:
            raise CubicleError(f"--data is not valid JSON: {error}") from None

    result = request(
        profile,
        "POST",
        f"/api/functions/{fn['id']}/test",
        body={"body": body, "session_id": args.session},
    )

    colour = "green" if result["status_code"] < 400 else "red"
    print(
        f"\n  {paint(str(result['status_code']), colour)} · {result['duration_ms']:.0f}ms"
        f"{' · cold start' if result['cold'] else ''}\n"
    )
    if result["logs"]:
        for line in result["logs"]:
            print(paint(f"  {line}", "dim"))
        print()
    # A handler that raised has no body, so without this the whole answer to
    # "why did that fail" was the word null.
    if result.get("error"):
        print(paint(f"  {result['error']}", "red"))
        print()
    print(json.dumps(result["body"], indent=2))
    print()
    return 0 if result["status_code"] < 400 else 1


def cmd_logs(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    wanted = _log_function(args.function)
    if args.follow:
        print(paint("  tailing — ctrl-c to stop", "dim"))
        # The stream filters by level and nothing else, so the other two
        # filters are applied here rather than left as flags that silently do
        # nothing when --follow is passed.
        for batch in stream(profile, "/api/logs/stream", params={"level": args.level}):
            for entry in batch:
                if _matches(entry, wanted, args.search):
                    _print_log(entry)
        return 0

    page = request(
        profile,
        "GET",
        "/api/logs",
        params={
            "level": args.level,
            "function": wanted,
            "search": args.search,
            # Checked against the endpoint's own bounds so a number outside
            # them is a sentence rather than FastAPI's list of validation
            # errors. The ceiling on lines used to be a thousand and is now
            # five hundred, so `--limit 1000` is a number people already have
            # in scripts. Upstream puts no ceiling on the offset at all, and a
            # page of logs a billion lines in is a typo as well.
            "limit": bounded(args.limit, "--limit", 1, 500),
            "offset": bounded(args.offset, "--offset", 0, 1_000_000_000),
        },
    )
    # /api/logs answers with a page, not a list. Its rows come newest first so
    # that a limit keeps the most recent ones; a terminal is read downwards,
    # so they are printed oldest first.
    items = page["items"]
    for entry in reversed(items):
        _print_log(entry)

    seen = args.offset + len(items)
    if page["total"] > seen:
        print(paint(f"\n  {page['total'] - seen} older lines · --offset {seen}", "dim"))
    return 0


def cmd_env(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    if args.env_command == "ls":
        rows = [
            [item["key"], item["value"], "secret" if item["is_secret"] else "plain"]
            for item in request(profile, "GET", "/api/env")
        ]
        print()
        print(table(["key", "value", "type"], rows))
        print()
        return 0

    if args.env_command == "set":
        if "=" not in args.assignment:
            raise CubicleError("Use KEY=value.")
        key, value = args.assignment.split("=", 1)
        request(
            profile, "POST", "/api/env", body={"key": key, "value": value, "is_secret": args.secret}
        )
        # The API decides the name it is filed under, so this echoes what it
        # stored rather than what was typed: `stripe-key` is STRIPE_KEY there,
        # and printing STRIPE-KEY would teach a name that removes nothing.
        print(f"  {paint('set', 'green')} {env_key(key)}")
        return 0

    key = env_key(args.key)
    request(profile, "DELETE", f"/api/env/{key}")
    print(f"  {paint('removed', 'green')} {key}")
    return 0


def cmd_secrets(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    fn = find_function(profile, args.function)

    if args.secrets_command == "ls":
        rows = [
            [item["key"], item["value"]]
            for item in request(profile, "GET", f"/api/functions/{fn['id']}/secrets")
        ]
        print()
        print(table(["key", "value"], rows))
        print()
        return 0

    if args.secrets_command == "set":
        value = getpass.getpass("value: ")
        request(
            profile,
            "POST",
            f"/api/functions/{fn['id']}/secrets",
            body={"key": args.key, "value": value},
        )
        print(f"  {paint('sealed', 'green')} {env_key(args.key)}")
        return 0

    # The same normalisation the write path applies, because a secret is
    # addressed by name in the path and the name in the store is the upper-case
    # one. Without it `secrets rm stripe_key` deletes nothing while printing
    # that it did, which used to be entirely silent: the endpoint answered 204
    # whether or not a row matched.
    key = env_key(args.key)
    request(profile, "DELETE", f"/api/functions/{fn['id']}/secrets/{key}")
    print(f"  {paint('removed', 'green')} {key}")
    return 0


# ── helpers ──────────────────────────────────────────────────────────────────


def _runtime(profile: Profile, key: str) -> dict:
    """The instance's record for a runtime key, or a message listing the real ones."""
    catalogue = list_runtimes(profile)
    for spec in catalogue:
        if spec["key"] == key:
            return spec
    known = ", ".join(spec["key"] for spec in catalogue)
    raise CubicleError(f"No {key} runtime on this instance. It has: {known}.")


def _ceilings(resources: dict) -> list[tuple[str, str]]:
    """Quota lines, for the resources that actually have a ceiling.

    A cluster with no quota has no denominator to show, so it gets no line
    rather than a misleading zero. These are the numbers that explain a 507
    from a deploy.
    """
    rows = []
    for label, unit, digits in (("memory", "MB", 0), ("cpu", "cores", 2)):
        headroom = resources.get(label) or {}
        if headroom.get("limited"):
            held = f"{headroom['held']:.{digits}f}"
            cap = f"{headroom['cap']:.{digits}f}"
            rows.append((label, f"{held}/{cap} {unit} ({headroom['pct']:.0f}%)"))
    return rows


def _version_cell(fn: dict) -> str:
    """`v3 ready`, unless the function is paused and that is the fact that matters."""
    if fn.get("status") != "active":
        return f"v{fn['version']} {fn['status']}"
    return f"v{fn['version']} {fn['version_status']}"


def _log_function(target: str | None) -> str | None:
    """The name a log line is filed under, from either spelling of --function.

    A log row carries `function_name` and no namespace, so the namespace cannot
    take part in the filter either here or in the API. Both spellings are still
    accepted, because every other --function in this CLI takes
    <namespace>/<function> and a flag that means one thing under `logs` and
    another under `secrets` and `schedule` is how a filter comes to match
    nothing at all without saying so.
    """
    if target and "/" in target:
        return split_target(target)[1]
    return target


def _matches(entry: dict, function: str | None, search: str | None) -> bool:
    if function and entry.get("function_name") != function:
        return False
    return not search or search.lower() in entry.get("message", "").lower()


def _print_log(entry: dict) -> None:
    colour = {"ERROR": "red", "WARN": "yellow", "INFO": "blue"}.get(entry.get("level", ""), "dim")
    print(
        f"  {paint(entry.get('time', ''), 'dim')} "
        f"{paint(entry.get('level', '').ljust(5), colour)} "
        f"{entry.get('function_name', '').ljust(20)[:20]} "
        f"{entry.get('message', '')} "
        f"{paint(entry.get('duration') or '', 'dim')}"
    )


COMMANDS = {
    "login": cmd_login,
    "clusters": cmd_clusters,
    "status": cmd_status,
    "ls": cmd_ls,
    "init": cmd_init,
    "deploy": cmd_deploy,
    "invoke": cmd_invoke,
    "logs": cmd_logs,
    "env": cmd_env,
    "secrets": cmd_secrets,
}
