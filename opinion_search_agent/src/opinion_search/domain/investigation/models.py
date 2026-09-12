from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opinion_search.app.contracts import SearchRequest
from opinion_search.runtime.completion import CompletionVerdict
from opinion_search.tools.contracts import ToolOutcome

Text = Annotated[str, Field(min_length=1)]


def uid(prefix: str, *values: str) -> str:
    return prefix + "-" + sha256("\x1f".join(values).encode()).hexdigest()[:20]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class InvestigationRequest(SearchRequest):
    region: str | None = None
    reference_urls: tuple[str, ...] = ()
    clarification: str | None = None


class QuestionProposal(Record):
    question: Text
    required: bool = True
    covers: tuple[Text, ...] = ()


FACET_NAMES = ("rule_change", "service_change", "billing_remedy", "investigation_correction", "general")
Facet = Literal["rule_change", "service_change", "billing_remedy", "investigation_correction", "general"]


class EventProfile(Record):
    """Composable event facets proposed by the model, confirmed by the program.

    Facets are product content policy, not agent types: they only decide which
    whitelisted modules a workbench page highlights. Unknown values are dropped
    by the confirmation step; they never widen the module whitelist.
    """

    facets: tuple[Facet, ...] = ("general",)
    rationale: str = ""
    question_refs: tuple[Text, ...] = ()
    config_version: str = "workbench-modules-1"


class PlanProposal(Record):
    subject: Text
    region: str | None = None
    aliases: tuple[str, ...] = ()
    clarification: tuple[Text, ...] = ()
    questions: tuple[QuestionProposal, ...] = Field(default=(), max_length=6)
    facets: tuple[str, ...] = ()
    facet_rationale: str = ""

    @model_validator(mode="after")
    def complete_or_clarify(self):
        if not self.clarification and not 3 <= len(self.questions) <= 6:
            raise ValueError("a ready plan requires 3 to 6 questions")
        return self


class Issue(Record):
    issue_id: Text
    question: Text
    required: bool = True
    status: Literal["open", "answered", "disputed", "not_found", "unavailable"] = "open"
    note: str = ""
    evidence_ids: tuple[str, ...] = ()
    origin_questions: tuple[Text, ...] = ()


class SourceVersion(Record):
    version_id: Text
    url: Text
    final_url: Text
    title: Text
    fetched_at: datetime
    published_at: datetime | None = None
    updated_at: datetime | None = None
    artifact_ref: Text
    content_hash: Text
    role: Literal["original", "reporting", "commentary", "unknown"] = "unknown"
    duplicate_of: str | None = None
    origin_url: str | None = None


class Evidence(Record):
    evidence_id: Text
    version_id: Text
    excerpt: Text
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    locator: Text


class FindingProposal(Record):
    issue_id: Text
    text: Text
    kind: Literal["fact", "attributed", "interpretation", "request"]
    stakeholder: str = ""
    stance: Literal["support", "oppose", "conditional", "unclear"] = "unclear"
    stance_target: str = ""
    evidence_ids: tuple[Text, ...] = Field(min_length=1)
    contradicting_ids: tuple[Text, ...] = ()
    event_time: str | None = None
    response: Literal["direct", "partial", "non_substantive", "not_found", "unknown"] | None = None
    response_target: str = ""
    covered: tuple[Text, ...] = ()
    uncovered: tuple[Text, ...] = ()
    coverage_reason: str = ""


class Finding(FindingProposal):
    finding_id: Text
    active: bool = True


class Retirement(Record):
    finding_id: Text
    reason: Text


class IssueAssessment(Record):
    issue_id: Text
    status: Literal["open", "answered", "disputed", "not_found", "unavailable"]
    reason: Text
    evidence_ids: tuple[str, ...] = ()


class SearchDecision(Record):
    action: Literal["search"] = "search"
    issue_id: Text
    query: Text
    purpose: Literal["original", "positions", "independent", "official_response", "event_response", "followup"]
    page: int = Field(default=0, ge=0, le=2)
    background: bool = False
    # Which known gap this query is meant to close; empty for base discovery.
    target_gap: str = ""


class ReadDecision(Record):
    action: Literal["read"] = "read"
    issue_id: Text
    url: Text
    focus: Text
    role: Literal["original", "reporting", "commentary", "unknown"] = "unknown"


class RetrieveDecision(Record):
    action: Literal["retrieve"] = "retrieve"
    issue_id: Text
    query: Text
    version_id: str | None = None


class ReflectDecision(Record):
    action: Literal["reflect"] = "reflect"
    findings: tuple[FindingProposal, ...] = ()
    assessments: tuple[IssueAssessment, ...] = ()
    add_questions: tuple[QuestionProposal, ...] = ()
    retirements: tuple[Retirement, ...] = ()
    reason: Text


class ReviewDecision(Record):
    action: Literal["review"] = "review"
    finding_ids: tuple[Text, ...] = Field(min_length=1, max_length=8)


class FinishDecision(Record):
    action: Literal["finish"] = "finish"
    conclusion_ids: tuple[str, ...] = Field(default=(), max_length=8)


Decision = Annotated[SearchDecision | ReadDecision | RetrieveDecision | ReflectDecision | ReviewDecision | FinishDecision, Field(discriminator="action")]


class ReviewItem(Record):
    finding_id: Text
    verdict: Literal["supported", "partial", "contradicted", "insufficient"]
    reason: Text


class ReviewResult(Record):
    items: tuple[ReviewItem, ...]


class ReviewRecord(ReviewItem):
    finding_hash: Text
    model: Text
    reviewed_at: datetime


class RetiredFinding(Record):
    finding_id: Text
    reason: Text
    retired_at: datetime


class SourceCheck(Record):
    """One bounded re-inspection of a URL inside a run, for update provenance."""

    url: Text
    version_id: Text
    checked_at: datetime
    changed: bool = False


class SearchAttempt(Record):
    issue_id: Text
    query: Text
    purpose: str
    page: int
    outcome: Literal["candidates", "empty", "filtered", "duplicate", "error"]
    count: int = 0
    # Coverage record: program-maintained identity of the search task, the gap
    # it addressed and the discovery mode that produced it.
    task_id: Text = ""
    target_gap: str = ""
    discovery_mode: Literal["discovery", "targeted", "user_provided"] = "discovery"


class State(Record):
    schema_version: Literal[2] = 2
    request: InvestigationRequest
    subject: Text
    aliases: tuple[str, ...] = ()
    cutoff: datetime
    required_questions: tuple[Text, ...] = ()
    issues: tuple[Issue, ...] = Field(min_length=3, max_length=8)
    candidates: tuple[dict, ...] = ()
    sources: tuple[SourceVersion, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    findings: tuple[Finding, ...] = ()
    retired: tuple[RetiredFinding, ...] = ()
    checks: tuple[SourceCheck, ...] = ()
    reviews: tuple[ReviewRecord, ...] = ()
    searches: tuple[SearchAttempt, ...] = ()
    read_attempts: tuple[str, ...] = ()
    read_errors: tuple[str, ...] = ()
    history: tuple[str, ...] = ()
    conclusion_ids: tuple[str, ...] = ()
    profile: EventProfile | None = None
    revision: int = 0

    @model_validator(mode="after")
    def references(self):
        for values, key in ((self.issues, "issue_id"), (self.sources, "version_id"), (self.evidence, "evidence_id"), (self.findings, "finding_id")):
            ids = [getattr(x, key) for x in values]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {key}")
        issues = {x.issue_id for x in self.issues}
        sources = {x.version_id for x in self.sources}
        evidence = {x.evidence_id for x in self.evidence}
        findings = {x.finding_id for x in self.findings}
        if any(x.version_id not in sources or x.end - x.start != len(x.excerpt) for x in self.evidence):
            raise ValueError("evidence identity or locator mismatch")
        for x in self.findings:
            if x.issue_id not in issues or not set(x.evidence_ids + x.contradicting_ids) <= evidence:
                raise ValueError("finding references unknown issue or evidence")
        if any(not set(x.evidence_ids) <= evidence for x in self.issues):
            raise ValueError("issue references unknown evidence")
        if any(x.finding_id not in findings for x in self.reviews) or not set(self.conclusion_ids) <= findings:
            raise ValueError("unknown reviewed or concluded finding")
        if any(x.finding_id not in findings for x in self.retired):
            raise ValueError("unknown retired finding")
        covered = {text for issue in self.issues for text in issue.origin_questions}
        if not set(self.required_questions) <= covered:
            raise ValueError("a user question was dropped from the investigation plan")
        if self.profile is not None and not set(self.profile.question_refs) <= issues:
            raise ValueError("profile references an unknown issue")
        return self


class Action(Record):
    decision: Decision
    tool_name: str | None = None
    arguments: dict = Field(default_factory=dict)
    review_context: str | None = None
    verdict: CompletionVerdict | None = None


class Observation(Record):
    action: str
    outcome: ToolOutcome | None = None
    sources: tuple[SourceVersion, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    reviews: tuple[ReviewRecord, ...] = ()
    check: SourceCheck | None = None
    verdict: CompletionVerdict | None = None


class Delta(Record):
    decision: Decision
    observation: Observation


def finding_hash(finding: Finding) -> str:
    return uid("finding-version", finding.model_dump_json())


def accepted_review(state: State, finding: Finding) -> ReviewRecord | None:
    return next((r for r in reversed(state.reviews) if r.finding_id == finding.finding_id and r.finding_hash == finding_hash(finding)), None)
