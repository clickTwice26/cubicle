"""Cubicle AI — the console's code assistant, and the settings behind it.

Writing a function is a developer action, so generating one is too: ``/generate``
sits behind the developer role and only ever reaches functions in the active
cluster. Configuring the provider is an admin action, and the key it stores is
write-only — it goes in envelope-encrypted and comes back as a hint, never as
itself.

What the model is sent is assembled in ``runtime.assistant`` and handed back to
the caller as ``context_sent``, so the console can show exactly what left the
machine rather than asking anyone to take it on trust.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ..crypto import encrypt
from ..deps import (
    CurrentCluster,
    CurrentPrincipal,
    DbSession,
    InstanceDep,
    RequireAdmin,
    RequireDeveloper,
)
from ..logging_setup import log
from ..runtime import assistant
from .functions import current_version, load_function

router = APIRouter(prefix="/api/ai", tags=["ai"])


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=assistant.MAX_HISTORY_CHARS)


class GenerateRequest(BaseModel):
    function_id: uuid.UUID
    prompt: str = Field(min_length=1, max_length=assistant.MAX_PROMPT)
    #: "write" starts from nothing; "edit" rewrites what is in the editor.
    mode: str = Field(default="edit", pattern="^(write|edit)$")
    #: The unsaved editor buffer, so the assistant edits what you are looking at
    #: rather than the last deployed version.
    code: str | None = Field(default=None, max_length=assistant.MAX_CODE_IN)
    requirements: str | None = Field(default=None, max_length=4000)
    #: The editor's README buffer, for the same reason as the code.
    readme: str | None = Field(default=None, max_length=assistant.MAX_README_IN)
    #: Playground session, so the assistant can see the shape of the live context.
    session_id: str | None = Field(default=None, max_length=120)
    #: Earlier turns of this conversation, oldest first.
    history: list[Turn] = Field(default_factory=list, max_length=assistant.MAX_HISTORY)


class SettingsUpdate(BaseModel):
    #: Omitted leaves the stored key alone; "" clears it.
    api_key: str | None = Field(default=None, max_length=400)
    base_url: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=80)


@router.get("/status")
async def ai_status(instance: InstanceDep, _: CurrentPrincipal):
    """Whether the assistant is usable, for the editor panel. Never the key."""
    return assistant.status(instance)


@router.put("/settings")
async def update_settings(
    payload: SettingsUpdate, instance: InstanceDep, db: DbSession, principal: RequireAdmin
):
    changed: list[str] = []

    if payload.api_key is not None:
        key = payload.api_key.strip()
        instance.ai_key_ciphertext = encrypt(key, aad="ai:key") if key else None
        changed.append("key set" if key else "key cleared")

    if payload.base_url is not None:
        url = payload.base_url.strip().rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "The base URL must start with http:// or https://."
            )
        instance.ai_base_url = url
        changed.append("base url")

    if payload.model is not None:
        instance.ai_model = payload.model.strip()
        changed.append("model")

    await db.commit()
    await db.refresh(instance)
    log.info("assistant settings updated", changed=changed, by=principal.user.email)
    return assistant.status(instance)


@router.post("/test")
async def test_connection(instance: InstanceDep, _: RequireAdmin):
    """Spend one token proving the key and model actually work."""
    try:
        return await assistant.check(assistant.config_for(instance))
    except assistant.AssistantError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/generate")
async def generate(
    payload: GenerateRequest,
    db: DbSession,
    cluster: CurrentCluster,
    instance: InstanceDep,
    principal: RequireDeveloper,
):
    fn = await load_function(db, payload.function_id, cluster)
    version = await current_version(db, fn)
    files = version.files if version else {}

    brief = await assistant.build_brief(db, cluster, fn, payload.session_id)
    try:
        result = await assistant.generate(
            config=assistant.config_for(instance),
            brief=brief,
            prompt=payload.prompt,
            mode=payload.mode,
            current_code=payload.code if payload.code is not None else files.get("handler.py"),
            requirements=(
                payload.requirements
                if payload.requirements is not None
                else files.get("requirements.txt")
            ),
            readme=payload.readme if payload.readme is not None else files.get("README.md"),
            history=[turn.model_dump() for turn in payload.history],
        )
    except assistant.AssistantError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    log.info(
        "assistant used",
        cluster=cluster.slug,
        function=f"{fn.group.ns}/{fn.name}",
        mode=payload.mode,
        by=principal.user.email,
    )
    return result
