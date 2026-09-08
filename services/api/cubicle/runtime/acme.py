"""Obtaining and renewing certificates for an instance behind another server.

An install where Caddy owns 80 and 443 never comes here: it gets its own
certificates on first request and renews them itself. This exists for the other
shape, where nginx or Traefik terminates TLS and the certificate is theirs to
hold — which means somebody has to ask for it, and that somebody may as well be
the console rather than a person with an ssh session.

A wildcard is the point. It cannot be issued over HTTP-01, so the request is
made over DNS-01: certbot writes a TXT record in the zone, Let's Encrypt reads
it, certbot removes it. That is why a DNS token is needed and an HTTP challenge
is not enough, and it is the only reason one is asked for.

certbot runs in its own container against the same Docker engine everything
else here uses. The token is written into a file for the length of that run and
removed after it, and the certificate lands in a directory the front-end server
reads directly.
"""

from __future__ import annotations

import contextlib
import re
from datetime import UTC, datetime
from pathlib import Path

import docker
from docker.errors import DockerException

from ..config import settings
from ..logging_setup import log
from .engine import LOCAL_HOST, engines

#: Where certbot keeps its state, inside the container it runs in. The host
#: path is bind-mounted so the front-end server can read the result.
CONTAINER_CONFIG = "/etc/letsencrypt"
IMAGE = "certbot/dns-cloudflare:latest"

#: Renew with this much life left. Let's Encrypt issues for 90 days and
#: recommends renewing at 30, which also leaves room for a few failed attempts
#: before anything is actually expired.
RENEW_WITHIN_DAYS = 30

PROVIDERS = {
    "cloudflare": {"flag": "--dns-cloudflare", "credential": "cloudflare.ini"},
}


class AcmeError(RuntimeError):
    """Something the operator should read on the certificates page."""


def configured() -> bool:
    """Whether this instance can write certificates where they are needed."""
    return bool(settings.cert_host_dir)


def cert_paths(name: str) -> dict[str, str]:
    """Where the front-end server should point, on the host filesystem."""
    root = settings.cert_host_dir.rstrip("/")
    return {
        "fullchain": f"{root}/live/{name}/fullchain.pem",
        "privkey": f"{root}/live/{name}/privkey.pem",
    }


def _credentials_body(provider: str, token: str) -> str:
    if provider != "cloudflare":
        raise AcmeError(f"{provider} is not supported yet.")
    return f"dns_cloudflare_api_token = {token}\n"


def _write_credentials(provider: str, token: str) -> Path:
    """A file only root can read, for the length of one certbot run."""
    secrets_dir = Path(CONTAINER_CONFIG) / "cubicle-secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    secrets_dir.chmod(0o700)
    path = secrets_dir / PROVIDERS[provider]["credential"]
    path.write_text(_credentials_body(provider, token))
    path.chmod(0o600)
    return path


async def issue(
    *, name: str, hostnames: list[str], provider: str, token: str, email: str, staging: bool = False
) -> tuple[bool, str]:
    """Ask for a certificate. Returns whether it worked, and the transcript."""
    if not configured():
        raise AcmeError(
            "This instance has no certificate directory. Set CUBICLE_CERT_DIR and restart."
        )
    if not token:
        raise AcmeError("No DNS token saved yet.")
    if provider not in PROVIDERS:
        raise AcmeError(f"{provider} is not supported yet.")

    credentials = _write_credentials(provider, token)
    command = [
        "certonly",
        PROVIDERS[provider]["flag"],
        f"{PROVIDERS[provider]['flag']}-credentials",
        f"{CONTAINER_CONFIG}/cubicle-secrets/{credentials.name}",
        f"{PROVIDERS[provider]['flag']}-propagation-seconds",
        "30",
        "--non-interactive",
        "--agree-tos",
        "--cert-name",
        name,
        "-m",
        email,
    ]
    for hostname in hostnames:
        command += ["-d", hostname]
    if staging:
        command.append("--staging")

    try:
        code, output = await _run_async(command)
    finally:
        # The token is not left lying in a directory nginx can read.
        credentials.unlink(missing_ok=True)

    return code == 0, output[-20_000:]


async def renew() -> tuple[bool, str]:
    """Renew anything close enough to expiry. certbot decides which."""
    if not configured():
        raise AcmeError("This instance has no certificate directory.")
    code, output = await _run_async(["renew", "--non-interactive"])
    return code == 0, output[-20_000:]


async def _run_async(command: list[str]) -> tuple[int, str]:
    def _execute(client: docker.DockerClient) -> tuple[int, str]:
        container = client.containers.run(
            IMAGE,
            command=command,
            detach=True,
            volumes={settings.cert_host_dir: {"bind": CONTAINER_CONFIG, "mode": "rw"}},
            labels={"cubicle.role": "acme"},
        )
        try:
            result = container.wait(timeout=600)
            output = container.logs().decode("utf-8", "replace")
            return int(result.get("StatusCode", 1)), output
        finally:
            with contextlib.suppress(DockerException):
                container.remove(force=True)

    try:
        return await engines.call(LOCAL_HOST, _execute)
    except DockerException as exc:
        raise AcmeError(f"could not run certbot: {exc}") from exc


def expiry(name: str) -> datetime | None:
    """When the certificate on disk runs out, read from the file itself."""
    path = Path(CONTAINER_CONFIG) / "live" / name / "cert.pem"
    if not path.is_file():
        return None
    try:
        from cryptography import x509

        certificate = x509.load_pem_x509_certificate(path.read_bytes())
        return certificate.not_valid_after_utc
    except Exception as exc:  # noqa: BLE001 - the page falls back to "unknown"
        log.info("could not read certificate expiry", name=name, error=str(exc))
        return None


def needs_renewal(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return True
    remaining = expires_at - datetime.now(UTC)
    return remaining.days <= RENEW_WITHIN_DAYS


def summarise(output: str) -> str:
    """The line worth showing next to a failure, out of certbot's whole log."""
    for pattern in (
        r"^Error.*$",
        r"^.*(?:Problem|problem).*$",
        r"^.*(?:failed|Failed).*$",
    ):
        found = re.findall(pattern, output, re.MULTILINE)
        if found:
            return found[-1].strip()[:400]
    return output.strip().splitlines()[-1][:400] if output.strip() else "certbot failed"
