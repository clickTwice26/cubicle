"""Cubicle AI — generating handler code with the runtime's own context.

A general model writes plausible Python; it does not know that ``ctx`` is a
session store shared across a namespace, that ``env`` resolves at invocation
time, or that this particular function is declared *read only* on the context.
So the model is not asked to guess: every request carries a brief describing the
runtime contract, plus the live facts about this function — its method, its
context access, which env keys exist, what the session currently holds, whether
Postgres and Redis are actually running, and which sibling functions share the
namespace.

What never leaves the machine is the one thing the model does not need in order
to write correct code: the *values* of secrets and env vars. Names are enough to
write ``env.require("STRIPE_KEY")``; the value would only be a credential handed
to a third party. That rule is enforced here rather than left to the caller —
this module never decrypts anything.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..crypto import DecryptionError, decrypt, mask
from ..logging_setup import log
from ..models import Cluster, EnvVar, Function, FunctionSecret, Group, Instance
from . import invoker, services

#: How many earlier turns are replayed, and how much of each. A chat that
#: grows without bound eventually costs more in context than the answer is
#: worth, and the oldest turns are the least relevant.
MAX_HISTORY = 12
MAX_HISTORY_CHARS = 2000

MAX_PROMPT = 4000
MAX_CODE_IN = 24_000
#: A README is prose and grows without bound; the code is what the model has to
#: get right, so it keeps the larger share of the window.
MAX_README_IN = 6_000
#: Enough to show shape without shipping payloads to a third party.
CONTEXT_PREVIEW = 80

RUNTIME_BRIEF = """\
You write Python handlers for Cubicle, a self-hosted serverless platform. Follow \
its contract exactly — it is not Flask, FastAPI or AWS Lambda.

THE HANDLER
- One module, `handler.py`, exporting `def handler(req, ctx):`. No framework, no \
app object, no decorators, no `if __name__ == "__main__"`.
- Imports available without listing them in requirements.txt:
    from cubicle_context import Request, Context, env
    from cubicle_db import postgres, redis

THE REQUEST (`req`)
- req.json()      parsed JSON body, returns the default instead of raising
- req.text()      body as text
- req.body        parsed JSON, raw text, or None
- req.headers     dict, lower-cased keys; req.header(name, default)
- req.method, req.path, req.query (dict)
- req.session_id, req.request_id, req.namespace, req.function
- `req` is also a Mapping, so req["body"] works.

RETURNING — four accepted shapes, checked in this order:
- {"ok": True}                          -> 200 with that JSON body
- (body, 201)                            -> two-tuple sets the status
- {"statusCode": 404, "headers": {...}, "body": {...}}  -> full control
- "plain text"                           -> 200 with the string as the body
An unhandled exception is a 502 and destroys the isolate. Return an explicit \
status for expected failures instead of raising.

THE SESSION CONTEXT (`ctx`)
- A JSON store keyed by the X-Cubicle-Session header, shared by every function \
in the same namespace, expiring 30 minutes after its last write.
- ctx.get(key, default=None), ctx.set(key, value), ctx.delete(key), ctx.all(), \
`key in ctx`.
- Values must be JSON-serialisable; ctx.set validates immediately.
- Writes apply once, at the end of a successful invocation.
- Respect this function's declared access mode. With `read only`, calling \
ctx.set raises PermissionError — do not call it. With `no access`, reads return \
the default and writes raise; do not use ctx at all.

CONFIGURATION (`env`)
- env.get(name, default=None), env.require(name), env.get_int, env.get_bool, \
env.get_json(name, default).
- Resolved per invocation. Use only the keys listed below as existing; if the \
task needs a new one, use env.get with a sensible default and say so in notes.
- Never hard-code a credential and never print an env value.

DATA (`postgres`, `redis`)
- Check `postgres.available` / `redis.available` first and degrade gracefully.
- `with postgres.session() as db:` is a transaction — commits on exit, rolls \
back on an exception.
- db.execute(sql, **params) with :name placeholders, then .fetchone(), \
.fetchall() or .scalar(). Bind values; never f-string them into SQL.
- redis.get/set/setex/incr/delete, and redis.client for anything else.

WHAT IT RUNS INSIDE
- One request per isolate, so module scope is safe from races and is the right \
place for a reusable client. It is not shared storage and does not survive.
- Read-only filesystem except /tmp. Memory and timeout are capped per function.
- Only the standard library plus what requirements.txt pins is importable. \
psycopg and redis are already in the image; never list those.

STYLE
- Complete, runnable file content — never a diff, never an ellipsis, never a \
placeholder like `# your logic here`.
- Type hints on the signature, a short docstring, guard clauses for bad input.
- Keep README.md true. It is the first thing whoever inherits this function \
reads, so when the request changes the endpoint's shape, its inputs or what it \
needs configured, update the README to match. Return it unchanged when nothing \
about it changed.
- Comment only what is not obvious from the code.
- Prefer the standard library. Add a dependency only when it genuinely earns \
its place, and pin it exactly.
"""

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "code": {
            "type": "string",
            "description": "The complete contents of handler.py. No markdown fences.",
        },
        "requirements": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Pinned requirements the code needs, e.g. 'httpx==0.28.1'. "
                "Empty when the standard library and the built-in SDKs are enough."
            ),
        },
        "readme": {
            "type": "string",
            "description": (
                "The complete contents of README.md, in markdown. Document what the "
                "endpoint does, the request and response shape, and anything it needs "
                "in Global env. Return the current README unchanged when the request "
                "did not affect what it says."
            ),
        },
        "notes": {
            "type": "string",
            "description": (
                "Two or three sentences for the operator: what the code does, and "
                "anything they must do themselves, such as adding an env key."
            ),
        },
    },
    "required": ["code", "requirements", "readme", "notes"],
    "additionalProperties": False,
}


class AssistantError(RuntimeError):
    """Something the operator should read: not configured, or the provider said no."""


@dataclass(slots=True)
class AiConfig:
    """Where the assistant sends its requests, and as whom.

    The key is set in the console and stored envelope-encrypted alongside every
    other secret, so it is decrypted here and nowhere else. The environment is
    only a fallback for installs that would rather bake it into ``.env``.
    """

    api_key: str
    base_url: str
    model: str
    max_output_tokens: int = 4000
    timeout: float = 90.0

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @property
    def provider(self) -> str:
        return self.base_url.split("//", 1)[-1].split("/", 1)[0]


def config_for(instance: Instance) -> AiConfig:
    key = ""
    if instance.ai_key_ciphertext:
        try:
            key = decrypt(instance.ai_key_ciphertext, aad="ai:key")
        except DecryptionError:
            # A key wrapped with a master key that has since changed is not
            # recoverable; say so rather than sending an empty Authorization.
            log.warning("assistant key could not be decrypted")
            key = ""
    return AiConfig(
        api_key=key or settings.ai_api_key,
        base_url=(instance.ai_base_url or settings.ai_base_url).rstrip("/"),
        model=instance.ai_model or settings.ai_model,
        max_output_tokens=settings.ai_max_output_tokens,
        timeout=settings.ai_timeout,
    )


def status(instance: Instance) -> dict[str, Any]:
    """What the console shows. The key itself never appears, only its shape."""
    config = config_for(instance)
    stored = bool(instance.ai_key_ciphertext)
    return {
        "enabled": config.configured,
        "model": config.model,
        "base_url": config.base_url,
        "provider": config.provider,
        "key_hint": mask(config.api_key) if config.configured else None,
        "key_source": "console" if stored else ("environment" if config.configured else None),
        "max_prompt_chars": MAX_PROMPT,
    }


@dataclass(slots=True)
class Brief:
    """The live facts sent alongside the prompt. Values are never in here."""

    function: dict[str, Any]
    env_keys: list[dict[str, Any]] = field(default_factory=list)
    secret_keys: list[str] = field(default_factory=list)
    context: list[dict[str, Any]] = field(default_factory=list)
    services: list[dict[str, Any]] = field(default_factory=list)
    siblings: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "function": self.function,
            "env_keys": self.env_keys,
            "secret_keys": self.secret_keys,
            "context": self.context,
            "services": self.services,
            "siblings": self.siblings,
        }


# ── the brief ────────────────────────────────────────────────────────────────


def _shape(value: Any) -> dict[str, Any]:
    """A context value described rather than reproduced."""
    kind = {
        type(None): "null",
        bool: "boolean",
        int: "number",
        float: "number",
        str: "string",
        list: "array",
        dict: "object",
    }.get(type(value), "unknown")
    if isinstance(value, dict):
        preview = "{" + ", ".join(sorted(value)[:8]) + "}"
    else:
        preview = json.dumps(value, default=str)
    if len(preview) > CONTEXT_PREVIEW:
        preview = preview[:CONTEXT_PREVIEW] + "…"
    return {"type": kind, "preview": preview}


async def build_brief(
    db: AsyncSession, cluster: Cluster, fn: Function, session_id: str | None
) -> Brief:
    group: Group = fn.group

    env_rows = (
        (await db.execute(select(EnvVar).where(EnvVar.cluster_id == cluster.id))).scalars().all()
    )
    secret_rows = (
        (await db.execute(select(FunctionSecret).where(FunctionSecret.function_id == fn.id)))
        .scalars()
        .all()
    )
    sibling_rows = (
        (await db.execute(select(Function).where(Function.group_id == fn.group_id))).scalars().all()
    )

    context: list[dict[str, Any]] = []
    if session_id and fn.ctx_access in ("rw", "r"):
        scope = invoker.scope_for(cluster.slug, group.ns)
        for key, value in (await invoker.read_context(scope, session_id)).items():
            context.append({"key": key, **_shape(value)})

    available: list[dict[str, Any]] = []
    for kind in ("postgres", "redis"):
        service = await services.get_service(db, cluster.id, kind)
        available.append(
            {
                "kind": kind,
                "available": bool(service and service.status == "running"),
                "version": service.version if service else None,
            }
        )

    return Brief(
        function={
            "namespace": group.ns,
            "name": fn.name,
            "method": fn.method,
            "runtime": fn.runtime,
            "context_access": {
                "rw": "read+write",
                "r": "read only",
                "w": "write only",
                "none": "no access",
            }[fn.ctx_access],
            "timeout_seconds": fn.timeout_s,
            "memory_mb": fn.memory_mb,
            "max_instances": fn.max_instances,
            "auth_required": fn.auth_required,
        },
        # Names only. The values stay on this machine.
        env_keys=[
            {"key": row.key, "secret": row.is_secret}
            for row in sorted(env_rows, key=lambda r: r.key)
        ],
        secret_keys=sorted(row.key for row in secret_rows),
        context=context,
        services=available,
        siblings=[
            {
                "name": row.name,
                "method": row.method,
                "path": f"/{group.ns}/{row.name}",
            }
            for row in sorted(sibling_rows, key=lambda r: r.name)
            if row.id != fn.id
        ],
    )


def _render(
    brief: Brief,
    current_code: str | None,
    requirements: str | None,
    readme: str | None = None,
) -> str:
    """The brief as the model sees it: facts, not prose."""
    fn = brief.function
    lines = [
        "THIS FUNCTION",
        f"- endpoint: {fn['method']} /{fn['namespace']}/{fn['name']}",
        f"- runtime: {fn['runtime']}, timeout {fn['timeout_seconds']}s,"
        f" memory {fn['memory_mb']} MB",
        f"- context access: {fn['context_access']}",
        f"- concurrency ceiling: {fn['max_instances']} isolates",
    ]

    if brief.env_keys:
        names = ", ".join(
            f"{row['key']}{' (secret)' if row['secret'] else ''}" for row in brief.env_keys
        )
        lines += ["", f"GLOBAL ENV KEYS THAT EXIST (values withheld): {names}"]
    else:
        lines += ["", "GLOBAL ENV: no keys defined on this cluster yet."]

    if brief.secret_keys:
        lines.append(
            "SECRET KEYS ON THIS FUNCTION (values withheld): " + ", ".join(brief.secret_keys)
        )

    lines.append("")
    if brief.context:
        lines.append("SESSION CONTEXT CURRENTLY HOLDS (shapes, truncated):")
        lines += [f"- {row['key']}: {row['type']} {row['preview']}" for row in brief.context]
    else:
        lines.append("SESSION CONTEXT: empty right now.")

    lines += ["", "DATA SERVICES:"]
    for row in brief.services:
        state = f"available ({row['version']})" if row["available"] else "not available"
        lines.append(f"- {row['kind']}: {state}")

    if brief.siblings:
        lines += ["", "OTHER FUNCTIONS IN THIS NAMESPACE (they share the same ctx):"]
        lines += [f"- {row['method']} {row['path']}" for row in brief.siblings]

    if current_code:
        lines += ["", "CURRENT handler.py:", "```python", current_code[:MAX_CODE_IN], "```"]
    if requirements and requirements.strip():
        lines += ["", "CURRENT requirements.txt:", "```", requirements[:2000], "```"]
    if readme and readme.strip():
        lines += ["", "CURRENT README.md:", "```markdown", readme[:MAX_README_IN], "```"]

    return "\n".join(lines)


# ── the call ─────────────────────────────────────────────────────────────────


def _instruction(mode: str) -> str:
    if mode == "edit":
        return (
            "Rewrite the current handler.py to satisfy the request below. Keep what "
            "already works, change what the request asks for, and return the complete "
            "file. Do not drop existing behaviour that the request did not mention."
        )
    return "Write handler.py from scratch for the request below. Return the complete file."


async def generate(
    *,
    config: AiConfig,
    brief: Brief,
    prompt: str,
    mode: str,
    current_code: str | None,
    requirements: str | None,
    readme: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    if not config.configured:
        raise AssistantError("Cubicle AI has no API key yet. Add one under Settings → Cubicle AI.")
    prompt = prompt.strip()
    if not prompt:
        raise AssistantError("Describe what the function should do.")
    if len(prompt) > MAX_PROMPT:
        raise AssistantError(f"That prompt is longer than {MAX_PROMPT} characters.")

    # Earlier turns sit between the brief and the current request. Only what
    # the assistant *said* is replayed, never the code it produced — the
    # editor's current buffer is already in the render below, and sending
    # every past version would spend the context window on stale files.
    turns: list[dict[str, str]] = []
    for entry in (history or [])[-MAX_HISTORY:]:
        role = entry.get("role")
        content = (entry.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            turns.append({"role": role, "content": content[:MAX_HISTORY_CHARS]})

    # `write` starts from nothing, so the current handler is withheld; the
    # README still goes in, because a rewrite should keep the documentation
    # true rather than start it over.
    seen_code = current_code if mode == "edit" else None
    rendered = _render(brief, seen_code, requirements, readme)

    messages = [
        {"role": "system", "content": RUNTIME_BRIEF},
        *turns,
        {
            "role": "user",
            "content": (f"{_instruction(mode)}\n\n" f"{rendered}\n\n" f"REQUEST\n{prompt}"),
        },
    ]

    started = time.perf_counter()
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "cubicle_function",
                "strict": True,
                "schema": RESPONSE_SCHEMA,
            },
        },
        "temperature": 0.1,
    }
    # OpenAI renamed the output cap; other OpenAI-compatible servers still take
    # the old name, and this endpoint is deliberately pointable at either.
    cap = "max_completion_tokens" if "openai.com" in config.base_url else "max_tokens"
    payload[cap] = config.max_output_tokens

    body = await _post(config, payload)
    choice = (body.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content") or ""
    result = _parse(content)

    usage = body.get("usage") or {}
    log.info(
        "assistant generated",
        model=body.get("model", config.model),
        mode=mode,
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        ms=round((time.perf_counter() - started) * 1000),
    )
    return {
        "code": result["code"],
        "requirements": result.get("requirements") or [],
        "notes": result.get("notes") or "",
        "model": body.get("model", config.model),
        "usage": {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
        },
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "context_sent": brief.as_dict(),
    }


async def check(config: AiConfig) -> dict[str, Any]:
    """A one-token round trip, so a saved key is verified rather than assumed."""
    if not config.configured:
        raise AssistantError("No API key set.")
    started = time.perf_counter()
    payload = {
        "model": config.model,
        "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
    }
    cap = "max_completion_tokens" if "openai.com" in config.base_url else "max_tokens"
    payload[cap] = 16
    body = await _post(config, payload)
    return {
        "ok": True,
        "model": body.get("model", config.model),
        "provider": config.provider,
        "duration_ms": round((time.perf_counter() - started) * 1000),
    }


async def _post(config: AiConfig, payload: dict[str, Any]) -> dict[str, Any]:
    """One request, with the retries that make this portable across providers."""
    url = config.base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {config.api_key}"}

    async with httpx.AsyncClient(timeout=config.timeout) as client:
        for attempt in range(3):
            try:
                response = await client.post(url, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                raise AssistantError(
                    f"The model did not answer within {config.timeout:.0f}s."
                ) from exc
            except httpx.HTTPError as exc:
                raise AssistantError(f"Could not reach {url}: {exc}") from exc

            if response.status_code < 400:
                return response.json()

            detail = _detail(response)
            # A 400 naming one of the optional parameters means this model or
            # server does not take it. Drop that one and try again rather than
            # making the operator discover it from a provider error string.
            if response.status_code == 400 and attempt < 2:
                dropped = _drop_unsupported(payload, detail)
                if dropped:
                    log.info("assistant retrying without parameter", parameter=dropped)
                    continue
            raise AssistantError(_message(config, response.status_code, detail))

    raise AssistantError("The model rejected every form of that request.")


def _drop_unsupported(payload: dict[str, Any], detail: str) -> str | None:
    lowered = detail.lower()
    if "response_format" in lowered or "json_schema" in lowered:
        # Fall back to plain JSON mode; the schema is described in the prompt.
        if payload.get("response_format", {}).get("type") == "json_schema":
            payload["response_format"] = {"type": "json_object"}
            payload["messages"][0]["content"] += (
                "\n\nReply with a single JSON object holding exactly the keys "
                '"code" (string), "requirements" (array of strings) and "notes" (string).'
            )
            return "response_format.json_schema"
        payload.pop("response_format", None)
        return "response_format"
    for parameter in ("temperature", "max_completion_tokens", "max_tokens"):
        if parameter in lowered and parameter in payload:
            payload.pop(parameter)
            return parameter
    return None


def _detail(response: httpx.Response) -> str:
    try:
        error = response.json().get("error") or {}
        return str(error.get("message") or response.text)[:500]
    except ValueError:
        return response.text[:500]


def _message(config: AiConfig, code: int, detail: str) -> str:
    if code in (401, 403):
        return f"{config.provider} rejected the API key."
    if code == 404:
        return f"{config.provider} has no model called '{config.model}'. — {detail}"
    if code == 429:
        return f"Rate limited or out of quota at the provider. — {detail}"
    if code >= 500:
        return f"The provider failed ({code}). — {detail}"
    return detail or f"The provider refused the request ({code})."


def _parse(content: str) -> dict[str, Any]:
    """Take the answer apart, whether it arrived as JSON or as a fenced file."""
    text = content.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and isinstance(parsed.get("code"), str):
            return parsed
    except ValueError:
        pass

    # Some servers ignore response_format entirely and answer with prose plus a
    # code fence. That is still a usable answer.
    if "```" in text:
        block = text.split("```", 2)[1]
        code = block.split("\n", 1)[1] if block.lower().startswith("python") else block
        return {"code": code.strip(), "requirements": [], "notes": ""}
    if text.startswith(("from ", "import ", "def ", '"""')):
        return {"code": text, "requirements": [], "notes": ""}
    raise AssistantError("The model did not return usable code. Try rephrasing the request.")
