"""cubicle — command line client for a self-hosted Cubicle cluster.

Everything here goes through the same HTTP API the console uses; there is no
privileged back channel.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import tomllib
from pathlib import Path

from .client import (
    CubicleError,
    Profile,
    load_profile,
    paint,
    request,
    save_profile,
    stream,
    table,
)

FILES = ("handler.py", "requirements.txt", "cubicle.toml", "README.md")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cubicle", description="Self-hosted serverless functions.", allow_abbrev=False
    )
    parser.add_argument("--url", help="Override the configured instance URL.")
    parser.add_argument("--token", help="Override the configured API token.")
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="Authenticate against an instance.")
    login.add_argument("instance_url")

    sub.add_parser("status", help="Show control plane, node and isolate health.")
    sub.add_parser("ls", help="List namespaces and functions.")

    init = sub.add_parser("init", help="Scaffold a function directory locally.")
    init.add_argument("target", help="<namespace>/<function>")
    init.add_argument("--runtime", default="python312", choices=["python312", "python311"])
    init.add_argument("--method", default="POST", choices=["GET", "POST", "PUT", "DELETE"])

    deploy = sub.add_parser("deploy", help="Deploy the function in a directory.")
    deploy.add_argument("directory", nargs="?", default=".")

    invoke = sub.add_parser("invoke", help="Invoke a function and print the response.")
    invoke.add_argument("target", help="<namespace>/<function>")
    invoke.add_argument("--data", "-d", default=None, help="JSON body, or @file.json")
    invoke.add_argument("--session", default=None)

    logs = sub.add_parser("logs", help="Show or follow logs.")
    logs.add_argument("--follow", "-f", action="store_true")
    logs.add_argument("--level", default="all", choices=["all", "INFO", "WARN", "ERROR"])
    logs.add_argument("--limit", type=int, default=60)

    env = sub.add_parser("env", help="Cluster-wide configuration.")
    env_sub = env.add_subparsers(dest="env_command", required=True)
    env_sub.add_parser("ls")
    env_set = env_sub.add_parser("set")
    env_set.add_argument("assignment", help="KEY=value")
    env_set.add_argument("--secret", action="store_true")
    env_rm = env_sub.add_parser("rm")
    env_rm.add_argument("key")

    secrets = sub.add_parser("secrets", help="Per-function secrets.")
    secrets.add_argument("--function", required=True, help="<namespace>/<function>")
    secrets_sub = secrets.add_subparsers(dest="secrets_command", required=True)
    secrets_sub.add_parser("ls")
    secrets_set = secrets_sub.add_parser("set")
    secrets_set.add_argument("key")
    secrets_rm = secrets_sub.add_parser("rm")
    secrets_rm.add_argument("key")

    args = parser.parse_args(argv)

    try:
        return COMMANDS[args.command](args)
    except CubicleError as error:
        print(paint(f"✗ {error}", "red"), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


# ── commands ─────────────────────────────────────────────────────────────────


def cmd_login(args) -> int:
    url = args.instance_url.rstrip("/")
    token = args.token or getpass.getpass("token: ")
    profile = Profile(url, token.strip())
    me = request(profile, "GET", "/api/auth/me")
    instance = request(profile, "GET", "/api/settings/instance")
    save_profile(profile)
    print(
        f"  {paint('authenticated', 'green')} as {me['email']} · {instance['cluster_name']}\n"
        f"  {paint('saved to', 'dim')} ~/.cubicle/config.toml"
    )
    return 0


def cmd_status(args) -> int:
    profile = load_profile(args.url, args.token)
    health = request(profile, "GET", "/healthz")
    instance = request(profile, "GET", "/api/settings/instance")
    nodes = request(profile, "GET", "/api/cluster/nodes")
    isolates = request(profile, "GET", "/api/cluster/isolates")

    def ok(flag: bool) -> str:
        return paint("ready", "green") if flag else paint("down", "red")

    ready = sum(1 for node in nodes if node["status"] == "ready")
    names = ", ".join(node["name"] for node in nodes)

    print()
    print(f"  CONTROL PLANE   {ok(health['status'] == 'ok')}    v{instance['version']}")
    print(f"  DATABASE        {ok(health['checks']['database'])}")
    print(f"  DOCKER          {ok(health['checks']['docker'])}")
    print(f"  NODES           {paint(f'{ready}/{len(nodes)}', 'green')}      {names}")
    print(f"  ISOLATES        {isolates['count']} warm")
    print(f"  INGRESS         {instance['public_url']}")
    print()
    return 0


def cmd_ls(args) -> int:
    profile = load_profile(args.url, args.token)
    functions = request(profile, "GET", "/api/functions")
    rows = [
        [
            f"{fn['namespace']}/{fn['name']}",
            fn["method"],
            fn["runtime_label"],
            f"v{fn['version']} {fn['version_status']}",
            fn["stats"]["invocations_label"],
            fn["stats"]["p95"],
        ]
        for fn in functions
    ]
    print()
    print(table(["function", "method", "runtime", "version", "invocations", "p95"], rows))
    print()
    return 0


def cmd_init(args) -> int:
    profile = load_profile(args.url, args.token)
    namespace, name = _split(args.target)

    groups = request(profile, "GET", "/api/groups")
    group = next((g for g in groups if g["ns"] == namespace), None)
    if group is None:
        group = request(profile, "POST", "/api/groups", body={"name": namespace})
        print(f"  {paint('created', 'green')} namespace {group['ns']}")

    existing = request(profile, "GET", "/api/functions", params={"group_id": group["id"]})
    fn = next((f for f in existing if f["name"] == name), None)
    if fn is None:
        fn = request(
            profile,
            "POST",
            f"/api/groups/{group['id']}/functions",
            body={"name": name, "runtime": args.runtime, "method": args.method},
        )
        print(f"  {paint('created', 'green')} {namespace}/{name}")

    detail = request(profile, "GET", f"/api/functions/{fn['id']}")
    directory = Path(name)
    directory.mkdir(exist_ok=True)
    for filename, content in detail["files"].items():
        (directory / filename).write_text(content)
        print(f"  {paint('wrote', 'dim')}   {directory / filename}")
    print(f"\n  cd {name} && cubicle deploy\n")
    return 0


def cmd_deploy(args) -> int:
    profile = load_profile(args.url, args.token)
    directory = Path(args.directory).resolve()
    config_path = directory / "cubicle.toml"
    if not config_path.exists():
        raise CubicleError(f"No cubicle.toml in {directory}. Run `cubicle init` first.")

    config = tomllib.loads(config_path.read_text()).get("function", {})
    namespace, name = config.get("namespace"), config.get("name")
    if not namespace or not name:
        raise CubicleError("cubicle.toml is missing function.namespace or function.name.")

    fn = _find_function(profile, namespace, name)
    files = {
        filename: (directory / filename).read_text()
        for filename in FILES
        if (directory / filename).exists()
    }
    if "handler.py" not in files:
        raise CubicleError("handler.py is required.")

    print(f"  bundling       {len(files)} files · {sum(len(f) for f in files.values())} B")
    result = request(profile, "POST", f"/api/functions/{fn['id']}/deploy", body={"files": files})

    if result["version_status"] == "ready":
        print(f"  building       {result['build_ms']}ms")
        print(f"  {paint('deployed', 'green')}       {result['url']} (v{result['version']})")
        return 0

    print(paint("  build failed", "red"))
    print(result.get("build_log", ""))
    return 1


def cmd_invoke(args) -> int:
    profile = load_profile(args.url, args.token)
    namespace, name = _split(args.target)
    fn = _find_function(profile, namespace, name)

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
    print(json.dumps(result["body"], indent=2))
    print()
    return 0 if result["status_code"] < 400 else 1


def cmd_logs(args) -> int:
    profile = load_profile(args.url, args.token)
    if args.follow:
        print(paint("  tailing — ctrl-c to stop", "dim"))
        for batch in stream(profile, "/api/logs/stream", params={"level": args.level}):
            for entry in batch:
                _print_log(entry)
        return 0

    entries = request(
        profile, "GET", "/api/logs", params={"level": args.level, "limit": args.limit}
    )
    for entry in reversed(entries):
        _print_log(entry)
    return 0


def cmd_env(args) -> int:
    profile = load_profile(args.url, args.token)
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
        print(f"  {paint('set', 'green')} {key.upper()}")
        return 0

    request(profile, "DELETE", f"/api/env/{args.key}")
    print(f"  {paint('removed', 'green')} {args.key}")
    return 0


def cmd_secrets(args) -> int:
    profile = load_profile(args.url, args.token)
    namespace, name = _split(args.function)
    fn = _find_function(profile, namespace, name)

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
        print(f"  {paint('sealed', 'green')} {args.key.upper()}")
        return 0

    request(profile, "DELETE", f"/api/functions/{fn['id']}/secrets/{args.key}")
    print(f"  {paint('removed', 'green')} {args.key}")
    return 0


# ── helpers ──────────────────────────────────────────────────────────────────


def _split(target: str) -> tuple[str, str]:
    if "/" not in target:
        raise CubicleError("Use <namespace>/<function>, for example payments/create-charge.")
    namespace, name = target.split("/", 1)
    return namespace.strip("/"), name.strip("/")


def _find_function(profile: Profile, namespace: str, name: str) -> dict:
    functions = request(profile, "GET", "/api/functions")
    for fn in functions:
        if fn["namespace"] == namespace and fn["name"] == name:
            return fn
    raise CubicleError(f"No function at {namespace}/{name}.")


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
    "status": cmd_status,
    "ls": cmd_ls,
    "init": cmd_init,
    "deploy": cmd_deploy,
    "invoke": cmd_invoke,
    "logs": cmd_logs,
    "env": cmd_env,
    "secrets": cmd_secrets,
}


if __name__ == "__main__":
    raise SystemExit(main())
