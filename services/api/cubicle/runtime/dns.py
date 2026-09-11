"""Creating the DNS record a domain needs, when we already hold the key to.

The token saved for certificates is scoped to edit DNS in a zone. Adding a
hostname to an app and then being told to go and create a record by hand, in
the zone Cubicle can already write to, is a step that exists only because
nobody wired the two together.

So it is wired: a hostname inside a zone the token can edit gets its record
made when the domain is added. A hostname outside it is left alone and said so
— this never guesses at zones it was not given, and never touches a record it
did not create the shape of.

Records are made unproxied on purpose. A proxied record hides the origin behind
a CDN whose certificate has to cover the name, which for a second-level
subdomain it usually does not; the certificate this instance obtains is on the
origin, so the name has to reach the origin.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..logging_setup import log

API = "https://api.cloudflare.com/client/v4"
TIMEOUT = 20


class DnsError(RuntimeError):
    """Something the operator should read next to the domain they just added."""


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _check(payload: dict[str, Any]) -> Any:
    if not payload.get("success"):
        errors = payload.get("errors") or []
        message = "; ".join(str(e.get("message", e)) for e in errors) or "Cloudflare said no"
        raise DnsError(message[:300])
    return payload.get("result")


#: Cloudflare answers a malformed token with 400 and one of these, not with
#: 401 — so "this token cannot edit that zone" would be the wrong thing to
#: tell someone whose token is simply not a token.
AUTH_ERROR_CODES = {6003, 6111, 9109, 10000}


def _rejected_token(response: httpx.Response) -> bool:
    if response.status_code != 400:
        return False
    try:
        errors = response.json().get("errors") or []
    except ValueError:
        return False
    for error in errors:
        if int(error.get("code", 0)) in AUTH_ERROR_CODES:
            return True
        chain = error.get("error_chain") or []
        if any(int(link.get("code", 0)) in AUTH_ERROR_CODES for link in chain):
            return True
    return False


def candidate_zones(hostname: str) -> list[str]:
    """The zones a hostname could belong to, most specific first.

    ``a.b.example.com`` might live in ``b.example.com`` or in ``example.com``;
    both are real arrangements, so both are asked about rather than assumed.
    """
    labels = hostname.strip(".").split(".")
    return [".".join(labels[i:]) for i in range(len(labels) - 1)]


async def find_zone(token: str, hostname: str) -> tuple[str, str] | None:
    """The zone this token can edit that contains the hostname, if any."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for candidate in candidate_zones(hostname):
            try:
                response = await client.get(
                    f"{API}/zones", params={"name": candidate}, headers=_headers(token)
                )
            except httpx.HTTPError as exc:
                raise DnsError(f"could not reach Cloudflare: {exc}") from exc
            if response.status_code in (401, 403) or _rejected_token(response):
                raise DnsError(
                    "Cloudflare rejected the saved API token — check it under "
                    "Settings → TLS certificates."
                )
            if response.status_code >= 400:
                continue
            zones = _check(response.json()) or []
            if zones:
                return str(zones[0]["id"]), str(zones[0]["name"])
    return None


async def ensure_a_record(token: str, hostname: str, address: str) -> str:
    """Point a hostname at this machine. Returns what happened.

    One of ``created``, ``updated``, ``unchanged`` — or raises with something
    worth showing. A record that already points somewhere else is repointed,
    because the operator just asked for this hostname to serve this app and
    that is the same instruction.
    """
    if not address:
        raise DnsError("this instance does not know its own public address")

    found = await find_zone(token, hostname)
    if found is None:
        raise DnsError(
            f"the saved token cannot edit a zone containing {hostname} — "
            f"add the record yourself, or use a hostname in a zone it can"
        )
    zone_id, zone_name = found

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        listed = await client.get(
            f"{API}/zones/{zone_id}/dns_records",
            params={"name": hostname, "type": "A"},
            headers=_headers(token),
        )
        existing = _check(listed.json()) or []
        body = {
            "type": "A",
            "name": hostname,
            "content": address,
            "ttl": 60,
            # Unproxied: the certificate is on this origin, so the name has to
            # arrive here rather than at a CDN holding a different one.
            "proxied": False,
            "comment": "Managed by Cubicle",
        }

        if existing:
            record = existing[0]
            if record.get("content") == address and record.get("proxied") is False:
                return "unchanged"
            updated = await client.put(
                f"{API}/zones/{zone_id}/dns_records/{record['id']}",
                json=body,
                headers=_headers(token),
            )
            _check(updated.json())
            log.info("dns record updated", hostname=hostname, zone=zone_name)
            return "updated"

        created = await client.post(
            f"{API}/zones/{zone_id}/dns_records", json=body, headers=_headers(token)
        )
        _check(created.json())
        log.info("dns record created", hostname=hostname, zone=zone_name)
        return "created"
