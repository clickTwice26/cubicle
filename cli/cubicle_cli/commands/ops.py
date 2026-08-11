"""Keeping an instance healthy: updates, drift, and what the month came to.

These are the commands an operator runs on a production box, often over the one
connection into it, so each one says what it is about to do, asks before doing
anything that cannot be taken back, and reports what actually changed rather
than that the call returned.

The two that change something are unusual in opposite ways. Applying an update
restarts the control plane being talked to, so the connection dropping is the
command working. Applying a reconcile re-scans first and acts on what it finds
then, so what comes back is the truth about a slightly later moment than the
report the operator read.
"""

from __future__ import annotations

import argparse

from ..client import (
    BUILD_TIMEOUT,
    CubicleError,
    Profile,
    confirm,
    confirmable,
    load_profile,
    paint,
    poll,
    record,
    request,
    table,
)

ORDER = 40

#: How this program is updated, as opposed to the instance it talks to.
#:
#: `pipx upgrade` re-resolves the git ref and swaps the commit, which is what
#: is wanted. It then reports "already at latest version 1.0.0", because the
#: version string does not move between commits and that is the only thing it
#: compares. The line to read is the `-` and `+` pair above it, which names the
#: commit that went and the one that arrived.
CLI_UPGRADE = "pipx upgrade cubicle-cli"

#: When the version really has not moved and pipx declines to do anything, or
#: the install came from pip rather than pipx.
CLI_UPGRADE_FORCED = (
    'pipx install --force "git+https://github.com/clickTwice26/cubicle.git#subdirectory=cli"'
)


def register(sub: argparse._SubParsersAction) -> None:
    update = sub.add_parser("update", help="Check whether the branch has moved on.")
    update.add_argument(
        "--refresh",
        action="store_true",
        help="Ask GitHub again rather than reuse the instance's cached answer.",
    )
    update_sub = update.add_subparsers(dest="update_command")
    update_sub.add_parser(
        "apply",
        parents=[confirmable()],
        help="Rebuild and restart this instance from the branch.",
    )

    reconcile = sub.add_parser("reconcile", help="Show where the record and Docker disagree.")
    reconcile_sub = reconcile.add_subparsers(dest="reconcile_command")
    reconcile_apply = reconcile_sub.add_parser(
        "apply", parents=[confirmable()], help="Fix findings. Safe ones by default."
    )
    reconcile_apply.add_argument(
        "ids",
        nargs="*",
        help="Finding ids from `cubicle reconcile`. With none, every fixable safe finding.",
    )

    metering = sub.add_parser("metering", help="This month's usage for the cluster.")
    metering.add_argument("--csv", action="store_true", help="Write the export as CSV instead.")


# ── commands ─────────────────────────────────────────────────────────────────


def cmd_update(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    if args.update_command == "apply":
        return _update_apply(profile, assume_yes=args.yes)

    # The answer is cached for fifteen minutes upstream to stay inside GitHub's
    # unauthenticated rate limit, so asking again is a flag rather than the
    # default.
    status = request(
        profile, "GET", "/api/update", params={"refresh": "true" if args.refresh else None}
    )
    print()
    print(record(_update_rows(status)))

    # A check that could not be made comes back 200 with `error` filled in and
    # available=false, which is indistinguishable from up to date unless this
    # says so.
    if status["error"]:
        print(f"\n  {paint('WARN', 'yellow')} {status['error']}\n")
        return 1

    if status["available"]:
        print(
            f"\n  {paint('INFO', 'blue')} `cubicle update apply` rebuilds and restarts "
            "this instance"
        )
    else:
        print(f"\n  {paint('up to date', 'green')}")
    if status["cached"]:
        print(paint("  answered from the instance's cached check; --refresh asks again", "dim"))

    # This command is about the instance, and somebody reading it is often
    # asking about this program. They are updated separately and the names are
    # close enough that saying so once is cheaper than the confusion.
    print(
        paint(
            f"\n  this updates the instance, not the CLI. To update the CLI:\n"
            f"    {CLI_UPGRADE}\n"
            f"  `cubicle --version` names the commit, which is what actually moves",
            "dim",
        )
    )
    print()
    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    # Instance-wide rather than cluster-scoped: most drift has no cluster, so
    # each finding says which one it belongs to instead of the header doing it.
    report = request(profile, "GET", "/api/reconcile")
    if args.reconcile_command == "apply":
        return _reconcile_apply(profile, report, args.ids, assume_yes=args.yes)

    print()
    if not report["findings"]:
        print(f"  {paint('in sync', 'green')}        the record and Docker agree")
        print()
        return 0

    for finding in report["findings"]:
        _print_finding(finding)
    print(
        paint(
            f"\n  {report['errors']} breaking · {report['warnings']} wasteful · "
            f"{report['fixable']} fixable by `cubicle reconcile apply`",
            "dim",
        )
    )
    print()
    return 0


def cmd_metering(args: argparse.Namespace) -> int:
    profile = load_profile(args.url, args.token, args.cluster)
    if args.csv:
        # text/csv with a filename attached, so it is read as bytes and passed
        # through untouched rather than decoded as JSON.
        payload = request(profile, "GET", "/api/cluster/metering/export.csv", raw=True)
        print(payload.decode(), end="")
        return 0

    usage = request(profile, "GET", "/api/cluster/metering")
    window = (
        f"{usage['window_start'][:10]} to {usage['window_end'][:10]} "
        f"({usage['window_progress']:.0f}% through)"
    )
    print()
    print(
        record(
            [
                ("cluster", usage["cluster"]),
                ("window", window),
                ("invocations", usage["invocations_label"]),
                ("compute", f"{usage['gb_seconds_label']} GB-seconds"),
                ("egress", usage["egress_label"]),
                ("storage", usage["storage_label"]),
                ("warm isolates", str(usage["warm_isolates"])),
            ]
        )
    )
    print()
    rows = [
        [namespace["name"], namespace["invocations_label"], namespace["gb_seconds_label"]]
        for namespace in usage["namespaces"]
    ]
    print(table(["namespace", "invocations", "gb-seconds"], rows))
    cost = usage["cost"]
    print(
        paint(
            f"\n  ${cost['self_hosted_total']:.2f} of electricity, against "
            f"${cost['avoided_vs_aws']:.2f} more at AWS Lambda list prices "
            f"({cost['rates_as_of']})",
            "dim",
        )
    )
    print()
    return 0


# ── helpers ──────────────────────────────────────────────────────────────────


def _sha(sha: str) -> str:
    """A commit as an operator refers to it, or a word saying it is not known."""
    return sha[:7] if sha else "(unknown)"


def _update_rows(status: dict) -> list[tuple[str, str]]:
    """What is deployed against what is on the branch.

    The commit lines are only there when GitHub answered, because an instance
    that cannot be checked still has a branch and a deployed commit worth
    printing and no newest commit to name.
    """
    rows = [
        ("repo", status["repo"] or "(no GitHub remote)"),
        ("branch", status["branch"] or "(unknown)"),
        ("deployed", _sha(status["current"])),
        ("latest", _sha(status["latest"])),
    ]
    if status["message"]:
        rows.append(("commit", status["message"]))
    byline = ", ".join(part for part in (status["author"], status["date"][:10]) if part)
    if byline:
        rows.append(("author", byline))
    return rows


def _update_apply(profile: Profile, *, assume_yes: bool) -> int:
    """Rebuild this instance from the branch and wait for the container doing it.

    The updater runs in a container of its own precisely because it replaces
    the one answering this request, so the control plane disappears partway
    through. That is why the progress endpoint reads the updater's logs rather
    than any state of its own: it is the one thing still true on the other side
    of the restart.
    """
    # The cached check on purpose. This is about to fetch on the host anyway,
    # and naming the commit is worth more than being five minutes fresher at
    # the cost of a GitHub call the operator did not ask for.
    status = request(profile, "GET", "/api/update")
    if status["error"]:
        print(f"  {paint('WARN', 'yellow')} {status['error']}")
    elif status["available"]:
        print(
            f"  {paint('INFO', 'blue')} {_sha(status['current'])} to {_sha(status['latest'])} · "
            f"{status['message']}"
        )
    else:
        print(
            f"  {paint('INFO', 'blue')} already at {_sha(status['current'])}, so this rebuilds "
            "the same commit"
        )

    if not confirm("Rebuild and restart this instance now?", assume_yes=assume_yes):
        print(paint("  nothing applied", "dim"))
        return 1

    request(profile, "POST", "/api/update/apply")
    print(paint("  the control plane restarts during this, so the connection will drop", "dim"))

    progress = poll(
        lambda: _progress(profile),
        done=lambda state: state["state"] in {"success", "failed"},
        # A rebuild of every image, on hardware nobody chose for its build
        # times. The wait is the same one a deploy is given.
        timeout=BUILD_TIMEOUT,
        interval=5.0,
    )

    print()
    print(paint("\n".join(progress["logs"].strip().splitlines()[-12:]), "dim"))
    print()
    if progress["state"] == "failed":
        print(paint("  update failed", "red"))
        if progress["exit_code"] == 2:
            print("  the checkout has local changes to tracked files, so nothing was applied")
        return 1

    landed = status["latest"][:7] or "the branch tip"
    print(f"  {paint('updated', 'green')}        this instance is now on {landed}")
    return 0


def _progress(profile: Profile) -> dict:
    """The updater's state, reading a dropped connection as work in progress.

    This polls the process that is being restarted. Anything that cannot answer
    right now is the update doing what it was asked to do, so it counts as
    running rather than as a failure; the short timeout is so a connection that
    is refused slowly does not stall the poll.
    """
    try:
        return request(profile, "GET", "/api/update/progress", timeout=10.0)
    except (CubicleError, OSError):
        return {"state": "running", "logs": "", "exit_code": None}


def _print_finding(finding: dict) -> None:
    """One finding: what is wrong, then which id fixes it and what fixing does."""
    colour = {"error": "red", "warn": "yellow"}.get(finding["severity"], "blue")
    where = f"{finding['cluster']} · " if finding["cluster"] else ""
    print(f"  {paint(finding['severity'].upper().ljust(5), colour)} {finding['summary']}")
    print(paint(f"        {where}{finding['id']} · {finding['fix'] or 'no automatic fix'}", "dim"))


def _reconcile_apply(profile: Profile, report: dict, ids: list[str], *, assume_yes: bool) -> int:
    """Apply chosen findings, or every safe one, and say what each of them did.

    Choosing nothing means every finding that has a fix and destroys nothing,
    which is the set the console's own fix-all covers. A finding that destroys
    data has to be named, and one with no fix is refused here rather than sent:
    the API ignores those silently, and a silent no-op is the worst answer to
    give someone who just asked for something to be repaired.
    """
    findings = {finding["id"]: finding for finding in report["findings"]}
    unknown = [wanted for wanted in ids if wanted not in findings]
    if unknown:
        raise CubicleError(
            f"This instance has no finding called {', '.join(unknown)}. "
            "`cubicle reconcile` lists the current ones."
        )

    chosen = (
        [findings[wanted] for wanted in ids]
        if ids
        else [f for f in report["findings"] if f["fix"] and not f["destructive"]]
    )
    unfixable = [finding["id"] for finding in chosen if not finding["fix"]]
    if unfixable:
        raise CubicleError(
            f"{', '.join(unfixable)} has no automatic fix, so applying it would do nothing. "
            "It needs a decision rather than a command."
        )
    if not chosen:
        print(paint("  nothing to fix", "dim"))
        return 0

    print()
    for finding in chosen:
        destroys = paint("  destroys data", "yellow") if finding["destructive"] else ""
        print(f"  {finding['fix']}{destroys}")
        print(paint(f"    {finding['id']} · {finding['summary']}", "dim"))
    print()

    destructive = [finding for finding in chosen if finding["destructive"]]
    question = f"Apply {len(chosen)} fix{'' if len(chosen) == 1 else 'es'}?"
    if destructive:
        question += f" {len(destructive)} of them cannot be undone."
    if not confirm(question, assume_yes=assume_yes):
        print(paint("  nothing applied", "dim"))
        return 1

    result = request(
        profile,
        "POST",
        "/api/reconcile/apply",
        body={"ids": [finding["id"] for finding in chosen]},
        # Three full scans of every node in one request, and a node that is not
        # answering is exactly the sort of thing being reconciled.
        timeout=BUILD_TIMEOUT,
    )

    for applied in result["applied"]:
        print(f"  {paint('fixed', 'green')}          {findings[applied]['summary']}")
    for failure in result["failed"]:
        print(f"  {paint('failed', 'red')}         {failure['id']}: {failure['error']}")
    for skipped in result["skipped"]:
        print(paint(f"  skipped        {skipped} resolved itself before this ran", "dim"))

    left = result["report"]
    print(paint(f"\n  {left['errors']} breaking · {left['warnings']} wasteful left", "dim"))
    print()
    return 1 if result["failed"] else 0


COMMANDS = {"update": cmd_update, "reconcile": cmd_reconcile, "metering": cmd_metering}
