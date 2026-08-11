"""Passwords, sessions and API keys.

Cubicle has no registration flow and no external identity provider by default.
The administrator password is chosen once, during first-run setup, and that
account owns the cluster. Sessions are opaque tokens held in Redis so that
signing out — or revoking every session — takes effect immediately.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Request, Response

from .config import settings
from .db import get_redis

_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4)

SESSION_PREFIX = "cubicle:session:"
LOGIN_ATTEMPT_PREFIX = "cubicle:login:"
API_KEY_PREFIX = "cbcl_"

MIN_PASSWORD_LENGTH = 12


@dataclass(slots=True)
class PasswordPolicy:
    ok: bool
    reason: str = ""


def check_password_policy(password: str) -> PasswordPolicy:
    if len(password) < MIN_PASSWORD_LENGTH:
        return PasswordPolicy(False, f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if password.lower() in {"password1234", "administrator", "cubiclecubicle"}:
        return PasswordPolicy(False, "That password is too easy to guess.")
    classes = sum(
        [
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ]
    )
    if classes < 3:
        return PasswordPolicy(
            False, "Mix at least three of: lower case, upper case, digits, symbols."
        )
    return PasswordPolicy(True)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return True


# ── sessions ─────────────────────────────────────────────────────────────────


async def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(36)
    await get_redis().setex(SESSION_PREFIX + _digest(token), settings.session_ttl, user_id)
    return token


async def read_session(token: str) -> str | None:
    key = SESSION_PREFIX + _digest(token)
    user_id = await get_redis().get(key)
    if user_id:
        # Sliding expiry: an active operator is never logged out mid-task.
        await get_redis().expire(key, settings.session_ttl)
    return user_id


async def destroy_session(token: str) -> None:
    await get_redis().delete(SESSION_PREFIX + _digest(token))


async def destroy_all_sessions(user_id: str) -> int:
    removed = 0
    async for key in get_redis().scan_iter(match=SESSION_PREFIX + "*", count=200):
        if await get_redis().get(key) == user_id:
            await get_redis().delete(key)
            removed += 1
    return removed


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.session_cookie,
        token,
        max_age=settings.session_ttl,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(settings.session_cookie, path="/")


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ── login throttling ─────────────────────────────────────────────────────────


async def register_login_failure(identifier: str) -> int:
    key = LOGIN_ATTEMPT_PREFIX + _digest(identifier)
    count = await get_redis().incr(key)
    if count == 1:
        await get_redis().expire(key, settings.login_window)
    return count


async def login_attempts(identifier: str) -> int:
    value = await get_redis().get(LOGIN_ATTEMPT_PREFIX + _digest(identifier))
    return int(value) if value else 0


async def clear_login_failures(identifier: str) -> None:
    await get_redis().delete(LOGIN_ATTEMPT_PREFIX + _digest(identifier))


# ── API keys ─────────────────────────────────────────────────────────────────


def generate_api_key() -> tuple[str, str, str]:
    """Return ``(token, prefix, token_hash)``. The token is shown exactly once."""
    body = secrets.token_urlsafe(30)
    token = f"{API_KEY_PREFIX}{body}"
    return token, token[: len(API_KEY_PREFIX) + 6], hash_api_key(token)


def hash_api_key(token: str) -> str:
    return hmac.new(settings.secret_key.encode(), token.encode(), hashlib.sha256).hexdigest()


def api_key_prefix(token: str) -> str:
    return token[: len(API_KEY_PREFIX) + 6]


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def client_ip(request: Request) -> str:
    """The caller's address, as far as it can be trusted.

    ``X-Forwarded-For`` grows left to right: each proxy appends the address it
    received the request from. So the entries on the right are the ones written
    by proxies we run, and the entries on the left are whatever the client
    chose to send. Reading the leftmost entry, which is the obvious way to do
    this, hands an attacker a fresh identity per request and defeats every
    control keyed on the address, login throttling included.

    ``proxy_hops`` is how many proxies sit in front of this process. A default
    install has exactly one, Caddy, so the address it recorded is the last
    entry. Anything further left is untrusted and is ignored.
    """
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            hops = [part.strip() for part in forwarded.split(",") if part.strip()]
            if hops:
                # Count in from the right, but never past the start of the list:
                # a request that arrived with fewer hops than configured is
                # either misconfiguration or someone stripping headers, and in
                # both cases the leftmost entry we actually received is the
                # closest thing to the truth that exists.
                index = max(0, len(hops) - settings.proxy_hops)
                return hops[index]
    return request.client.host if request.client else "unknown"
