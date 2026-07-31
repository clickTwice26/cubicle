"""Request and response models.

These are the contract the console and the CLI both code against; the console
is just another client of this API, exactly as the docs promise.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Runtime = Literal["python312", "python311"]
Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
CtxAccess = Literal["rw", "r", "w", "none"]
Role = Literal["owner", "admin", "developer", "readonly"]

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$|^[a-z0-9]$")

# Paths the console owns. A namespace may never take one of these, or it would
# shadow the UI at the edge.
RESERVED_NAMESPACES = {
    "api",
    "assets",
    "console",
    "docs",
    "fonts",
    "healthz",
    "metrics",
    "setup",
    "static",
    "well-known",
}


def validate_slug(value: str, *, what: str) -> str:
    value = value.strip().lower()
    if not SLUG_RE.match(value):
        raise ValueError(
            f"{what} must be lower-case letters, digits and hyphens, "
            "and start and end alphanumeric."
        )
    return value


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── clusters ─────────────────────────────────────────────────────────────────


class ClusterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    slug: str | None = None
    ingress_domain: str = Field(default="", max_length=255)
    data_dir: str = Field(default="/var/lib/cubicle", max_length=255)
    kms_backend: Literal["file", "vault", "kms", "pkcs11"] = "file"
    default_node_pool: str = Field(default="general", max_length=40)
    description: str = Field(default="", max_length=255)
    make_default: bool = False

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = validate_slug(v, what="Cluster slug")
        if v in RESERVED_NAMESPACES:
            raise ValueError(f"'{v}' is reserved by the console.")
        return v

    @field_validator("ingress_domain")
    @classmethod
    def _domain(cls, v: str) -> str:
        return v.strip().lower().removeprefix("*.")


class ClusterUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    ingress_domain: str | None = Field(default=None, max_length=255)
    data_dir: str | None = Field(default=None, max_length=255)
    default_node_pool: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=255)
    status: Literal["active", "paused"] | None = None

    @field_validator("ingress_domain")
    @classmethod
    def _domain(cls, v: str | None) -> str | None:
        return v.strip().lower().removeprefix("*.") if v is not None else None


class ClusterOut(ORMModel):
    id: UUID
    name: str
    slug: str
    ingress_domain: str
    data_dir: str
    kms_backend: str
    default_node_pool: str
    is_default: bool
    status: str
    description: str
    base_url: str = ""
    node_count: int = 0
    function_count: int = 0
    namespace_count: int = 0
    created_at: datetime


# ── setup & auth ─────────────────────────────────────────────────────────────


class SetupStatus(BaseModel):
    setup_complete: bool
    version: str
    cluster_name: str | None = None
    public_url: str
    domain: str
    tls: bool


class SetupNodeSelection(BaseModel):
    name: str
    schedulable: bool = True


class SetupRequest(BaseModel):
    admin_name: str = Field(min_length=1, max_length=120)
    admin_email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    cluster_name: str = Field(default="prod-cluster", max_length=80)
    ingress_domain: str = Field(default="localhost", max_length=255)
    data_dir: str = Field(default="/var/lib/cubicle", max_length=255)
    kms_backend: Literal["file", "vault", "kms", "pkcs11"] = "file"
    nodes: list[str] = Field(default_factory=list)

    @field_validator("cluster_name")
    @classmethod
    def _cluster(cls, v: str) -> str:
        return validate_slug(v, what="Cluster name")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=256)


class UserOut(ORMModel):
    id: UUID
    email: str
    name: str
    role: Role
    initials: str
    is_active: bool
    last_login_at: datetime | None = None


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    role: Role = "developer"


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    role: Role | None = None
    is_active: bool | None = None


# ── namespaces & functions ───────────────────────────────────────────────────


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    ns: str | None = None

    @field_validator("ns")
    @classmethod
    def _ns(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = validate_slug(v, what="Namespace")
        if v in RESERVED_NAMESPACES:
            raise ValueError(f"'{v}' is reserved by the console.")
        return v


class GroupOut(ORMModel):
    id: UUID
    name: str
    ns: str
    base_url: str = ""
    function_count: int = 0
    created_at: datetime


class FunctionCreate(BaseModel):
    name: str
    method: Method = "POST"
    runtime: Runtime = "python312"
    ctx_access: CtxAccess = "rw"
    memory_mb: int = Field(default=512, ge=64, le=8192)
    timeout_s: int = Field(default=30, ge=1, le=900)
    auth_required: bool = True
    node_pool: str = "general"

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return validate_slug(v, what="Function name")


class FunctionUpdate(BaseModel):
    name: str | None = None
    method: Method | None = None
    runtime: Runtime | None = None
    ctx_access: CtxAccess | None = None
    memory_mb: int | None = Field(default=None, ge=64, le=8192)
    timeout_s: int | None = Field(default=None, ge=1, le=900)
    min_instances: int | None = Field(default=None, ge=0, le=20)
    auth_required: bool | None = None
    node_pool: str | None = None
    status: Literal["active", "paused"] | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return validate_slug(v, what="Function name") if v else None


class FunctionOut(ORMModel):
    id: UUID
    group_id: UUID
    namespace: str = ""
    name: str
    method: Method
    runtime: Runtime
    runtime_label: str = ""
    ctx_access: CtxAccess
    memory_mb: int
    timeout_s: int
    min_instances: int
    node_pool: str
    auth_required: bool
    status: str
    path: str = ""
    url: str = ""
    version: int = 0
    version_status: str = "pending"
    updated_at: datetime
    created_at: datetime


class FunctionStats(BaseModel):
    invocations: int = 0
    invocations_label: str = "0"
    p50: str = "—"
    p90: str = "—"
    p95: str = "—"
    p99: str = "—"
    error_rate: str = "—"
    cold_rate: str = "—"
    last_deploy: str | None = None


class FunctionDetail(FunctionOut):
    files: dict[str, str] = Field(default_factory=dict)
    build_log: str = ""
    build_ms: int = 0
    stats: FunctionStats = Field(default_factory=FunctionStats)


class DeployRequest(BaseModel):
    files: dict[str, str]
    message: str | None = None

    @field_validator("files")
    @classmethod
    def _files(cls, v: dict[str, str]) -> dict[str, str]:
        allowed = {"handler.py", "requirements.txt", "cubicle.toml", "README.md"}
        unknown = set(v) - allowed
        if unknown:
            raise ValueError(f"Unsupported files: {', '.join(sorted(unknown))}")
        if "handler.py" not in v:
            raise ValueError("handler.py is required.")
        total = sum(len(c.encode()) for c in v.values())
        if total > 2_000_000:
            raise ValueError("Function bundle is larger than 2 MB.")
        return v


class VersionOut(ORMModel):
    id: UUID
    number: int
    status: str
    build_ms: int
    build_log: str
    created_at: datetime
    deployed_at: datetime | None = None


# ── configuration ────────────────────────────────────────────────────────────


class EnvVarIn(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    value: str = Field(default="", max_length=100_000)
    is_secret: bool = False

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        v = re.sub(r"[^A-Z0-9_]", "_", v.strip().upper())
        if not v or v[0].isdigit():
            raise ValueError("Keys must start with a letter or underscore.")
        return v


class EnvVarOut(BaseModel):
    key: str
    value: str
    is_secret: bool
    masked: bool
    updated_at: datetime


class SecretIn(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    value: str = Field(max_length=100_000)

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        return re.sub(r"[^A-Z0-9_]", "_", v.strip().upper())


class SecretOut(BaseModel):
    key: str
    value: str
    updated_at: datetime


# ── invocation & playground ──────────────────────────────────────────────────


class TestInvokeRequest(BaseModel):
    body: Any = None
    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, str] = Field(default_factory=dict)
    session_id: str | None = None


class TestInvokeResult(BaseModel):
    status_code: int
    duration_ms: float
    cold: bool
    body: Any = None
    logs: list[str] = Field(default_factory=list)
    error: str | None = None
    context_read: list[str] = Field(default_factory=list)
    context_wrote: list[str] = Field(default_factory=list)


class ContextState(BaseModel):
    session_id: str
    data: dict[str, Any] = Field(default_factory=dict)
    log: list[dict[str, Any]] = Field(default_factory=list)
    size_bytes: int = 0
    ttl_seconds: int = 1800


# ── observability ────────────────────────────────────────────────────────────


class LogOut(BaseModel):
    id: UUID
    ts: datetime
    time: str
    level: str
    function_name: str
    message: str
    duration: str | None = None
    request_id: str = ""


class LogPage(BaseModel):
    items: list[LogOut]
    total: int
    limit: int
    offset: int


class Kpi(BaseModel):
    label: str
    value: str
    delta: str | None = None
    direction: Literal["up", "down", "flat"] = "flat"


class ChartBar(BaseModel):
    ok: float
    err: float
    bucket: datetime


class DashboardOut(BaseModel):
    kpis: list[Kpi]
    chart: list[ChartBar]
    functions: list[dict[str, Any]]
    function_count: int
    node_count: int


# ── cluster & metering ───────────────────────────────────────────────────────


class NodeOut(ORMModel):
    id: UUID
    name: str
    pool: str
    status: str
    arch: str
    cpus: int
    memory_bytes: int
    spec: str = ""
    is_local: bool
    schedulable: bool
    engine_version: str = ""
    cpu_allocated_pct: float = 0.0
    memory_allocated_pct: float = 0.0
    memory_label: str = ""
    isolates: int = 0
    last_error: str | None = None


class NodeCreate(BaseModel):
    name: str
    docker_host: str
    pool: str = "general"

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return validate_slug(v, what="Node name")


class MeteringOut(BaseModel):
    window_start: datetime
    window_end: datetime
    window_progress: float
    invocations: int
    gb_seconds: float
    egress_bytes: int
    storage_bytes: int
    namespaces: list[dict[str, Any]]
    cost_comparison: list[dict[str, Any]]
    avoided: float
    avoided_annualised: float


# ── managed services ─────────────────────────────────────────────────────────


class ServiceCreate(BaseModel):
    version: str
    memory: str = "1 GB"
    storage: str = "20 GB"
    eviction: str | None = None
    node_pool: str = "general"


class ServiceOut(BaseModel):
    kind: str
    created: bool
    status: str
    version: str
    config: dict[str, Any]
    connection_url: str | None = None
    node: str = ""
    stats: dict[str, Any] = Field(default_factory=dict)
    last_error: str | None = None


# ── settings ─────────────────────────────────────────────────────────────────


class InstanceOut(BaseModel):
    """The active cluster's settings, plus the instance-wide facts around it."""

    cluster_id: UUID
    cluster_name: str
    cluster_slug: str
    ingress_domain: str
    data_dir: str
    kms_backend: str
    default_node_pool: str
    is_default: bool
    base_url: str
    cluster_count: int
    version: str
    public_url: str
    tls: bool


class InstanceUpdate(BaseModel):
    cluster_name: str | None = Field(default=None, max_length=80)
    ingress_domain: str | None = Field(default=None, max_length=255)
    data_dir: str | None = Field(default=None, max_length=255)
    default_node_pool: str | None = Field(default=None, max_length=40)

    @field_validator("ingress_domain")
    @classmethod
    def _domain(cls, v: str | None) -> str | None:
        return v.strip().lower().removeprefix("*.") if v is not None else None


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scope: Literal["admin", "deploy", "readonly"] = "admin"


class ApiKeyOut(ORMModel):
    id: UUID
    name: str
    prefix: str
    scope: str
    created_at: datetime
    last_used_at: datetime | None = None
    token: str | None = None
