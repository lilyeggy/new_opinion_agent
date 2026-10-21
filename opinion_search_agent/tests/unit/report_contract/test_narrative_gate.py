"""The summary may only say what reviewed findings can back."""

from __future__ import annotations

from opinion_search.report_contract.contracts import (
    NarrativeClause, NarrativeParagraph, NarrativeSection,
)
from opinion_search.report_contract.narrative import filter_narrative, unsupported_tokens

FINDINGS = {
    "f-supported": {"evidence_ids": ["e1"], "review": {"verdict": "supported"}},
    "f-partial": {"evidence_ids": ["e2"], "review": {"verdict": "partial"}},
}
EVIDENCE = {
    "e1": {"excerpt": "9月12日罗永浩发文称“很一般”，门店回应客流正常。"},
    "e2": {"excerpt": "另一份材料"},
}
APPROVED = {"f-supported"}


def _section(*clauses: NarrativeClause, headline: str = "", headline_ids=()) -> NarrativeSection:
    return NarrativeSection(
        headline=headline, headline_finding_ids=headline_ids,
        paragraphs=(NarrativeParagraph(role="定性", clauses=clauses),),
    )


def test_supported_clause_survives():
    clean, dropped = filter_narrative(
        _section(NarrativeClause(text="争议始于 9月12日 的一条吐槽。", finding_ids=("f-supported",))),
        FINDINGS, EVIDENCE, APPROVED,
    )
    assert clean is not None
    assert len(clean.paragraphs[0].clauses) == 1
    assert dropped == []


def test_clause_without_a_reviewed_finding_is_dropped():
    clean, dropped = filter_narrative(
        _section(NarrativeClause(text="没有绑定判断的句子。", finding_ids=())),
        FINDINGS, EVIDENCE, APPROVED,
    )
    assert clean is None
    assert dropped[0]["reason"] == "no_reviewed_finding"


def test_clause_bound_to_an_unreviewed_finding_is_dropped():
    clean, dropped = filter_narrative(
        _section(NarrativeClause(text="这条判断只部分支持。", finding_ids=("f-partial",))),
        FINDINGS, EVIDENCE, APPROVED,
    )
    assert clean is None
    assert dropped[0]["reason"] == "no_reviewed_finding"


def test_clause_with_an_unbacked_number_is_dropped():
    clean, dropped = filter_narrative(
        _section(NarrativeClause(text="品牌方在 9月16日 才首次公开回应。", finding_ids=("f-supported",))),
        FINDINGS, EVIDENCE, APPROVED,
    )
    assert clean is None
    assert dropped[0]["reason"] == "unsupported_specifics"
    assert "9月16日" in dropped[0]["tokens"]


def test_clause_with_an_unbacked_quote_is_dropped():
    clean, dropped = filter_narrative(
        _section(NarrativeClause(text="品牌方称“完全是误会”。", finding_ids=("f-supported",))),
        FINDINGS, EVIDENCE, APPROVED,
    )
    assert clean is None
    assert dropped[0]["reason"] == "unsupported_specifics"


def test_a_partly_supported_paragraph_keeps_only_the_backed_clauses():
    clean, dropped = filter_narrative(
        _section(
            NarrativeClause(text="争议始于 9月12日 的一条吐槽。", finding_ids=("f-supported",)),
            NarrativeClause(text="品牌方在 9月16日 才回应。", finding_ids=("f-supported",)),
        ),
        FINDINGS, EVIDENCE, APPROVED,
    )
    assert clean is not None
    assert [c.text for c in clean.paragraphs[0].clauses] == ["争议始于 9月12日 的一条吐槽。"]
    assert len(dropped) == 1


def test_unsupported_tokens_ignores_text_that_is_fully_present():
    support = "9月12日罗永浩发文称“很一般”"
    assert unsupported_tokens("9月12日 罗永浩发文称“很一般”", support) == []


def test_no_narrative_means_no_work():
    clean, dropped = filter_narrative(None, FINDINGS, EVIDENCE, APPROVED)
    assert clean is None and dropped == []
