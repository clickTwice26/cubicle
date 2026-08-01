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
    memory_mb: Mapped[int] = mapped_column(Integer, default=512)
    timeout_s: Mapped[int] = mapped_column(Integer, default=30)
    min_instances: Mapped[int] = mapped_column(Integer, default=0)
    #: Ceiling on concurrent isolates. Requests past it queue for a free one
    #: rather than starting another container, which is what stops one busy
    #: function from taking the whole node.
    max_instances: Mapped[int] = mapped_column(Integer, default=4)
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
