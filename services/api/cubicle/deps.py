from __future__ import annotations

import secrets as pysecrets
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import security
from .config import settings
from .db import get_db
from .models import ApiKey, Instance, User

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
            key.last_used_at = datetime.now(UTC)
            owner = None
            if key.created_by:
                owner = await db.get(User, key.created_by)
            if owner is None:
                owner = (await db.execute(select(User).order_by(User.created_at))).scalars().first()
            if owner is None:
                return None
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
