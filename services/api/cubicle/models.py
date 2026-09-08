"""Control-plane schema.

One Postgres database holds the entire cluster state: instance configuration,
users, namespaces, functions and their versions, encrypted configuration,
invocation records and the managed data services. Nothing is kept only in
memory, so the control plane can be restarted at any moment without losing
anything except warm isolates.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Instance(Base, TimestampMixin):
    """Singleton row (id == 1) for state that spans every cluster.

    Anything a single cluster owns — its name, ingress domain, nodes,
    namespaces, configuration — lives on :class:`Cluster` instead.
    """

    __tablename__ = "instance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    setup_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[str] = mapped_column(String(20), default="1.0.0")

    #: Cubicle AI. The key is envelope-encrypted like every other secret here,
    #: so the database on its own never holds usable credentials.
    ai_key_ciphertext: Mapped[str | None] = mapped_column(Text)
    ai_base_url: Mapped[str] = mapped_column(String(200), default="")
    ai_model: Mapped[str] = mapped_column(String(80), default="")

    #: Cloudflare Turnstile on the sign-in form. Instance-wide rather than
    #: per-cluster because signing in happens before a cluster is chosen.
    #:
    #: The site key is public by design: it is rendered into the login page and
    #: any visitor can read it. The secret key is envelope-encrypted like the AI
    #: key, and only ever leaves the database to be posted to Cloudflare.
    #: DNS credentials for obtaining certificates, used only when something
    #: else terminates TLS in front of this instance. A wildcard cannot be
    #: issued over HTTP, so the only way to ask for one is to prove control of
    #: the zone — which means a token that can write a record in it.
    acme_provider: Mapped[str] = mapped_column(String(20), default="cloudflare")
    acme_token_ciphertext: Mapped[str | None] = mapped_column(Text)
    acme_email: Mapped[str] = mapped_column(String(255), default="")

    turnstile_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    turnstile_site_key: Mapped[str] = mapped_column(String(120), default="")
    turnstile_secret_ciphertext: Mapped[str | None] = mapped_column(Text)


class Cluster(Base, TimestampMixin):
    """One scheduling domain: its own nodes, namespaces, config and data services.

    Nothing crosses a cluster boundary. Two clusters may both own a namespace
    called ``payments`` and a variable called ``DATABASE_URL`` without
    colliding, which is what makes prod/staging separation on one instance
    meaningful rather than cosmetic.

    Requests reach a cluster in one of three ways, checked in this order:

    1. the ``Host`` header matches ``ingress_domain``,
    2. the path starts with ``/<slug>/``,
    3. otherwise the default cluster answers, so ``/<ns>/<fn>`` keeps working.
    """

    __tablename__ = "clusters"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(80))
    slug: Mapped[str] = mapped_column(String(63), unique=True, index=True)
    ingress_domain: Mapped[str] = mapped_column(String(255), default="")
    data_dir: Mapped[str] = mapped_column(String(255), default="/var/lib/cubicle")
    kms_backend: Mapped[str] = mapped_column(String(20), default="file")
    default_node_pool: Mapped[str] = mapped_column(String(40), default="general")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    description: Mapped[str] = mapped_column(String(255), default="")

    #: Hard ceilings for everything this cluster may allocate, set by the super
    #: admin. Zero means no ceiling. They bound the per-function settings
    #: rather than replacing them: a function may ask for 1 GB and eight
    #: instances, and still be refused the ninth gigabyte because the cluster
    #: has none left.
    max_memory_mb: Mapped[int] = mapped_column(Integer, default=0)
    max_cpu_cores: Mapped[float] = mapped_column(Float, default=0.0)
    max_storage_gb: Mapped[int] = mapped_column(Integer, default=0)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20), default="owner")
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def initials(self) -> str:
        parts = [p for p in self.name.replace("-", " ").split() if p]
        if not parts:
            return self.email[:2].upper()
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()


class ApiKey(Base, TimestampMixin):
    """Bearer credentials for the CLI and CI. Only the hash is stored."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(24), index=True)
    token_hash: Mapped[str] = mapped_column(String(255))
    scope: Mapped[str] = mapped_column(String(20), default="admin")
    # Null means the key works against every cluster on this instance.
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("clusters.id", ondelete="CASCADE"), index=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class UserCluster(Base):
    """Which clusters a user may touch.

    Absent a row, a user cannot see or address a cluster at all — not its
    functions, not its logs, not its data services. The owner is the exception
    and is checked before this table is consulted: the account that completed
    setup is the super admin and always reaches everything, which is what keeps
    an instance recoverable when a grant is misconfigured.
    """

    __tablename__ = "user_clusters"
    __table_args__ = (UniqueConstraint("user_id", "cluster_id", name="uq_user_cluster"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clusters.id", ondelete="CASCADE"), index=True
    )


class Node(Base, TimestampMixin):
    """A Docker engine that can run isolates.

    The local engine is registered automatically on first boot. Additional
    engines are added by URL (``tcp://host:2376`` with client certificates),
    which is how a Cubicle cluster grows past one machine.
    """

    __tablename__ = "nodes"
    __table_args__ = (UniqueConstraint("cluster_id", "name", name="uq_node_name_per_cluster"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clusters.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80), index=True)
    docker_host: Mapped[str] = mapped_column(String(255), default="unix:///var/run/docker.sock")
    pool: Mapped[str] = mapped_column(String(40), default="general")
    status: Mapped[str] = mapped_column(String(20), default="ready")
    arch: Mapped[str] = mapped_column(String(20), default="amd64")
    cpus: Mapped[int] = mapped_column(Integer, default=0)
    memory_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    engine_version: Mapped[str] = mapped_column(String(40), default="")
    is_local: Mapped[bool] = mapped_column(Boolean, default=False)
    schedulable: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class Group(Base, TimestampMixin):
    """A namespace. Every function below it is served under ``/<ns>/``."""

    __tablename__ = "groups"
    __table_args__ = (UniqueConstraint("cluster_id", "ns", name="uq_namespace_per_cluster"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clusters.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    ns: Mapped[str] = mapped_column(String(63), index=True)

    functions: Mapped[list[Function]] = relationship(
        back_populates="group", cascade="all, delete-orphan", lazy="selectin"
    )


class Function(Base, TimestampMixin):
    __tablename__ = "functions"
    __table_args__ = (UniqueConstraint("group_id", "name", name="uq_function_name_per_group"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(63), index=True)
    method: Mapped[str] = mapped_column(String(10), default="POST")
    runtime: Mapped[str] = mapped_column(String(20), default="python312")
    ctx_access: Mapped[str] = mapped_column(String(6), default="rw")
    #: ``dependent`` may be sent a request body; ``independent`` takes no input
    #: at all. Nothing in the runtime reads this — it is a label an operator
    #: applies so a namespace says which of its functions are triggered with
    #: data and which just run. Enforcing it would make it a contract, and it
    #: is deliberately not one.
    function_type: Mapped[str] = mapped_column(String(12), default="dependent")
    #: Resource defaults are the smallest each control offers. A function that
    #: needs more says so; one created and forgotten costs the least it can.
    memory_mb: Mapped[int] = mapped_column(Integer, default=128)
    timeout_s: Mapped[int] = mapped_column(Integer, default=30)
    min_instances: Mapped[int] = mapped_column(Integer, default=0)
    #: Ceiling on concurrent isolates. Requests past it queue for a free one
    #: rather than starting another container, which is what stops one busy
    #: function from taking the whole node.
    max_instances: Mapped[int] = mapped_column(Integer, default=1)
    #: Seconds an instance may sit idle before it is reclaimed. Zero defers to
    #: the instance-wide TTL, which is what every function did before this
    #: existed — a function nobody has an opinion about keeps the old behaviour.
    idle_timeout_s: Mapped[int] = mapped_column(Integer, default=0)
    node_pool: Mapped[str] = mapped_column(String(40), default="general")
    auth_required: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("function_versions.id", ondelete="SET NULL", use_alter=True)
    )

    group: Mapped[Group] = relationship(back_populates="functions", lazy="joined")
    versions: Mapped[list[FunctionVersion]] = relationship(
        back_populates="function",
        cascade="all, delete-orphan",
        foreign_keys="FunctionVersion.function_id",
        order_by="FunctionVersion.number.desc()",
    )

    @property
    def path(self) -> str:
        return f"/{self.group.ns}/{self.name}"


class FunctionVersion(Base):
    """An immutable snapshot of a function's source plus its build result."""

    __tablename__ = "function_versions"
    __table_args__ = (UniqueConstraint("function_id", "number", name="uq_version_number"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    function_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("functions.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer, default=1)
    files: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    build_log: Mapped[str] = mapped_column(Text, default="")
    build_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    function: Mapped[Function] = relationship(back_populates="versions", foreign_keys=[function_id])


class EnvVar(Base):
    """Cluster-wide configuration, readable from any function at invoke time."""

    __tablename__ = "env_vars"
    __table_args__ = (UniqueConstraint("cluster_id", "key", name="uq_env_key_per_cluster"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clusters.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(120), index=True)
    value_ciphertext: Mapped[str] = mapped_column(Text)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FunctionSecret(Base):
    """Per-function secret material, injected into the isolate at cold start."""

    __tablename__ = "function_secrets"
    __table_args__ = (UniqueConstraint("function_id", "key", name="uq_secret_key_per_function"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    function_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("functions.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(120))
    value_ciphertext: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Invocation(Base):
    """One row per invocation — the source of truth for metrics and metering."""

    __tablename__ = "invocations"
    __table_args__ = (
        Index("ix_invocations_ts", "ts"),
        Index("ix_invocations_fn_ts", "function_id", "ts"),
        Index("ix_invocations_cluster_ts", "cluster_id", "ts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clusters.id", ondelete="CASCADE"), index=True
    )

    function_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("functions.id", ondelete="CASCADE")
    )
    function_name: Mapped[str] = mapped_column(String(63), default="")
    namespace: Mapped[str] = mapped_column(String(63), default="", index=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    status_code: Mapped[int] = mapped_column(Integer, default=200)
    cold: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str] = mapped_column(String(40), default="")
    memory_mb: Mapped[int] = mapped_column(Integer, default=512)
    gb_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    egress_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    node_name: Mapped[str] = mapped_column(String(80), default="")


class LogEntry(Base):
    __tablename__ = "log_entries"
    __table_args__ = (
        Index("ix_logs_ts", "ts"),
        Index("ix_logs_fn_ts", "function_id", "ts"),
        Index("ix_logs_cluster_ts", "cluster_id", "ts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clusters.id", ondelete="CASCADE"), index=True
    )

    function_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("functions.id", ondelete="CASCADE")
    )
    function_name: Mapped[str] = mapped_column(String(63), default="", index=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    level: Mapped[str] = mapped_column(String(8), default="INFO", index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[float | None] = mapped_column(Float)
    request_id: Mapped[str] = mapped_column(String(40), default="")


class ManagedService(Base, TimestampMixin):
    """A PostgreSQL or Redis instance the console provisions on the cluster."""

    __tablename__ = "managed_services"
    __table_args__ = (UniqueConstraint("cluster_id", "kind", name="uq_service_per_cluster"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clusters.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20), index=True)
    version: Mapped[str] = mapped_column(String(20), default="16.3")
    status: Mapped[str] = mapped_column(String(20), default="stopped")
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    container_id: Mapped[str | None] = mapped_column(String(80))
    container_name: Mapped[str] = mapped_column(String(80), default="")
    volume_name: Mapped[str] = mapped_column(String(80), default="")
    node_name: Mapped[str] = mapped_column(String(80), default="")
    password_ciphertext: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)


class Trigger(Base, TimestampMixin):
    """Something other than an HTTP request that causes a function to run.

    Only schedules for now. The interesting column is ``next_run_at``: the
    scheduler claims work by updating it, so a due trigger is taken exactly
    once even if two control planes are looking at the same row.
    """

    __tablename__ = "triggers"
    __table_args__ = (Index("ix_triggers_due", "enabled", "next_run_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    function_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("functions.id", ondelete="CASCADE"), index=True
    )
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clusters.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20), default="schedule")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    #: Standard five-field cron. The console writes it from a friendlier form,
    #: but the stored value is the thing the scheduler reads.
    cron: Mapped[str] = mapped_column(String(120), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")

    #: When it is next owed a run. Null means it has no future — disabled, or
    #: an expression that stopped parsing after a timezone change.
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str] = mapped_column(String(20), default="")
    last_error: Mapped[str | None] = mapped_column(Text)
    run_count: Mapped[int] = mapped_column(Integer, default=0)


# ── applications ─────────────────────────────────────────────────────────────


class GitCredential(Base, TimestampMixin):
    """A token Cubicle uses to clone private repositories.

    A token, not an OAuth login: the operator creates a personal access token
    with the scope they are willing to give, pastes it once, and it is stored
    envelope-encrypted like every other secret here. Nothing about this install
    needs to be registered anywhere, and revoking access is something the
    operator does at the provider without asking us.
    """

    __tablename__ = "git_credentials"
    __table_args__ = (UniqueConstraint("cluster_id", "name", name="uq_git_credential_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clusters.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(20), default="github")
    #: GitHub ignores the username on token auth; other hosts do not.
    username: Mapped[str] = mapped_column(String(120), default="x-access-token")
    token_ciphertext: Mapped[str] = mapped_column(Text)
    #: Set after a successful clone, so the console can show it as verified.
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class App(Base, TimestampMixin):
    """A long-running container Cubicle builds, runs and routes traffic to.

    Functions are the platform's short-lived half: one request, one isolate,
    scale to zero. An app is the other half — a Next.js site, an API server,
    anything with a Dockerfile — that stays up, holds a hostname and is
    reachable by name from every other app on the cluster.
    """

    __tablename__ = "apps"
    __table_args__ = (UniqueConstraint("cluster_id", "name", name="uq_app_name_per_cluster"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clusters.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(63), index=True)

    #: "git" builds from a repository, "image" runs a published image as-is.
    source_kind: Mapped[str] = mapped_column(String(10), default="git")
    repo_url: Mapped[str] = mapped_column(String(500), default="")
    branch: Mapped[str] = mapped_column(String(120), default="main")
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("git_credentials.id", ondelete="SET NULL")
    )
    image_ref: Mapped[str] = mapped_column(String(400), default="")

    #: The cubicle.json the last successful build resolved, whether it came
    #: from the repository or was inferred from what was in it.
    definition: Mapped[dict] = mapped_column(JSONB, default=dict)

    #: The whole env map, encrypted as one blob. Values are frequently
    #: credentials and there is no case for storing them in the clear.
    env_ciphertext: Mapped[str] = mapped_column(Text, default="")

    port: Mapped[int] = mapped_column(Integer, default=3000)
    replicas: Mapped[int] = mapped_column(Integer, default=1)
    memory_mb: Mapped[int] = mapped_column(Integer, default=512)
    cpus: Mapped[float] = mapped_column(Float, default=1.0)
    health_path: Mapped[str] = mapped_column(String(200), default="")
    node_pool: Mapped[str] = mapped_column(String(40), default="general")

    #: Managed services and other apps whose connection details are injected
    #: into this app's environment at start.
    links: Mapped[list] = mapped_column(JSONB, default=list)
    #: [{"path": "/data", "name": "..."}] — named volumes that survive deploys.
    volumes: Mapped[list] = mapped_column(JSONB, default=list)

    status: Mapped[str] = mapped_column(String(20), default="created")
    last_error: Mapped[str | None] = mapped_column(Text)

    #: The instant link. Assigned once, never changes, and needs no DNS at all:
    #: the app is reachable at `<instance>/<path_token>` from the moment it is
    #: live, which is what makes a deploy checkable before a record exists.
    path_token: Mapped[str] = mapped_column(String(32), default="", index=True)

    auto_deploy: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Shared secret in the webhook URL, and the HMAC key the provider signs
    #: its payload with.
    webhook_secret: Mapped[str] = mapped_column(String(64), default="")

    current_deployment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_deployments.id", ondelete="SET NULL", use_alter=True)
    )

    credential: Mapped[GitCredential | None] = relationship(lazy="joined")
    deployments: Mapped[list[AppDeployment]] = relationship(
        back_populates="app",
        cascade="all, delete-orphan",
        foreign_keys="AppDeployment.app_id",
        order_by="AppDeployment.number.desc()",
    )
    domains: Mapped[list[AppDomain]] = relationship(
        back_populates="app", cascade="all, delete-orphan", order_by="AppDomain.hostname"
    )


class AppDeployment(Base):
    """One build and release of an app. Immutable once it finishes."""

    __tablename__ = "app_deployments"
    __table_args__ = (UniqueConstraint("app_id", "number", name="uq_app_deployment_number"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    app_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("apps.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer, default=1)

    status: Mapped[str] = mapped_column(String(20), default="pending")
    #: manual · webhook · cli — how this deploy was asked for.
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
    triggered_by: Mapped[str] = mapped_column(String(200), default="")

    commit_sha: Mapped[str] = mapped_column(String(80), default="")
    commit_message: Mapped[str] = mapped_column(String(500), default="")
    image_tag: Mapped[str] = mapped_column(String(300), default="")

    #: The whole build transcript. Streamed live while it runs and kept
    #: afterwards, because the log of the deploy that broke is the one people
    #: actually go looking for.
    build_log: Mapped[str] = mapped_column(Text, default="")
    build_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    app: Mapped[App] = relationship(back_populates="deployments", foreign_keys=[app_id])


class AppDomain(Base, TimestampMixin):
    """A hostname the edge routes to an app.

    Caddy obtains a certificate for it on the first request, so adding a
    hostname here is the whole of "put this app on the internet" — provided
    the DNS points at this machine.
    """

    __tablename__ = "app_domains"
    __table_args__ = (UniqueConstraint("hostname", name="uq_app_domain_hostname"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    app_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("apps.id", ondelete="CASCADE"), index=True)
    hostname: Mapped[str] = mapped_column(String(253))
    #: The one shown as the app's address in the console.
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    app: Mapped[App] = relationship(back_populates="domains")


class Certificate(Base, TimestampMixin):
    """A TLS certificate Cubicle obtains and renews on the operator's behalf.

    Only needed when something else terminates TLS in front of this instance.
    When Caddy owns the ports it does this itself, on first request, and there
    is nothing here to manage.

    The private key and chain live on disk where the front-end server can read
    them; this row is the record of what was asked for and how it went.
    """

    __tablename__ = "certificates"
    __table_args__ = (UniqueConstraint("name", name="uq_certificate_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    #: The certbot lineage, which is also the directory it writes into.
    name: Mapped[str] = mapped_column(String(253), index=True)
    #: Every name on the certificate. A wildcard is one entry like
    #: ``*.apps.example.com``.
    hostnames: Mapped[list] = mapped_column(JSONB, default=list)
    provider: Mapped[str] = mapped_column(String(20), default="cloudflare")

    status: Mapped[str] = mapped_column(String(20), default="pending")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    #: The transcript of the last attempt, kept because a failed issuance is
    #: almost always explained by one line certbot printed.
    last_log: Mapped[str] = mapped_column(Text, default="")
    renewals: Mapped[int] = mapped_column(Integer, default=0)
