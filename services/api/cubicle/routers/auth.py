from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from .. import security, turnstile
from ..config import settings
from ..deps import CurrentPrincipal, DbSession
from ..logging_setup import log
from ..models import Instance, User
from ..schemas import LoginRequest, PasswordChange, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
async def login(payload: LoginRequest, request: Request, response: Response, db: DbSession):
    ip = security.client_ip(request)
    identifier = f"{ip}:{payload.email.lower()}"

    if await security.login_attempts(identifier) >= settings.login_max_attempts:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed attempts. Try again in a few minutes.",
        )

    # Before the password is touched, because verifying one costs argon2id at
    # 64 MB and that is the work an unauthenticated caller would otherwise be
    # able to spend freely. A failed challenge counts as a failed attempt: an
    # attacker who can defeat Turnstile should still meet the throttle.
    instance = await db.get(Instance, 1)
    if instance is not None and turnstile.configured(instance):
        verdict = await turnstile.verify(instance, payload.turnstile_token, remote_ip=ip)
        if not verdict.ok:
            await security.register_login_failure(identifier)
            log.warning("turnstile blocked a sign-in", email=payload.email, ip=ip)
            raise HTTPException(status.HTTP_403_FORBIDDEN, verdict.reason)

    user = (
        await db.execute(select(User).where(User.email == payload.email.lower()))
    ).scalar_one_or_none()

    # Always spend the hashing time so a missing account is not distinguishable.
    password_hash = user.password_hash if user else security.hash_password("placeholder")
    valid = security.verify_password(password_hash, payload.password)

    if not user or not valid or not user.is_active:
        await security.register_login_failure(identifier)
        log.warning("failed sign-in", email=payload.email, ip=ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")

    if security.needs_rehash(user.password_hash):
        user.password_hash = security.hash_password(payload.password)

    await security.clear_login_failures(identifier)
    user.last_login_at = datetime.now(UTC)
    await db.commit()

    token = await security.create_session(str(user.id))
    security.set_session_cookie(response, token)
    log.info("signed in", email=user.email, ip=ip)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response) -> Response:
    cookie = request.cookies.get(settings.session_cookie)
    if cookie:
        await security.destroy_session(cookie)
    security.clear_session_cookie(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
async def me(principal: CurrentPrincipal):
    return principal.user


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: PasswordChange, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Response:
    user = principal.user
    if not security.verify_password(user.password_hash, payload.current_password):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Current password is incorrect.")

    policy = security.check_password_policy(payload.new_password)
    if not policy.ok:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, policy.reason)

    user.password_hash = security.hash_password(payload.new_password)
    await db.commit()

    # Changing the password ends every other session immediately.
    await security.destroy_all_sessions(str(user.id))
    log.info("password changed", email=user.email, ip=security.client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
