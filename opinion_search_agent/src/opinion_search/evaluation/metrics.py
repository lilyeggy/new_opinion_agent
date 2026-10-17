"""Deterministic metrics over a frozen run.

Each function takes a :class:`~opinion_search.evaluation.bundle.RunBundle` (and,
where the judgement is human, a hand-written annotation spec) and returns a plain
dict. Nothing here reads the clock, the network, or a model, so the same inputs
always produce the same numbers.
"""

from __future__ import annotations

from collections import Counter
import re
from typing import Any
from urllib.parse import urlparse

from opinion_search.domain.numeric import find_conflicts
from opinion_search.evaluation.bundle import RunBundle, normalize

_QUOTE_PAIR = re.compile(r"\u201c([^\u201c\u201d]{4,})\u201d")


def provenance_closure(bundle: RunBundle) -> dict[str, Any]:
    """Every reference in the report must resolve to something that exists."""
    known_evidence = {item.evidence_id for item in bundle.evidence}
    known_sources = {item.source_id for item in bundle.sources}
    checked = 0
    dangling: list[str] = []
    for claim in bundle.claims:
        for ref in (*claim.support_ids, *claim.contradict_ids):
            checked += 1
            if ref not in known_evidence:
                dangling.append(f"{claim.claim_id}->{ref}")
    for group, refs in bundle.refs:
        for ref in refs:
            checked += 1
            if ref not in known_evidence:
                dangling.append(f"{group}->{ref}")
    for item in bundle.evidence:
        checked += 1
        if item.source_id not in known_sources:
            dangling.append(f"{item.evidence_id}->{item.source_id}")
    dangling = sorted(set(dangling))
    resolved = checked - len(dangling)
    return {
        "checked": checked,
        "resolved": resolved,
        "dangling": dangling,
        "closure_rate": None if checked == 0 else resolved / checked,
    }


def excerpt_grounding(bundle: RunBundle) -> dict[str, Any]:
    """Evidence excerpts must sit inside the frozen snapshot they cite.

    Investigation runs store character offsets into the reader snapshot, so the
    check is exact. Opinion runs store no offsets, so the check is containment.
    Evidence whose snapshot was never frozen is counted as *unverifiable* rather
    than silently passed.
    """
    verified = 0
    mismatch = 0
    unverifiable = 0
    failures: list[dict[str, Any]] = []
    unverifiable_sources: set[str] = set()
    for item in bundle.evidence:
        source = bundle.source_for(item.source_id)
        if source is None or source.text is None:
            unverifiable += 1
            unverifiable_sources.add(item.source_id)
            continue
        if item.start is not None and item.end is not None:
            hit = normalize(source.text[item.start:item.end]) == normalize(item.excerpt)
        else:
            hit = normalize(item.excerpt) in normalize(source.text)
        if hit:
            verified += 1
        else:
            mismatch += 1
            failures.append({
                "evidence_id": item.evidence_id,
                "source_id": item.source_id,
                "url": source.url,
            })
    checkable = verified + mismatch
    return {
        "verified": verified,
        "mismatch": mismatch,
        "unverifiable": unverifiable,
        "checkable": checkable,
        "grounding_rate": None if checkable == 0 else verified / checkable,
        "unverifiable_sources": sorted(unverifiable_sources),
        "failures": failures,
    }


def claim_grounding(bundle: RunBundle) -> dict[str, Any]:
    """Every claim must carry at least one resolvable evidence binding."""
    known = {item.evidence_id for item in bundle.evidence}
    grounded = 0
    ungrounded_ids: list[str] = []
    for claim in bundle.claims:
        refs = [ref for ref in (*claim.support_ids, *claim.contradict_ids) if ref in known]
        if refs:
            grounded += 1
        else:
            ungrounded_ids.append(claim.claim_id)
    total = len(bundle.claims)
    return {
        "grounded": grounded,
        "ungrounded": len(ungrounded_ids),
        "total": total,
        "grounding_rate": None if total == 0 else grounded / total,
        "ungrounded_ids": ungrounded_ids,
    }


def _domain_summary(urls: list[str]) -> dict[str, Any]:
    domains = Counter(urlparse(url).netloc.lower() for url in urls if url)
    top_domain, top_count = domains.most_common(1)[0] if domains else ("", 0)
    return {
        "urls": len(urls),
        "domains": len(domains),
        "top_domain": top_domain,
        "top_domain_share": None if not urls else top_count / len(urls),
        "domain_counts": dict(domains.most_common(8)),
    }


def source_diversity(bundle: RunBundle) -> dict[str, Any]:
    """Who the run actually read, and how concentrated the candidate pool was."""
    return {
        "read": _domain_summary([source.url for source in bundle.sources]),
        "discovered": _domain_summary(list(bundle.candidate_urls)),
    }


def _matches(rule: dict[str, Any], url: str, title: str) -> bool:
    keywords = [item.lower() for item in rule.get("keywords") or ()]
    if keywords and not any(item in title.lower() for item in keywords):
        return False
    host = urlparse(url).netloc.lower()
    suffixes = [item.lower().lstrip(".") for item in rule.get("domain_suffix") or ()]
    if suffixes and not any(host == suffix or host.endswith("." + suffix) for suffix in suffixes):
        return False
    if not keywords and not suffixes:
        raise ValueError("match rule needs keywords or domain_suffix")
    return True


def retrieval_recall(bundle: RunBundle, spec: dict[str, Any] | None) -> dict[str, Any]:
    """Did the run surface each content item an acceptable investigation needs?

    The item list is hand-written. The ``match`` rule inside each item is applied
    mechanically to (url, title) pairs, so the verdict is reproducible. Where the
    item records the earlier published verdict, the two are compared and the
    agreement is reported instead of hidden.
    """
    if not spec or not spec.get("items"):
        return {"available": False}
    items: list[dict[str, Any]] = []
    agree = 0
    comparable = 0
    for entry in spec["items"]:
        rule = entry["match"]
        discovered = any(_matches(rule, url, title) for url, title in bundle.candidates)
        read = any(_matches(rule, url, bundle.title_for_url(url)) for url, _ in bundle.read)
        published_discovery = entry.get("published_discovery")
        published_read = entry.get("published_read")
        if published_discovery is not None:
            comparable += 1
            agree += int(discovered == published_discovery)
        items.append({
            "item_id": entry["item_id"],
            "content": entry["content"],
            "discovered": discovered,
            "read": read,
            "published_discovery": published_discovery,
            "published_read": published_read,
        })
    discovery_hits = sum(1 for item in items if item["discovered"])
    read_hits = sum(1 for item in items if item["read"])
    return {
        "available": True,
        "total": len(items),
        "discovery_hits": discovery_hits,
        "discovery_rate": discovery_hits / len(items),
        "read_hits": read_hits,
        "read_rate": read_hits / len(items),
        "reported_discovery_hits": sum(1 for item in items if item["published_discovery"]),
        "reported_read_hits": sum(1 for item in items if item["published_read"]),
        "agreement": {"comparable": comparable, "agree": agree,
                      "rate": None if comparable == 0 else agree / comparable},
        "items": items,
    }


def _quote_coverage(claim_text: str, excerpts: list[str]) -> float | None:
    """Share of a claim's quoted phrases that appear in its bound excerpts."""
    quotes = _QUOTE_PAIR.findall(claim_text)
    if not quotes:
        return None
    joined = normalize("".join(excerpts))
    return sum(1 for quote in quotes if normalize(quote) in joined) / len(quotes)


def faithfulness(bundle: RunBundle, spec: dict[str, Any] | None) -> dict[str, Any]:
    """Compare the run's own review verdicts with the frozen human labels."""
    verdicts = Counter(claim.review_verdict for claim in bundle.claims if claim.review_verdict)
    system: dict[str, Any] = {
        "total": len(bundle.claims),
        "reviewed": sum(verdicts.values()),
        "verdicts": dict(verdicts),
        "supported_rate": None if not verdicts else verdicts.get("supported", 0) / sum(verdicts.values()),
    }
    labels = (spec or {}).get("labels") or []
    human: dict[str, Any] = {"available": False}
    if labels:
        by_id = {claim.claim_id: claim for claim in bundle.claims}
        counts = Counter(label["judgement"] for label in labels)
        excerpts: dict[str, list[str]] = {}
        for evidence in bundle.evidence:
            for claim in bundle.claims:
                if evidence.evidence_id in (*claim.support_ids, *claim.contradict_ids):
                    excerpts.setdefault(claim.claim_id, []).append(evidence.excerpt)
        coverage = {
            label["claim_id"]: _quote_coverage(by_id[label["claim_id"]].text, excerpts.get(label["claim_id"], []))
            for label in labels if label.get("claim_id") in by_id
        }
        human = {
            "available": True,
            "method": (spec or {}).get("method", ""),
            "total": len(labels),
            "counts": dict(counts),
            "fully_supported_rate": counts.get("fully_supported", 0) / len(labels),
            "fabricated": counts.get("fabricated", 0),
            "labels": labels,
            "quote_coverage": coverage,
        }
    return {"system": system, "human": human}


def adversarial(bundle: RunBundle, spec: dict[str, Any] | None) -> dict[str, Any]:
    """Did the run adopt the planted correction, cite the planted counter-voice,
    and keep the planted wrong numbers out of the judgment layer?

    ``scope`` is ``narrative`` (everything before the raw evidence appendix) or
    ``report``. A planted number that shows up only as a quoted excerpt in the
    appendix is reported as such rather than silently counted as a pass.
    """
    if not spec or not spec.get("checks"):
        return {"available": False}
    evidence_by_source: dict[str, set[str]] = {}
    for item in bundle.evidence:
        evidence_by_source.setdefault(item.source_id, set()).add(item.evidence_id)
    cited: set[str] = set()
    for claim in bundle.claims:
        cited.update(claim.support_ids)
        cited.update(claim.contradict_ids)
    for _, refs in bundle.refs:
        cited.update(refs)

    checks: list[dict[str, Any]] = []
    for check in spec["checks"]:
        kind = check["kind"]
        scope = check.get("scope", "narrative")
        text = bundle.narrative_text if scope == "narrative" else bundle.report_text
        if kind == "text_present_all":
            observed = {marker: marker in text for marker in check["markers"]}
            passed = all(observed.values())
        elif kind == "text_absent":
            found = [marker for marker in check["markers"] if marker in text]
            appendix = [
                marker for marker in check["markers"]
                if marker in bundle.report_text and marker not in text
            ]
            observed = {"scope": scope, "found_in_scope": found, "found_in_appendix": appendix}
            passed = not found
        elif kind == "source_evidence_cited":
            source_ids = {
                source.source_id for source in bundle.sources
                if check["url_contains"] in source.url
            }
            evidence_ids: set[str] = set()
            for source_id in source_ids:
                evidence_ids |= evidence_by_source.get(source_id, set())
            was_cited = bool(evidence_ids & cited)
            observed = {
                "url_contains": check["url_contains"],
                "evidence_count": len(evidence_ids),
                "cited_count": len(evidence_ids & cited),
                "was_cited": was_cited,
            }
            passed = was_cited == check["expect"]
        elif kind == "numeric_conflict":
            documents = [
                (source.source_id, source.text)
                for source in bundle.sources
                if source.text
            ]
            conflicts = find_conflicts(documents)
            wanted = check.get("expect_metrics") or []
            factor = check.get("expect_factor")
            matched: list[str] = []
            for name in wanted:
                for conflict in conflicts:
                    if factor is not None and conflict.factor != factor:
                        continue
                    if name in conflict.metric or conflict.metric in name:
                        matched.append(name)
                        break
            missing = [name for name in wanted if name not in matched]
            observed = {
                "documents": len(documents),
                "conflicts": [
                    {
                        "metric": conflict.metric,
                        "lower": conflict.lower.literal,
                        "higher": conflict.higher.literal,
                        "factor": conflict.factor,
                    }
                    for conflict in conflicts
                ],
                "detected": matched,
                "missing": missing,
            }
            passed = not missing
        else:
            raise ValueError(f"unknown adversarial check kind: {kind}")
        checks.append({
            "check_id": check["check_id"],
            "question": check["question"],
            "layer": check.get("layer", "report"),
            "expect": check["expect"],
            "passed": passed,
            "note": check.get("note", ""),
            "observed": observed,
        })
    passed_count = sum(1 for check in checks if check["passed"])
    report_checks = [check for check in checks if check["layer"] == "report"]
    report_passed = sum(1 for check in report_checks if check["passed"])
    return {
        "available": True,
        "passed": passed_count,
        "total": len(checks),
        "rate": passed_count / len(checks),
        "report_passed": report_passed,
        "report_total": len(report_checks),
        "checks": checks,
    }
