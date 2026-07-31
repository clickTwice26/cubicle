"""Prometheus metrics.

Exposed unauthenticated on ``/metrics`` so a scrape job needs no credentials —
this is the metering export the console points at. Every series is derived from
real invocations; nothing here is sampled.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

REGISTRY = CollectorRegistry(auto_describe=True)

INVOCATIONS = Counter(
    "cubicle_invocations_total",
    "Function invocations by outcome.",
    ["namespace", "function", "status"],
    registry=REGISTRY,
)

INVOCATION_SECONDS = Histogram(
    "cubicle_invocation_duration_seconds",
    "End-to-end invocation latency, including cold starts.",
    ["namespace", "function"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
    registry=REGISTRY,
)

COLD_STARTS = Counter(
    "cubicle_cold_starts_total",
    "Invocations that had to start a new isolate.",
    ["namespace", "function"],
    registry=REGISTRY,
)

BUILDS = Counter(
    "cubicle_builds_total",
    "Function builds by result.",
    ["result"],
    registry=REGISTRY,
)

WARM_ISOLATES = Gauge(
    "cubicle_warm_isolates",
    "Isolates currently resident.",
    registry=REGISTRY,
)

GB_SECONDS = Counter(
    "cubicle_gb_seconds_total",
    "Metered compute, attributed to the function's namespace.",
    ["namespace"],
    registry=REGISTRY,
)


def render() -> bytes:
    return generate_latest(REGISTRY)
