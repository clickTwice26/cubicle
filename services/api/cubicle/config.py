"""Process configuration.

Everything here comes from the environment, which is written once by
``install.sh``. Nothing in this file is user-editable at runtime — instance
settings the operator can change live in the database (see ``models.Instance``).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RUNTIMES: dict[str, str] = {
    "python312": "Python 3.12",
    "python311": "Python 3.11",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CUBICLE_", extra="ignore")

    version: str = "1.0.0"
    log_level: str = "info"
    testing: bool = False

    database_url: str = "postgresql+asyncpg://cubicle:cubicle@postgres:5432/cubicle"
    redis_url: str = "redis://redis:6379/0"

    secret_key: str = Field(min_length=16)
    master_key: str = Field(min_length=16)

    domain: str = "localhost"
    public_url: str = "http://localhost:7000"
    trust_proxy: bool = True

    data_dir: Path = Path("/var/lib/cubicle")

    # ── isolate runtime ──────────────────────────────────────────────────
    function_network: str = "cubicle_fn"
    runtime_image_py312: str = "cubicle/runtime-py312:1.0.0"
    runtime_image_py311: str = "cubicle/runtime-py311:1.0.0"
    isolate_idle_ttl: int = 900
    #: How long a burst keeps the pool wide. Once concurrency has not been seen
    #: for this long the reconcile loop starts giving isolates back, one per
    #: pass, without waiting out the much longer idle TTL — that one governs
    #: going fully cold, not shedding the surplus a spike created.
    isolate_scaledown_window: int = 60
    isolate_start_timeout: float = 30.0
    isolate_max_per_function: int = 8
    build_timeout: int = 600
    reconcile_interval: int = 30

    # ── sessions ─────────────────────────────────────────────────────────
    session_ttl: int = 60 * 60 * 12
    session_cookie: str = "cubicle_session"
    login_max_attempts: int = 10
    login_window: int = 300

    # Session context store shared between functions in a namespace.
    context_ttl: int = 1800

    @field_validator("data_dir", mode="before")
    @classmethod
    def _expand(cls, v: str | Path) -> Path:
        return Path(v).expanduser()

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")

    @property
    def functions_dir(self) -> Path:
        return self.data_dir / "functions"

    def runtime_image(self, runtime: str) -> str:
        return {
            "python312": self.runtime_image_py312,
            "python311": self.runtime_image_py311,
        }.get(runtime, self.runtime_image_py312)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
