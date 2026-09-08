"""Applications: deploy, route, scale, watch.

The deploy itself runs detached, the way a function build does — the request
that asks for one returns as soon as the deployment row exists, and everything
after that is reported through the deployment's status and its build log. That
is what lets the console show a build happening rather than a spinner.

Traffic only ever moves after the new containers answer. If a build fails, or
the release never becomes healthy, the previous one is still running and still
routed, and the failure is a row in the deployments list rather than an outage.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from slugify import slugify
from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from ..config import settings
from ..crypto import decrypt, encrypt, mask
from ..db import session_scope
from ..deps import CurrentCluster, CurrentPrincipal, DbSession, RequireAdmin, RequireDeveloper
from ..logging_setup import log
from ..models import App, AppDeployment, AppDomain, Cluster, GitCredential
from ..runtime import apps as runtime
from ..runtime import edge, services
from ..runtime.nodes import is_private, pick_node, public_address

router = APIRouter(prefix="/api/apps", tags=["apps"])

RESERVED_NAMES = {"api", "console", "docs", "setup", "assets", "fonts", "healthz", "metrics"}


def apps_base_domain(cluster: Cluster) -> str:
    """What an app's own subdomain hangs off.

    The hostname the console itself is served on, so an instance at
    ``cubicle.example.com`` gives its apps ``<app>.cubicle.example.com`` — one
    wildcard record covers every app that will ever exist here, and it is a
    record for a name the operator already owns and already points at this
    machine. Deriving it from the cluster's domain instead would put apps on
    ``<app>.example.com`` the moment someone set that to an apex, which is a
    different zone with different consequences.
    """
    host = settings.public_url.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    if host and host != "localhost" and "." in host:
        return host
    if cluster.ingress_domain and cluster.ingress_domain != "localhost":
        return cluster.ingress_domain
    if settings.domain and settings.domain != "localhost":
        return settings.domain
    return ""


# ── payloads ─────────────────────────────────────────────────────────────────


class CredentialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    provider: str = Field(default="github", pattern="^(github|gitlab|bitbucket|generic)$")
    username: str = Field(default="x-access-token", max_length=120)
    token: str = Field(min_length=8, max_length=400)


class AppCreate(BaseModel):
    name: str = Field(min_length=1, max_length=63)
    source_kind: str = Field(default="git", pattern="^(git|image)$")
    repo_url: str = Field(default="", max_length=500)
    branch: str = Field(default="main", max_length=120)
    credential_id: uuid.UUID | None = None
    image_ref: str = Field(default="", max_length=400)
    port: int = Field(default=3000, ge=1, le=65535)
    replicas: int = Field(default=1, ge=0, le=20)
    memory_mb: int = Field(default=512, ge=64, le=16384)
    cpus: float = Field(default=1.0, ge=0.1, le=32)
    env: dict[str, str] = Field(default_factory=dict)
    deploy_now: bool = True


class AppUpdate(BaseModel):
    #: Renaming moves the app's own subdomain and the name other apps reach it
    #: by. Custom domains and the instant link are unaffected.
    name: str | None = Field(default=None, min_length=1, max_length=63)
    branch: str | None = Field(default=None, max_length=120)
    repo_url: str | None = Field(default=None, max_length=500)
    credential_id: uuid.UUID | None = None
    image_ref: str | None = Field(default=None, max_length=400)
    port: int | None = Field(default=None, ge=1, le=65535)
    replicas: int | None = Field(default=None, ge=0, le=20)
    memory_mb: int | None = Field(default=None, ge=64, le=16384)
    cpus: float | None = Field(default=None, ge=0.1, le=32)
    health_path: str | None = Field(default=None, max_length=200)
    auto_deploy: bool | None = None
    links: list[str] | None = None
    volumes: list[dict] | None = None
    node_pool: str | None = Field(default=None, max_length=40)


class EnvUpdate(BaseModel):
    env: dict[str, str]


class DomainCreate(BaseModel):
    hostname: str = Field(min_length=3, max_length=253)
    primary: bool = False


# ── helpers ──────────────────────────────────────────────────────────────────


def read_env(app: App) -> dict[str, str]:
    if not app.env_ciphertext:
        return {}
    try:
        return json.loads(decrypt(app.env_ciphertext, aad=f"app:{app.id}"))
    except Exception:  # noqa: BLE001 - a rotated master key must not 500 the page
        log.warning("app env could not be decrypted", app=app.name)
        return {}


def write_env(app: App, env: dict[str, str]) -> None:
    app.env_ciphertext = encrypt(json.dumps(env), aad=f"app:{app.id}")


def serialize(app: App, *, containers: list[dict] | None = None) -> dict:
    primary = next((d for d in app.domains if d.is_primary), None) or (
        app.domains[0] if app.domains else None
    )
    latest = app.deployments[0] if app.deployments else None
    return {
        "id": str(app.id),
        "name": app.name,
        "source_kind": app.source_kind,
        "repo_url": app.repo_url,
        "branch": app.branch,
        "credential_id": str(app.credential_id) if app.credential_id else None,
        "credential_name": app.credential.name if app.credential else None,
        "image_ref": app.image_ref,
        "port": app.port,
        "replicas": app.replicas,
        "memory_mb": app.memory_mb,
        "cpus": app.cpus,
        "health_path": app.health_path,
        "node_pool": app.node_pool,
        "links": app.links or [],
        "volumes": app.volumes or [],
        "status": app.status,
        "last_error": app.last_error,
        "auto_deploy": app.auto_deploy,
        # Shown to anyone who could deploy by hand anyway; it is the
        # whole point of the hook that the URL is copyable.
        "webhook_path": f"/api/apps/{app.id}/webhook/{app.webhook_secret}",
        "definition": app.definition or {},
        "url": f"https://{primary.hostname}" if primary else "",
        # Works from the moment the app is live: no record, no certificate, no
        # wildcard. The other two addresses are things you arrange elsewhere.
        "instant_url": f"{settings.public_url.rstrip('/')}/{app.path_token}"
        if app.path_token
        else "",
        "path_token": app.path_token,
        "domains": [
            {"id": str(d.id), "hostname": d.hostname, "primary": d.is_primary} for d in app.domains
        ],
        "deployment": _deployment_out(latest) if latest else None,
        "deployment_count": len(app.deployments),
        "containers": containers or [],
        "created_at": app.created_at.isoformat() if app.created_at else None,
    }


def _deployment_out(deployment: AppDeployment, *, with_log: bool = False) -> dict:
    out = {
        "id": str(deployment.id),
        "number": deployment.number,
        "status": deployment.status,
        "trigger": deployment.trigger,
        "triggered_by": deployment.triggered_by,
        "commit_sha": deployment.commit_sha[:8],
        "commit_message": deployment.commit_message,
        "build_ms": deployment.build_ms,
        "error": deployment.error,
        "created_at": deployment.created_at.isoformat() if deployment.created_at else None,
        "finished_at": deployment.finished_at.isoformat() if deployment.finished_at else None,
    }
    if with_log:
        out["build_log"] = deployment.build_log
    return out


async def load_app(db, app_id: uuid.UUID, cluster: Cluster) -> App:
    app = (
        await db.execute(
            select(App)
            .where(App.id == app_id, App.cluster_id == cluster.id)
            .options(selectinload(App.domains), selectinload(App.deployments))
            # Without this the identity map hands back the collections as they
            # were before this request changed them, and a domain that was just
            # added comes back missing from the response that confirms it.
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such app.")
    return app


async def routing_table(db, cluster: Cluster) -> list[dict]:
    """Every hostname on this cluster, with the containers behind it."""
    apps = (
        (
            await db.execute(
                select(App).where(App.cluster_id == cluster.id).options(selectinload(App.domains))
            )
        )
        .scalars()
        .all()
    )
    table: list[dict] = []
    for app in apps:
        if app.status != "running" or not app.current_deployment_id:
            continue
        deployment = await db.get(AppDeployment, app.current_deployment_id)
        if deployment is None:
            continue
        upstreams = [
            f"{runtime.container_name(cluster.slug, app.name, deployment.number, index)}:{app.port}"
            for index in range(max(1, app.replicas))
        ]
        # One entry carries both addresses: the hostnames are rendered as site
        # blocks, the token as a path handle on the instance's own site.
        table.append(
            {
                "hostname": "",
                "token": app.path_token,
                "upstreams": upstreams,
                "app": app.name,
            }
        )
        for domain in app.domains:
            table.append(
                {
                    "hostname": domain.hostname,
                    "token": "",
                    "upstreams": upstreams,
                    "app": app.name,
                }
            )
    return table


async def republish_routes(cluster_id: uuid.UUID) -> None:
    """Regenerate the whole edge fragment for a cluster and reload."""
    async with session_scope() as db:
        cluster = await db.get(Cluster, cluster_id)
        if cluster is None:
            return
        table = await routing_table(db, cluster)
        # An instance with a domain has Caddy terminating TLS, and app
        # hostnames get their own certificates. Without one there is nothing to
        # issue them, and the app is served over plain HTTP.
        tls = bool(cluster.ingress_domain) or settings.domain not in ("", "localhost")
    await edge.apply(table, tls=tls)


async def link_env(db, cluster: Cluster, app: App) -> dict[str, str]:
    """Connection details for the things this app says it is linked to."""
    injected: dict[str, str] = {}
    for link in app.links or []:
        if link in ("postgres", "redis"):
            service = await services.get_service(db, cluster.id, link)
            if service is None or service.status != "running":
                continue
            url = services.connection_url(service)
            injected["DATABASE_URL" if link == "postgres" else "REDIS_URL"] = url
        else:
            other = (
                await db.execute(select(App).where(App.cluster_id == cluster.id, App.name == link))
            ).scalar_one_or_none()
            if other is None:
                continue
            key = link.upper().replace("-", "_") + "_URL"
            # The alias is stable across deploys; the container name is not.
            injected[key] = f"http://{slugify(other.name)}:{other.port}"
    return injected


# ── git credentials ──────────────────────────────────────────────────────────


NGINX_SNIPPET = """\
# Applications on this Cubicle instance. One block covers every app that will
# ever run here — Cubicle routes by hostname behind it — so nothing in nginx
# changes when you add one.

server {{
    listen 80;
    server_name *.{base};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl;
    server_name *.{base};

    # A wildcard certificate cannot be issued over HTTP-01. With DNS at
    # Cloudflare that is:
    #   certbot certonly --dns-cloudflare -d '*.{base}'
    ssl_certificate     /etc/letsencrypt/live/{base}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{base}/privkey.pem;

    location / {{
        proxy_pass         http://127.0.0.1:{port};
        proxy_http_version 1.1;

        # Host is what Cubicle routes on. Without it every app hostname
        # arrives looking like the same request.
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        # Server-sent events: no buffering, and long enough to outlive a
        # function's timeout.
        proxy_buffering    off;
        proxy_cache        off;
        proxy_read_timeout 15m;
    }}
}}
"""


@router.get("/hosting")
async def hosting(db: DbSession, cluster: CurrentCluster, _: CurrentPrincipal):
    """What an app's addresses look like on this instance, with real values.

    The console renders the DNS record from this rather than from a placeholder,
    because a guide that says example.com is a guide people have to translate.
    """
    base = apps_base_domain(cluster)
    instance = settings.public_url.rstrip("/")
    node = await pick_node(db, cluster, cluster.default_node_pool)
    address = await public_address(node.docker_host)
    return {
        "base_domain": base,
        "instance_url": instance,
        "tls": instance.startswith("https://"),
        # "caddy" — this instance owns 80/443 and issues its own certificates.
        # "proxy" — something else does, and app hostnames need a server block
        # and a certificate there. Getting this wrong is the difference between
        # a working guide and one that explains someone else's install.
        "edge_mode": "proxy" if settings.behind_proxy else "caddy",
        "proxy_snippet": (
            NGINX_SNIPPET.format(base=base, port=settings.http_port)
            if settings.behind_proxy and base
            else ""
        ),
        "server_ip": address,
        # True when the machine is behind NAT, so the console can say that the
        # record wants the address in front of it rather than this one.
        "server_ip_private": bool(address) and is_private(address),
        # The one record that covers every app that will ever exist here.
        "wildcard_record": {
            "type": "A",
            "name": f"*.{base}" if base else "",
            "value": address,
        },
        "example_hostname": f"my-app.{base}" if base else "",
        "configured": bool(base),
    }


@router.get("/credentials")
async def list_credentials(db: DbSession, cluster: CurrentCluster, _: CurrentPrincipal):
    rows = (
        (
            await db.execute(
                select(GitCredential)
                .where(GitCredential.cluster_id == cluster.id)
                .order_by(GitCredential.name)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "provider": row.provider,
            "username": row.username,
            "token_hint": mask(decrypt(row.token_ciphertext, aad="git:token")),
            "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        }
        for row in rows
    ]


@router.post("/credentials", status_code=status.HTTP_201_CREATED)
async def create_credential(
    payload: CredentialCreate, db: DbSession, cluster: CurrentCluster, principal: RequireAdmin
):
    credential = GitCredential(
        cluster_id=cluster.id,
        name=payload.name.strip(),
        provider=payload.provider,
        username=payload.username.strip() or "x-access-token",
        token_ciphertext=encrypt(payload.token.strip(), aad="git:token"),
    )
    db.add(credential)
    await db.commit()
    await db.refresh(credential)
    log.info("git credential added", provider=payload.provider, by=principal.user.email)
    return {"id": str(credential.id), "name": credential.name, "provider": credential.provider}


@router.delete("/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: uuid.UUID, db: DbSession, cluster: CurrentCluster, _: RequireAdmin
) -> Response:
    await db.execute(
        delete(GitCredential).where(
            GitCredential.id == credential_id, GitCredential.cluster_id == cluster.id
        )
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── apps ─────────────────────────────────────────────────────────────────────


@router.get("")
async def list_apps(db: DbSession, cluster: CurrentCluster, _: CurrentPrincipal):
    apps = (
        (
            await db.execute(
                select(App)
                .where(App.cluster_id == cluster.id)
                .options(selectinload(App.domains), selectinload(App.deployments))
                .order_by(App.name)
            )
        )
        .scalars()
        .all()
    )
    return [serialize(app) for app in apps]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_app(
    payload: AppCreate, db: DbSession, cluster: CurrentCluster, principal: RequireDeveloper
):
    name = slugify(payload.name)[:63]
    if not name or name in RESERVED_NAMES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"'{payload.name}' is not a usable name.")
    if payload.source_kind == "git" and not payload.repo_url.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A git app needs a repository URL.")
    if payload.source_kind == "image" and not payload.image_ref.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An image app needs an image reference.")

    exists = (
        await db.execute(select(App).where(App.cluster_id == cluster.id, App.name == name))
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"This cluster already has an app '{name}'.")

    app = App(
        cluster_id=cluster.id,
        name=name,
        source_kind=payload.source_kind,
        repo_url=payload.repo_url.strip(),
        branch=payload.branch.strip() or "main",
        credential_id=payload.credential_id,
        image_ref=payload.image_ref.strip(),
        port=payload.port,
        replicas=payload.replicas,
        memory_mb=payload.memory_mb,
        cpus=payload.cpus,
        node_pool=cluster.default_node_pool,
        webhook_secret=runtime.new_secret(),
        path_token=runtime.new_path_token(),
        status="created",
    )
    db.add(app)
    await db.flush()
    write_env(app, payload.env)

    # A hostname of its own from the start, so the app has an address before it
    # has a release. On an install with a domain this resolves for free.
    base = apps_base_domain(cluster)
    if base:
        db.add(AppDomain(app_id=app.id, hostname=f"{name}.{base}", is_primary=True))

    await db.commit()
    app = await load_app(db, app.id, cluster)
    log.info("app created", app=name, cluster=cluster.slug, by=principal.user.email)

    if payload.deploy_now:
        await _queue_deploy(db, cluster, app, trigger="manual", by=principal.user.email)
        app = await load_app(db, app.id, cluster)
    return serialize(app)


@router.get("/{app_id}")
async def get_app(app_id: uuid.UUID, db: DbSession, cluster: CurrentCluster, _: CurrentPrincipal):
    app = await load_app(db, app_id, cluster)
    node = await pick_node(db, cluster, app.node_pool)
    containers = await runtime.running_containers(node.docker_host, cluster.slug, app.name)
    return serialize(app, containers=containers)


@router.patch("/{app_id}")
async def update_app(
    app_id: uuid.UUID,
    payload: AppUpdate,
    db: DbSession,
    cluster: CurrentCluster,
    principal: RequireDeveloper,
):
    app = await load_app(db, app_id, cluster)
    changes = payload.model_dump(exclude_unset=True)
    scale_only = set(changes) <= {"replicas"}

    old_name = app.name
    renamed = False
    if "name" in changes:
        new_name = slugify(str(changes.pop("name")))[:63]
        if not new_name or new_name in RESERVED_NAMES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"'{new_name}' is not a usable name.")
        if new_name != old_name:
            taken = (
                await db.execute(
                    select(App).where(App.cluster_id == cluster.id, App.name == new_name)
                )
            ).scalar_one_or_none()
            if taken is not None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT, f"This cluster already has an app '{new_name}'."
                )
            base = apps_base_domain(cluster)
            for domain in app.domains:
                # Only the hostname this app was given; a custom domain is the
                # operator's and is not ours to rewrite.
                if base and domain.hostname == f"{old_name}.{base}":
                    domain.hostname = f"{new_name}.{base}"
            app.name = new_name
            renamed = True

    for field, value in changes.items():
        setattr(app, field, value)
    await db.commit()

    if renamed:
        # The containers carry the old name, and nothing finds them by the new
        # one — so they go, and the current release comes back up renamed.
        node = await pick_node(db, cluster, app.node_pool)
        await runtime.remove_app_containers(node.docker_host, old_name)
        if app.current_deployment_id:
            asyncio.create_task(_release_current(cluster.id, app.id))  # noqa: RUF006
        else:
            await republish_routes(cluster.id)
        log.info("app renamed", was=old_name, now=app.name, by=principal.user.email)

    # Replicas take effect without a rebuild: the image is already there, so
    # this is starting or stopping containers, not deploying.
    if scale_only and app.status == "running" and app.current_deployment_id:
        await _rescale(cluster.id, app.id)
    app = await load_app(db, app_id, cluster)
    log.info("app updated", app=app.name, fields=sorted(changes), by=principal.user.email)
    return serialize(app)


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_app(
    app_id: uuid.UUID,
    db: DbSession,
    cluster: CurrentCluster,
    principal: RequireDeveloper,
    keep_volumes: bool = False,
) -> Response:
    app = await load_app(db, app_id, cluster)
    node = await pick_node(db, cluster, app.node_pool)
    name = app.name
    await runtime.destroy(node.docker_host, cluster.slug, name, keep_volumes=keep_volumes)
    await db.delete(app)
    await db.commit()
    await republish_routes(cluster.id)
    log.info("app deleted", app=name, cluster=cluster.slug, by=principal.user.email)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── env ──────────────────────────────────────────────────────────────────────


@router.get("/{app_id}/env")
async def get_env(app_id: uuid.UUID, db: DbSession, cluster: CurrentCluster, _: RequireDeveloper):
    app = await load_app(db, app_id, cluster)
    return {"env": read_env(app)}


@router.put("/{app_id}/env")
async def set_env(
    app_id: uuid.UUID,
    payload: EnvUpdate,
    db: DbSession,
    cluster: CurrentCluster,
    principal: RequireDeveloper,
):
    app = await load_app(db, app_id, cluster)
    clean = {k.strip(): v for k, v in payload.env.items() if k.strip()}
    write_env(app, clean)
    await db.commit()
    log.info("app env updated", app=app.name, keys=len(clean), by=principal.user.email)
    # Env reaches a container at start, so it applies on the next release.
    return {"env": clean, "restart_required": app.status == "running"}


# ── domains ──────────────────────────────────────────────────────────────────


@router.post("/{app_id}/domains", status_code=status.HTTP_201_CREATED)
async def add_domain(
    app_id: uuid.UUID,
    payload: DomainCreate,
    db: DbSession,
    cluster: CurrentCluster,
    principal: RequireDeveloper,
):
    app = await load_app(db, app_id, cluster)
    hostname = payload.hostname.strip().lower().rstrip(".")
    if "/" in hostname or " " in hostname or "." not in hostname:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That is not a hostname.")

    taken = (
        await db.execute(select(AppDomain).where(AppDomain.hostname == hostname))
    ).scalar_one_or_none()
    if taken is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That hostname is already routed.")

    if payload.primary:
        for domain in app.domains:
            domain.is_primary = False
    db.add(
        AppDomain(
            app_id=app.id,
            hostname=hostname,
            is_primary=payload.primary or not app.domains,
        )
    )
    await db.commit()
    await republish_routes(cluster.id)
    log.info("app domain added", app=app.name, hostname=hostname, by=principal.user.email)
    return serialize(await load_app(db, app_id, cluster))


@router.delete("/{app_id}/domains/{domain_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_domain(
    app_id: uuid.UUID,
    domain_id: uuid.UUID,
    db: DbSession,
    cluster: CurrentCluster,
    _: RequireDeveloper,
) -> Response:
    app = await load_app(db, app_id, cluster)
    await db.execute(delete(AppDomain).where(AppDomain.id == domain_id, AppDomain.app_id == app.id))
    await db.commit()
    await republish_routes(cluster.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── deployments ──────────────────────────────────────────────────────────────


@router.get("/{app_id}/deployments")
async def list_deployments(
    app_id: uuid.UUID, db: DbSession, cluster: CurrentCluster, _: CurrentPrincipal
):
    app = await load_app(db, app_id, cluster)
    return [_deployment_out(d) for d in app.deployments[:50]]


@router.get("/{app_id}/deployments/{deployment_id}")
async def get_deployment(
    app_id: uuid.UUID,
    deployment_id: uuid.UUID,
    db: DbSession,
    cluster: CurrentCluster,
    _: CurrentPrincipal,
):
    await load_app(db, app_id, cluster)
    deployment = await db.get(AppDeployment, deployment_id)
    if deployment is None or deployment.app_id != app_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such deployment.")
    out = _deployment_out(deployment, with_log=True)
    # While it runs the transcript lives in Redis; afterwards it is the row.
    if deployment.status in ("pending", "building", "releasing"):
        live_lines = await runtime.read_log(str(deployment.id))
        if live_lines:
            out["build_log"] = "\n".join(live_lines)
    return out


@router.get("/{app_id}/deployments/{deployment_id}/stream")
async def stream_build_log(
    app_id: uuid.UUID,
    deployment_id: uuid.UUID,
    db: DbSession,
    cluster: CurrentCluster,
    _: CurrentPrincipal,
) -> StreamingResponse:
    """The build transcript as it is written, then the outcome."""
    await load_app(db, app_id, cluster)
    deployment = await db.get(AppDeployment, deployment_id)
    if deployment is None or deployment.app_id != app_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such deployment.")

    async def events():
        cursor = 0
        idle = 0
        while idle < 900:  # ~15 minutes of quiet is a dead build
            lines = await runtime.read_log(str(deployment_id), cursor)
            if lines:
                cursor += len(lines)
                idle = 0
                yield f"event: log\ndata: {json.dumps({'lines': lines})}\n\n"
            else:
                idle += 1

            async with session_scope() as fresh:
                current = await fresh.get(AppDeployment, deployment_id)
                state = current.status if current else "failed"
                error = current.error if current else None
            if state not in ("pending", "building", "releasing"):
                tail = await runtime.read_log(str(deployment_id), cursor)
                if tail:
                    yield f"event: log\ndata: {json.dumps({'lines': tail})}\n\n"
                yield f"event: done\ndata: {json.dumps({'status': state, 'error': error})}\n\n"
                return
            await asyncio.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{app_id}/deploy", status_code=status.HTTP_202_ACCEPTED)
async def deploy(
    app_id: uuid.UUID, db: DbSession, cluster: CurrentCluster, principal: RequireDeveloper
):
    app = await load_app(db, app_id, cluster)
    deployment = await _queue_deploy(db, cluster, app, trigger="manual", by=principal.user.email)
    return _deployment_out(deployment)


@router.post("/{app_id}/stop")
async def stop_app(
    app_id: uuid.UUID, db: DbSession, cluster: CurrentCluster, principal: RequireDeveloper
):
    app = await load_app(db, app_id, cluster)
    node = await pick_node(db, cluster, app.node_pool)
    await runtime.remove_other_deployments(
        node.docker_host, cluster.slug, app.name, keep_deployment=None
    )
    app.status = "stopped"
    await db.commit()
    await republish_routes(cluster.id)
    log.info("app stopped", app=app.name, by=principal.user.email)
    return serialize(await load_app(db, app_id, cluster))


@router.post("/{app_id}/restart")
async def restart_app(
    app_id: uuid.UUID, db: DbSession, cluster: CurrentCluster, principal: RequireDeveloper
):
    """Start the current release again, with whatever env it has now."""
    app = await load_app(db, app_id, cluster)
    if not app.current_deployment_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "This app has never been deployed.")
    asyncio.create_task(_release_current(cluster.id, app.id))  # noqa: RUF006
    log.info("app restarting", app=app.name, by=principal.user.email)
    return {"status": "restarting"}


# ── runtime logs ─────────────────────────────────────────────────────────────


@router.get("/{app_id}/logs")
async def app_logs(
    app_id: uuid.UUID,
    db: DbSession,
    cluster: CurrentCluster,
    _: CurrentPrincipal,
    since: float = Query(0, ge=0),
    lines: int = Query(200, ge=1, le=2000),
):
    app = await load_app(db, app_id, cluster)
    node = await pick_node(db, cluster, app.node_pool)
    containers = await runtime.running_containers(node.docker_host, cluster.slug, app.name)
    names = [c["name"] for c in containers]
    if not names:
        return {"lines": [], "now": time.time()}
    entries = await runtime.logs_since(node.docker_host, names, since, lines=lines)
    return {"lines": entries, "now": time.time()}


@router.get("/{app_id}/logs/stream")
async def stream_logs(
    app_id: uuid.UUID, db: DbSession, cluster: CurrentCluster, _: CurrentPrincipal
) -> StreamingResponse:
    """A live tail across every replica."""
    app = await load_app(db, app_id, cluster)
    node = await pick_node(db, cluster, app.node_pool)
    host, slug, name = node.docker_host, cluster.slug, app.name

    async def events():
        # Docker's `since` has second resolution, so the first read takes a
        # tail and every read after that starts one second back and drops what
        # it has already sent. Duplicates are cheap; gaps are not.
        seen: set[str] = set()
        since = 0.0
        while True:
            containers = await runtime.running_containers(host, slug, name)
            names = [c["name"] for c in containers]
            if names:
                entries = await runtime.logs_since(host, names, since, lines=200)
                fresh = []
                for entry in entries:
                    key = f"{entry['replica']}|{entry['time']}|{entry['text']}"
                    if key in seen:
                        continue
                    seen.add(key)
                    fresh.append(entry)
                if len(seen) > 5000:
                    seen = set(list(seen)[-2000:])
                if fresh:
                    yield f"event: log\ndata: {json.dumps({'lines': fresh})}\n\n"
                since = max(time.time() - 2, 1)
            else:
                yield "event: ping\ndata: {}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── webhook ──────────────────────────────────────────────────────────────────


@router.post("/{app_id}/webhook/{secret}", include_in_schema=False)
async def webhook(app_id: uuid.UUID, secret: str, request: Request, db: DbSession):
    """Push-to-deploy. Unauthenticated by design, verified two ways.

    The URL carries a secret only the console has shown, and when the provider
    signs its payload the signature is checked against that same secret. A
    push to a branch the app does not track is accepted and ignored, because
    telling a webhook it was wrong just fills somebody's delivery log.
    """
    app = (await db.execute(select(App).where(App.id == app_id))).scalar_one_or_none()
    if app is None or not app.webhook_secret:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such hook.")
    if not hmac.compare_digest(secret, app.webhook_secret):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bad hook secret.")

    body = await request.body()
    signature = request.headers.get("x-hub-signature-256", "")
    if signature:
        expected = (
            "sha256=" + hmac.new(app.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        )
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Signature does not match.")

    if not app.auto_deploy:
        return {"deployed": False, "reason": "auto deploy is off for this app"}

    payload: dict[str, Any] = {}
    with contextlib.suppress(ValueError):
        payload = json.loads(body or b"{}")
    ref = str(payload.get("ref", ""))
    if ref and not ref.endswith(f"/{app.branch}"):
        return {"deployed": False, "reason": f"push was to {ref}, not {app.branch}"}

    cluster = await db.get(Cluster, app.cluster_id)
    app = await load_app(db, app.id, cluster)
    sender = str((payload.get("sender") or {}).get("login", "")) or "webhook"
    deployment = await _queue_deploy(db, cluster, app, trigger="webhook", by=sender)
    log.info("webhook deploy accepted", app=app.name, by=sender)
    return {"deployed": True, "deployment": deployment.number}


# ── the deploy itself ────────────────────────────────────────────────────────


async def _queue_deploy(db, cluster: Cluster, app: App, *, trigger: str, by: str):
    number = (
        await db.execute(
            select(func.coalesce(func.max(AppDeployment.number), 0)).where(
                AppDeployment.app_id == app.id
            )
        )
    ).scalar_one() + 1

    deployment = AppDeployment(
        app_id=app.id, number=number, status="pending", trigger=trigger, triggered_by=by[:200]
    )
    db.add(deployment)
    app.status = "deploying"
    app.last_error = None
    await db.commit()
    await db.refresh(deployment)

    asyncio.create_task(_run_deploy(cluster.id, app.id, deployment.id))  # noqa: RUF006
    return deployment


async def _run_deploy(cluster_id: uuid.UUID, app_id: uuid.UUID, deployment_id: uuid.UUID) -> None:
    """Fetch, build, start, health-check, then move the traffic."""
    started = time.perf_counter()
    dep_key = str(deployment_id)

    async with session_scope() as db:
        cluster = await db.get(Cluster, cluster_id)
        app = await load_app(db, app_id, cluster)
        deployment = await db.get(AppDeployment, deployment_id)
        if cluster is None or deployment is None:
            return
        deployment.status = "building"
        node = await pick_node(db, cluster, app.node_pool)
        host = node.docker_host
        env = {**read_env(app), **(await link_env(db, cluster, app))}
        token = ""
        username = "x-access-token"
        if app.credential is not None:
            token = decrypt(app.credential.token_ciphertext, aad="git:token")
            username = app.credential.username
        snapshot = {
            "name": app.name,
            "slug": cluster.slug,
            "source_kind": app.source_kind,
            "repo_url": app.repo_url,
            "branch": app.branch,
            "image_ref": app.image_ref,
            "port": app.port,
            "replicas": max(1, app.replicas),
            "memory_mb": app.memory_mb,
            "cpus": app.cpus,
            "health_path": app.health_path,
            "volumes": app.volumes or [],
            "number": deployment.number,
        }
        await db.commit()

    error: str | None = None
    definition_out: dict[str, Any] = {}
    commit_sha = commit_message = ""

    try:
        await runtime.append_log(dep_key, f"$ deploy {snapshot['name']} #{snapshot['number']}")

        if snapshot["source_kind"] == "image":
            tag = snapshot["image_ref"]
            await runtime.pull_image(host=host, image=tag, deployment_id=dep_key)
            port = snapshot["port"]
            health_path = snapshot["health_path"]
        else:
            source = await runtime.fetch_source(
                repo_url=snapshot["repo_url"],
                branch=snapshot["branch"],
                username=username,
                token=token,
                deployment_id=dep_key,
            )
            commit_sha, commit_message = source.commit_sha, source.commit_message
            await runtime.append_log(
                dep_key, f"$ {commit_sha[:8]} {commit_message}" if commit_sha else "$ cloned"
            )

            definition = runtime.resolve_definition(source.path, fallback_port=snapshot["port"])
            definition_out = {
                "source": definition.detected,
                "port": definition.port,
                "image": definition.image,
            }
            tag = runtime.image_tag(snapshot["slug"], snapshot["name"], snapshot["number"])
            if definition.image:
                tag = definition.image
                await runtime.pull_image(host=host, image=tag, deployment_id=dep_key)
            else:
                await runtime.build_image(
                    host=host,
                    source=source,
                    definition=definition,
                    tag=tag,
                    deployment_id=dep_key,
                )
            env = {**definition.env, **env}
            port = definition.port or snapshot["port"]
            health_path = snapshot["health_path"] or definition.health_path

        async with session_scope() as db:
            deployment = await db.get(AppDeployment, deployment_id)
            if deployment is not None:
                deployment.status = "releasing"
                deployment.image_tag = tag
                deployment.commit_sha = commit_sha
                deployment.commit_message = commit_message
            await db.commit()

        names = await runtime.start_replicas(
            host=host,
            cluster_slug=snapshot["slug"],
            app_name=snapshot["name"],
            deployment=snapshot["number"],
            image=tag,
            replicas=snapshot["replicas"],
            port=port,
            env=env,
            memory_mb=snapshot["memory_mb"],
            cpus=snapshot["cpus"],
            volumes=snapshot["volumes"],
            deployment_id=dep_key,
        )
        await runtime.wait_healthy(
            host=host,
            names=names,
            port=port,
            health_path=health_path,
            deployment_id=dep_key,
        )

    except runtime.AppError as exc:
        error = str(exc)
    except Exception as exc:  # noqa: BLE001 - any failure belongs in the log
        log.exception("app deploy failed", app=str(app_id))
        error = f"unexpected failure: {exc}"

    duration = int((time.perf_counter() - started) * 1000)
    transcript = "\n".join(await runtime.read_log(dep_key))[-runtime.MAX_LOG_CHARS :]

    async with session_scope() as db:
        cluster = await db.get(Cluster, cluster_id)
        deployment = await db.get(AppDeployment, deployment_id)
        app = await load_app(db, app_id, cluster)
        if deployment is None:
            return
        deployment.build_log = transcript
        deployment.build_ms = duration
        deployment.finished_at = datetime.now(UTC)
        if error is None:
            deployment.status = "live"
            app.current_deployment_id = deployment.id
            app.status = "running"
            app.last_error = None
            if definition_out:
                app.definition = definition_out
            if port and port != app.port:
                app.port = port
        else:
            deployment.status = "failed"
            deployment.error = error[:2000]
            # A first deploy that fails leaves nothing running; a later one
            # leaves the previous release exactly where it was.
            app.status = "running" if app.current_deployment_id else "failed"
            app.last_error = error[:2000]
        await db.commit()
        slug, name, keep = cluster.slug, app.name, deployment.number if error is None else None

    if error is None:
        await republish_routes(cluster_id)
        # Only now: the new release is up, healthy and routed.
        await runtime.remove_other_deployments(host, slug, name, keep_deployment=keep)
        await runtime.append_log(dep_key, f"$ live in {duration}ms")
        log.info("app deployed", app=name, ms=duration, deployment=keep)
    else:
        await runtime.append_log(dep_key, f"$ failed after {duration}ms: {error}")
        log.warning("app deploy failed", app=name, error=error)

    await runtime.discard_source(dep_key)


async def _release_current(cluster_id: uuid.UUID, app_id: uuid.UUID) -> None:
    """Start the current release's containers again, unchanged."""
    async with session_scope() as db:
        cluster = await db.get(Cluster, cluster_id)
        app = await load_app(db, app_id, cluster)
        deployment = await db.get(AppDeployment, app.current_deployment_id)
        if deployment is None or cluster is None:
            return
        node = await pick_node(db, cluster, app.node_pool)
        env = {**read_env(app), **(await link_env(db, cluster, app))}
        host, slug = node.docker_host, cluster.slug
        snapshot = {
            "name": app.name,
            "number": deployment.number,
            "image": deployment.image_tag,
            "replicas": max(1, app.replicas),
            "port": app.port,
            "memory_mb": app.memory_mb,
            "cpus": app.cpus,
            "volumes": app.volumes or [],
            "health_path": app.health_path,
        }

    try:
        names = await runtime.start_replicas(
            host=host,
            cluster_slug=slug,
            app_name=snapshot["name"],
            deployment=snapshot["number"],
            image=snapshot["image"],
            replicas=snapshot["replicas"],
            port=snapshot["port"],
            env=env,
            memory_mb=snapshot["memory_mb"],
            cpus=snapshot["cpus"],
            volumes=snapshot["volumes"],
            deployment_id=str(app_id),
        )
        await runtime.wait_healthy(
            host=host,
            names=names,
            port=snapshot["port"],
            health_path=snapshot["health_path"],
            deployment_id=str(app_id),
        )
        status_now, failure = "running", None
    except runtime.AppError as exc:
        status_now, failure = "failed", str(exc)

    async with session_scope() as db:
        app = await db.get(App, app_id)
        if app is not None:
            app.status = status_now
            app.last_error = failure
            await db.commit()
    await republish_routes(cluster_id)
    await runtime.remove_other_deployments(
        host, slug, snapshot["name"], keep_deployment=snapshot["number"]
    )


async def _rescale(cluster_id: uuid.UUID, app_id: uuid.UUID) -> None:
    """Apply a new replica count to the release already running."""
    async with session_scope() as db:
        app = await db.get(App, app_id)
        if app is None:
            return
        if app.replicas == 0:
            cluster = await db.get(Cluster, cluster_id)
            node = await pick_node(db, cluster, app.node_pool)
            await runtime.remove_other_deployments(
                node.docker_host, cluster.slug, app.name, keep_deployment=None
            )
            app.status = "stopped"
            await db.commit()
            await republish_routes(cluster_id)
            return
    await _release_current(cluster_id, app_id)
