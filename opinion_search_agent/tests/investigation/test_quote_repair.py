"""A finding must be able to show the sentence it puts in quotation marks."""

from __future__ import annotations

import asyncio
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from opinion_search.domain.investigation.engine import reduce_state
from opinion_search.domain.investigation.models import (
    Delta, Evidence, FindingProposal, InvestigationRequest, Issue, ReflectDecision, SourceVersion, State,
    finding_identifier, utcnow,
)
from opinion_search.investigation.service import Executor
from opinion_search.investigation.storage import Corpus

DOCUMENT = (
    "开头是一段与引语无关的背景介绍。\n\n"
    "评论写道：“反常规就会从记忆点变成冒犯点”，品牌本想成为嘴替。\n\n"
    "结尾同样无关。"
)
QUOTE = "反常规就会从记忆点变成冒犯点"


def _fixture(tmp_path: Path):
    corpus = Corpus(tmp_path)
    ref = asyncio.run(corpus.artifacts.put_text(DOCUMENT))
    source = SourceVersion(
        version_id="v1", url="https://example.org/commentary", final_url="https://example.org/commentary",
        title="评论", fetched_at=utcnow(), artifact_ref=ref,
        content_hash=sha256(DOCUMENT.encode()).hexdigest(),
    )
    # The excerpt the selector kept stops before the sentence the finding quotes.
    evidence = Evidence(evidence_id="e1", version_id="v1", excerpt="开头是一段与引语无关的背景介绍。",
                        start=0, end=16, locator="Reader text chars 0:16")
    state = State(
        request=InvestigationRequest(question="广告文案为何引发争议"),
        subject="广告争议", cutoff=utcnow(), required_questions=("争议是什么",),
        sources=(source,), evidence=(evidence,),
        issues=(
            Issue(issue_id="i1", question="争议是什么", required=True,
                  origin_questions=("争议是什么",)),
            Issue(issue_id="i2", question="各方如何回应"),
            Issue(issue_id="i3", question="后续进展如何"),
        ),
    )
    proposal = FindingProposal(issue_id="i1", text=f"有评论认为“{QUOTE}”。", kind="attributed",
                               stakeholder="评论作者", evidence_ids=("e1",))
    decision = ReflectDecision(findings=(proposal,), reason="记录反方观点")
    executor = Executor(tool_executor=None, checkpoint=SimpleNamespace(path=tmp_path / "run.json"),
                        corpus=corpus, reviewer=None, model_name="test")
    return state, proposal, decision, executor


def test_record_findings_recovers_the_quoted_span_from_the_saved_document(tmp_path: Path):
    state, _, decision, executor = _fixture(tmp_path)
    observation = asyncio.run(executor._record_findings(decision, state))

    assert len(observation.evidence) == 1
    recovered = observation.evidence[0]
    assert recovered.excerpt == QUOTE
    assert DOCUMENT[recovered.start:recovered.end] == QUOTE
    assert observation.finding_evidence[0].evidence_ids == (recovered.evidence_id,)
    assert observation.finding_evidence[0].finding_id == finding_identifier(decision.findings[0])


def test_reducer_binds_recovered_evidence_onto_the_finding(tmp_path: Path):
    state, proposal, decision, executor = _fixture(tmp_path)
    observation = asyncio.run(executor._record_findings(decision, state))

    updated = reduce_state(state, Delta(decision=decision, observation=observation))

    finding = next(item for item in updated.findings if item.finding_id == finding_identifier(proposal))
    assert "e1" in finding.evidence_ids
    assert observation.evidence[0].evidence_id in finding.evidence_ids
    assert any(item.excerpt == QUOTE for item in updated.evidence)


def test_record_findings_stays_quiet_when_the_quote_is_already_in_the_excerpt(tmp_path: Path):
    state, _, decision, executor = _fixture(tmp_path)
    covered = Evidence(evidence_id="e2", version_id="v1", excerpt=QUOTE,
                       start=DOCUMENT.index(QUOTE), end=DOCUMENT.index(QUOTE) + len(QUOTE),
                       locator="Reader text chars x:y")
    state = state.model_copy(update={"evidence": (*state.evidence, covered)})
    decision = decision.model_copy(update={"findings": (
        decision.findings[0].model_copy(update={"evidence_ids": ("e1", "e2")}),)})

    observation = asyncio.run(executor._record_findings(decision, state))

    assert observation.evidence == ()
    assert observation.finding_evidence == ()


def test_record_findings_binds_a_supporting_sentence_when_specifics_are_missing(tmp_path):
    """A number the excerpts never covered should pull in the sentence that has it."""

    state, _, decision, executor = _fixture(tmp_path)
    proposal = decision.findings[0].model_copy(
        update={"text": "评论认为反常规会变成冒犯点，并提到 2026 年的案例。"}
    )
    decision = decision.model_copy(update={"findings": (proposal,)})

    observation = asyncio.run(executor._record_findings(decision, state))

    assert observation.evidence, "a supporting span should have been bound"
    span = observation.evidence[0]
    assert DOCUMENT[span.start:span.end] == span.excerpt
    assert span.excerpt in DOCUMENT
