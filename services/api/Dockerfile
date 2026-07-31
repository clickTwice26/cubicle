FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build deps for asyncpg / argon2-cffi wheels that have no aarch64 wheel yet.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN python -m pip install --upgrade pip \
    && python - <<'PY' > /tmp/requirements.txt
import tomllib
with open("pyproject.toml", "rb") as fh:
    data = tomllib.load(fh)
print("\n".join(data["project"]["dependencies"]))
PY
RUN pip install -r /tmp/requirements.txt

COPY . .
RUN pip install --no-deps -e . \
    && chmod +x /app/docker-entrypoint.sh

# The control plane talks to the Docker socket, which is owned by a host group
# whose gid varies. Running as root inside this container is the pragmatic,
# documented trade-off; nothing else in the stack has socket access.
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=6 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "cubicle.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
