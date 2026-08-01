from __future__ import annotations

import secrets as pysecrets
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import clusters, security
from .config import settings
from .db import get_db
from .logging_setup import log
from .models import ApiKey, Cluster, Instance, User

DbSession = Annotated[AsyncSession, Depends(get_db)]

ROLE_RANK = {"readonly": 0, "developer": 1, "admin": 2, "owner": 3}


async def get_instance(db: DbSession) -> Instance:
    instance = await db.get(Instance, 1)
    if instance is None:
        instance = Instance(id=1, version=settings.version)
        db.add(instance)
        await db.commit()
        await db.refresh(instance)
    return instance


InstanceDep = Annotated[Instance, Depends(get_instance)]


async def require_setup(instance: InstanceDep) -> Instance:
    if not instance.setup_complete:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "setup_required", "message": "This instance has not been set up yet."},
        )
    return instance


async def get_cluster(request: Request, db: DbSession, principal: CurrentPrincipal) -> Cluster:
    """The cluster this request is about, if the caller may have it.

    The console and the CLI name it explicitly with ``X-Cubicle-Cluster`` (an
    id or a slug); anything that does not gets the first cluster the caller can
    reach, so single-cluster installs never have to think about this.

    This is where cluster access is enforced. Every cluster-scoped endpoint
    depends on it, which is the point: a new route cannot forget the check,
    because it cannot obtain a cluster without passing through here.

    A cluster the caller may not reach answers exactly as a cluster that does
    not exist. Distinguishing the two would tell an account which clusters it
    has been kept out of.
    """
    # EventSource cannot set headers, so a query parameter is accepted too.
    ref = request.headers.get(clusters.CLUSTER_HEADER) or request.query_params.get("cluster")

    if ref:
        cluster = await clusters.by_reference(db, ref)
        if cluster is None or not await _principal_may_access(db, principal, cluster):
            if cluster is not None:
                log.warning(
                    "cluster access denied",
                    cluster=cluster.slug,
                    user=principal.user.email,
                    via=principal.via,
                )
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No cluster '{ref}'.")
        return cluster

    cluster = await clusters.first_accessible(db, principal.user)
    if cluster is not None and await _principal_may_access(db, principal, cluster):
        return cluster

    total = await clusters.count(db)
    if total == 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "setup_required", "message": "This instance has no cluster yet."},
        )
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "This account has not been given access to any cluster. Ask an owner to grant one.",
    )


async def _principal_may_access(db: AsyncSession, principal: Principal, cluster: Cluster) -> bool:
    """Both gates: the API key's own scope, then the user's grants.

    A key scoped to one cluster cannot reach another even if the account that
    created it could — narrowing a key must actually narrow it.
    """
    key = principal.api_key
    if key is not None and key.cluster_id is not None and key.cluster_id != cluster.id:
        return False
    return await clusters.may_access(db, principal.user, cluster.id)


CurrentCluster = Annotated[Cluster, Depends(get_cluster)]


class Principal:
    """Whoever is making the request: a signed-in operator, or an API key."""

    __slots__ = ("user", "api_key", "via")

    def __init__(self, user: User, via: str, api_key: ApiKey | None = None) -> None:
        self.user = user
        self.via = via
        self.api_key = api_key

    @property
    def role(self) -> str:
        return self.user.role

    def can(self, minimum: str) -> bool:
        return ROLE_RANK.get(self.role, 0) >= ROLE_RANK[minimum]


async def _principal_from_api_key(db: AsyncSession, token: str) -> Principal | None:
    prefix = security.api_key_prefix(token)
    result = await db.execute(
        select(ApiKey).where(ApiKey.prefix == prefix, ApiKey.revoked_at.is_(None))
    )
    digest = security.hash_api_key(token)
    for key in result.scalars():
        if pysecrets.compare_digest(key.token_hash, digest):
            # No fallback to "some user". This used to reach for the oldest
            # account when the creator was missing, which is the owner — so a
            # key made by a developer became an owner key the moment that
            # developer was deleted. A key without a live, active creator is
            # simply not a credential any more.
            if not key.created_by:
                return None
            owner = await db.get(User, key.created_by)
            if owner is None or not owner.is_active:
                return None
            key.last_used_at = datetime.now(UTC)
            await db.commit()
            return Principal(owner, via="api_key", api_key=key)
    return None


async def current_principal(request: Request, db: DbSession) -> Principal:
    token = security.bearer_token(request)
    if token:
        principal = await _principal_from_api_key(db, token)
        if principal is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key.")
        return principal

    cookie = request.cookies.get(settings.session_cookie)
    if not cookie:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in.")
    user_id = await security.read_session(cookie)
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired.")
    user = await db.get(User, uuid.UUID(user_id))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is no longer active.")
    return Principal(user, via="session")


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def require_role(minimum: str):
    async def _guard(principal: CurrentPrincipal) -> Principal:
        if not principal.can(minimum):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"This action needs the {minimum} role or higher.",
            )
        return principal

    return _guard


RequireDeveloper = Annotated[Principal, Depends(require_role("developer"))]
RequireAdmin = Annotated[Principal, Depends(require_role("admin"))]
RequireOwner = Annotated[Principal, Depends(require_role("owner"))]
