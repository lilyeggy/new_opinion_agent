"""Finish-gate guidance: rejections must name the legal next move.

A bare "questions remain open" rejection let a live run spin on finish 29
times (2026-09-23, run cb395088). The gate now names undisposed evidence,
unread candidates, and the honest exits per open question, and refuses to
finish while a negative-existence finding collides with undisposed
response-bearing evidence.
"""

from __future__ import annotations

from opinion_search.domain.investigation.engine import completion
from opinion_search.domain.investigation.models import (
    Evidence,
    Finding,
    FindingProposal,
    InvestigationRequest,
    Issue,
    State,
    SourceVersion,
    uid,
    utcnow,
)
from opinion_search.runtime.completion import CompletionDisposition

TEXTS = ("发生了什么", "品牌方如何回应", "争议焦点是什么")


def _evidence(evidence_id: str, version_id: str, excerpt: str) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        version_id=version_id,
        excerpt=excerpt,
        start=0,
        end=len(excerpt),
        locator=f"chars 0:{len(excerpt)}",
    )


def _source(version_id: str, url: str) -> SourceVersion:
    return SourceVersion(
        version_id=version_id,
        url=url,
        final_url=url,
        title="报道",
        fetched_at=utcnow(),
        artifact_ref="artifact://sha256/" + "7" * 64,
        content_hash="7" * 64,
    )


def _finding(finding_id: str, issue_id: str, text: str, **overrides) -> Finding:
    base = dict(
        issue_id=issue_id,
        text=text,
        kind="fact",
        evidence_ids=("e-linked",),
    )
    base.update(overrides)
    proposal = FindingProposal(**base)
    return Finding(**proposal.model_dump(), finding_id=finding_id)


def _state(**extra) -> State:
    issues = tuple(Issue(issue_id=uid("issue", text), question=text) for text in TEXTS)
    linked_excerpt = "已有证据摘录。"
    linked = _evidence("e-linked", "v-linked", linked_excerpt)
    source = _source("v-linked", "https://example.org/linked")
    defaults = dict(
        request=InvestigationRequest(question="某品牌广告争议"),
        subject="某品牌广告争议",
        cutoff=utcnow(),
        issues=issues,
        sources=(source,),
        evidence=(linked,),
    )
    defaults.update(extra)
    return State(**defaults)


def _close_all_issues(state: State, status: str = "answered") -> State:
    issues = tuple(
        issue.model_copy(update={"status": status, "note": "已处置"})
        for issue in state.issues
    )
    return state.model_copy(update={"issues": issues})


def test_open_question_rejection_names_undisposed_evidence() -> None:
    issue_id = uid("issue", "品牌方如何回应")
    undisposed_excerpt = "品牌方在官方微博发布声明回应广告争议。"
    state = _state(
        sources=(
            _source("v-linked", "https://example.org/linked"),
            _source("v-new", "https://example.org/response"),
        ),
        evidence=(
            _evidence("e-linked", "v-linked", "已有证据摘录。"),
            _evidence("e-new", "v-new", undisposed_excerpt),
        ),
        candidates=(
            {
                "url": "https://example.org/response",
                "title": "回应报道",
                "snippet": "摘要",
                "issue_id": issue_id,
            },
        ),
        read_attempts=("https://example.org/response",),
    )

    verdict = completion(state)

    assert verdict.disposition is CompletionDisposition.REJECT_AND_CONTINUE
    assert "e-new" in verdict.reason
    assert "Reflect" in verdict.reason


def test_open_question_rejection_names_unread_candidates() -> None:
    issue_id = uid("issue", "品牌方如何回应")
    state = _state(
        candidates=(
            {
                "url": "https://example.org/unread",
                "title": "未读报道",
                "snippet": "摘要",
                "issue_id": issue_id,
            },
        ),
    )

    verdict = completion(state)

    assert verdict.disposition is CompletionDisposition.REJECT_AND_CONTINUE
    assert "unread" in verdict.reason
    assert "https://example.org/unread" in verdict.reason


def test_open_question_without_material_names_honest_exits() -> None:
    verdict = completion(_state())

    assert verdict.disposition is CompletionDisposition.REJECT_AND_CONTINUE
    assert "not_found" in verdict.reason
    assert "unavailable" in verdict.reason


def test_stale_not_found_finding_blocks_finish() -> None:
    issue_id = uid("issue", "品牌方如何回应")
    stale = _finding(
        "f-stale",
        issue_id,
        "品牌方尚未公开回应广告争议。",
        response="not_found",
    )
    state = _close_all_issues(
        _state(
            sources=(
                _source("v-linked", "https://example.org/linked"),
                _source("v-new", "https://example.org/response"),
            ),
            evidence=(
                _evidence("e-linked", "v-linked", "已有证据摘录。"),
                _evidence("e-new", "v-new", "品牌方发布声明回应广告争议，宣布撤下相关物料。"),
            ),
            findings=(stale,),
        )
    )

    verdict = completion(state)

    assert verdict.disposition is CompletionDisposition.REJECT_AND_CONTINUE
    assert "f-stale" in verdict.reason
    assert "e-new" in verdict.reason


def test_stale_check_accepts_disposed_evidence() -> None:
    issue_id = uid("issue", "品牌方如何回应")
    stale = _finding(
        "f-stale",
        issue_id,
        "品牌方尚未公开回应广告争议。",
        response="not_found",
    )
    # A second finding already cites the response-bearing evidence: it is
    # disposed, so the stale check must stay silent.
    other = _finding(
        "f-other",
        issue_id,
        "品牌方发布声明回应广告争议。",
        evidence_ids=("e-linked", "e-new"),
    )
    state = _close_all_issues(
        _state(
            sources=(
                _source("v-linked", "https://example.org/linked"),
                _source("v-new", "https://example.org/response"),
            ),
            evidence=(
                _evidence("e-linked", "v-linked", "已有证据摘录。"),
                _evidence("e-new", "v-new", "品牌方发布声明回应广告争议，宣布撤下相关物料。"),
            ),
            findings=(stale, other),
        )
    )

    verdict = completion(state)

    assert verdict.disposition is not CompletionDisposition.REJECT_AND_CONTINUE


def test_stale_check_requires_topical_overlap() -> None:
    issue_id = uid("issue", "品牌方如何回应")
    stale = _finding(
        "f-stale",
        issue_id,
        "品牌方尚未公开回应广告争议。",
        response="not_found",
    )
    # Response-bearing evidence about an unrelated company must not trip the
    # gate for this finding.
    state = _close_all_issues(
        _state(
            sources=(
                _source("v-linked", "https://example.org/linked"),
                _source("v-new", "https://example.org/other"),
            ),
            evidence=(
                _evidence("e-linked", "v-linked", "已有证据摘录。"),
                _evidence("e-new", "v-new", "另一家无关企业发布公告回应产品质量问题。"),
            ),
            findings=(stale,),
        )
    )

    verdict = completion(state)

    assert verdict.disposition is not CompletionDisposition.REJECT_AND_CONTINUE


def test_negative_existence_wording_triggers_without_response_field() -> None:
    issue_id = uid("issue", "品牌方如何回应")
    stale = _finding("f-stale", issue_id, "截至发稿未见品牌方公开表态。")
    state = _close_all_issues(
        _state(
            sources=(
                _source("v-linked", "https://example.org/linked"),
                _source("v-new", "https://example.org/response"),
            ),
            evidence=(
                _evidence("e-linked", "v-linked", "已有证据摘录。"),
                _evidence("e-new", "v-new", "品牌方通过官方账号发文表态并致歉。"),
            ),
            findings=(stale,),
        )
    )

    verdict = completion(state)

    assert verdict.disposition is CompletionDisposition.REJECT_AND_CONTINUE
    assert "f-stale" in verdict.reason
