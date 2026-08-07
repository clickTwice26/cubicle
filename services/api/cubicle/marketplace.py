"""The community function marketplace.

There is no Cubicle server, so there is no Cubicle registry either. A registry
here is a JSON index at a URL — by default one in the Cubicle repository, which
anyone can add to with a pull request, and which an operator can point somewhere
else entirely. That keeps the feature working with no infrastructure behind it,
and keeps a company's private registry a URL change rather than a fork.

Installing runs somebody else's code on your cluster, with whatever env and
secrets that namespace can reach. That is the point of the feature and it is
also the risk in it, so nothing here installs without being asked, nothing
updates itself, and the whole source is fetched and shown before anything is
created. A function is one readable file; that is a better position than most
package managers put you in, and the console leans on it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import runtimes
from .config import settings
from .logging_setup import log

#: A package is source code, not an archive. These bound what a registry can
#: talk this instance into holding in memory before anything is validated.
MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_PACKAGE_BYTES = 1 * 1024 * 1024
MAX_FILES = 12
MAX_FILE_BYTES = 256 * 1024

#: The same shape a function name has to be, single characters included — a
#: package slug becomes a function name, so a slug this refuses is a package
#: nobody could install anyway.
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$|^[a-z0-9]$")

#: Read far enough to see an over-long slug and refuse it. Reading exactly the
#: maximum would truncate one into a different, valid slug instead.
SLUG_READ_LIMIT = 200

#: Only these ever reach a build. A package naming anything else is refused
#: rather than filtered, because a package with files it cannot install is not
#: the package its author tested.
ALLOWED_FILES = {"handler.py", "requirements.txt", "handler.js", "package.json", "README.md"}

TIMEOUT = httpx.Timeout(10.0, read=20.0)


class MarketplaceError(RuntimeError):
    """The registry could not be read, or gave us something unusable."""


@dataclass
class Listing:
    """One row of a registry index."""

    slug: str
    name: str
    summary: str = ""
    author: str = ""
    runtime: str = runtimes.DEFAULT
    language: str = ""
    tags: list[str] = field(default_factory=list)
    url: str = ""
    version: str = ""
    homepage: str = ""

    def as_json(self) -> dict:
        return {
            "slug": self.slug,
            "name": self.name,
            "summary": self.summary,
            "author": self.author,
            "runtime": self.runtime,
            "language": runtimes.get(self.runtime).language,
            "tags": self.tags,
            "url": self.url,
            "version": self.version,
            "homepage": self.homepage,
        }


@dataclass
class Package:
    """A complete function someone published: metadata plus its source."""

    slug: str
    name: str
    runtime: str
    files: dict[str, str]
    summary: str = ""
    author: str = ""
    license: str = ""
    version: str = ""
    homepage: str = ""
    method: str = "POST"
    ctx_access: str = "rw"
    function_type: str = "dependent"
    memory_mb: int = 128
    timeout_s: int = 30
    tags: list[str] = field(default_factory=list)
    #: What the function needs in Global env to work. Declared, never set for
    #: you — an installer that writes secrets on your behalf is a bad idea.
    env: list[dict] = field(default_factory=list)
    readme: str = ""

    def as_json(self) -> dict:
        spec = runtimes.get(self.runtime)
        return {
            "slug": self.slug,
            "name": self.name,
            "summary": self.summary,
            "author": self.author,
            "license": self.license,
            "version": self.version,
            "homepage": self.homepage,
            "runtime": self.runtime,
            "runtime_label": spec.label,
            "language": spec.language,
            "method": self.method,
            "ctx_access": self.ctx_access,
            "function_type": self.function_type,
            "memory_mb": self.memory_mb,
            "timeout_s": self.timeout_s,
            "tags": self.tags,
            "env": self.env,
            "readme": self.readme,
            "files": self.files,
        }


def _text(value: Any, *, limit: int = 400) -> str:
    return str(value or "").strip()[:limit]


def parse_index(payload: Any, *, base_url: str) -> list[Listing]:
    """Turn a registry index into listings, skipping entries that make no sense.

    One malformed row does not spoil a registry: it is dropped and logged. A
    malformed *index* is an error, because then nothing can be trusted.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("packages"), list):
        raise MarketplaceError(
            "That URL did not return a registry index. Expected an object with a "
            "'packages' array."
        )

    listings: list[Listing] = []
    for entry in payload["packages"][:500]:
        if not isinstance(entry, dict):
            continue
        slug = _text(entry.get("slug"), limit=SLUG_READ_LIMIT).lower()
        if not SLUG_RE.match(slug):
            log.warning("skipping marketplace entry with an unusable slug", slug=slug)
            continue
        listings.append(
            Listing(
                slug=slug,
                name=_text(entry.get("name")) or slug,
                summary=_text(entry.get("summary")),
                author=_text(entry.get("author"), limit=80),
                runtime=_text(entry.get("runtime"), limit=32) or runtimes.DEFAULT,
                tags=[_text(tag, limit=24) for tag in (entry.get("tags") or [])][:8],
                url=_absolute(_text(entry.get("url"), limit=500), base_url),
                version=_text(entry.get("version"), limit=32),
                homepage=_text(entry.get("homepage"), limit=500),
            )
        )
    return listings


def _absolute(url: str, base: str) -> str:
    """Resolve a package URL against the index it came from.

    Registries are mostly a directory of files next to an index, so relative
    paths are the natural way to write one. Anything absolute is left alone.
    """
    if not url or url.startswith(("http://", "https://")):
        return url
    return base.rsplit("/", 1)[0] + "/" + url.lstrip("./")


def parse_package(payload: Any) -> Package:
    """Validate a published package hard enough to create a function from it."""
    if not isinstance(payload, dict):
        raise MarketplaceError("That package is not a JSON object.")

    slug = _text(payload.get("slug"), limit=SLUG_READ_LIMIT).lower()
    if not SLUG_RE.match(slug):
        raise MarketplaceError(
            "The package has no usable slug. It must be lower-case letters, " "digits and hyphens."
        )

    runtime = _text(payload.get("runtime"), limit=32) or runtimes.DEFAULT
    if runtime not in runtimes.RUNTIMES:
        raise MarketplaceError(
            f"This package needs the '{runtime}' runtime, which this instance "
            "does not know about."
        )

    files = payload.get("files")
    if not isinstance(files, dict) or not files:
        raise MarketplaceError("The package carries no files.")
    if len(files) > MAX_FILES:
        raise MarketplaceError(f"The package has more than {MAX_FILES} files.")

    spec = runtimes.get(runtime)
    cleaned: dict[str, str] = {}
    for name, body in files.items():
        name = str(name)
        if name not in ALLOWED_FILES:
            raise MarketplaceError(f"The package contains an unexpected file: {name}")
        if not isinstance(body, str):
            raise MarketplaceError(f"{name} is not text.")
        if len(body.encode()) > MAX_FILE_BYTES:
            raise MarketplaceError(f"{name} is larger than {MAX_FILE_BYTES // 1024} KB.")
        cleaned[name] = body

    if spec.entry_file not in cleaned:
        raise MarketplaceError(
            f"A {spec.label} package must contain {spec.entry_file}; this one does not."
        )

    return Package(
        slug=slug,
        name=_text(payload.get("name")) or slug,
        runtime=runtime,
        files=cleaned,
        summary=_text(payload.get("summary")),
        author=_text(payload.get("author"), limit=80),
        license=_text(payload.get("license"), limit=40),
        version=_text(payload.get("version"), limit=32),
        homepage=_text(payload.get("homepage"), limit=500),
        method=(_text(payload.get("method"), limit=8) or "POST").upper(),
        ctx_access=_text(payload.get("ctx_access"), limit=4) or "rw",
        function_type=_text(payload.get("function_type"), limit=12) or "dependent",
        memory_mb=_bounded(payload.get("memory_mb"), 128, 64, 8192),
        timeout_s=_bounded(payload.get("timeout_s"), 30, 1, 900),
        tags=[_text(tag, limit=24) for tag in (payload.get("tags") or [])][:8],
        env=[
            {
                "key": _text(item.get("key"), limit=64),
                "required": bool(item.get("required")),
                "description": _text(item.get("description")),
            }
            for item in (payload.get("env") or [])[:20]
            if isinstance(item, dict) and _text(item.get("key"), limit=64)
        ],
        readme=_text(payload.get("readme") or cleaned.get("README.md", ""), limit=20000),
    )


def _bounded(value: Any, fallback: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return fallback


async def _fetch(url: str, *, limit: int) -> Any:
    if not url.startswith(("http://", "https://")):
        raise MarketplaceError("A registry URL must be http or https.")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise MarketplaceError(f"Could not reach {url}: {exc}") from exc

    if response.status_code != 200:
        raise MarketplaceError(f"{url} answered {response.status_code}.")
    if len(response.content) > limit:
        raise MarketplaceError(f"{url} returned more than {limit // 1024} KB.")
    try:
        return response.json()
    except ValueError as exc:
        raise MarketplaceError(f"{url} did not return JSON.") from exc


async def index(url: str | None = None) -> tuple[str, list[Listing]]:
    """Every package a registry lists."""
    source = url or settings.marketplace_url
    return source, parse_index(await _fetch(source, limit=MAX_INDEX_BYTES), base_url=source)


async def package(url: str) -> Package:
    """One package, fetched and validated, ready to be shown before installing."""
    return parse_package(await _fetch(url, limit=MAX_PACKAGE_BYTES))


def publish_bundle(
    *,
    slug: str,
    name: str,
    summary: str,
    author: str,
    fn,
    files: dict[str, str],
) -> dict:
    """The package document for a function on this instance.

    Publishing is a document you take somewhere, not a call to a service: there
    is no service. The console shows it, lets you copy it, and points at the
    registry's pull request page.
    """
    shareable = {name_: body for name_, body in files.items() if name_ in ALLOWED_FILES}
    return {
        "schema": 1,
        "slug": slug,
        "name": name,
        "summary": summary,
        "author": author,
        "version": "1.0.0",
        "license": "MIT",
        "runtime": fn.runtime,
        "method": fn.method,
        "ctx_access": fn.ctx_access,
        "function_type": fn.function_type,
        "memory_mb": fn.memory_mb,
        "timeout_s": fn.timeout_s,
        "tags": [],
        "env": [],
        "files": shareable,
    }
