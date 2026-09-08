"""Certificates for instances that sit behind another web server.

Nothing here runs on an install where Caddy owns 80 and 443 — it issues and
renews its own, and the console says so instead of offering a button that would
duplicate it.

Issuance happens in the background: the request returns as soon as the row says
"issuing", and the outcome arrives as a status and a transcript. A wildcard
takes as long as DNS takes to propagate, which is longer than a request should
wait and nothing like long enough to watch a spinner for.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..config import settings
from ..crypto import decrypt, encrypt, mask
from ..db import session_scope
from ..deps import CurrentPrincipal, DbSession, InstanceDep, RequireAdmin
from ..logging_setup import log
from ..models import Certificate, Instance
from ..runtime import acme

router = APIRouter(prefix="/api/certificates", tags=["certificates"])


class CredentialUpdate(BaseModel):
    provider: str = Field(default="cloudflare", pattern="^(cloudflare)$")
    #: Omitted leaves the stored token alone; "" clears it.
    token: str | None = Field(default=None, max_length=400)
    email: str | None = Field(default=None, max_length=255)


class IssueRequest(BaseModel):
    hostnames: list[str] = Field(min_length=1, max_length=20)
    #: Let's Encrypt's staging CA. Untrusted by browsers, but not rate limited,
    #: which is what you want while a DNS token is still being argued with.
    staging: bool = False


def _token(instance: Instance) -> str:
    if not instance.acme_token_ciphertext:
        return ""
    try:
        return decrypt(instance.acme_token_ciphertext, aad="acme:token")
    except Exception:  # noqa: BLE001 - a rotated master key is not a 500
        log.warning("acme token could not be decrypted")
        return ""


def _serialize(certificate: Certificate) -> dict:
    return {
        "id": str(certificate.id),
        "name": certificate.name,
        "hostnames": certificate.hostnames,
        "status": certificate.status,
        "provider": certificate.provider,
        "issued_at": certificate.issued_at.isoformat() if certificate.issued_at else None,
        "expires_at": certificate.expires_at.isoformat() if certificate.expires_at else None,
        "days_left": (
            (certificate.expires_at - datetime.now(UTC)).days if certificate.expires_at else None
        ),
        "last_error": certificate.last_error,
        "last_log": certificate.last_log[-8000:],
        "renewals": certificate.renewals,
        "paths": acme.cert_paths(certificate.name),
    }


@router.get("")
async def list_certificates(db: DbSession, instance: InstanceDep, _: CurrentPrincipal):
    rows = (await db.execute(select(Certificate).order_by(Certificate.name))).scalars().all()
    token = _token(instance)
    return {
        # Only meaningful behind another server; the console hides the whole
        # section otherwise rather than offering something with no effect.
        "manages_certificates": settings.behind_proxy and acme.configured(),
        "provider": instance.acme_provider,
        "email": instance.acme_email,
        "token_hint": mask(token) if token else None,
        "cert_dir": settings.cert_host_dir,
        "certificates": [_serialize(row) for row in rows],
    }


@router.put("/credentials")
async def set_credentials(
    payload: CredentialUpdate, db: DbSession, instance: InstanceDep, principal: RequireAdmin
):
    if payload.token is not None:
        token = payload.token.strip()
        instance.acme_token_ciphertext = encrypt(token, aad="acme:token") if token else None
    if payload.email is not None:
        instance.acme_email = payload.email.strip()
    instance.acme_provider = payload.provider
    await db.commit()
    log.info("acme credentials updated", provider=payload.provider, by=principal.user.email)
    return await list_certificates(db, instance, principal)


@router.post("/issue", status_code=status.HTTP_202_ACCEPTED)
async def issue(
    payload: IssueRequest, db: DbSession, instance: InstanceDep, principal: RequireAdmin
):
    if not acme.configured():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This instance has no certificate directory. Pull the latest compose file and "
            "restart, then try again.",
        )
    token = _token(instance)
    if not token:
        raise HTTPException(status.HTTP_409_CONFLICT, "Save a DNS token first.")
    email = instance.acme_email or principal.user.email

    hostnames = [h.strip().lower().rstrip(".") for h in payload.hostnames if h.strip()]
    if not hostnames:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No hostnames given.")
    # certbot names the lineage after the first name, minus the wildcard part,
    # and so does the directory nginx will point at.
    name = hostnames[0].removeprefix("*.")

    existing = (
        await db.execute(select(Certificate).where(Certificate.name == name))
    ).scalar_one_or_none()
    if existing is None:
        existing = Certificate(name=name, hostnames=hostnames, provider=instance.acme_provider)
        db.add(existing)
    else:
        if existing.status == "issuing":
            raise HTTPException(status.HTTP_409_CONFLICT, "That certificate is being issued now.")
        existing.hostnames = hostnames
    existing.status = "issuing"
    existing.last_error = None
    await db.commit()
    await db.refresh(existing)

    asyncio.create_task(  # noqa: RUF006
        _issue(existing.id, hostnames, instance.acme_provider, token, email, payload.staging)
    )
    log.info("certificate requested", name=name, by=principal.user.email)
    return _serialize(existing)


@router.post("/{certificate_id}/renew", status_code=status.HTTP_202_ACCEPTED)
async def renew_one(
    certificate_id: uuid.UUID, db: DbSession, instance: InstanceDep, principal: RequireAdmin
):
    certificate = await db.get(Certificate, certificate_id)
    if certificate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such certificate.")
    token = _token(instance)
    if not token:
        raise HTTPException(status.HTTP_409_CONFLICT, "Save a DNS token first.")
    certificate.status = "issuing"
    await db.commit()
    asyncio.create_task(  # noqa: RUF006
        _issue(
            certificate.id,
            list(certificate.hostnames),
            instance.acme_provider,
            token,
            instance.acme_email or principal.user.email,
            False,
        )
    )
    return _serialize(certificate)


async def _issue(
    certificate_id: uuid.UUID,
    hostnames: list[str],
    provider: str,
    token: str,
    email: str,
    staging: bool,
) -> None:
    name = hostnames[0].removeprefix("*.")
    try:
        ok, output = await acme.issue(
            name=name,
            hostnames=hostnames,
            provider=provider,
            token=token,
            email=email,
            staging=staging,
        )
        failure = None if ok else acme.summarise(output)
    except acme.AcmeError as exc:
        ok, output, failure = False, str(exc), str(exc)

    async with session_scope() as db:
        certificate = await db.get(Certificate, certificate_id)
        if certificate is None:
            return
        certificate.last_log = output[-40_000:]
        certificate.status = "issued" if ok else "failed"
        certificate.last_error = failure
        if ok:
            certificate.issued_at = datetime.now(UTC)
            certificate.expires_at = acme.expiry(name)
            certificate.renewals += 1
        await db.commit()

    log.info("certificate issuance finished", name=name, ok=ok)


async def renew_due() -> None:
    """Renew anything close to expiry. Called by the scheduler, daily."""
    if not (settings.behind_proxy and acme.configured()):
        return
    async with session_scope() as db:
        instance = await db.get(Instance, 1)
        rows = (await db.execute(select(Certificate))).scalars().all()
        token = _token(instance) if instance else ""
        due = [row for row in rows if acme.needs_renewal(row.expires_at)]
        email = (instance.acme_email if instance else "") or ""

    if not due or not token or not instance:
        return

    log.info("renewing certificates", count=len(due))
    for certificate in due:
        await _issue(
            certificate.id,
            list(certificate.hostnames),
            instance.acme_provider,
            token,
            email,
            False,
        )
