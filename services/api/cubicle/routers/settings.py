"""Instance settings, API keys and local user accounts."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .. import security
from ..config import settings
from ..deps import CurrentPrincipal, DbSession, InstanceDep, RequireAdmin, RequireOwner
from ..logging_setup import log
from ..models import ApiKey, User
from ..schemas import (
    ApiKeyCreate,
    ApiKeyOut,
    InstanceOut,
    InstanceUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/instance", response_model=InstanceOut)
async def get_instance(instance: InstanceDep, _: CurrentPrincipal):
    return InstanceOut(
        cluster_name=instance.cluster_name,
        ingress_domain=instance.ingress_domain,
        data_dir=instance.data_dir,
        kms_backend=instance.kms_backend,
        default_node_pool=instance.default_node_pool,
        version=settings.version,
        public_url=settings.public_url,
        tls=settings.public_url.startswith("https://"),
    )


@router.patch("/instance", response_model=InstanceOut)
async def update_instance(
    payload: InstanceUpdate, instance: InstanceDep, db: DbSession, principal: RequireAdmin
):
    data = payload.model_dump(exclude_unset=True)
    if "ingress_domain" in data and data["ingress_domain"]:
        data["ingress_domain"] = data["ingress_domain"].strip().removeprefix("*.")
    for key, value in data.items():
        if value is not None:
            setattr(instance, key, value)
    await db.commit()
    await db.refresh(instance)
    log.info("instance settings updated", by=principal.user.email, changed=list(data))
    return await get_instance(instance, principal)


# ── API keys ─────────────────────────────────────────────────────────────────


@router.get("/api-keys", response_model=list[ApiKeyOut])
async def list_keys(db: DbSession, _: CurrentPrincipal):
    rows = (
        (
            await db.execute(
                select(ApiKey).where(ApiKey.revoked_at.is_(None)).order_by(ApiKey.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@router.post("/api-keys", response_model=ApiKeyOut, status_code=status.HTTP_201_CREATED)
async def create_key(payload: ApiKeyCreate, db: DbSession, principal: RequireAdmin):
    token, prefix, token_hash = security.generate_api_key()
    key = ApiKey(
        name=payload.name,
        prefix=prefix,
        token_hash=token_hash,
        scope=payload.scope,
        created_by=principal.user.id,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    log.info("api key created", name=key.name, by=principal.user.email)

    out = ApiKeyOut.model_validate(key)
    # The only time the token is ever returned.
    out.token = token
    return out


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(key_id: uuid.UUID, db: DbSession, principal: RequireAdmin) -> Response:
    key = await db.get(ApiKey, key_id)
    if key is None or key.revoked_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such API key.")
    key.revoked_at = func.now()
    await db.commit()
    log.info("api key revoked", name=key.name, by=principal.user.email)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── users ────────────────────────────────────────────────────────────────────


@router.get("/users", response_model=list[UserOut])
async def list_users(db: DbSession, _: CurrentPrincipal):
    rows = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    return list(rows)


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, db: DbSession, principal: RequireAdmin):
    policy = security.check_password_policy(payload.password)
    if not policy.ok:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, policy.reason)
    if payload.role == "owner" and not principal.can("owner"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an owner can create another owner.")

    user = User(
        email=str(payload.email).lower(),
        name=payload.name.strip(),
        role=payload.role,
        password_hash=security.hash_password(payload.password),
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That email is already in use.") from exc
    await db.refresh(user)
    log.info("user created", email=user.email, role=user.role, by=principal.user.email)
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID, payload: UserUpdate, db: DbSession, principal: RequireAdmin
):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such user.")

    data = payload.model_dump(exclude_unset=True)
    if data.get("role") == "owner" and not principal.can("owner"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an owner can grant the owner role.")
    if user.role == "owner" and user.id != principal.user.id and not principal.can("owner"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an owner can change another owner.")

    if data.get("is_active") is False or (data.get("role") and user.role == "owner"):
        owners = (
            await db.execute(
                select(func.count(User.id)).where(User.role == "owner", User.is_active.is_(True))
            )
        ).scalar_one()
        if user.role == "owner" and owners <= 1:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "The cluster must keep at least one active owner."
            )

    for key, value in data.items():
        if value is not None:
            setattr(user, key, value)
    await db.commit()
    await db.refresh(user)

    if data.get("is_active") is False:
        await security.destroy_all_sessions(str(user.id))
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: uuid.UUID, db: DbSession, principal: RequireOwner) -> Response:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such user.")
    if user.id == principal.user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot delete your own account.")
    if user.role == "owner":
        owners = (
            await db.execute(select(func.count(User.id)).where(User.role == "owner"))
        ).scalar_one()
        if owners <= 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "The cluster must keep an owner.")

    await security.destroy_all_sessions(str(user.id))
    await db.delete(user)
    await db.commit()
    log.info("user deleted", email=user.email, by=principal.user.email)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
