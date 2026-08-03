"""Scaffolding for new functions.

The generated handler is deliberately a working example of every runtime
facility at once: the request, the cluster-wide env store, the session context
shared across a namespace, and the managed data services.
"""

from __future__ import annotations

from . import runtimes

RUNTIME_LABELS = runtimes.labels()
RUNTIME_TOML = {
    key: (
        f"python{spec.label.split()[-1]}"
        if spec.language == "Python"
        else f"node{spec.label.split()[-1]}"
    )
    for key, spec in runtimes.RUNTIMES.items()
}
CTX_LABELS = {"rw": "read+write", "r": "read only", "w": "write only", "none": "no access"}


def default_handler(name: str, namespace: str) -> str:
    key = name.replace("-", "_")
    return f'''from cubicle_context import Request, Context, env
from cubicle_db import postgres, redis


def handler(req: Request, ctx: Context):
    """{namespace}/{name}"""
    body = req.json()

    # Global env — one store per cluster, readable from any function.
    # Values resolve at invocation time, so no redeploy is needed to change one.
    api_base = env.get("PAYMENTS_API_BASE", "https://payments.internal/v2")

    # ctx — session-scoped, keyed by X-Cubicle-Session, shared with every
    # function in this namespace for as long as the session lives.
    actor = ctx.get("actor") or {{"tier": "anonymous"}}

    if postgres.available:
        with postgres.session() as db:
            db.execute(
                "create table if not exists {key} ("
                "  id serial primary key,"
                "  actor text,"
                "  amount numeric,"
                "  at timestamptz default now())"
            )
            db.execute(
                "insert into {key} (actor, amount) values (:actor, :amount)",
                actor=actor.get("id", "anonymous"),
                amount=body.get("amount", 0),
            )

    if redis.available:
        redis.setex(f"{key}:{{req.session_id}}", 300, "ok")

    ctx.set("{key}", {{
        "amount": body.get("amount"),
        "api_base": api_base,
        "status": "ok",
    }})

    return {{"ok": True, "actor": actor}}
'''


def default_requirements() -> str:
    return (
        "# cubicle_context and cubicle_db ship inside the runtime image — do not\n"
        "# pin them here. Anything you add is installed at deploy time and cached\n"
        "# in the version's volume, so it costs nothing at invocation.\n"
        "#\n"
        "# httpx==0.28.1\n"
    )


def default_toml(
    *,
    name: str,
    namespace: str,
    runtime: str,
    method: str,
    memory_mb: int,
    timeout_s: int,
    ctx_access: str,
    max_instances: int = 4,
) -> str:
    return f"""[function]
name       = "{name}"
namespace  = "{namespace}"
runtime    = "{RUNTIME_TOML.get(runtime, "python3.12")}"
entrypoint = "handler.handler"
method     = "{method}"

[resources]
memory_mb     = {memory_mb}
timeout_s     = {timeout_s}
min_instances = 0
max_instances = {max_instances}
node_pool     = "general"

[context]
access = "{CTX_LABELS.get(ctx_access, "read+write")}"
header = "X-Cubicle-Session"
ttl    = "30m"
"""


def default_readme(name: str, namespace: str, base_url: str) -> str:
    return f"""# {name}

Served at `{base_url}`.

```bash
curl -X POST {base_url} \\
  -H 'Content-Type: application/json' \\
  -H 'X-Cubicle-Session: sess_local' \\
  -d '{{"amount": 4200}}'
```

Edit `handler.py` in the console or deploy from your machine with
`cubicle deploy` from this directory. Both write the same version.
"""


def default_handler_js(name: str, namespace: str) -> str:
    return f"""/**
 * {namespace}/{name}
 *
 * Export `handler` by name or as the default. It may be async; the agent awaits
 * whatever it returns.
 */
export async function handler(req, ctx) {{
  const body = req.json()

  // ctx.env — one store per cluster, readable from any function. Values resolve
  // at invocation time, so changing one needs no redeploy.
  const apiBase = ctx.env.PAYMENTS_API_BASE ?? 'https://payments.internal/v2'

  // ctx — session-scoped, keyed by X-Cubicle-Session and shared with every
  // function in this namespace for as long as the session lives.
  const seen = ctx.get('seen', 0)
  ctx.set('seen', seen + 1)
  ctx.set('last_seen_by', '{name}')

  // Anything written to the console is captured per invocation and shows up in
  // the logs for this request, not on the container's stdout.
  console.log('handling', req.method, req.path)

  return {{
    statusCode: 200,
    body: {{
      ok: true,
      function: '{namespace}/{name}',
      received: body,
      seen: seen + 1,
      api_base: apiBase,
      request_id: req.requestId,
    }},
  }}
}}
"""


def default_package_json(name: str) -> str:
    return (
        "{\n"
        f'  "name": "{name}",\n'
        '  "private": true,\n'
        '  "type": "module",\n'
        '  "version": "1.0.0",\n'
        "  // Anything added here is installed with npm at deploy.\n"
        '  "dependencies": {}\n'
        "}\n"
    ).replace("  // Anything added here is installed with npm at deploy.\n", "")


def scaffold(
    *,
    name: str,
    namespace: str,
    runtime: str,
    method: str,
    memory_mb: int,
    timeout_s: int,
    ctx_access: str,
    base_url: str,
    max_instances: int = 4,
) -> dict[str, str]:
    spec = runtimes.get(runtime)
    if spec.language == "JavaScript":
        source = {
            "handler.js": default_handler_js(name, namespace),
            "package.json": default_package_json(name),
        }
    else:
        source = {
            "handler.py": default_handler(name, namespace),
            "requirements.txt": default_requirements(),
        }

    return {
        **source,
        "cubicle.toml": default_toml(
            name=name,
            namespace=namespace,
            runtime=runtime,
            method=method,
            memory_mb=memory_mb,
            timeout_s=timeout_s,
            ctx_access=ctx_access,
            max_instances=max_instances,
        ),
        "README.md": default_readme(name, namespace, base_url),
    }
