"""What one function is doing right now, and the settings that govern it.

Everything here addresses a single function by `<namespace>/<function>`, which
`find_function` turns into the id the API wants. The read commands answer the
two questions a pager wakes you up with, which containers are alive and what
the last builds did, and the write commands are the knobs those answers make
you want to reach for.

`scale` matters more than it used to. The isolate pool no longer starts a
container the moment every warm one is busy: it first waits for the busy one
if it is due back sooner than a cold start would take, so `max_instances` is a
ceiling that the pool grows towards under sustained load rather than a target
it fills on the first burst.

Bounds are checked here as well as in the API. FunctionUpdate is stricter than
FunctionCreate, min_instances stops at 20 and max_instances at 32 where
creation allows 64 of each, and a 422 answers a typo with a JSON list of
validation errors rather than a sentence.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from ..client import (
    CubicleError,
    Profile,
    bounded,
    confirm,
    confirmable,
    find_function,
    list_runtimes,
    load_profile,
    paint,
    record,
    request,
    table,
)

ORDER = 10

METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]

#: Eight rows of block, which is enough resolution to see a spike and cheap
#: enough to sit inside a label/value block.
BLOCKS = "▁▂▃▄▅▆▇█"


def register(sub: argparse._SubParsersAction) -> None:
    instances = sub.add_parser("instances", help="Show the containers serving a function.")
    instances.add_argument("target", help="<namespace>/<function>")

    kill = sub.add_parser("kill", parents=[confirmable()], help="Destroy one isolate.")
    kill.add_argument("target", help="<namespace>/<function>")
    kill.add_argument("isolate", help="Container id, as `cubicle instances` prints it.")

    scale = sub.add_parser("scale", help="Set how many isolates a function may run.")
    scale.add_argument("target", help="<namespace>/<function>")
    scale.add_argument(
        "--min", type=int, default=None, dest="min_instances", help="Warm instances, 0 to 20."
    )
    scale.add_argument(
        "--max", type=int, default=None, dest="max_instances", help="Ceiling, 1 to 32."
    )

    config = sub.add_parser("config", help="Show or change a function's settings.")
    config.add_argument("target", help="<namespace>/<function>")
    config.add_argument("--memory", type=int, default=None, help="MB per isolate, 32 to 8192.")
    config.add_argument("--timeout", type=int, default=None, help="Seconds per call, 1 to 900.")
    config.add_argument(
        "--idle", type=int, default=None, help="Idle seconds before reclaim, 0 for the default."
    )
    config.add_argument(
        "--auth", choices=["true", "false"], default=None, help="Require a token to invoke."
    )
    config.add_argument(
        "--method", choices=METHODS, default=None, help="HTTP method the function answers on."
    )
    config.add_argument(
        "--ctx",
        choices=["rw", "r", "w", "none"],
        default=None,
        help="What the handler may do with its context store.",
    )
    config.add_argument(
        "--type",
        choices=["dependent", "independent"],
        dest="function_type",
        help="Independent functions need no request body, so they can be scheduled.",
    )
    config.add_argument("--pool", default=None, help="Node pool to schedule on.")
    config.add_argument("--runtime", default=None, help="Runtime key. Rebuilds the version.")

    pause = sub.add_parser("pause", help="Stop serving and drain the isolates.")
    pause.add_argument("target", help="<namespace>/<function>")

    resume = sub.add_parser("resume", help="Serve again after a pause.")
    resume.add_argument("target", help="<namespace>/<function>")

    versions = sub.add_parser("versions", help="List a function's builds.")
    versions.add_argument("target", help="<namespace>/<function>")
    versions.add_argument(
        "--log", type=int, default=None, metavar="N", help="Print version N's build log."
    )

    metrics = sub.add_parser("metrics", help="Latency, errors and cold starts over a window.")
    metrics.add_argument("target", help="<namespace>/<function>")
    metrics.add_argument("--hours", type=int, default=24, help="Window in hours, 1 to 720.")

    rm = sub.add_parser(
        "rm", parents=[confirmable()], help="Delete a function and every version of it."
    )
    rm.add_argument("target", help="<namespace>/<function>")


# ── commands ─────────────────────────────────────────────────────────────────


def cmd_instances(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    fn = find_function(profile, args.target)
    state = request(profile, "GET", f"/api/functions/{fn['id']}/isolates")
    running = state["isolates"]

    rows = [
        [
            isolate["id"],
            isolate["node"],
            "busy" if isolate["busy"] else "idle",
            _duration(isolate["age_s"]),
            _duration(isolate["idle_s"]),
            str(isolate["invocations"]),
            f"{isolate['memory_mb']} MB",
        ]
        for isolate in running
    ]
    print()
    print(table(["isolate", "node", "state", "age", "idle", "served", "memory"], rows))
    # An empty pool is the normal resting state of a function nobody is
    # calling, so the counts go underneath whether or not there is a table.
    print(
        paint(
            f"\n  {len(running)} running of max {state['max_instances']} · "
            f"{state['min_instances']} kept warm · v{state['version']}",
            "dim",
        )
    )
    print()
    return 0


def cmd_kill(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    fn = find_function(profile, args.target)
    # Look the isolate up before asking about it. A mistyped id would otherwise
    # be a 404 after the confirmation, and knowing whether the container is
    # mid-request is the whole difference between a free reclaim and a failed
    # customer call.
    listing = request(profile, "GET", f"/api/functions/{fn['id']}/isolates")["isolates"]
    isolate = next((entry for entry in listing if entry["id"] == args.isolate), None)
    if isolate is None:
        raise CubicleError(
            f"No isolate {args.isolate} on {args.target}. "
            f"Run `cubicle instances {args.target}` for the ones there are."
        )

    doing = (
        "serving a request right now"
        if isolate["busy"]
        else f"idle for {_duration(isolate['idle_s'])}"
    )
    if not confirm(f"Destroy {args.isolate} on {isolate['node']}, {doing}?", assume_yes=args.yes):
        print(paint("  cancelled", "dim"))
        return 1

    request(profile, "DELETE", f"/api/functions/{fn['id']}/isolates/{args.isolate}")
    print(f"  {paint('removed', 'green')} isolate {args.isolate}")
    return 0


def cmd_scale(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    if args.min_instances is None and args.max_instances is None:
        raise CubicleError("Nothing to change. Pass --min, --max or both.")

    fn = find_function(profile, args.target)
    changes: dict[str, int] = {}
    if args.min_instances is not None:
        changes["min_instances"] = bounded(args.min_instances, "--min", 0, 20)
    if args.max_instances is not None:
        changes["max_instances"] = bounded(args.max_instances, "--max", 1, 32)

    # The API refuses this too, but it can only refuse the pair it ends up
    # with, and half of that pair is whatever the function already had.
    floor = changes.get("min_instances", fn["min_instances"])
    ceiling = changes.get("max_instances", fn["max_instances"])
    if ceiling < floor:
        raise CubicleError(
            f"A ceiling of {ceiling} is below the {floor} warm instance(s) this function "
            "keeps resident. Raise --max or lower --min."
        )

    updated = request(profile, "PATCH", f"/api/functions/{fn['id']}", body=changes)
    print(
        f"  {paint('set', 'green')} {args.target} to "
        f"{updated['min_instances']}-{updated['max_instances']} instances"
    )
    if "max_instances" in changes:
        print(
            paint(
                "  a ceiling, not a target: the pool waits for a busy isolate when one is due "
                "back\n  sooner than a cold start, and grows only under load that outlasts it",
                "dim",
            )
        )
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    fn = find_function(profile, args.target)
    changes = _changes(args)

    if not changes:
        print()
        print(record(_settings(fn)))
        print()
        return 0

    spec = _runtime(profile, args.runtime) if args.runtime else None
    request(profile, "PATCH", f"/api/functions/{fn['id']}", body=changes)
    for key, value in changes.items():
        print(f"  {paint('set', 'green')} {key} {value}")

    if spec is not None:
        # The rebuild is an asyncio task the PATCH does not wait for, and the
        # record it answers with still carries the old version_status, so there
        # is nothing here worth polling for: the build log is the answer.
        print(
            paint(
                f"  rebuilding the current version as {spec['label']} in the background;\n"
                f"  `cubicle versions {args.target}` has the result",
                "dim",
            )
        )
        # A runtime change rewrites nothing on disk, so the bundle that built
        # under Python is still handler.py when node22 goes looking for
        # handler.js.
        print(paint("  the files are kept as they are; deploy this runtime's bundle next", "dim"))
        if not spec["installed"]:
            print(f"  {paint('note', 'dim')}    {spec['label']} is not installed on this instance")
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    fn = find_function(profile, args.target)
    request(profile, "PATCH", f"/api/functions/{fn['id']}", body={"status": "paused"})
    print(f"  {paint('paused', 'green')} {args.target}")
    print(paint("  every isolate was drained; calls are refused until it is resumed", "dim"))
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    fn = find_function(profile, args.target)
    updated = request(profile, "PATCH", f"/api/functions/{fn['id']}", body={"status": "active"})
    print(f"  {paint('resumed', 'green')} {args.target} on v{updated['version']}")
    return 0


def cmd_versions(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    fn = find_function(profile, args.target)
    # The listing carries every build log with it, so asking for one costs no
    # second call: this is the same response, read differently.
    builds = request(profile, "GET", f"/api/functions/{fn['id']}/versions")

    if args.log is not None:
        wanted = next((build for build in builds if build["number"] == args.log), None)
        if wanted is None:
            raise CubicleError(
                f"No v{args.log} of {args.target}. The API keeps the last 25 builds, "
                f"and this function has {len(builds)}."
            )
        print()
        print(wanted["build_log"] or paint("  (this build wrote no log)", "dim"))
        print()
        return 0

    rows = [
        [
            ("* " if build["number"] == fn["version"] else "  ") + f"v{build['number']}",
            build["status"],
            f"{build['build_ms']}ms",
            _stamp(build["created_at"]),
            _stamp(build["deployed_at"]),
        ]
        for build in builds
    ]
    print()
    print(table(["version", "status", "build", "created", "deployed"], rows))
    print(paint("\n  * serving now · --log N prints one build's log", "dim"))
    print()
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    # The API declares no bounds on `hours` at all, so an accidental 0 or a
    # negative reaches the query as it was typed.
    hours = bounded(args.hours, "--hours", 1, 720)
    fn = find_function(profile, args.target)
    data = request(profile, "GET", f"/api/functions/{fn['id']}/metrics", params={"hours": hours})
    stats = data["stats"]

    rows = [
        ("window", f"{hours}h to now"),
        # The percentiles say how bad it got and the series says when, which is
        # the difference between a slow function and a function that was slow
        # at nine this morning.
        ("invocations", f"{stats['invocations_label']}  {_spark(_totals(data['invocations']))}"),
        ("p95", f"{stats['p95']}  {_spark([bucket['p95'] for bucket in data['latency']])}"),
        ("p50 / p99", f"{stats['p50']} / {stats['p99']}"),
        ("errors", stats["error_rate"]),
        ("cold starts", stats["cold_rate"]),
        ("gb seconds", f"{stats['gb_seconds']:.3f}"),
        ("last invocation", _stamp(stats["last_invocation"])),
    ]
    print()
    print(record(rows, label_width=18))
    print()
    return 0


def cmd_rm(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    fn = find_function(profile, args.target)
    target = f"{fn['namespace']}/{fn['name']}"
    if not _confirm_name(target, assume_yes=args.yes):
        print(paint("  cancelled", "dim"))
        return 1

    request(profile, "DELETE", f"/api/functions/{fn['id']}")
    print(f"  {paint('removed', 'green')} {target} and every version of it")
    return 0


# ── helpers ──────────────────────────────────────────────────────────────────


def _changes(args: argparse.Namespace) -> dict[str, object]:
    """The FunctionUpdate body for whichever flags were given.

    PATCH is exclude_unset, so a key that is absent here is left exactly as it
    was. That is why every flag defaults to None rather than to the value it
    usually has: a default would quietly rewrite a setting nobody named.
    """
    changes: dict[str, object] = {}
    if args.memory is not None:
        changes["memory_mb"] = bounded(args.memory, "--memory", 32, 8192)
    if args.timeout is not None:
        changes["timeout_s"] = bounded(args.timeout, "--timeout", 1, 900)
    if args.idle is not None:
        changes["idle_timeout_s"] = bounded(args.idle, "--idle", 0, 86400)
    if args.auth is not None:
        changes["auth_required"] = args.auth == "true"
    if args.method:
        changes["method"] = args.method
    if args.ctx:
        changes["ctx_access"] = args.ctx
    if args.function_type:
        changes["function_type"] = args.function_type
    if args.pool:
        changes["node_pool"] = args.pool
    if args.runtime:
        changes["runtime"] = args.runtime
    return changes


def _settings(fn: dict) -> list[tuple[str, str]]:
    """One function's configuration as the label/value block.

    Built from the listing record `find_function` already fetched. The detail
    endpoint would say the same things and drop the cluster, so a second call
    would buy nothing.
    """
    # An idle timeout of zero means "whatever the instance says", and the
    # number it resolves to is the one an operator is actually asking about.
    idle = (
        f"{fn['idle_timeout_s']}s"
        if fn["idle_timeout_s"]
        else f"{fn['effective_idle_timeout_s']}s (instance default)"
    )
    return [
        ("function", f"{fn['namespace']}/{fn['name']}"),
        ("url", fn["url"]),
        ("method", fn["method"]),
        ("runtime", f"{fn['runtime_label']} ({fn['runtime']})"),
        ("type", fn["function_type"]),
        ("context", fn["ctx_access"]),
        ("auth", "required" if fn["auth_required"] else "open"),
        ("memory", f"{fn['memory_mb']} MB"),
        ("timeout", f"{fn['timeout_s']}s"),
        ("idle timeout", idle),
        ("instances", f"{fn['min_instances']}-{fn['max_instances']}"),
        ("node pool", fn["node_pool"]),
        ("status", fn["status"]),
        ("version", f"v{fn['version']} {fn['version_status']}"),
    ]


def _runtime(profile: Profile, key: str) -> dict:
    """The instance's record for a runtime key, or a message listing the real ones.

    Checked before the PATCH because `runtime` is a schema enum: an unknown key
    is a 422 whose body is a list of error objects, and the seven keys it would
    have accepted are not in it.
    """
    catalogue = list_runtimes(profile)
    for spec in catalogue:
        if spec["key"] == key:
            return spec
    known = ", ".join(spec["key"] for spec in catalogue)
    raise CubicleError(f"No {key} runtime on this instance. It has: {known}.")


def _confirm_name(target: str, *, assume_yes: bool) -> bool:
    """Make deleting a function cost a moment's attention.

    A y/N prompt is answered by muscle memory, and this one takes the versions,
    the secrets and the schedules with it and cannot be undone. So the question
    is answered by typing the name, which is hard to do by accident and hard to
    do to the wrong function.
    """
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise CubicleError(
            f"Deleting {target} removes every version, secret and trigger it has. "
            "There is no terminal to ask; pass --yes to go ahead."
        )
    print(paint(f"  This deletes {target}, its versions, its secrets and its schedules.", "yellow"))
    try:
        typed = input(f"  Type {target} to confirm: ")
    except EOFError:
        # ctrl-d typed nothing, and nothing is not the name.
        return False
    return typed.strip() == target


def _duration(seconds: float) -> str:
    """Elapsed seconds at the precision a glance can use."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m"
    return f"{seconds / 3600:.1f}h"


def _stamp(value: str | None) -> str:
    """An ISO timestamp trimmed to the minute, which is as fine as a build needs."""
    return value.replace("T", " ")[:16] if value else "never"


def _totals(buckets: Sequence[dict]) -> list[float]:
    """Calls per bucket, successful and failed together."""
    return [bucket["ok"] + bucket["err"] for bucket in buckets]


def _spark(values: Sequence[float]) -> str:
    """A series as one line of block characters.

    Scaled to its own peak rather than to an absolute, so it answers "when",
    not "how much"; the number beside it is the one that answers how much.
    """
    peak = max(values, default=0)
    if not peak:
        return paint("(no traffic in this window)", "dim")
    return "".join(BLOCKS[round(value / peak * (len(BLOCKS) - 1))] for value in values)


COMMANDS = {
    "instances": cmd_instances,
    "kill": cmd_kill,
    "scale": cmd_scale,
    "config": cmd_config,
    "pause": cmd_pause,
    "resume": cmd_resume,
    "versions": cmd_versions,
    "metrics": cmd_metrics,
    "rm": cmd_rm,
}
