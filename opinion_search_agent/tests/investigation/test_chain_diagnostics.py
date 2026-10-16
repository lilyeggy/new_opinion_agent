"""Production-chain observability for public-event investigations."""

from __future__ import annotations

from opinion_search.domain.investigation.models import (
    Evidence,
    Finding,
    FindingProposal,
    InvestigationRequest,
    Issue,
    SourceVersion,
    State,
    SearchAttempt,
    uid,
    utcnow,
)
from opinion_search.investigation.diagnostics import FORMAT, STAGE_ORDER, build_chain_diagnostics


def _degraded_state() -> State:
    issues = (
        Issue(issue_id="facts", question="发生了什么？", status="answered"),
        Issue(issue_id="positions", question="各方观点是什么？", status="unavailable"),
        Issue(issue_id="response", question="机构回应覆盖了什么？", status="answered"),
    )
    source = SourceVersion(
        version_id="version-one", url="https://only.example/report", final_url="https://only.example/report",
        title="单一报道", fetched_at=utcnow(), artifact_ref="artifacts/source.txt", content_hash="hash-one",
        role="reporting",
    )
    evidence = Evidence(evidence_id="evidence-one", version_id=source.version_id, excerpt="机构发布了一份说明。",
                        start=0, end=10, locator="Reader text chars 0:10")
    proposal = FindingProposal(issue_id="facts", text="报道转述机构发布了说明。", kind="attributed",
                               stakeholder="机构", evidence_ids=(evidence.evidence_id,))
    finding = Finding(**proposal.model_dump(), finding_id=uid("finding", proposal.issue_id, proposal.text))
    return State(
        request=InvestigationRequest(question="调查事件事实、各方观点和机构回应"), subject="测试事件",
        cutoff=utcnow(), issues=issues, sources=(source,), evidence=(evidence,), findings=(finding,),
        candidates=({"url": source.url}, {"url": "https://only.example/unread"}),
        read_attempts=(source.url,),
        searches=(SearchAttempt(issue_id="facts", query="测试事件 公告", purpose="original", page=0,
                                outcome="candidates", count=2),),
    )


def test_diagnostics_name_specific_pipeline_failures_without_a_quality_score():
    diagnostics = build_chain_diagnostics(_degraded_state(), publication_status="completed")
    codes = {item["code"] for item in diagnostics["signals"]}

    assert diagnostics["format"] == FORMAT
    assert [stage["id"] for stage in diagnostics["stages"]] == list(STAGE_ORDER)
    assert diagnostics["summary"]["status"] == "blocked"
    assert "required_issues_unresolved" in codes
    assert "unread_candidates" in codes
    assert "single_source_domain" in codes
    assert "source_independence_unverified" in codes
    assert "response_coverage_missing" in codes
    assert "active_findings_unreviewed" in codes
    assert "completion_status_mismatch" in codes
    analysis = next(stage for stage in diagnostics["stages"] if stage["id"] == "analysis")["metrics"]
    assert analysis["stance_distribution_eligible"] is False
    assert "公众观点占比" in analysis["stance_distribution_reason"]
    assert "质量分数" in diagnostics["summary"]["disclaimer"]


def test_completed_offline_run_persists_runtime_and_budget_diagnostics(manager, run_offline):
    snapshot = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    diagnostics = snapshot["report"]["diagnostics"]
    runtime = next(stage for stage in diagnostics["stages"] if stage["id"] == "runtime")["metrics"]

    assert diagnostics == manager.diagnostics(snapshot["run_id"])
    assert runtime["available"] is True
    assert runtime["checkpoint_boundary"] == "published"
    assert runtime["committed_steps"] > 0
    assert runtime["actions"].get("search", 0) > 0
    assert runtime["budget"]["available"] is True

