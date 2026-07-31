"""Transport and configuration for the CLI.

Standard library only, so `pipx install ./cli` pulls nothing else in and the
CLI works on an air-gapped jump host.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(os.environ.get("CUBICLE_CONFIG", Path.home() / ".cubicle" / "config.toml"))
USER_AGENT = "cubicle-cli/1.0"


class CubicleError(RuntimeError):
    pass


@dataclass(slots=True)
class Profile:
    url: str
    token: str
    cluster: str | None = None

    @property
    def base(self) -> str:
        return self.url.rstrip("/")


def load_profile(
    url: str | None = None, token: str | None = None, cluster: str | None = None
) -> Profile:
    url = url or os.environ.get("CUBICLE_URL")
    token = token or os.environ.get("CUBICLE_TOKEN")
    cluster = cluster or os.environ.get("CUBICLE_CLUSTER")
    if url and token:
        return Profile(url, token, cluster)

    if not CONFIG_PATH.exists():
        raise CubicleError(
            "Not signed in. Run `cubicle login <url>` first, or set CUBICLE_URL and CUBICLE_TOKEN."
        )
    data = tomllib.loads(CONFIG_PATH.read_text())
    profile = data.get("default", {})
    url = url or profile.get("url")
    token = token or profile.get("token")
    cluster = cluster or profile.get("cluster") or None
    if not url or not token:
        raise CubicleError(f"{CONFIG_PATH} is missing a url or token.")
    return Profile(url, token, cluster)


def save_profile(profile: Profile) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Written by `cubicle login`. Treat this file as a credential.",
        "[default]",
        f'url = "{profile.base}"',
        f'token = "{profile.token}"',
    ]
    if profile.cluster:
        lines.append(f'cluster = "{profile.cluster}"')
    CONFIG_PATH.write_text("\n".join(lines) + "\n")
    CONFIG_PATH.chmod(0o600)


def request(
    profile: Profile,
    method: str,
    path: str,
    *,
    body: Any = None,
    params: dict[str, Any] | None = None,
    raw: bool = False,
    timeout: float = 60.0,
    headers: dict[str, str] | None = None,
) -> Any:
    url = profile.base + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})

    data = None
    request_headers = {
        "Authorization": f"Bearer {profile.token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        # Omitted means "the instance default", which is what a single-cluster
        # install always wants.
        **({"X-Cubicle-Cluster": profile.cluster} if profile.cluster else {}),
        **(headers or {}),
    }
    if body is not None:
        data = json.dumps(body).encode()
        request_headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=data, method=method, headers=request_headers)
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as response:  # noqa: S310
            payload = response.read()
            if raw:
                return payload
            if not payload:
                return None
            return json.loads(payload)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        try:
            parsed = json.loads(detail)
            message = parsed.get("detail") or parsed.get("message") or detail
            if isinstance(message, dict):
                message = message.get("message", str(message))
        except json.JSONDecodeError:
            message = detail or error.reason
        raise CubicleError(f"{error.code}: {message}") from None
    except urllib.error.URLError as error:
        raise CubicleError(f"Could not reach {profile.base}: {error.reason}") from None


def stream(profile: Profile, path: str, *, params: dict[str, Any] | None = None):
    """Yield decoded server-sent events until interrupted."""
    url = profile.base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {profile.token}",
            "Accept": "text/event-stream",
            "User-Agent": USER_AGENT,
            **({"X-Cubicle-Cluster": profile.cluster} if profile.cluster else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=None) as response:  # noqa: S310
        for line in response:
            decoded = line.decode(errors="replace").strip()
            if decoded.startswith("data:"):
                try:
                    yield json.loads(decoded[5:].strip())
                except json.JSONDecodeError:
                    continue


# ── output helpers ───────────────────────────────────────────────────────────

TTY = sys.stdout.isatty()


def paint(text: str, colour: str) -> str:
    if not TTY:
        return text
    codes = {
        "green": "\033[38;5;154m",
        "red": "\033[31m",
        "yellow": "\033[33m",
        "blue": "\033[34m",
        "dim": "\033[2m",
        "bold": "\033[1m",
    }
    return f"{codes.get(colour, '')}{text}\033[0m"


def table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return paint("  (nothing to show)", "dim")
    widths = [
        max(len(str(headers[i])), *(len(str(row[i])) for row in rows)) for i in range(len(headers))
    ]
    lines = ["  " + "  ".join(paint(h.upper().ljust(widths[i]), "dim") for i, h in enumerate(headers))]
    for row in rows:
        lines.append("  " + "  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)))
    return "\n".join(lines)
