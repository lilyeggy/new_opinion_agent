from __future__ import annotations

from datetime import date
from urllib.parse import urlsplit
import json

from opinion_search.domain.investigation.models import (
    Action, Delta, Evidence, Finding, FinishDecision, Issue, Observation,
    ReadDecision, ReflectDecision, RetiredFinding, RetrieveDecision, ReviewDecision,
    SearchAttempt, SearchDecision, State, accepted_review, uid, utcnow,
)
from opinion_search.domain.opinion.framing import build_task_frame
from opinion_search.runtime.completion import CompletionDisposition as Disposition, CompletionVerdict
from opinion_search.tools.contracts import ToolError
from opinion_search.tools.url import normalize_public_url


SOCIAL_DOMAINS = ("weibo.com", "weibo.cn", "douyin.com", "xiaohongshu.com", "xhslink.com", "tiktok.com", "twitter.com", "x.com", "facebook.com", "instagram.com", "douban.com", "zhihu.com", "bilibili.com", "mp.weixin.qq.com", "tieba.baidu.com", "kuaishou.com", "reddit.com")
RESPONSE_PURPOSES = {"official_response", "event_response", "followup"}


def matches(host: str, domain: str):
    return host == domain or host.endswith("." + domain)


def allowed_url(url: str, state: State) -> bool:
    try:
        normalized = normalize_public_url(url)
    except (ValueError, UnicodeError):
        return False
    host = urlsplit(normalized).hostname or ""
    excluded = (*SOCIAL_DOMAINS, *state.request.exclude_domains)
    return not any(matches(host, d) for d in excluded) and (not state.request.include_domains or any(matches(host, d) for d in state.request.include_domains))


def response_search_complete(state, issue_id):
    """A 'no response found' claim needs scoped, substantive, finished searching."""

    attempts = [x for x in state.searches if x.issue_id == issue_id and x.purpose in RESPONSE_PURPOSES]
    covered = {x.purpose for x in attempts if x.outcome in {"candidates", "empty"}}
    if not RESPONSE_PURPOSES <= covered or state.read_errors:
        return False
    unread = [c for c in state.candidates
              if c.get("issue_id") == issue_id and c["url"] not in state.read_attempts and allowed_url(c["url"], state)]
    return not unread


class Validator:
    def validate(self, state: State, decision):
        issues = {x.issue_id: x for x in state.issues}
        evidence = {x.evidence_id for x in state.evidence}
        findings = {x.finding_id: x for x in state.findings}
        issue_id = getattr(decision, "issue_id", None)
        if issue_id is not None and issue_id not in issues:
            raise ValueError("unknown investigation question")
        if isinstance(decision, SearchDecision):
            if any((x.issue_id, x.query.casefold(), x.page) == (decision.issue_id, decision.query.casefold(), decision.page) for x in state.searches):
                raise ValueError("query/page already attempted; change the search direction")
        elif isinstance(decision, ReadDecision):
            if decision.url in state.read_attempts:
                raise ValueError("use retrieve to revisit a page already fetched in this version")
            candidate_urls = {x["url"] for x in state.candidates}

            def _canon(value: str) -> str:
                try:
                    value = normalize_public_url(value)
                except (ValueError, UnicodeError):
                    pass
                return value.rstrip("/")

            matched = decision.url in candidate_urls or _canon(decision.url) in {_canon(u) for u in candidate_urls}
            if not matched:
                # The model may reformat a known url (scheme case, trailing
                # slash) or reach for a link it saw on a page; name the rule
                # and point at legal candidates so the retry can recover.
                unread = [x["url"] for x in state.candidates if x["url"] not in state.read_attempts]
                hint = " | ".join(unread[:3]) if unread else "run search first"
                raise ValueError(f"read url is not a discovered candidate; copy a candidate url exactly ({hint})")
            if not allowed_url(decision.url, state):
                raise ValueError("read url is outside the allowed public source domains")
        elif isinstance(decision, RetrieveDecision):
            if decision.version_id and decision.version_id not in {x.version_id for x in state.sources}:
                raise ValueError("unknown source version")
        elif isinstance(decision, ReflectDecision):
            if len(state.issues) + len(decision.add_questions) > 8:
                raise ValueError("at most eight questions; preserve existing required questions")
            retired_ids = [x.finding_id for x in decision.retirements]
            if len(set(retired_ids)) != len(retired_ids) or not set(retired_ids) <= set(findings):
                raise ValueError("unknown or duplicate retired finding")
            if len({x.issue_id for x in decision.assessments}) != len(decision.assessments):
                raise ValueError("duplicate question assessments")
            for item in (*decision.findings, *decision.assessments):
                if item.issue_id not in issues or not set(item.evidence_ids) <= evidence:
                    raise ValueError("unknown issue or evidence reference")
            for item in decision.findings:
                if not set(item.contradicting_ids) <= evidence or set(item.evidence_ids) & set(item.contradicting_ids):
                    raise ValueError("invalid contradiction evidence")
                if item.kind == "attributed" and not item.stakeholder:
                    raise ValueError("attributed claims require an identified speaker")
                if item.stance != "unclear" and not item.stance_target:
                    raise ValueError("stance requires a specific target")
                if item.response == "not_found" and not response_search_complete(state, item.issue_id):
                    raise ValueError("missing-response assessment requires successful scoped response searches")
                if item.response in {"direct", "partial", "non_substantive"} and not item.coverage_reason:
                    raise ValueError("set 'coverage_reason' to the concrete basis for this response judgement")
                if item.response == "direct" and item.uncovered:
                    raise ValueError("response='direct' answers every part, so 'uncovered' must be empty")
                if item.response == "partial" and not item.uncovered:
                    raise ValueError(
                        "response='partial' must list the unanswered parts in 'uncovered', "
                        "or set response to 'direct'/'non_substantive' instead"
                    )
            for assessment in decision.assessments:
                if assessment.status in {"answered", "disputed"} and not assessment.evidence_ids:
                    raise ValueError("answered questions require evidence")
                if assessment.status == "not_found" and not response_search_complete(state, assessment.issue_id):
                    raise ValueError("not_found requires a completed scoped search; use unavailable")
        elif isinstance(decision, ReviewDecision):
            if len(set(decision.finding_ids)) != len(decision.finding_ids) or not set(decision.finding_ids) <= set(findings):
                raise ValueError("review requires distinct known finding IDs")
        elif isinstance(decision, FinishDecision):
            if not set(decision.conclusion_ids) <= set(findings):
                raise ValueError("unknown conclusion")
            for identifier in decision.conclusion_ids:
                item = findings[identifier]
                review = accepted_review(state, item)
                if not item.active or review is None or review.verdict != "supported":
                    raise ValueError("core conclusions must be active and supported by a current review")


def completion(state: State):
    if any(x.required and x.status == "open" for x in state.issues):
        return CompletionVerdict(disposition=Disposition.REJECT_AND_CONTINUE, reason="Required investigation questions remain open.")
    active = [x for x in state.findings if x.active]
    problems = [x for x in state.issues if x.required and x.status == "unavailable"]
    unreviewed = [x for x in active if (r := accepted_review(state, x)) is None or r.verdict != "supported"]
    answered_without_findings = [q for q in state.issues if q.status in {"answered", "disputed"} and not any(f.issue_id == q.issue_id for f in active)]
    if not active or not state.evidence or problems or unreviewed or answered_without_findings:
        return CompletionVerdict(disposition=Disposition.ACCEPT_PARTIAL, reason="Material or review limitations remain; inspect the issue-level caveats.")
    return CompletionVerdict(disposition=Disposition.ACCEPT_COMPLETE, reason="Required questions have explicit dispositions and active findings passed evidence review; this is not a truth guarantee.")


class Resolver:
    def resolve(self, state: State, decision):
        if isinstance(decision, SearchDecision):
            scope = build_task_frame(state.request, anchor_date=state.cutoff.date()).temporal_scope
            core = decision.query
            if state.request.include_domains:
                core += " (" + " OR ".join("site:" + d for d in state.request.include_domains) + ")"
            exclusions = tuple(dict.fromkeys((*SOCIAL_DOMAINS[:6], *state.request.exclude_domains)))
            suffix = " " + " ".join("-site:" + d for d in exclusions)
            query = core + suffix if len(core + suffix) <= 600 else core
            if len(query) > 600:
                raise ValueError("search query is too long; split the request into bounded queries")
            return Action(decision=decision, tool_name="search.web", arguments={
                "query": query, "max_results": 10, "offset": decision.page,
                "search_lang": "zh-hans" if state.request.language.startswith("zh") else "en",
                "freshness": f"{scope.start_date}to{scope.end_date}" if scope.is_bounded and not decision.background else None,
            })
        if isinstance(decision, ReadDecision):
            return Action(decision=decision, tool_name="read.web", arguments={"url": decision.url})
        if isinstance(decision, ReviewDecision):
            findings = [x for x in state.findings if x.finding_id in decision.finding_ids]
            ids = {i for x in findings for i in x.evidence_ids + x.contradicting_ids}
            ev = [x for x in state.evidence if x.evidence_id in ids]
            version_ids = {x.version_id for x in ev}
            context = {"findings": [x.model_dump(mode="json") for x in findings], "evidence": [x.model_dump(mode="json") for x in ev], "sources": [x.model_dump(mode="json") for x in state.sources if x.version_id in version_ids], "issues": [x.model_dump(mode="json") for x in state.issues if x.issue_id in {f.issue_id for f in findings}]}
            return Action(decision=decision, review_context=json.dumps(context, ensure_ascii=False))
        if isinstance(decision, FinishDecision):
            return Action(decision=decision, verdict=completion(state))
        return Action(decision=decision)


class Processor:
    def build_delta(self, state, decision, observation):
        if observation.action != decision.action:
            raise ValueError("observation action mismatch")
        return Delta(decision=decision, observation=observation)


def merge(existing, additions, key):
    values = {getattr(x, key): x for x in existing}
    for item in additions:
        identifier = getattr(item, key)
        if identifier in values and values[identifier] != item:
            raise ValueError(f"immutable {key} conflict")
        values[identifier] = item
    return tuple(values.values())


def reduce_state(state: State, delta: Delta):
    d, o = delta.decision, delta.observation
    changes = {}
    if isinstance(d, SearchDecision):
        error = isinstance(o.outcome, ToolError)
        items = [] if error or o.outcome is None else o.outcome.payload.get("items", [])
        candidates = {x["url"]: x for x in state.candidates}
        allowed = [x for x in items if allowed_url(x["url"], state)]
        added = 0
        for item in allowed:
            normalized = normalize_public_url(item["url"])
            if normalized not in candidates:
                candidates[normalized] = {**item, "url": normalized, "issue_id": d.issue_id}
                added += 1
        outcome = "error" if error else "empty" if not items else "filtered" if not allowed else "duplicate" if not added else "candidates"
        changes.update(candidates=tuple(candidates.values()), searches=state.searches + (SearchAttempt(
            issue_id=d.issue_id, query=d.query, purpose=d.purpose, page=d.page, outcome=outcome, count=added,
            task_id=uid("search-task", d.issue_id, d.query, str(d.page)),
            target_gap=d.target_gap, discovery_mode="targeted" if d.target_gap else "discovery"),))
    if isinstance(d, ReadDecision):
        changes["read_attempts"] = (*state.read_attempts, d.url)
        if isinstance(o.outcome, ToolError):
            changes["read_errors"] = (*state.read_errors, d.url)
    if o.sources:
        additions = []
        for source in o.sources:
            duplicate = next((s for s in state.sources if s.content_hash == source.content_hash and s.version_id != source.version_id), None)
            additions.append(source.model_copy(update={"duplicate_of": duplicate.version_id if duplicate else None}))
        changes["sources"] = merge(state.sources, additions, "version_id")
    if o.check is not None:
        changes["checks"] = (*state.checks, o.check)
    if o.evidence:
        changes["evidence"] = merge(state.evidence, o.evidence, "evidence_id")
    if isinstance(d, ReflectDecision):
        retired_ids = {x.finding_id for x in d.retirements}
        findings = [f.model_copy(update={"active": False}) if f.finding_id in retired_ids else f for f in state.findings]
        for proposal in d.findings:
            identifier = uid("finding", proposal.issue_id, proposal.model_dump_json())
            item = Finding(**proposal.model_dump(), finding_id=identifier)
            findings = [f for f in findings if f.finding_id != identifier] + [item]
        issues = {x.issue_id: x for x in state.issues}
        for item in d.assessments:
            issues[item.issue_id] = issues[item.issue_id].model_copy(update={"status": item.status, "note": item.reason, "evidence_ids": item.evidence_ids})
        for item in d.add_questions:
            identifier = uid("issue", item.question)
            if identifier not in issues:
                issues[identifier] = Issue(issue_id=identifier, question=item.question, required=item.required, origin_questions=item.covers)
        retired = state.retired
        for item in d.retirements:
            if not any(x.finding_id == item.finding_id for x in retired):
                retired = (*retired, RetiredFinding(finding_id=item.finding_id, reason=item.reason, retired_at=utcnow()))
        changes.update(findings=tuple(findings), issues=tuple(issues.values()), retired=retired, history=(*state.history, d.reason))
    if o.reviews:
        changes["reviews"] = (*state.reviews, *o.reviews)
    if isinstance(d, FinishDecision) and o.verdict and o.verdict.disposition != Disposition.REJECT_AND_CONTINUE:
        changes["conclusion_ids"] = d.conclusion_ids
    return State.model_validate({**state.model_dump(), **changes, "revision": state.revision + 1})


class CompletionEvaluator:
    def evaluate(self, state, decision, observation):
        return observation.verdict if isinstance(decision, FinishDecision) else None
