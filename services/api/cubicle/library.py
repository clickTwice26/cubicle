"""The application catalogue.

A curated list of images that run well on a small cluster, with the port,
volumes and environment each one actually needs already filled in. Picking one
is meant to be the difference between "deploy Vaultwarden" and reading a
docker-compose file to find out which directory holds the data.

Shipped as data rather than fetched, unlike the function marketplace: these
entries name images that get pulled and run with volumes attached, and an index
that decides that should travel with the release that was tested against it
rather than change under a running instance.

Three placeholder forms let an entry describe values only the instance knows:
``from: "hostname"`` and ``from: "url"`` are filled in from the app's own
address, and ``generate: true`` means a secret the operator should not have to
invent.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from .logging_setup import log

CATALOGUE = Path(__file__).parent / "data" / "app_library.json"

#: Long enough that nobody is tempted to treat it as a password to remember.
GENERATED_LENGTH = 32


@dataclass(slots=True)
class EnvSpec:
    key: str
    label: str = ""
    help: str = ""
    value: str = ""
    #: "hostname" or "url" — filled from the app's own address at create time.
    source: str = ""
    secret: bool = False
    generate: bool = False

    @property
    def required(self) -> bool:
        """Needs a value from somewhere, but not necessarily from a person."""
        return not self.value and not self.source and not self.generate

    @property
    def prompt(self) -> bool:
        """Whether to put this in front of the operator at all.

        A label is the author saying this is a choice — a timezone, a sign-up
        policy. Plumbing like NODE_ENV=production carries no label and is
        simply applied: asking about it is how a two-field form becomes a
        six-field one nobody reads.
        """
        if self.source:
            return False
        return self.required or self.generate or bool(self.label)


@dataclass(slots=True)
class Entry:
    slug: str
    name: str
    summary: str
    category: str
    image: str
    port: int
    memory_mb: int
    cpus: float
    volumes: list[dict] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    env: list[EnvSpec] = field(default_factory=list)
    requires: str = ""
    docs: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "summary": self.summary,
            "category": self.category,
            "image": self.image,
            "port": self.port,
            "memory_mb": self.memory_mb,
            "cpus": self.cpus,
            "volumes": self.volumes,
            "links": self.links,
            "requires": self.requires,
            "docs": self.docs,
            "env": [
                {
                    "key": spec.key,
                    "label": spec.label or spec.key,
                    "help": spec.help,
                    "value": "" if spec.secret else spec.value,
                    "secret": spec.secret,
                    "generated": spec.generate,
                    "derived": bool(spec.source),
                    "required": spec.required,
                    "prompt": spec.prompt,
                }
                for spec in self.env
            ],
        }


@lru_cache
def catalogue() -> list[Entry]:
    """Everything in the library, read once."""
    try:
        payload = json.loads(CATALOGUE.read_text())
    except (OSError, ValueError) as exc:
        log.warning("application catalogue unreadable", error=str(exc))
        return []

    entries: list[Entry] = []
    for raw in payload.get("apps", []):
        try:
            entries.append(
                Entry(
                    slug=str(raw["slug"]),
                    name=str(raw["name"]),
                    summary=str(raw.get("summary", "")),
                    category=str(raw.get("category", "Other")),
                    image=str(raw["image"]),
                    port=int(raw.get("port", 3000)),
                    memory_mb=int(raw.get("memory_mb", 512)),
                    cpus=float(raw.get("cpus", 1)),
                    volumes=list(raw.get("volumes", [])),
                    links=list(raw.get("links", [])),
                    requires=str(raw.get("requires", "")),
                    docs=str(raw.get("docs", "")),
                    env=[
                        EnvSpec(
                            key=str(item["key"]),
                            label=str(item.get("label", "")),
                            help=str(item.get("help", "")),
                            value=str(item.get("value", "")),
                            source=str(item.get("from", "")),
                            secret=bool(item.get("secret")),
                            generate=bool(item.get("generate")),
                        )
                        for item in raw.get("env", [])
                    ],
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("skipping catalogue entry", slug=raw.get("slug"), error=str(exc))
    return entries


def get(slug: str) -> Entry | None:
    return next((entry for entry in catalogue() if entry.slug == slug), None)


def resolve_env(
    entry: Entry, *, supplied: dict[str, str], hostname: str, url: str
) -> dict[str, str]:
    """The environment this app starts with.

    What the operator typed wins. Everything else comes from the entry: a fixed
    value, the app's own address, or a generated secret — so the common case is
    picking something from a list and pressing create.
    """
    env: dict[str, str] = {}
    for spec in entry.env:
        given = supplied.get(spec.key, "").strip()
        if given:
            env[spec.key] = given
        elif spec.source == "hostname" and hostname:
            env[spec.key] = hostname
        elif spec.source == "url" and url:
            env[spec.key] = url
        elif spec.generate:
            env[spec.key] = secrets.token_urlsafe(GENERATED_LENGTH)
        elif spec.value:
            env[spec.key] = spec.value
    # Anything the operator added that the entry never mentioned.
    for key, value in supplied.items():
        if key not in env and key.strip():
            env[key.strip()] = value
    return env
