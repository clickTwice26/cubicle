Prepare this repository to be deployed on Cubicle.

Cubicle is a self-hosted platform. It clones a Git branch, builds it with Docker and runs the image as long-lived containers behind its own reverse proxy. Your job is to make the build explicit and correct: a production-ready Dockerfile, plus a `cubicle.json` only where one is needed. Read the repository before changing anything, and work from what is actually in it.

## How Cubicle builds and runs a repository

### Build

- It reads the repository root in this order and uses the first match:
  1. `cubicle.json`, then `captain-definition` (CapRover's file, read as-is) — followed exactly.
  2. `Dockerfile` — built unchanged.
  3. Otherwise it guesses from the layout (Next.js, Vite/React, Node, static HTML, Python with a Procfile). Do not leave it to the guess.
- It runs `docker build --pull` with the repository root as the build context, even when the Dockerfile lives in a subdirectory.
- Environment variables set in the console do not exist during the build. A value the build needs (`NEXT_PUBLIC_*`, `VITE_*`, …) must be an `ARG` in the Dockerfile and a `buildArgs` entry in `cubicle.json` — which is committed, so it must never hold a secret.

### Run

- Port: `port` in `cubicle.json` if set; otherwise the `EXPOSE` in the Dockerfile's final stage; otherwise the port set in the console (3000 by default). The container is given `PORT` set to that value.
- The server must listen on `0.0.0.0` on that port and speak plain HTTP. The proxy and the health check reach the container over a Docker network, so `127.0.0.1`/`localhost` is unreachable. TLS ends at the proxy, which sends `X-Forwarded-Proto`, `X-Forwarded-For` and `X-Forwarded-Host`.
- Health: with a `healthCheckPath`, a GET to it must return a status below 400 within 90 seconds of the container starting, or the deploy fails and the previous release keeps serving. Without one, any HTTP response counts. A container that exits during startup fails the deploy, and its last output lands in the build log.
- Logs are whatever the process writes to stdout and stderr. Keep them unbuffered (`PYTHONUNBUFFERED=1` for Python).
- Every release runs in new containers — possibly several replicas — with a memory limit (512 MB unless changed). The previous release's containers are removed as soon as the new one is healthy, without a graceful shutdown, and their filesystem goes with them. Keep state in a database, Redis or object storage, and never in process memory if it has to survive a deploy or be shared between replicas.
- The app is served at {{app_address}}, and at an instant link, {{instant_address}}, where the proxy strips `/<token>` and passes it on as `X-Forwarded-Prefix`. Prefer relative asset and link URLs where the framework allows it.

### Configuration

- Runtime configuration is environment variables, set on the app's Environment tab in the console (stored encrypted, injected at start). They override `env` in `cubicle.json`.
- An app linked to the cluster's managed services (Settings → Links) also receives `DATABASE_URL` (`postgres://user:password@host:5432/cubicle`, no TLS) and `REDIS_URL` (`redis://:password@host:6379/0`). Convert the scheme if a driver insists on `postgresql://` or `postgresql+asyncpg://`. That Postgres is small and shared with the cluster's functions — it can allow as few as 20 connections — so keep connection pools small.
- Other apps on the same cluster are reachable at `http://<app-name>:<port>`.

## cubicle.json

Optional, at the repository root. Every key is optional, and at most one of `dockerfilePath`, `dockerfileLines` and `imageName` may be set.

```json
{
  "schemaVersion": 1,
  "dockerfilePath": "./Dockerfile",
  "port": 3000,
  "healthCheckPath": "/healthz",
  "env": { "NODE_ENV": "production" },
  "buildArgs": { "NEXT_PUBLIC_API_URL": "https://api.example.com" }
}
```

- `dockerfilePath` — a Dockerfile elsewhere in the repository, for monorepos. Paths inside it stay relative to the root.
- `dockerfileLines` — the Dockerfile itself, inline, as an array of strings.
- `imageName` — skip the build and run a published image.
- `port`, `healthCheckPath` — as described above.
- `env` — non-secret runtime defaults.
- `buildArgs` — passed as `--build-arg`.

A repository that already carries a CapRover `captain-definition` keeps it: Cubicle reads it as-is, and `cubicle.json` wins when both exist.

## Steps

1. Inspect the project: language, framework and version; package manager and lockfile; build and start commands; the port it listens on and how that is set; every environment variable it reads (config and settings modules, `.env.example`, `process.env`, `os.environ`); any existing health endpoint; any Dockerfile, compose file or Procfile; whether it is a monorepo; and how database migrations run.
2. If a Dockerfile exists, check it against the rules above and change only what is needed. Otherwise write one at the root:
   - multi-stage, with pinned base images (`node:22-alpine`, `python:3.12-slim`, …);
   - dependency manifests copied and installed before the source so the layer caches, installing from the lockfile (`npm ci`, `pnpm install --frozen-lockfile`, `yarn install --immutable`, `pip install -r requirements.txt`, `uv sync --frozen`, …);
   - a final stage holding only what runs — build output and production dependencies — as a non-root user where the base image allows it;
   - `EXPOSE` the port, and start the server bound to `0.0.0.0` on `$PORT`, defaulting to that same port;
   - an exec-form `CMD` (a JSON array), or `exec` at the end of an entrypoint script, so the server is PID 1.
3. Framework notes, where they apply:
   - Next.js: `output: "standalone"` in the Next config; the final stage copies `.next/standalone`, `.next/static` and `public`, sets `HOSTNAME=0.0.0.0`, and runs `node server.js`.
   - Single-page apps (Vite, Create React App, Angular): build, then serve the output with nginx and an SPA fallback (`try_files $uri $uri/ /index.html;`), listening on the exposed port (`nginxinc/nginx-unprivileged` listens on 8080 as a non-root user).
   - Python: gunicorn or uvicorn bound to `0.0.0.0:$PORT`; trust the proxy's forwarded headers (`--forwarded-allow-ips="*"`, Django's `SECURE_PROXY_SSL_HEADER`); read `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` from the environment; collect static files during the build.
   - Migrations: run them at container start, before the server, in a way that is safe to repeat — never during the build, which has no database.
4. Add a `.dockerignore` excluding `.git`, dependency directories (`node_modules`, `.venv`), build output, `.env*` (but not `.env.example`), logs, and editor and OS files.
5. If the app has no health endpoint, add a cheap `GET /healthz` that returns 200 without touching the database, and set it as `healthCheckPath`. If the framework makes that awkward, use a path that already returns 200.
6. Add `cubicle.json` only for what needs saying: the health path, a Dockerfile that is not at the root, build arguments, non-secret defaults. Leave `port` out when the Dockerfile's `EXPOSE` already says it.
7. Keep the change about deployment: no refactoring of application code, no compose file for this, and never a committed secret or `.env` file.
8. If Docker is available, verify: `docker build -t cubicle-check .`, then `docker run --rm -p 8080:<port> -e <each required variable> cubicle-check`, and request `http://localhost:8080<health path>`. If it is not, say so and describe what you checked instead.

## Report back

- The files you added or changed, and why.
- The port and health path Cubicle will use.
- A table of environment variables to set on the app's Environment tab: name, required or optional, what it is for, and an example value (a placeholder — never a real secret).
- Whether the app needs Postgres or Redis linked, or storage that must outlive a deploy.
