"""What this workload would cost on a hosted platform.

The comparison the console shows is arithmetic over the invocations you have
actually served — request count, metered GB-seconds and measured response
bytes — priced at each vendor's public list rate. It is not a benchmark and
not an estimate of your bill: no committed-use discounts, no free tiers, no
data-transfer agreements, us-east equivalents.

The Cubicle line is marginal electricity only. Hardware you already own, rack
space and operator time are deliberately excluded, because those costs do not
disappear when you move the workload somewhere else.
"""

from __future__ import annotations

from dataclasses import dataclass

RATES_AS_OF = "2026-07"

GB = 1024**3


@dataclass(frozen=True, slots=True)
class Vendor:
    key: str
    name: str
    per_million_requests: float
    per_gb_second: float
    per_gb_egress: float
    free_requests_per_month: int = 0
    colour: str = "var(--text-3)"

    def cost(self, requests: int, gb_seconds: float, egress_bytes: int) -> dict[str, float]:
        billable = max(0, requests - self.free_requests_per_month)
        request_cost = (billable / 1_000_000) * self.per_million_requests
        compute_cost = gb_seconds * self.per_gb_second
        egress_cost = (egress_bytes / GB) * self.per_gb_egress
        return {
            "requests": request_cost,
            "compute": compute_cost,
            "egress": egress_cost,
            "total": request_cost + compute_cost + egress_cost,
        }


VENDORS: tuple[Vendor, ...] = (
    Vendor("aws", "AWS Lambda", 0.20, 0.0000166667, 0.09, colour="var(--warn)"),
    Vendor("azure", "Azure Functions", 0.20, 0.000016, 0.087, colour="var(--info)"),
    Vendor("gcp", "Google Cloud Run functions", 0.40, 0.0000100, 0.12, colour="var(--err)"),
    Vendor("do", "DigitalOcean Functions", 0.0, 0.0000185, 0.01, colour="var(--text-3)"),
)

# Marginal draw of a busy isolate, used only for the self-hosted line.
WATTS_PER_GB_SECOND = 0.35 / 3600  # ~0.35 W per resident GB, expressed per GB-second
DEFAULT_KWH_PRICE = 0.11


def self_hosted_cost(gb_seconds: float, kwh_price: float = DEFAULT_KWH_PRICE) -> dict[str, float]:
    kwh = gb_seconds * WATTS_PER_GB_SECOND / 1000
    compute = kwh * kwh_price
    return {"requests": 0.0, "compute": compute, "egress": 0.0, "total": compute}


def comparison(
    *, requests: int, gb_seconds: float, egress_bytes: int, kwh_price: float = DEFAULT_KWH_PRICE
) -> dict:
    rows = []
    for vendor in VENDORS:
        cost = vendor.cost(requests, gb_seconds, egress_bytes)
        rows.append({"key": vendor.key, "name": vendor.name, "colour": vendor.colour, **cost})

    mine = self_hosted_cost(gb_seconds, kwh_price)
    rows.append(
        {
            "key": "cubicle",
            "name": "Cubicle · this cluster",
            "colour": "var(--accent)",
            **mine,
            "self": True,
        }
    )

    peak = max((r["total"] for r in rows), default=0.0) or 1.0
    for row in rows:
        row["bar"] = round((row["total"] / peak) * 100, 1)
        row["saved"] = None if row.get("self") else round(row["total"] - mine["total"], 2)

    baseline = next((r for r in rows if r["key"] == "aws"), None)
    avoided = round((baseline["total"] - mine["total"]), 2) if baseline else 0.0
    return {
        "rows": rows,
        "self_hosted_total": round(mine["total"], 2),
        "avoided_vs_aws": avoided,
        "rates_as_of": RATES_AS_OF,
        "kwh_price": kwh_price,
    }
