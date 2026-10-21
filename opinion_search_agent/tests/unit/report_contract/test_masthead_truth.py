"""The masthead must only claim what the run actually did."""

from __future__ import annotations

from opinion_search.report_contract.contracts import PresentationPlan
from opinion_search.report_contract.renderer import _audit_badges


def _plan(audit: dict) -> PresentationPlan:
    return PresentationPlan(
        source_content_revision=1, report_id="run-abc", subject="事件", status="partial", generated_at="2026-10-20",
        sections=(), profile={"audit": audit},
    )


def test_unreviewed_run_is_rated_unrated():
    badges = _audit_badges(_plan({"findings_total": 17, "findings_reviewed": 0}))
    assert "未评级" in badges["rating"]
    assert "17 条判断尚未送审" == badges["mechanism"]


def test_reviewed_run_reports_its_own_counts():
    badges = _audit_badges(_plan({
        "findings_total": 25, "findings_reviewed": 25, "findings_supported": 24,
        "issues_total": 6, "issues_closed": 2,
        "relations_total": 9, "relations_unverified": 9,
    }))
    assert badges["rating"] == "核查评级：24/25 条过审"
    assert "2/6 个议题已收口" in badges["mechanism"]
    assert badges["ledger"] == "来源关系：9/9 个未核实"


def test_no_findings_means_no_rating_claim():
    badges = _audit_badges(_plan({}))
    assert badges["rating"] == "未评级"
    assert badges["ledger"] == "来源关系：未核验"
