"""Instance settings, API keys and local user accounts."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from .. import clusters as cluster_svc
from .. import security, turnstile
from ..config import settings
from ..deps import (
    CurrentCluster,
    CurrentPrincipal,
    DbSession,
    RequireAdmin,
    RequireOwner,
)
from ..deps import (
    # Aliased: this module already has an endpoint called get_instance, and
    # that one returns the active cluster's settings, not the singleton row.
    get_instance as get_instance_row,
)
from ..logging_setup import log
from ..models import ApiKey, Cluster, Instance, User, UserCluster
from ..schemas import (
    ApiKeyCreate,
    ApiKeyOut,
    InstanceOut,
    InstanceUpdate,
    TurnstileOut,
    TurnstileSettings,
    UserCreate,
    UserOut,
    UserUpdate,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/instance", response_model=InstanceOut)
async def get_instance(cluster: CurrentCluster, db: DbSession, _: CurrentPrincipal):
    return await _instance_out(db, cluster)


async def _instance_out(db, cluster: Cluster) -> InstanceOut:
    return InstanceOut(
        cluster_id=cluster.id,
        cluster_name=cluster.name,
        cluster_slug=cluster.slug,
        ingress_domain=cluster.ingress_domain,
        data_dir=cluster.data_dir,
        kms_backend=cluster.kms_backend,
        default_node_pool=cluster.default_node_pool,
        is_default=cluster.is_default,
        base_url=cluster_svc.function_url(cluster),
        cluster_count=await cluster_svc.count(db),
        version=settings.version,
        public_url=settings.public_url,
        tls=settings.public_url.startswith("https://"),
    )


@router.patch("/instance", response_model=InstanceOut)
async def update_instance(
    payload: InstanceUpdate, cluster: CurrentCluster, db: DbSession, principal: RequireAdmin
):
    """Edit the active cluster. Instance-wide settings live in the environment."""
    data = payload.model_dump(exclude_unset=True)
    if data.get("ingress_domain"):
        clash = await cluster_svc.by_domain(db, data["ingress_domain"])
        if clash is not None and clash.id != cluster.id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{data['ingress_domain']} already routes to '{clash.slug}'.",
            )
    for key, value in data.items():
        if value is None:
            continue
        setattr(cluster, "name" if key == "cluster_name" else key, value)
    await db.commit()
    await db.refresh(cluster)
    log.info(
        "cluster settings updated",
        cluster=cluster.slug,
        by=principal.user.email,
        changed=list(data),
    )
    return await _instance_out(db, cluster)


# ── sign-in protection ───────────────────────────────────────────────────────


def _turnstile_out(instance: Instance, **extra) -> TurnstileOut:
    return TurnstileOut(
        enabled=instance.turnstile_enabled,
        site_key=instance.turnstile_site_key,
        secret_set=bool(instance.turnstile_secret_ciphertext),
        **extra,
    )


@router.get("/turnstile", response_model=TurnstileOut)
async def get_turnstile(db: DbSession, _: RequireAdmin) -> TurnstileOut:
    """The current configuration, without the secret key.

    The secret is never returned, not even to an owner. There is nothing an
    operator can do with it here that rotating it in Cloudflare would not do
    better, and a settings page that can display it is a settings page that can
    leak it.
    """
    instance = await get_instance_row(db)
    return _turnstile_out(instance)


@router.put("/turnstile", response_model=TurnstileOut)
async def set_turnstile(
    payload: TurnstileSettings, db: DbSession, principal: RequireAdmin
) -> TurnstileOut:
    """Save the keys, after checking them against Cloudflare.

    Checking first matters more than it usually would: these credentials guard
    the sign-in form, so a typo saved without verification locks every operator
    out of the instance until someone edits the database by hand. The check
    costs one request and removes that failure mode entirely.

    Omitting ``secret_key`` keeps the stored one, so the enabled flag and the
    site key can be edited without the console ever holding the secret.
    """
    instance = await get_instance_row(db)

    site_key = (payload.site_key or "").strip()
    secret = payload.secret_key.strip() if payload.secret_key is not None else None

    # Turning it on is the only case that must be right. Saving keys while it
    # is off is how an operator stages the configuration before enabling it.
    if payload.enabled:
        candidate = secret if secret else turnstile.unseal(instance)
        if not candidate:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "A secret key is needed before sign-in protection can be turned on.",
            )
        verdict = await turnstile.check_credentials(site_key, candidate)
        if not verdict.ok:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, verdict.reason)

    instance.turnstile_enabled = payload.enabled
    instance.turnstile_site_key = site_key
    if secret:
        instance.turnstile_secret_ciphertext = turnstile.seal(secret)
    elif secret == "":
        # An explicit empty string clears it. Omitting the field does not.
        instance.turnstile_secret_ciphertext = None

    await db.commit()
    await db.refresh(instance)

    log.info(
        "sign-in protection updated",
        by=principal.user.email,
        enabled=instance.turnstile_enabled,
        secret_changed=bool(secret),
    )
    return _turnstile_out(
        instance,
        verified=payload.enabled,
        message=(
            "Verified with Cloudflare. The sign-in page will challenge visitors immediately."
            if payload.enabled
            else "Saved. Sign-in protection is off."
        ),
    )


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


async def _grants(db, user: User) -> list[uuid.UUID]:
    rows = await db.execute(select(UserCluster.cluster_id).where(UserCluster.user_id == user.id))
    return list(rows.scalars())


async def _user_out(db, user: User) -> dict:
    return {
        **{c.name: getattr(user, c.name) for c in User.__table__.columns},
        "initials": user.initials,
        "cluster_ids": [] if cluster_svc.is_super_admin(user) else await _grants(db, user),
        "is_super_admin": cluster_svc.is_super_admin(user),
    }


async def _set_grants(db, user: User, wanted: list[uuid.UUID], principal) -> None:
    """Replace a user's grants, refusing to hand out what you do not hold.

    An admin can only delegate access they have themselves. Without this an
    admin scoped to staging could grant themselves — or anyone — production by
    creating an account and signing in as it.
    """
    unique = list(dict.fromkeys(wanted))
    existing = (
        set((await db.execute(select(Cluster.id).where(Cluster.id.in_(unique)))).scalars())
        if unique
        else set()
    )
    missing = [str(c) for c in unique if c not in existing]
    if missing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No cluster {missing[0]}.")

    allowed = await cluster_svc.accessible_ids(db, principal.user)
    if allowed is not None:
        beyond = [str(c) for c in unique if c not in allowed]
        if beyond:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "You can only grant access to clusters you have access to yourself.",
            )

    await db.execute(delete(UserCluster).where(UserCluster.user_id == user.id))
    for cluster_id in unique:
        db.add(UserCluster(user_id=user.id, cluster_id=cluster_id))
    await db.commit()


@router.get("/users", response_model=list[UserOut])
async def list_users(db: DbSession, _: CurrentPrincipal):
    rows = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    return [await _user_out(db, user) for user in rows]


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
    await _set_grants(db, user, payload.cluster_ids, principal)
    log.info(
        "user created",
        email=user.email,
        role=user.role,
        clusters=len(payload.cluster_ids),
        by=principal.user.email,
    )
    return await _user_out(db, user)


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

    grants = data.pop("cluster_ids", None)
    for key, value in data.items():
        if value is not None:
            setattr(user, key, value)
    await db.commit()
    await db.refresh(user)

    if grants is not None:
        await _set_grants(db, user, grants, principal)

    # Losing access should take effect now, not whenever the session happens to
    # expire. Deactivation and a narrowed set of grants both qualify.
    if data.get("is_active") is False or grants is not None:
        await security.destroy_all_sessions(str(user.id))
    return await _user_out(db, user)


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
