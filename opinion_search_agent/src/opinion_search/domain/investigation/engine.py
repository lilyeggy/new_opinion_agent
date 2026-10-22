from __future__ import annotations

from urllib.parse import urlsplit
import json
import re

from opinion_search.domain.investigation.models import (
    Action, Delta, Evidence, FACET_MODULE_TYPES, Finding, FinishDecision, Issue, finding_identifier,
    QuestionComponent, ReadDecision, ReflectDecision, RetiredFinding, RetrieveDecision, ReviewDecision,
    SearchAttempt, SearchDecision, SourceRelation, State, accepted_review, uid, utcnow,
)
from opinion_search.domain.opinion.framing import build_task_frame
from opinion_search.investigation.page_plan import required_module_gaps
from opinion_search.runtime.completion import CompletionDisposition as Disposition, CompletionVerdict
from opinion_search.tools.contracts import ToolError
from opinion_search.tools.url import normalize_public_url


SOCIAL_DOMAINS = ("weibo.com", "weibo.cn", "douyin.com", "xiaohongshu.com", "xhslink.com", "tiktok.com", "twitter.com", "x.com", "facebook.com", "instagram.com", "douban.com", "zhihu.com", "bilibili.com", "mp.weixin.qq.com", "tieba.baidu.com", "kuaishou.com", "reddit.com")
RESPONSE_PURPOSES = {"official_response", "event_response", "followup"}
FIRST_REFLECTION_SOURCE_LIMIT = 4
FIRST_REFLECTION_DUPLICATE_STREAK = 2
# Once findings exist, acquisition may continue — but not forever. When this
# many saved excerpts remain undisposed by any finding or assessment, the
# next acquisition decision is redirected into synthesis. Measured pain: a
# 2026-09-23 live run converted only 4 of 8 read sources into findings.
ONGOING_REFLECTION_UNDISPOSED_LIMIT = 8
# A run that keeps writing findings never spends its budget on review: one
# 40-step run produced 132 findings and reviewed 8. Cap the burst and force
# review once the backlog is real.
MAX_NEW_FINDINGS_PER_REFLECT = 6
REVIEW_BACKLOG_LIMIT = 8
# A finish with open required questions must not be accepted at step one, but
# refusing it forever merely converts a bounded partial result into a step-limit
# spin. These are the minimum evidence-producing actions before a partial finish
# becomes an honest terminal outcome rather than an early abandonment.
MIN_PARTIAL_FINISH_SEARCHES = 3
MIN_PARTIAL_FINISH_READS = 3
MIN_PARTIAL_FINISH_SOURCES = 2
# A 40-step live run used roughly two model calls per committed step. Reserving
# publication work only after two thirds of the model budget therefore races the
# step limit. Start the bounded closeout at half the model-call budget instead;
# the remaining half is still large enough to review and publish the subset.
CONSOLIDATION_MODEL_CALLS_PERCENT = 50


def consolidation_model_call_limit(limit: int) -> int:
    return max(1, (limit * CONSOLIDATION_MODEL_CALLS_PERCENT + 99) // 100)

# Finish-gate guidance limits: the rejection reason must stay scannable.
_GUIDANCE_PREVIEW_ITEMS = 3
_GUIDANCE_EXCERPT_CHARS = 80

# Language markers that some party publicly responded to the event. Used by
# the finish gate to spot response-bearing evidence nobody disposed of.
_RESPONSE_MARKERS = (
    "回应", "声明", "公告", "致歉", "道歉", "表态", "通报", "发文", "官博", "官微",
    "responded", "response", "statement", "apolog",
)

# Negative-existence claims ("X 尚未回应"): the stalest judgement in a live
# investigation, because later-fetched evidence can refute them silently.
_NEGATIVE_EXISTENCE = re.compile(
    r"未(?:公开)?(?:表态|回应|发声|发布声明)|尚未(?:公开)?(?:回应|表态|发声|发布)|"
    r"没有(?:公开)?(?:回应|表态|发声)|未见[^。；，]{0,16}?(?:回应|声明|表态|发声)|"
    r"no (?:public )?(?:response|statement)|has not (?:responded|issued)",
    re.IGNORECASE,
)

_STOP_TOKENS = {
    "the", "and", "for", "that", "this", "with", "have", "has", "not", "been",
    "their", "they", "them", "from", "about", "after", "before", "response",
}

# Response/negation vocabulary appears on both sides of a stale claim by
# construction ("未回应" vs "回应了"), so it is not topical-overlap evidence.
_GENERIC_TOKENS = frozenset(
    _RESPONSE_MARKERS
    + ("公开", "尚未", "未见", "没有", "截至", "发稿", "相关", "表示", "宣布")
)


def _linked_evidence_ids(state: State) -> set[str]:
    """Evidence already disposed of by a finding, issue, or component."""
    linked: set[str] = set()
    for finding in state.findings:
        if finding.active:
            linked.update(finding.evidence_ids)
            linked.update(finding.contradicting_ids)
    for issue in state.issues:
        linked.update(issue.evidence_ids)
        for component in issue.components:
            linked.update(component.evidence_ids)
    return linked


def _undisposed_evidence(state: State) -> list[Evidence]:
    linked = _linked_evidence_ids(state)
    return [item for item in state.evidence if item.evidence_id not in linked]


def _issue_id_for_evidence(state: State) -> dict[str, str]:
    """Best-effort evidence → issue map via source url → candidate issue."""
    candidate_issue = {
        candidate.get("url"): candidate.get("issue_id")
        for candidate in state.candidates
        if candidate.get("url")
    }
    version_url = {source.version_id: source.url for source in state.sources}
    mapping: dict[str, str] = {}
    for item in state.evidence:
        url = version_url.get(item.version_id)
        issue_id = candidate_issue.get(url) if url else None
        if issue_id:
            mapping[item.evidence_id] = issue_id
    return mapping


def _content_tokens(text: str) -> set[str]:
    """Meaning-bearing tokens shared between a claim and an excerpt."""
    tokens = {
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", text)
        if token.casefold() not in _STOP_TOKENS
    }
    for sequence in re.findall(r"[一-鿿]{2,}", text):
        tokens.update(
            sequence[index : index + width]
            for width in (2, 3, 4)
            for index in range(len(sequence) - width + 1)
        )
    return tokens - _GENERIC_TOKENS


def _issue_has_read_errors(state: State, issue_id: str) -> bool:
    """Check whether read failures occurred on candidate URLs for this specific issue."""

    if not state.read_errors:
        return False
    error_set = set(state.read_errors)
    all_candidate_urls = {c.get("url") for c in state.candidates if c.get("url")}
    if not (all_candidate_urls & error_set):
        # Fallback when read_errors were populated without candidate entries
        return True
    issue_urls = {
        c.get("url")
        for c in state.candidates
        if c.get("issue_id") == issue_id and c.get("url")
    }
    return bool(issue_urls & error_set)


def _open_questions_guidance(state: State, open_required: list[Issue]) -> str:
    """Turn a bare rejection into the actionable next step for each question.

    A bare "questions remain open" rejection gave the live model no legal
    move: a 2026-09-23 live run spun on finish 29 times until the step
    limit. For every open question the gate now names what the program can
    see — undisposed evidence, unread candidates, failed reads — and the
    three legal exits: dispose saved evidence (reflect/retrieve), acquire
    more (read/search), or close the question honestly (not_found after
    scoped searches, otherwise unavailable).
    """
    undisposed = _undisposed_evidence(state)
    evidence_issue = _issue_id_for_evidence(state)
    lines = ["Required investigation questions remain open."]
    for issue in open_required:
        held = [
            item for item in undisposed
            if evidence_issue.get(item.evidence_id) == issue.issue_id
        ]
        unread = [
            candidate["url"]
            for candidate in state.candidates
            if candidate.get("issue_id") == issue.issue_id
            and candidate.get("url") not in state.read_attempts
            and allowed_url(candidate["url"], state)
        ]
        parts = [f"- {issue.issue_id} ({issue.question[:60]}):"]
        if held:
            previews = "; ".join(
                f"{item.evidence_id} «{item.excerpt[:_GUIDANCE_EXCERPT_CHARS]}»"
                for item in held[:_GUIDANCE_PREVIEW_ITEMS]
            )
            parts.append(
                f"  {len(held)} saved evidence excerpts for this question are "
                f"not disposed by any finding or assessment ({previews}). "
                "Reflect to dispose them, or retrieve the saved page with a "
                "new focus."
            )
        if unread:
            parts.append(
                f"  {len(unread)} discovered candidates remain unread "
                f"(e.g. {unread[0]}). Read one before another search."
            )
        if not held and not unread:
            can_not_found = response_search_complete(state, issue.issue_id)
            has_read_err = _issue_has_read_errors(state, issue.issue_id)
            close_hint = (
                "scoped response searches are complete for this question, so you may close it as status='not_found'"
                if can_not_found
                else (
                    "candidate reads failed for this question, so close it as status='unavailable' if no further source exists"
                    if has_read_err
                    else "not_found only after the scoped response searches complete, otherwise unavailable"
                )
            )
            parts.append(
                "  No saved evidence and no unread candidates address it. "
                "Search a different direction (new alias, origin, or material "
                f"type), or reflect to close it honestly ({close_hint})."
            )
        lines.extend(parts)
    return "\n".join(lines)


def _stale_negative_findings(
    state: State,
) -> list[tuple[Finding, list[Evidence]]]:
    """Negative-existence findings contradicted by undisposed evidence.

    The 2026-09-23 live run published "the brand has not publicly responded"
    while the evidence store already held the official response — read but
    never converted into any finding. The gate cannot judge truth, but it
    can refuse to finish while response-bearing, topically-overlapping
    evidence remains undisposed. The exit is always available: one reflect
    that cites the evidence (supporting or contradicting) disposes it.
    """
    undisposed = _undisposed_evidence(state)
    if not undisposed:
        return []
    stale: list[tuple[Finding, list[Evidence]]] = []
    for finding in state.findings:
        if not finding.active:
            continue
        negative = (
            finding.response == "not_found"
            or bool(_NEGATIVE_EXISTENCE.search(finding.text))
        )
        if not negative:
            continue
        claim_tokens = _content_tokens(
            " ".join(
                part
                for part in (
                    finding.text,
                    finding.stakeholder,
                    finding.stance_target,
                    finding.response_target,
                )
                if part
            )
        )
        if not claim_tokens:
            continue
        suspects = [
            item
            for item in undisposed
            if any(marker in item.excerpt for marker in _RESPONSE_MARKERS)
            and _content_tokens(item.excerpt) & claim_tokens
        ]
        if suspects:
            stale.append((finding, suspects))
    return stale


def _stale_findings_guidance(stale: list[tuple[Finding, list[Evidence]]]) -> str:
    lines = [
        "Finish rejected: a finding claims no response exists while saved "
        "evidence that may bear a response remains undisposed."
    ]
    for finding, suspects in stale:
        previews = "; ".join(
            f"{item.evidence_id} «{item.excerpt[:_GUIDANCE_EXCERPT_CHARS]}»"
            for item in suspects[:_GUIDANCE_PREVIEW_ITEMS]
        )
        lines.append(
            f"- {finding.finding_id} «{finding.text[:60]}» conflicts with "
            f"undisposed evidence: {previews}. Reflect first: retire or "
            "reword the finding, or cite the evidence (supporting or "
            "contradicting) so it is disposed."
        )
    return "\n".join(lines)


_COUNTER_EVIDENCE_MARKERS = (
    "反驳", "质疑", "否认", "辟谣", "不实", "相反", "批评", "反对", "支持", "肯定", "并非", "但也有", "另一方面",
)
_NUMERIC_QUANTITY_RE = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)\s*(?P<scale>[万亿])?(?P<unit>元|人|户|件|条|%|％)"
)
_SCALE_FACTORS = {None: 1.0, "": 1.0, "万": 10000.0, "亿": 100000000.0}


def _bigrams(text: str) -> set[str]:
    runs = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    return {run[i : i + 2] for run in runs for i in range(len(run) - 1)}


def evidence_quality_signals(state: State) -> dict:
    """Deterministic M6 signals: aggregator saturation, near-duplicate wires, counter-evidence, and numeric conflicts."""

    # 1. Domain saturation & read-error hotspots
    host_counts: dict[str, int] = {}
    for c in state.candidates:
        host = urlsplit(str(c.get("url") or "")).hostname or ""
        if host:
            host_counts[host] = host_counts.get(host, 0) + 1
    error_hosts: dict[str, int] = {}
    for u in state.read_errors:
        host = urlsplit(str(u or "")).hostname or ""
        if host:
            error_hosts[host] = error_hosts.get(host, 0) + 1

    total_cands = len(state.candidates)
    saturated_domains = []
    for host, cnt in sorted(host_counts.items(), key=lambda x: x[1], reverse=True):
        err_cnt = error_hosts.get(host, 0)
        if (total_cands >= 4 and cnt / total_cands >= 0.5) or err_cnt >= 2:
            saturated_domains.append({
                "domain": host,
                "candidate_count": cnt,
                "read_errors": err_cnt,
                "advice": f"{host} 占比较高或多次读取失败，后续搜索请增加原发机构/媒体词或切换检索角度。",
            })

    # 2. Near-duplicate syndicated articles across read sources via Bigram Jaccard
    by_version: dict[str, str] = {}
    for ev in state.evidence:
        by_version[ev.version_id] = by_version.get(ev.version_id, "") + "\n" + ev.excerpt
    near_duplicates = []
    sources = list(state.sources)
    for i in range(len(sources)):
        for j in range(i + 1, len(sources)):
            s1, s2 = sources[i], sources[j]
            if s1.content_hash == s2.content_hash or s1.duplicate_of or s2.duplicate_of:
                continue
            bg1 = _bigrams(by_version.get(s1.version_id, ""))
            bg2 = _bigrams(by_version.get(s2.version_id, ""))
            if len(bg1) >= 12 and len(bg2) >= 12:
                jaccard = len(bg1 & bg2) / max(len(bg1 | bg2), 1)
                if jaccard >= 0.75:
                    near_duplicates.append({
                        "source_version_id": s1.version_id,
                        "related_version_id": s2.version_id,
                        "similarity": round(jaccard, 2),
                        "hint": "两份材料摘录高度重合，疑似同源通稿转载，请在 reflect 中记录 source_relations (repost/same_text)。",
                    })

    # 3. Undisposed counter-evidence
    undisposed = _undisposed_evidence(state)
    counter_items = []
    for ev in undisposed:
        matched_markers = [m for m in _COUNTER_EVIDENCE_MARKERS if m in ev.excerpt]
        if matched_markers:
            counter_items.append({
                "evidence_id": ev.evidence_id,
                "version_id": ev.version_id,
                "markers": matched_markers[:3],
                "excerpt_preview": ev.excerpt[:80],
            })

    # 4. Cross-source numeric conflicts (e.g., 316.03亿元 vs 3160.3亿元)
    quantities: list[tuple[str, str, float, str, set[str]]] = []
    for ev in state.evidence:
        tokens = _content_tokens(ev.excerpt)
        for m in _NUMERIC_QUANTITY_RE.finditer(ev.excerpt):
            val = float(m.group("num")) * _SCALE_FACTORS.get(m.group("scale"), 1.0)
            unit = "%" if m.group("unit") in {"%", "％"} else m.group("unit")
            raw_q = m.group(0)
            quantities.append((ev.evidence_id, raw_q, val, unit, tokens))

    numeric_conflicts = []
    seen_conflicts: set[tuple[str, str]] = set()
    for i in range(len(quantities)):
        for j in range(i + 1, len(quantities)):
            eid1, raw1, val1, unit1, tok1 = quantities[i]
            eid2, raw2, val2, unit2, tok2 = quantities[j]
            if eid1 == eid2 or unit1 != unit2 or raw1 == raw2:
                continue
            if min(val1, val2) <= 0:
                continue
            ratio = max(val1, val2) / min(val1, val2)
            shared = tok1 & tok2
            if ratio >= 2.0 and len(shared) >= 2:
                pair_key = tuple(sorted((f"{eid1}:{raw1}", f"{eid2}:{raw2}")))
                if pair_key not in seen_conflicts:
                    seen_conflicts.add(pair_key)
                    numeric_conflicts.append({
                        "evidence_a": eid1,
                        "value_a": raw1,
                        "evidence_b": eid2,
                        "value_b": raw2,
                        "shared_context": sorted(shared)[:4],
                        "hint": f"检测到同单位数值显著冲突（{raw1} vs {raw2}），核查时请勿静默并存，需核对原发信源并在 contradicting_ids 中标注。",
                    })

    return {
        "domain_saturation": saturated_domains[:3],
        "near_duplicate_sources": near_duplicates[:4],
        "undisposed_counter_evidence": counter_items[:5],
        "numeric_conflicts": numeric_conflicts[:4],
    }


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
    if not RESPONSE_PURPOSES <= covered or _issue_has_read_errors(state, issue_id):
        return False
    unread = [c for c in state.candidates
              if c.get("issue_id") == issue_id and c["url"] not in state.read_attempts and allowed_url(c["url"], state)]
    return not unread


def required_next_action(state: State) -> dict | None:
    """Bound acquisition bursts before they can consume the whole run.

    Prompt advice alone did not stop a live quality run from spending its full
    model budget without creating a Finding. Duplicate searches first drain
    known unread candidates; enough acquired material then requires synthesis.
    Once a substantive reflection creates a finding, ordinary gap-driven
    acquisition can continue — but only while its output keeps getting used:
    when too many saved excerpts remain undisposed, acquisition is redirected
    into synthesis again instead of letting read-but-unused evidence pile up.
    """

    if any(finding.active for finding in state.findings):
        unreviewed = [
            finding.finding_id for finding in state.findings
            if finding.active and accepted_review(state, finding) is None
        ]
        if len(unreviewed) >= REVIEW_BACKLOG_LIMIT:
            return {
                "required_action": "review",
                "finding_ids": unreviewed,
                "reason": (
                    f"{len(unreviewed)} active findings have never been reviewed; "
                    "review them before more acquisition or synthesis"
                ),
            }
        stale = _stale_negative_findings(state)
        if stale:
            return {
                "required_action": "reflect",
                "allow_assessment_only": True,
                "finding_ids": [finding.finding_id for finding, _ in stale],
                "reason": _stale_findings_guidance(stale),
            }
        undisposed = _undisposed_evidence(state)
        if len(undisposed) >= ONGOING_REFLECTION_UNDISPOSED_LIMIT:
            return {
                "required_action": "reflect",
                "allow_assessment_only": True,
                "reason": (
                    f"{len(undisposed)} saved evidence excerpts remain undisposed "
                    "by any finding or assessment; synthesize them before more "
                    "acquisition"
                ),
            }
        return None
    if not state.evidence:
        return None
    if len(state.sources) >= FIRST_REFLECTION_SOURCE_LIMIT:
        return {
            "required_action": "reflect",
            "reason": (
                f"{len(state.sources)} saved sources and {len(state.evidence)} evidence excerpts are available "
                "but no finding has been created"
            ),
        }
    if len(state.searches) >= FIRST_REFLECTION_DUPLICATE_STREAK and all(
        attempt.outcome == "duplicate"
        for attempt in state.searches[-FIRST_REFLECTION_DUPLICATE_STREAK:]
    ):
        unread = tuple(
            candidate["url"] for candidate in state.candidates
            if candidate.get("url") and candidate["url"] not in state.read_attempts
            and allowed_url(candidate["url"], state)
        )
        if unread:
            return {
                "required_action": "read",
                "reason": (
                    f"the last {FIRST_REFLECTION_DUPLICATE_STREAK} searches returned only already-known URLs "
                    f"while {len(unread)} discovered candidates remain unread"
                ),
                "allowed_urls": list(unread),
            }
        return {
            "required_action": "reflect",
            "reason": (
                f"the last {FIRST_REFLECTION_DUPLICATE_STREAK} searches returned only already-known URLs "
                "and saved evidence remains unsynthesized"
            ),
        }
    return None


class Validator:
    def validate(self, state: State, decision):
        issues = {x.issue_id: x for x in state.issues}
        evidence = {x.evidence_id for x in state.evidence}
        findings = {x.finding_id: x for x in state.findings}
        issue_id = getattr(decision, "issue_id", None)
        if issue_id is not None and issue_id not in issues:
            raise ValueError("unknown investigation question")
        next_action = required_next_action(state)
        if next_action is not None:
            required_action = next_action["required_action"]
            if required_action == "read" and not isinstance(decision, ReadDecision):
                raise ValueError(
                    "read is required before another search: " + next_action["reason"]
                )
            if required_action == "read" and decision.url not in next_action["allowed_urls"]:
                raise ValueError(
                    "read one of the discovered unread candidate URLs before another search"
                )
            if required_action == "review":
                if not isinstance(decision, ReviewDecision):
                    raise ValueError(
                        "review is required before more acquisition: " + next_action["reason"]
                    )
                allowed = set(next_action.get("finding_ids") or ())
                if not set(decision.finding_ids) <= allowed:
                    raise ValueError("review only findings that have never been reviewed")
            if required_action == "reflect" and not isinstance(decision, ReflectDecision):
                raise ValueError(
                    "reflect is required before more search/read/retrieve work: " + next_action["reason"]
                )
            if required_action == "reflect" and next_action.get("allow_assessment_only"):
                if not (
                    decision.findings
                    or decision.assessments
                    or decision.retirements
                    or decision.source_relations
                ):
                    raise ValueError(
                        "the required synthesis reflection must dispose evidence: "
                        "create findings or assessments, retire stale findings, or "
                        "record source relations"
                    )
            elif required_action == "reflect" and not decision.findings:
                raise ValueError(
                    "the required first reflection must create at least one evidence-linked finding; "
                    "leave assessments empty when current evidence cannot dispose a whole question"
                )
        if isinstance(decision, ReflectDecision) and len(decision.findings) > MAX_NEW_FINDINGS_PER_REFLECT:
            raise ValueError(
                f"at most {MAX_NEW_FINDINGS_PER_REFLECT} new findings per reflection; "
                "review the current backlog first"
            )
        if isinstance(decision, SearchDecision):
            # A repeated query used to reject the decision, and three rejections
            # ended the whole run. Let it through instead: the reducer records it
            # as a duplicate outcome and the budget still bounds the damage.
            repeat = any(
                (x.issue_id, x.query.casefold(), x.page)
                == (decision.issue_id, decision.query.casefold(), decision.page)
                for x in state.searches
            )
            if repeat:
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
            known_sources = {x.version_id for x in state.sources}
            relation_pairs = set()
            for relation in decision.source_relations:
                endpoints = {relation.source_version_id, relation.related_version_id}
                if len(endpoints) != 2 or not endpoints <= known_sources:
                    raise ValueError("source relation must reference two known source versions")
                basis = [item for item in state.evidence if item.evidence_id in relation.basis_evidence_ids]
                if not set(relation.basis_evidence_ids) <= evidence:
                    raise ValueError("source relation references unknown evidence")
                if not {item.version_id for item in basis} <= endpoints:
                    raise ValueError("source relation basis must come from its two versions")
                pair = frozenset(endpoints)
                if pair in relation_pairs:
                    raise ValueError("duplicate source relation pair in one reflection")
                relation_pairs.add(pair)
            if len({x.issue_id for x in decision.assessments}) != len(decision.assessments):
                raise ValueError("duplicate question assessments")
            for item in (*decision.findings, *decision.assessments):
                if item.issue_id not in issues:
                    raise ValueError(
                        "unknown issue reference; copy issue_id exactly from memory.next_action_constraint"
                    )
                if not set(item.evidence_ids) <= evidence:
                    raise ValueError(
                        "unknown evidence reference; copy evidence_ids exactly from "
                        "memory.next_action_constraint"
                    )
            for item in decision.findings:
                if not set(item.contradicting_ids) <= evidence or set(item.evidence_ids) & set(item.contradicting_ids):
                    raise ValueError("invalid contradiction evidence")
                if item.kind == "attributed" and not item.stakeholder:
                    raise ValueError("attributed claims require an identified speaker")
                if item.stance != "unclear" and not item.stance_target:
                    raise ValueError("stance requires a specific target")
                allowed_modules = {FACET_MODULE_TYPES[f] for f in (state.profile.facets if state.profile else ())
                                   if f in FACET_MODULE_TYPES}
                if any(field.module not in allowed_modules for field in item.module_fields):
                    raise ValueError("module fields require a confirmed facet module")
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
                if any(not set(component.evidence_ids) <= evidence for component in assessment.components):
                    raise ValueError("component assessment references unknown evidence")
                for component in assessment.components:
                    if component.status in {"answered", "disputed"} and not component.evidence_ids:
                        raise ValueError("answered or disputed components require evidence")
                    if component.status in {"not_found", "unavailable"} and not component.note.strip():
                        raise ValueError("not_found or unavailable components require a bounded note")
                declared = issues[assessment.issue_id].components
                provided = {component.text: component for component in assessment.components}
                missing_components = [component.text for component in declared if component.text not in provided]
                if declared and assessment.status in {"answered", "disputed"} and missing_components:
                    raise ValueError("compound issue assessment must dispose of every component")
                if assessment.status == "answered" and any(
                        component.status != "answered" for component in assessment.components):
                    raise ValueError("an answered issue cannot keep a non-answered component")
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


def partial_finish_allowed(state: State) -> bool:
    """Whether open questions now describe a bounded partial result.

    A finish proposal used to be rejected whenever a required question stayed
    open. That protected against premature completion, but it also made the
    completion gate unreachable once the agent had exhausted the useful work it
    could do within its step budget. The gate still rejects an early stop; only
    after material has been acquired, at least one finding has passed review,
    and no higher-priority local action remains may the run close as partial.
    """

    open_required = [x for x in state.issues if x.required and x.status == "open"]
    if not open_required:
        return False
    if _stale_negative_findings(state):
        return False
    if required_next_action(state) is not None:
        return False
    active = [x for x in state.findings if x.active]
    if any(accepted_review(state, finding) is None for finding in active):
        return False
    if not any(
        (review := accepted_review(state, finding)) is not None
        and review.verdict == "supported"
        for finding in active
    ):
        return False
    if len(state.searches) < MIN_PARTIAL_FINISH_SEARCHES:
        return False
    if len(state.read_attempts) < MIN_PARTIAL_FINISH_READS:
        return False
    if len(state.sources) < MIN_PARTIAL_FINISH_SOURCES:
        return False
    return True


def completion(state: State):
    stale = _stale_negative_findings(state)
    if stale:
        return CompletionVerdict(
            disposition=Disposition.REJECT_AND_CONTINUE,
            reason=_stale_findings_guidance(stale),
        )
    open_required = [x for x in state.issues if x.required and x.status == "open"]
    if open_required:
        if partial_finish_allowed(state):
            questions = " | ".join(issue.question[:60] for issue in open_required)
            return CompletionVerdict(
                disposition=Disposition.ACCEPT_PARTIAL,
                reason=(
                    "Required questions remain open after a bounded investigation; "
                    f"publishing a partial report with the limitations preserved: {questions}"
                ),
            )
        return CompletionVerdict(
            disposition=Disposition.REJECT_AND_CONTINUE,
            reason=_open_questions_guidance(state, open_required),
        )
    active = [x for x in state.findings if x.active]
    problems = [x for x in state.issues if x.required and x.status == "unavailable"]
    component_problems = [component for issue in state.issues if issue.required
                          for component in issue.components
                          if component.status in {"open", "unavailable"}
                          or issue.status == "answered" and component.status != "answered"]
    unreviewed = [x for x in active if (r := accepted_review(state, x)) is None or r.verdict != "supported"]
    answered_without_findings = [q for q in state.issues if q.status in {"answered", "disputed"} and not any(f.issue_id == q.issue_id for f in active)]
    module_gaps = required_module_gaps(state)
    if not active or not state.evidence or problems or component_problems or unreviewed or answered_without_findings or module_gaps:
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


def _auto_detect_syndicated_relations(
    existing_sources: tuple,
    new_sources: tuple,
    all_evidence: tuple,
    existing_relations: tuple,
) -> list[SourceRelation]:
    """Deterministically detect syndicated reposts across read sources via CJK bigram overlap."""

    if not existing_sources or not new_sources or not all_evidence:
        return []
    ev_by_version: dict[str, list[Evidence]] = {}
    for ev in all_evidence:
        ev_by_version.setdefault(ev.version_id, []).append(ev)
    known_pairs = {
        frozenset((rel.source_version_id, rel.related_version_id))
        for rel in existing_relations
    }
    detected: list[SourceRelation] = []
    for new_src in new_sources:
        new_evs = ev_by_version.get(new_src.version_id) or []
        if not new_evs:
            continue
        new_bgs = _bigrams("\n".join(e.excerpt for e in new_evs))
        if len(new_bgs) < 12:
            continue
        for old_src in existing_sources:
            if old_src.version_id == new_src.version_id:
                continue
            pair = frozenset((old_src.version_id, new_src.version_id))
            if pair in known_pairs:
                continue
            old_evs = ev_by_version.get(old_src.version_id) or []
            if not old_evs:
                continue
            old_bgs = _bigrams("\n".join(e.excerpt for e in old_evs))
            if len(old_bgs) < 12:
                continue
            jaccard = len(new_bgs & old_bgs) / max(len(new_bgs | old_bgs), 1)
            if jaccard >= 0.75:
                known_pairs.add(pair)
                relation_kind = "same_text" if jaccard >= 0.92 else "repost"
                rel_id = uid("relation", old_src.version_id, new_src.version_id, relation_kind)
                detected.append(
                    SourceRelation(
                        relation_id=rel_id,
                        source_version_id=old_src.version_id,
                        related_version_id=new_src.version_id,
                        relation=relation_kind,
                        basis_evidence_ids=(old_evs[0].evidence_id, new_evs[0].evidence_id),
                        explanation=f"程序自动同源聚类：核心摘录二元词重合度 {jaccard:.0%}，判定为同源转载/通稿。",
                    )
                )
    return detected


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
    if o.numeric:
        changes["numeric_ledger"] = merge(state.numeric_ledger, o.numeric, "observation_id")
    if o.evidence:
        merged_evidence = merge(state.evidence, o.evidence, "evidence_id")
        changes["evidence"] = merged_evidence
        if o.sources:
            auto_rels = _auto_detect_syndicated_relations(
                state.sources, o.sources, merged_evidence, state.relations
            )
            if auto_rels:
                changes["relations"] = merge(state.relations, auto_rels, "relation_id")
    if isinstance(d, ReflectDecision):
        retired_ids = {x.finding_id for x in d.retirements}
        findings = [f.model_copy(update={"active": False}) if f.finding_id in retired_ids else f for f in state.findings]
        for proposal in d.findings:
            identifier = finding_identifier(proposal)
            item = Finding(**proposal.model_dump(), finding_id=identifier)
            findings = [f for f in findings if f.finding_id != identifier] + [item]
        repairs = {link.finding_id: link.evidence_ids for link in o.finding_evidence}
        if repairs:
            repaired = []
            for finding in findings:
                extra = repairs.get(finding.finding_id)
                if extra:
                    finding = finding.model_copy(update={
                        "evidence_ids": tuple(dict.fromkeys((*finding.evidence_ids, *extra)))})
                repaired.append(finding)
            findings = repaired
        issues = {x.issue_id: x for x in state.issues}
        for item in d.assessments:
            current = issues[item.issue_id]
            components = {component.text: component for component in current.components}
            for component in item.components:
                components[component.text] = QuestionComponent(
                    text=component.text, status=component.status,
                    evidence_ids=component.evidence_ids, note=component.note)
            issues[item.issue_id] = current.model_copy(update={
                "status": item.status, "note": item.reason, "evidence_ids": item.evidence_ids,
                "components": tuple(components.values())})
        for item in d.add_questions:
            identifier = uid("issue", item.question)
            if identifier not in issues:
                issues[identifier] = Issue(issue_id=identifier, question=item.question, required=item.required, origin_questions=item.covers)
        if d.source_relations:
            additions = []
            for proposal in d.source_relations:
                relation_id = uid("relation", proposal.source_version_id,
                                  proposal.related_version_id, proposal.relation)
                additions.append(SourceRelation(**proposal.model_dump(), relation_id=relation_id))
            changes["relations"] = merge(state.relations, additions, "relation_id")
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
