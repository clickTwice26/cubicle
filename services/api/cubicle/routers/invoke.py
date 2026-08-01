"""The public function endpoint.

Caddy rewrites ``https://<host>/<namespace>/<function>`` onto this router, so
what a caller sees is exactly the URL the console shows them.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .. import clusters as cluster_svc
from .. import security
from ..config import settings
from ..deps import DbSession, _principal_from_api_key
from ..models import Cluster, Function, FunctionVersion, Group, User
from ..runtime import invoker
from ..runtime.nodes import pick_node

router = APIRouter(prefix="/api/invoke", tags=["invoke"])

SESSION_HEADER = "x-cubicle-session"
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "cookie",
    "authorization",
}


@router.api_route(
    "/{cluster_slug}/{namespace}/{name}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    include_in_schema=True,
    summary="Invoke a function in a named cluster",
)
async def invoke_in_cluster(
    cluster_slug: str, namespace: str, name: str, request: Request, db: DbSession
) -> Response:
    cluster = await cluster_svc.by_reference(db, cluster_slug)
    if cluster is None:
        return JSONResponse(
            {"error": "not_found", "message": f"No cluster '{cluster_slug}'."},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return await _invoke(cluster, namespace, name, request, db)


@router.api_route(
    "/{namespace}/{name}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    include_in_schema=True,
    summary="Invoke a function",
)
async def invoke_function(namespace: str, name: str, request: Request, db: DbSession) -> Response:
    """Two-segment form, valid only when the Host names the cluster.

    A cluster with its own ingress domain is fully identified by the hostname,
    so its functions live at ``/<ns>/<fn>``. Without such a host the path is
    ambiguous — every cluster could hold that namespace — so rather than
    guessing, this points the caller at the qualified URL.
    """
    cluster = await cluster_svc.by_domain(db, request.headers.get("host", ""))
    if cluster is not None:
        return await _invoke(cluster, namespace, name, request, db)

    return JSONResponse(
        {
            "error": "cluster_required",
            "message": (
                f"/{namespace}/{name} does not name a cluster. Use "
                f"/<cluster>/{namespace}/{name}, or point a hostname at the cluster."
            ),
            "clusters": await _candidates(db, namespace, name),
        },
        status_code=status.HTTP_404_NOT_FOUND,
    )


async def _candidates(db: DbSession, namespace: str, name: str) -> list[str]:
    """Qualified paths that would actually resolve — a 404 worth reading."""
    rows = (
        (
            await db.execute(
                select(Cluster.slug)
                .join(Group, Group.cluster_id == Cluster.id)
                .join(Function, Function.group_id == Group.id)
                .where(Group.ns == namespace.lower(), Function.name == name.lower())
                .order_by(Cluster.is_default.desc())
            )
        )
        .scalars()
        .all()
    )
    return [f"/{slug}/{namespace}/{name}" for slug in rows]


async def _invoke(
    cluster: Cluster, namespace: str, name: str, request: Request, db: DbSession
) -> Response:
    if request.method == "OPTIONS":
        return Response(status_code=204, headers={"Allow": "GET, POST, PUT, PATCH, DELETE"})

    fn = (
        await db.execute(
            select(Function)
            .options(selectinload(Function.group))
            .join(Group, Group.id == Function.group_id)
            .where(
                Group.cluster_id == cluster.id,
                Group.ns == namespace.lower(),
                Function.name == name.lower(),
            )
        )
    ).scalar_one_or_none()

    if fn is None:
        return JSONResponse(
            {
                "error": "not_found",
                "message": f"No function at /{namespace}/{name} in cluster '{cluster.slug}'.",
            },
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if fn.status == "paused":
        return JSONResponse(
            {"error": "paused", "message": "This function is paused."},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if fn.method != request.method and request.method != "HEAD":
        return JSONResponse(
            {"error": "method_not_allowed", "message": f"This endpoint accepts {fn.method}."},
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
            headers={"Allow": fn.method},
        )

    if fn.auth_required and not await _authorised(request, db, cluster):
        return JSONResponse(
            {"error": "unauthorized", "message": "This endpoint requires an API key."},
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    version = (
        await db.get(FunctionVersion, fn.current_version_id) if fn.current_version_id else None
    )
    if version is None or version.status != "ready":
        return JSONResponse(
            {"error": "not_deployed", "message": "This function has no successful build yet."},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    raw = await request.body()
    if len(raw) > 6 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Request body is too large.")

    content_type = request.headers.get("content-type", "")
    body: object
    if not raw:
        body = None
    elif "json" in content_type:
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            return JSONResponse(
                {"error": "bad_request", "message": "Body is not valid JSON."},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
    else:
        body = raw.decode("utf-8", errors="replace")

    node = await pick_node(db, cluster, fn.node_pool)
    session_id = request.headers.get(SESSION_HEADER) or "sess_" + uuid.uuid4().hex[:12]

    result = await invoker.invoke(
        db,
        cluster=cluster,
        function=fn,
        version=version,
        node=node,
        method=request.method,
        path=f"/{namespace}/{name}",
        headers={k.lower(): v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP},
        query=dict(request.query_params),
        body=body,
        session_id=session_id,
    )

    headers = {
        "X-Cubicle-Request-Id": result.request_id,
        "X-Cubicle-Cluster": cluster.slug,
        "X-Cubicle-Session": session_id,
        "X-Cubicle-Duration-Ms": f"{result.duration_ms:.1f}",
        "X-Cubicle-Cold-Start": "1" if result.cold else "0",
        **{k: v for k, v in result.headers.items() if k.lower() not in HOP_BY_HOP},
    }

    if isinstance(result.body, dict | list) or result.body is None:
        return JSONResponse(result.body, status_code=result.status_code, headers=headers)
    return PlainTextResponse(str(result.body), status_code=result.status_code, headers=headers)


async def _authorised(request: Request, db, cluster: Cluster) -> bool:
    """Whether this caller may invoke a protected function *in this cluster*.

    Being a valid credential somewhere on the instance is not enough. A key
    scoped to staging must not reach production, and an account that was never
    granted a cluster must not reach it either — otherwise the console enforces
    a boundary that the data plane hands straight back.
    """
    token = security.bearer_token(request)
    if token:
        principal = await _principal_from_api_key(db, token)
        if principal is None:
            return False
        key = principal.api_key
        if key is not None and key.cluster_id is not None and key.cluster_id != cluster.id:
            return False
        return await cluster_svc.may_access(db, principal.user, cluster.id)

    cookie = request.cookies.get(settings.session_cookie)
    if not cookie:
        return False
    user_id = await security.read_session(cookie)
    if not user_id:
        return False
    user = await db.get(User, uuid.UUID(user_id))
    if user is None or not user.is_active:
        return False
    return await cluster_svc.may_access(db, user, cluster.id)
