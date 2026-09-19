"""The public host-script endpoint.

Caddy rewrites ``https://<host>/run/<script>`` onto this router, so what a
caller sees is exactly the URL the console shows them — the same arrangement
:mod:`cubicle.routers.invoke` has for functions, and deliberately the same
shape of rules, because the difference between the two is what happens after
the request is accepted, not what it takes to be accepted.

Everything about who may call this is decided in one place below, and it is
decided before anything about the script is disclosed — including whether it
exists.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select

from .. import clusters as cluster_svc
from .. import scripts as script_svc
from ..deps import DbSession, get_instance
from ..models import Cluster, HostScript
from ..runtime import hostscripts as runtime
from .invoke import HOP_BY_HOP, BodyTooLarge, authorised_for_cluster, read_body

router = APIRouter(prefix="/api/run", tags=["scripts"])

#: How much of a failing run's own output travels back to the caller. A script
#: is owner-written and its URL is either authenticated or deliberately public,
#: so the reason a webhook failed belongs in the response where whoever wired
#: it up will see it — the alternative is an opaque 500 and a trip to the
#: console for every mistake. Anything a script prints on a public endpoint is
#: as public as the endpoint.
ERROR_TAIL = 2000


@router.api_route(
    "/{cluster_slug}/{name}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    summary="Run a host script in a named cluster",
)
async def run_in_cluster(cluster_slug: str, name: str, request: Request, db: DbSession) -> Response:
    cluster = await cluster_svc.by_reference(db, cluster_slug)
    if cluster is None:
        return JSONResponse(
            {"error": "not_found", "message": f"No cluster '{cluster_slug}'."},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return await _run(cluster, name, request, db)


@router.api_route(
    "/{name}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    summary="Run a host script",
)
async def run_script(name: str, request: Request, db: DbSession) -> Response:
    """One-segment form, valid only when the Host names the cluster.

    A cluster with its own ingress domain is fully identified by its hostname.
    Without one, two clusters could each hold a script by this name, so rather
    than picking one this answers with the qualified URLs that would work —
    the same refusal to guess that the function endpoint makes.
    """
    cluster = await cluster_svc.by_domain(db, request.headers.get("host", ""))
    if cluster is not None:
        return await _run(cluster, name, request, db)

    return JSONResponse(
        {
            "error": "cluster_required",
            "message": (
                f"/run/{name} does not name a cluster. Use /run/<cluster>/{name}, "
                "or point a hostname at the cluster."
            ),
            "clusters": await _candidates(db, name),
        },
        status_code=status.HTTP_404_NOT_FOUND,
    )


async def _candidates(db: DbSession, name: str) -> list[str]:
    rows = (
        (
            await db.execute(
                select(Cluster.slug)
                .join(HostScript, HostScript.cluster_id == Cluster.id)
                .where(HostScript.name == name.lower())
                .order_by(Cluster.is_default.desc())
            )
        )
        .scalars()
        .all()
    )
    return [f"/run/{slug}/{name}" for slug in rows]


async def _run(cluster: Cluster, name: str, request: Request, db: DbSession) -> Response:
    if request.method == "OPTIONS":
        return Response(status_code=204, headers={"Allow": "GET, POST, PUT, PATCH, DELETE"})

    script = (
        await db.execute(
            select(HostScript).where(
                HostScript.cluster_id == cluster.id, HostScript.name == name.lower()
            )
        )
    ).scalar_one_or_none()

    # Exactly the ordering the function endpoint uses, for exactly the same
    # reason: a caller with no credential must not be able to tell a script
    # that exists from one that does not, so the credential is checked first
    # and a missing script is treated as though it required one.
    if (script is None or script.auth_required) and not await authorised_for_cluster(
        request, db, cluster
    ):
        return JSONResponse(
            {"error": "unauthorized", "message": "This endpoint requires an API key."},
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    if script is None:
        return JSONResponse(
            {
                "error": "not_found",
                "message": f"No script at /run/{name} in cluster '{cluster.slug}'.",
            },
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # Checked after the credential, and checked here rather than only in the
    # console: turning the feature off has to stop the URLs, or it has not
    # turned anything off.
    instance = await get_instance(db)
    if not instance.host_scripts_enabled:
        return JSONResponse(
            {"error": "disabled", "message": "Host scripts are off for this instance."},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if script.status == "paused":
        return JSONResponse(
            {"error": "paused", "message": "This script is paused."},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if script.method != request.method and request.method != "HEAD":
        return JSONResponse(
            {"error": "method_not_allowed", "message": f"This endpoint accepts {script.method}."},
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
            headers={"Allow": script.method},
        )

    try:
        stdin = await read_body(request)
    except BodyTooLarge:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Request body is too large."
        ) from None

    caller = script_svc.Caller(
        method=request.method,
        path=f"/run/{name}",
        query=dict(request.query_params),
        headers={k.lower(): v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP},
    )

    try:
        done = await script_svc.execute(
            db, cluster, script, trigger="url", caller=caller, stdin=stdin
        )
    except runtime.ScriptError as exc:
        return JSONResponse(
            {"error": "not_run", "message": str(exc)},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    return _respond(done, script, cluster.slug)


def _respond(done: script_svc.Completed, script: HostScript, cluster_slug: str) -> Response:
    outcome = done.outcome
    headers = {
        "X-Cubicle-Run-Id": done.run_id,
        "X-Cubicle-Cluster": cluster_slug,
        "X-Cubicle-Node": done.node_name,
        "X-Cubicle-Exit-Code": str(outcome.exit_code),
        "X-Cubicle-Duration-Ms": f"{outcome.duration_ms:.1f}",
    }

    if not outcome.ok:
        return JSONResponse(
            {
                "error": "timeout" if outcome.timed_out else "script_failed",
                "message": (
                    f"The script ran past its {script.timeout_s}s limit and was stopped."
                    if outcome.timed_out
                    else f"The script exited {outcome.exit_code}."
                ),
                "exit_code": outcome.exit_code,
                "stderr": outcome.stderr_text()[-ERROR_TAIL:],
                "stdout": outcome.stdout_text()[-ERROR_TAIL:],
            },
            status_code=done.status_code,
            headers=headers,
        )

    body, media_type = runtime.interpret_output(outcome.stdout_text(), script.output_mode)
    if body is None:
        # JSON was demanded and the script did not print any. Answering 200
        # with the raw text would hand a caller that parses unconditionally a
        # failure it cannot see.
        return JSONResponse(
            {
                "error": "not_json",
                "message": "This script is set to answer JSON, and what it printed is not JSON.",
                "stdout": outcome.stdout_text()[-ERROR_TAIL:],
            },
            status_code=status.HTTP_502_BAD_GATEWAY,
            headers=headers,
        )

    if media_type == "application/json":
        return JSONResponse(body, status_code=done.status_code, headers=headers)
    return PlainTextResponse(
        body if isinstance(body, str) else json.dumps(body),
        status_code=done.status_code,
        headers=headers,
    )
