import pytest
from pydantic import ValidationError

from cubicle import pricing
from cubicle.analytics import fmt_bytes, fmt_count, fmt_ms, fmt_pct
from cubicle.schemas import DeployRequest, FunctionCreate, GroupCreate

GB = 1024**3


def test_comparison_is_arithmetic_over_real_usage():
    result = pricing.comparison(requests=1_000_000, gb_seconds=10_000, egress_bytes=10 * GB)
    aws = next(row for row in result["rows"] if row["key"] == "aws")

    assert aws["requests"] == pytest.approx(0.20)
    assert aws["compute"] == pytest.approx(0.166667, rel=1e-4)
    assert aws["egress"] == pytest.approx(0.90)
    assert aws["total"] == pytest.approx(aws["requests"] + aws["compute"] + aws["egress"])


def test_zero_usage_costs_nothing_anywhere():
    result = pricing.comparison(requests=0, gb_seconds=0, egress_bytes=0)
    assert all(row["total"] == 0 for row in result["rows"])
    assert result["avoided_vs_aws"] == 0


def test_self_hosted_line_is_present_and_cheapest_on_egress():
    result = pricing.comparison(requests=5_000_000, gb_seconds=50_000, egress_bytes=100 * GB)
    mine = next(row for row in result["rows"] if row["key"] == "cubicle")
    assert mine["egress"] == 0
    assert mine["saved"] is None
    assert result["avoided_vs_aws"] > 0


def test_digitalocean_free_requests_are_honoured():
    result = pricing.comparison(requests=1_000_000, gb_seconds=1, egress_bytes=0)
    do = next(row for row in result["rows"] if row["key"] == "do")
    assert do["requests"] == 0


# ── formatting ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, "—"), (0, "0ms"), (42.4, "42ms"), (1500, "1.50s"), (999.6, "1000ms")],
)
def test_fmt_ms(value, expected):
    assert fmt_ms(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0"), (None, "0"), (999, "999"), (1500, "1.5K"), (4_720_000, "4.72M")],
)
def test_fmt_count(value, expected):
    assert fmt_count(value) == expected


def test_fmt_pct_handles_no_data():
    assert fmt_pct(0, 0) == "—"
    assert fmt_pct(1, 200) == "0.50%"


def test_fmt_bytes():
    assert fmt_bytes(0) == "0 B"
    assert fmt_bytes(2048) == "2.0 KB"


# ── validation ───────────────────────────────────────────────────────────────


def test_reserved_namespaces_are_refused():
    with pytest.raises(ValidationError):
        GroupCreate(name="API", ns="api")


@pytest.mark.parametrize("name", ["Not Valid", "-leading", "trailing-", "under_score", ""])
def test_function_names_must_be_slugs(name):
    with pytest.raises(ValidationError):
        FunctionCreate(name=name)


@pytest.mark.parametrize(
    ("given", "expected"),
    [("  create-charge ", "create-charge"), ("Create-Charge", "create-charge"), ("A1", "a1")],
)
def test_function_names_are_normalised(given, expected):
    """Case and surrounding space are fixed up rather than rejected."""
    assert FunctionCreate(name=given).name == expected


def test_deploy_requires_a_handler():
    with pytest.raises(ValidationError):
        DeployRequest(files={"requirements.txt": ""})


def test_deploy_rejects_unknown_files():
    with pytest.raises(ValidationError):
        DeployRequest(files={"handler.py": "x", "../escape.py": "y"})


def test_deploy_rejects_oversized_bundles():
    with pytest.raises(ValidationError):
        DeployRequest(files={"handler.py": "x" * 2_000_001})
