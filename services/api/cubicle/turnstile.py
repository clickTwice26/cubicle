"""Cloudflare Turnstile verification for the sign-in form.

Turnstile is a CAPTCHA that usually shows the visitor nothing. The browser
solves a challenge and hands the page a token; this module posts that token to
Cloudflare with the secret key and gets back a yes or a no.

It guards sign-in specifically because that is the one unauthenticated endpoint
that costs real work: every attempt runs argon2id at 64 MB whether or not the
account exists, deliberately, so that a missing account and a wrong password
take the same time. Turnstile puts a cost on the caller before that happens.

Nothing else on the instance uses it. Function invocation is not a sensible
place for a CAPTCHA, because the caller is usually a program.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .crypto import DecryptionError, decrypt, encrypt
from .logging_setup import log
from .models import Instance

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

#: Long enough for a round trip to Cloudflare, short enough that an outage
#: cannot hold sign-in open. See ``verify`` for what happens when it expires.
TIMEOUT_S = 8.0

#: What Cloudflare's error codes mean to an operator reading a log line. Codes
#: not listed here are surfaced verbatim rather than guessed at.
REASONS = {
    "missing-input-secret": "No secret key is configured.",
    "invalid-input-secret": "The secret key is not valid for this widget.",
    "missing-input-response": "The sign-in form sent no Turnstile token.",
    "invalid-input-response": "The Turnstile token was not valid.",
    "timeout-or-duplicate": "The Turnstile token had already been used, or it expired.",
    "bad-request": "Cloudflare rejected the verification request.",
    "internal-error": "Cloudflare could not verify the token. Try again.",
}

AAD = "turnstile:secret"


@dataclass(slots=True)
class Verdict:
    ok: bool
    reason: str = ""


def seal(secret: str) -> str:
    """Wrap a secret key for storage."""
    return encrypt(secret, aad=AAD)


def unseal(instance: Instance) -> str | None:
    """The stored secret key, or None if there is not a usable one."""
    if not instance.turnstile_secret_ciphertext:
        return None
    try:
        return decrypt(instance.turnstile_secret_ciphertext, aad=AAD)
    except DecryptionError:
        # The master key changed. Say so rather than failing as though the
        # visitor got the challenge wrong.
        log.error("the stored Turnstile secret cannot be decrypted")
        return None


def configured(instance: Instance) -> bool:
    """Whether sign-in should present a challenge at all."""
    return bool(
        instance.turnstile_enabled
        and instance.turnstile_site_key
        and instance.turnstile_secret_ciphertext
    )


async def verify(instance: Instance, token: str | None, *, remote_ip: str | None = None) -> Verdict:
    """Check one token with Cloudflare.

    A missing token fails without a network call: there is nothing to check,
    and an empty token is what a form that skipped the widget sends.

    If Cloudflare cannot be reached the verdict is a failure, not a pass. The
    alternative is that anyone who can disrupt the control plane's egress also
    turns the challenge off, which makes the control worthless exactly when it
    is being attacked. The cost of this choice is that a Cloudflare outage
    stops sign-in, which an operator can end by turning Turnstile off.
    """
    if not configured(instance):
        return Verdict(True)

    if not token:
        return Verdict(False, REASONS["missing-input-response"])

    secret = unseal(instance)
    if secret is None:
        return Verdict(False, REASONS["missing-input-secret"])

    form = {"secret": secret, "response": token}
    if remote_ip and remote_ip != "unknown":
        form["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            response = await client.post(VERIFY_URL, data=form)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.error("turnstile verification failed to complete", error=str(exc))
        return Verdict(False, "The verification service could not be reached. Try again.")

    if payload.get("success"):
        return Verdict(True)

    codes = payload.get("error-codes") or []
    log.warning("turnstile rejected a sign-in", codes=codes)
    for code in codes:
        if code in REASONS:
            return Verdict(False, REASONS[code])
    return Verdict(False, "Verification failed. Reload the page and try again.")


async def check_credentials(site_key: str, secret: str) -> Verdict:
    """Confirm a key pair is real before it is saved.

    Called when an operator saves the settings, so a typo is caught there
    rather than by locking everyone out of the sign-in form.

    A deliberately invalid token is sent. Correct credentials come back with
    ``invalid-input-response``, meaning "the secret is fine, that token is
    not". ``invalid-input-secret`` means the secret itself is wrong, which is
    the answer being looked for.
    """
    if not site_key.strip():
        return Verdict(False, "A site key is required.")
    if not secret.strip():
        return Verdict(False, "A secret key is required.")

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            response = await client.post(
                VERIFY_URL, data={"secret": secret, "response": "cubicle-credential-check"}
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return Verdict(False, f"Could not reach Cloudflare to check the keys: {exc}")

    codes = payload.get("error-codes") or []
    if "invalid-input-secret" in codes or "missing-input-secret" in codes:
        return Verdict(False, REASONS["invalid-input-secret"])
    return Verdict(True)
