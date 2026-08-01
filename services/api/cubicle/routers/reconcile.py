"""Resource sync — what we believe against what Docker has, and fixing the gap."""

from __future__ import annotations

from fastapi import APIRouter

from ..deps import DbSession, RequireOwner
from ..runtime import reconcile
from ..schemas import ReconcileApply, ReconcileReport, ReconcileResult

router = APIRouter(prefix="/api/reconcile", tags=["reconcile"])


@router.get("", response_model=ReconcileReport)
async def scan(db: DbSession, principal: RequireOwner):
    """Report drift across every cluster. Reads only; changes nothing.

    Super admin only, and instance-wide rather than scoped to a cluster: drift
    is mostly the kind of thing that has no cluster — a volume whose service was
    deleted, a node that stopped answering.
    """
    findings = await reconcile.scan(db)
    return _report(findings)


@router.post("/apply", response_model=ReconcileResult)
async def apply(payload: ReconcileApply, db: DbSession, principal: RequireOwner):
    """Act on chosen findings, then report the state that remains.

    The scan is redone here rather than trusting what the browser was shown: it
    may be minutes old, and acting on a finding that has since resolved would
    remove something that became legitimate in between.
    """
    findings = await reconcile.scan(db)
    outcome = await reconcile.apply(db, findings, set(payload.ids))
    return {**outcome, "report": _report(await reconcile.scan(db))}


def _report(findings: list[reconcile.Finding]) -> dict:
    return {
        "findings": [f.__dict__ for f in findings],
        "errors": sum(1 for f in findings if f.severity == "error"),
        "warnings": sum(1 for f in findings if f.severity == "warn"),
        "fixable": sum(1 for f in findings if f.fix and not f.destructive),
    }
