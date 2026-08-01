"""Aggregations over the invocation table.

Every number the console shows comes from here, and every one of them is a
query over real rows. Where there is no data yet the helpers return an em dash
rather than inventing a plausible-looking figure.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Float, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Function, Invocation

DASH = "—"


# ── formatting ───────────────────────────────────────────────────────────────


def fmt_ms(value: float | None) -> str:
    if value is None:
        return DASH
    if value >= 1000:
        return f"{value / 1000:.2f}s".replace(".00s", "s")
    return f"{value:.0f}ms"


def fmt_count(value: int | None) -> str:
    if not value:
        return "0"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def fmt_pct(numerator: int, denominator: int) -> str:
    if not denominator:
        return DASH
    return f"{(numerator / denominator) * 100:.2f}%"


def fmt_bytes(value: float | None) -> str:
    if not value:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def relative(ts: datetime | None) -> str:
    if ts is None:
        return DASH
    delta = datetime.now(UTC) - ts
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


# ── per-function ─────────────────────────────────────────────────────────────

_PERCENTILES = (0.5, 0.9, 0.95, 0.99)


async def function_stats(db: AsyncSession, function_id: UUID, *, hours: int = 24) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(hours=hours)
    row = (
        await db.execute(
            select(
                func.count(Invocation.id),
                func.sum(case((Invocation.status_code >= 400, 1), else_=0)),
                func.sum(case((Invocation.cold.is_(True), 1), else_=0)),
                *[
                    func.percentile_cont(p).within_group(Invocation.duration_ms.asc())
                    for p in _PERCENTILES
                ],
                func.sum(Invocation.gb_seconds),
                func.max(Invocation.ts),
            ).where(Invocation.function_id == function_id, Invocation.ts >= since)
        )
    ).one()

    total, errors, colds, p50, p90, p95, p99, gbs, last = row
    total = total or 0
    return {
        "invocations": total,
        "invocations_label": fmt_count(total),
        "p50": fmt_ms(p50),
        "p90": fmt_ms(p90),
        "p95": fmt_ms(p95),
        "p99": fmt_ms(p99),
        "error_rate": fmt_pct(errors or 0, total),
        "cold_rate": fmt_pct(colds or 0, total),
        "gb_seconds": float(gbs or 0),
        "last_invocation": last,
    }


async def bulk_function_stats(
    db: AsyncSession, *, hours: int = 24, cluster_id: UUID | None = None
) -> dict[UUID, dict[str, Any]]:
    since = datetime.now(UTC) - timedelta(hours=hours)
    stmt = (
        select(
            Invocation.function_id,
            func.count(Invocation.id),
            func.sum(case((Invocation.status_code >= 400, 1), else_=0)),
            func.sum(case((Invocation.cold.is_(True), 1), else_=0)),
            func.percentile_cont(0.5).within_group(Invocation.duration_ms.asc()),
            func.percentile_cont(0.95).within_group(Invocation.duration_ms.asc()),
        )
        .where(Invocation.ts >= since)
        .group_by(Invocation.function_id)
    )
    if cluster_id is not None:
        stmt = stmt.where(Invocation.cluster_id == cluster_id)
    rows = (await db.execute(stmt)).all()

    result: dict[UUID, dict[str, Any]] = {}
    for fid, total, errors, colds, p50, p95 in rows:
        if fid is None:
            continue
        result[fid] = {
            "invocations": total or 0,
            "invocations_label": fmt_count(total or 0),
            "p50": fmt_ms(p50),
            "p95": fmt_ms(p95),
            "error_rate": fmt_pct(errors or 0, total or 0),
            "cold_rate": fmt_pct(colds or 0, total or 0),
            "errors": errors or 0,
        }
    return result


# ── dashboard ────────────────────────────────────────────────────────────────


async def invocation_series(
    db: AsyncSession,
    *,
    hours: int = 24,
    buckets: int = 28,
    function_id: UUID | None = None,
    cluster_id: UUID | None = None,
) -> list[dict[str, Any]]:
    """Bucketed success/error counts, oldest first, always ``buckets`` long."""
    now = datetime.now(UTC)
    since = now - timedelta(hours=hours)
    width = timedelta(hours=hours) / buckets

    stmt = (
        select(
            func.floor(
                cast(func.extract("epoch", Invocation.ts - since), Float) / width.total_seconds()
            ).label("bucket"),
            func.count(Invocation.id),
            func.sum(case((Invocation.status_code >= 400, 1), else_=0)),
        )
        .where(Invocation.ts >= since)
        .group_by("bucket")
    )
    if function_id is not None:
        stmt = stmt.where(Invocation.function_id == function_id)
    if cluster_id is not None:
        stmt = stmt.where(Invocation.cluster_id == cluster_id)

    counts = {
        int(b): (int(total or 0), int(errs or 0))
        for b, total, errs in (await db.execute(stmt)).all()
    }

    series = []
    for index in range(buckets):
        total, errors = counts.get(index, (0, 0))
        series.append(
            {
                "bucket": (since + width * index).isoformat(),
                "ok": total - errors,
                "err": errors,
            }
        )
    return series


async def latency_series(
    db: AsyncSession, function_id: UUID, *, hours: int = 24, buckets: int = 24
) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    since = now - timedelta(hours=hours)
    width = timedelta(hours=hours) / buckets

    rows = (
        await db.execute(
            select(
                func.floor(
                    cast(func.extract("epoch", Invocation.ts - since), Float)
                    / width.total_seconds()
                ).label("bucket"),
                func.percentile_cont(0.95).within_group(Invocation.duration_ms.asc()),
                func.sum(case((Invocation.cold.is_(True), 1), else_=0)),
                func.count(Invocation.id),
            )
            .where(Invocation.function_id == function_id, Invocation.ts >= since)
            .group_by("bucket")
        )
    ).all()

    values = {
        int(b): (float(p95 or 0), int(cold or 0), int(total or 0)) for b, p95, cold, total in rows
    }
    peak = max((v[0] for v in values.values()), default=0.0) or 1.0

    series = []
    for index in range(buckets):
        p95, cold, total = values.get(index, (0.0, 0, 0))
        series.append(
            {
                "bucket": (since + width * index).isoformat(),
                "p95": round(p95, 2),
                "fill": round((p95 / peak) * 100, 1),
                "cold": cold,
                "cold_pct": round((cold / total) * 100, 1) if total else 0.0,
            }
        )
    return series


async def cluster_kpis(
    db: AsyncSession, *, hours: int = 24, cluster_id: UUID | None = None
) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    current_since = now - timedelta(hours=hours)
    previous_since = now - timedelta(hours=hours * 2)

    async def window(start: datetime, end: datetime):
        stmt = select(
            func.count(Invocation.id),
            func.percentile_cont(0.5).within_group(Invocation.duration_ms.asc()),
            func.sum(case((Invocation.status_code >= 400, 1), else_=0)),
            func.sum(case((Invocation.cold.is_(True), 1), else_=0)),
        ).where(Invocation.ts >= start, Invocation.ts < end)
        if cluster_id is not None:
            stmt = stmt.where(Invocation.cluster_id == cluster_id)
        return (await db.execute(stmt)).one()

    total, p50, errors, colds = await window(current_since, now)
    prev_total, prev_p50, prev_errors, prev_colds = await window(previous_since, current_since)

    total, errors, colds = total or 0, errors or 0, colds or 0
    prev_total, prev_errors, prev_colds = prev_total or 0, prev_errors or 0, prev_colds or 0

    def delta_pct(current: float, previous: float) -> tuple[str | None, str]:
        if not previous:
            return (None, "flat")
        change = ((current - previous) / previous) * 100
        if abs(change) < 0.05:
            return ("0%", "flat")
        return (f"{change:+.1f}%", "up" if change > 0 else "down")

    err_rate = (errors / total * 100) if total else 0.0
    prev_err_rate = (prev_errors / prev_total * 100) if prev_total else 0.0
    cold_rate = (colds / total * 100) if total else 0.0
    prev_cold_rate = (prev_colds / prev_total * 100) if prev_total else 0.0

    inv_delta, inv_dir = delta_pct(total, prev_total)
    p50_delta = (
        f"{(p50 or 0) - (prev_p50 or 0):+.0f}ms"
        if p50 is not None and prev_p50 is not None
        else None
    )
    # `polarity` is what a rise *means*, which is not the same for every metric.
    # Without it the console has to guess from the label, and painted a busy
    # traffic day the same colour as a spike in failures.
    return [
        {
            "key": "invocations",
            "label": "Invocations",
            "value": fmt_count(total),
            "delta": inv_delta,
            "direction": inv_dir,
            "polarity": "neutral",
            "hint": f"served in the last {hours}h",
        },
        {
            "key": "latency",
            "label": "Median latency",
            "value": fmt_ms(p50),
            "delta": p50_delta,
            "direction": "down"
            if p50_delta and p50_delta.startswith("-")
            else "up"
            if p50_delta
            else "flat",
            "polarity": "lower_better",
            "hint": "half of requests finish faster",
        },
        {
            "key": "errors",
            "label": "Error rate",
            "value": f"{err_rate:.2f}%" if total else DASH,
            "delta": f"{err_rate - prev_err_rate:+.2f}%" if prev_total else None,
            "direction": "up"
            if err_rate > prev_err_rate
            else "down"
            if err_rate < prev_err_rate
            else "flat",
            "polarity": "lower_better",
            "hint": f"{fmt_count(errors)} of {fmt_count(total)} answered 4xx or 5xx"
            if total
            else "nothing to measure yet",
        },
        {
            "key": "cold",
            "label": "Cold starts",
            "value": f"{cold_rate:.1f}%" if total else DASH,
            "delta": f"{cold_rate - prev_cold_rate:+.1f}%" if prev_total else None,
            "direction": "up"
            if cold_rate > prev_cold_rate
            else "down"
            if cold_rate < prev_cold_rate
            else "flat",
            "polarity": "lower_better",
            "hint": "waited for a container to start",
        },
    ]


# ── metering ─────────────────────────────────────────────────────────────────


def month_window(now: datetime | None = None) -> tuple[datetime, datetime, float]:
    now = now or datetime.now(UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=32)).replace(day=1)
    progress = (now - start).total_seconds() / (end - start).total_seconds()
    return start, end, min(1.0, max(0.0, progress))


async def namespace_usage(
    db: AsyncSession, start: datetime, end: datetime, cluster_id: UUID | None = None
) -> list[dict[str, Any]]:
    stmt = (
        select(
            Invocation.namespace,
            func.count(Invocation.id),
            func.sum(Invocation.gb_seconds),
        )
        .where(Invocation.ts >= start, Invocation.ts < end)
        .group_by(Invocation.namespace)
        .order_by(func.count(Invocation.id).desc())
    )
    if cluster_id is not None:
        stmt = stmt.where(Invocation.cluster_id == cluster_id)
    rows = (await db.execute(stmt)).all()
    return [
        {
            "name": ns or "default",
            "invocations": int(count or 0),
            "invocations_label": f"{int(count or 0):,}",
            "gb_seconds": float(gbs or 0),
            "gb_seconds_label": f"{float(gbs or 0):,.1f}",
        }
        for ns, count, gbs in rows
    ]


async def function_count(db: AsyncSession) -> int:
    return (await db.execute(select(func.count(Function.id)))).scalar_one()
