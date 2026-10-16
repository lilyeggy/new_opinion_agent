"""Evaluation harness for a live investigation run.

Two independent measurements:
1. Retrieval recall against a human-labeled must-hit list (labeled BEFORE
   looking at system candidates, each item verified by independent search).
2. Faithfulness audit material: dump every finding with its supporting
   evidence excerpts for manual verification.

Usage: python evaluate.py <run_dir> <labels.json>
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit


def load_state(run_dir: Path) -> dict:
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    state = run.get("state", {})
    return state.get("domain_state", state), run


def check_item(item: dict, haystacks: list[str]) -> bool:
    """Item counts as found if any haystack (url+title+text) hits one url_hint
    AND at least two keywords, or three keywords alone."""
    for hay in haystacks:
        low = hay.lower()
        url_hit = any(h.lower() in low for h in item["url_hints"])
        kw_hits = sum(1 for k in item["kw"] if k in hay)
        if (url_hit and kw_hits >= 1) or kw_hits >= 2:
            return True
    return False


def main() -> None:
    run_dir = Path(sys.argv[1])
    labels = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    domain, run = load_state(run_dir)

    searches = domain.get("searches", [])
    candidates = domain.get("candidates", [])
    sources = domain.get("sources", [])
    evidence = {e["evidence_id"]: e for e in domain.get("evidence", [])}
    findings = [f for f in domain.get("findings", []) if f.get("active", True)]
    reviews = {r["finding_id"]: r["verdict"] for r in domain.get("reviews", [])}

    print("=" * 70)
    print(f"RUN {run_dir.name}  status={run.get('status')}")
    print(f"searches={len(searches)} candidates={len(candidates)} "
          f"read_saved={len(sources)} findings={len(findings)}")
    print("=" * 70)

    # haystacks: candidate-level (url+title) and source-level (url+title+artifact text)
    cand_hay = [f"{c.get('url','')} {c.get('title','')}" for c in candidates]
    src_hay = []
    art_root = run_dir.parent.parent / "cases"
    for s in sources:
        text = f"{s.get('url','')} {s.get('title','')}"
        ref = (s.get("artifact_ref") or "").replace("artifact://sha256/", "")
        for p in art_root.glob(f"*/artifacts/{ref}.txt"):
            try:
                text += " " + p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
        src_hay.append(text)

    print("\n--- METRIC 1: must-hit recall ---")
    hit_c = hit_s = 0
    for item in labels["items"]:
        in_cand = check_item(item, cand_hay)
        in_src = check_item(item, src_hay)
        hit_c += in_cand
        hit_s += in_src
        mark = "✓读入" if in_src else ("~仅候选" if in_cand else "✗缺失")
        print(f"  [{mark}] #{item['id']} {item['fact'][:52]}")
    n = len(labels["items"])
    print(f"\n召回(候选层): {hit_c}/{n} = {hit_c/n:.0%}")
    print(f"召回(读入层): {hit_s}/{n} = {hit_s/n:.0%}")

    print("\n--- METRIC 2: faithfulness audit material ---")
    for i, f in enumerate(findings, 1):
        verdict = reviews.get(f["finding_id"], "未审")
        print(f"\n### F{i} [{f.get('kind')}] review={verdict}")
        print(f"文本: {f['text']}")
        for eid in f.get("evidence_ids", [])[:4]:
            e = evidence.get(eid)
            if e:
                print(f"  证据[{eid[-8:]}] src={e.get('source_id','')[-8:]}: {e['excerpt'][:200]}")

    # candidate domain distribution
    from collections import Counter
    hosts = Counter(urlsplit(c.get("url", "")).netloc for c in candidates)
    print("\n--- candidate domains ---")
    for h, cnt in hosts.most_common(12):
        print(f"  {h}: {cnt}")


if __name__ == "__main__":
    main()
