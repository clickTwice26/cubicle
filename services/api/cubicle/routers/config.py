"""Global env — one store per cluster.

Values are read at invocation time rather than baked into a deploy, so changing
one takes effect on the next request without a redeploy. Anything marked as a
secret is envelope-encrypted at rest and masked everywhere in the console.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import delete, select

from ..crypto import DecryptionError, decrypt, encrypt, mask
from ..deps import CurrentCluster, CurrentPrincipal, DbSession, RequireDeveloper
from ..logging_setup import log
from ..models import EnvVar
from ..runtime import invoker
from ..schemas import EnvVarIn, EnvVarOut

router = APIRouter(prefix="/api/env", tags=["env"])


async def _find(db, cluster, key: str) -> EnvVar | None:
    return (
        await db.execute(select(EnvVar).where(EnvVar.cluster_id == cluster.id, EnvVar.key == key))
    ).scalar_one_or_none()


def _out(row: EnvVar, *, reveal: bool = False) -> EnvVarOut:
    try:
        value = decrypt(row.value_ciphertext, aad=f"env:{row.key}")
    except DecryptionError:
        return EnvVarOut(
            key=row.key,
            value="<undecryptable — root key changed>",
            is_secret=row.is_secret,
            masked=True,
            updated_at=row.updated_at,
        )
    masked = row.is_secret and not reveal
    return EnvVarOut(
        key=row.key,
        value=mask(value) if masked else value,
        is_secret=row.is_secret,
        masked=masked,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[EnvVarOut])
async def list_env(db: DbSession, cluster: CurrentCluster, _: CurrentPrincipal):
    rows = (
        (
            await db.execute(
                select(EnvVar).where(EnvVar.cluster_id == cluster.id).order_by(EnvVar.key)
            )
        )
        .scalars()
        .all()
    )
    return [_out(row) for row in rows]


@router.post("", response_model=EnvVarOut, status_code=status.HTTP_201_CREATED)
async def upsert_env(
    payload: EnvVarIn, db: DbSession, cluster: CurrentCluster, principal: RequireDeveloper
):
    row = await _find(db, cluster, payload.key)
    ciphertext = encrypt(payload.value, aad=f"env:{payload.key}")
    if row is None:
        row = EnvVar(
            cluster_id=cluster.id,
            key=payload.key,
            value_ciphertext=ciphertext,
            is_secret=payload.is_secret,
        )
        db.add(row)
    else:
        row.value_ciphertext = ciphertext
        row.is_secret = payload.is_secret
    await db.commit()
    await db.refresh(row)
    await invoker.bump_env_revision()
    log.info(
        "env var written",
        key=row.key,
        secret=row.is_secret,
        cluster=cluster.slug,
        by=principal.user.email,
    )
    return _out(row)


@router.get("/{key}/reveal", response_model=EnvVarOut)
async def reveal_env(key: str, db: DbSession, cluster: CurrentCluster, principal: CurrentPrincipal):
    row = await _find(db, cluster, key)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such variable.")
    if row.is_secret and not principal.can("admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can reveal secret values.")
    if row.is_secret:
        log.info("env secret revealed", key=key, by=principal.user.email)
    return _out(row, reveal=True)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_env(
    key: str, db: DbSession, cluster: CurrentCluster, principal: RequireDeveloper
) -> Response:
    result = await db.execute(
        delete(EnvVar).where(EnvVar.cluster_id == cluster.id, EnvVar.key == key)
    )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such variable.")
    await db.commit()
    await invoker.bump_env_revision()
    log.info("env var deleted", key=key, by=principal.user.email)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
