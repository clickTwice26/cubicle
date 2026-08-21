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


#: The largest body a function may be handed. Anything past this is refused,
#: and refused without being kept.
MAX_BODY_BYTES = 6 * 1024 * 1024


class _TooLarge(Exception):
    """The body went past MAX_BODY_BYTES, so reading it was abandoned."""


async def _read_body(request: Request) -> bytes:
    """The request body, or nothing at all if it is too big.

    Read in chunks and abandoned the moment it goes past the limit. Calling
    ``request.body()`` and measuring afterwards describes what is accepted
    without bounding what is read: a caller who sends ten gigabytes gets a 413,
    and the control plane holds ten gigabytes to produce it. This path is
    reachable without a credential on any function whose ``auth_required`` is
    off, which is the documented setting for a webhook.

    A declared Content-Length is checked first, which refuses the ordinary case
    before a single byte arrives. It is not trusted on its own, because it is a
    header and a body can be longer than it claims or arrive chunked with no
    length at all.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _TooLarge

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise _TooLarge
        chunks.append(chunk)
    return b"".join(chunks)


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

    # The credential is checked before anything else is disclosed, including
    # whether the function exists. Answering 404 for "no such function" and 401
    # for "exists, but you did not authenticate" tells an anonymous caller which
    # names are real, and the 405 and 503 below narrow it further. Everything a
    # caller without a credential may learn is decided here.
    #
    # A function that does not exist is treated as though it required a key, so
    # the two are indistinguishable from outside. The cost is a worse message
    # for somebody who forgot theirs, which is the right way round.
    if (fn is None or fn.auth_required) and not await _authorised(request, db, cluster):
        return JSONResponse(
            {"error": "unauthorized", "message": "This endpoint requires an API key."},
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )

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

    version = (
        await db.get(FunctionVersion, fn.current_version_id) if fn.current_version_id else None
    )
    if version is None or version.status != "ready":
        return JSONResponse(
            {"error": "not_deployed", "message": "This function has no successful build yet."},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        raw = await _read_body(request)
    except _TooLarge:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Request body is too large."
        ) from None

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
        # Binary bodies used to be decoded with errors="replace", which turned
        # every byte that is not valid UTF-8 into U+FFFD — an image arrived as
        # text that could never be turned back into an image. A body that does
        # not decode is carried as bytes instead of being destroyed on the way
        # in.
        try:
            body = raw.decode("utf-8")
        except UnicodeDecodeError:
            body = raw

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

    if isinstance(result.body, bytes):
        # `str(b"...")` would have sent the literal repr, which is how a handler
        # returning an image ended up returning the text "b'\\x89PNG...'".
        return Response(
            content=result.body,
            status_code=result.status_code,
            headers=headers,
            media_type=result.headers.get("content-type") or "application/octet-stream",
        )
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
