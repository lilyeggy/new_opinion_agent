# Portfolio Evidence

This directory contains the frozen evidence for the portfolio version of
OpinionSearch Agent. It is intentionally small: raw provider responses, full
observation caches and historical live runs are not part of the repository.

## Live completed run

- Run id: `6ba850f7c5684af7940b4b7c53b0ac4a`
- Mode: live
- Status: `completed`
- Stop reason: `Required questions have explicit dispositions and active findings passed evidence review; this is not a truth guarantee.`
- Scope: three explicit, verifiable questions about the Luo Yonghao / Wild Man
  ice-cream incident; this is a single-event investigation, not a general
  public-opinion monitoring platform.

Measured output:

| Metric | Value |
|---|---|
| Required issues | 5/5 answered |
| Active findings | 15 |
| Reviewed findings | 15/15 |
| Supported findings | 15/15 |
| Independent sources | 4 |
| Evidence excerpts | 20 |
| Narrative | 2 paragraphs / 6 clauses |
| Narrative dropped | 0 |
| `dossier.html` | generated, contains `narrative-block` |
| Model timing | 31 calls, p50 7.381s, max 37.683s |
| Tool timing | 26 calls, p50 2.105s, max 18.701s |

Files:

- `completed/report.md`: human-readable report.
- `completed/report.json`: typed report projection.
- `completed/presentation_plan.json`: narrative and presentation contract.
- `completed/dossier.html`: self-contained rendered dossier.
- `completed/run.json`: committed journal/checkpoint used for replay.
- `completed/timing.jsonl`: model/tool timing records.
- `completed/budget.json`: resource counters.
- `completed/workbench.json`: workbench projection.

## Honest partial example

`partial/report.md` is a real run that reached a bounded, explicit partial
state when required questions could not all be factually disposed. This is a
product behavior, not a hidden failure: the report preserves the open issues
and limitations instead of claiming completion.

## Failed-run fallback

`fallback/` is a forced unrecoverable-failure run. It demonstrates the delivery
guarantee: even a failed investigation emits `report.json`, `report.md`,
`workbench.json`, `presentation_plan.json`, and `dossier.html`. The report keeps
the failure reason and explicitly says the result is incomplete; the fallback
does not turn failure into a completed claim.

## Verification

From `opinion_search_agent/`:

```bash
NO_PROXY=localhost,127.0.0.1,::1 no_proxy=localhost,127.0.0.1,::1 \
  .venv/bin/python -m pytest -q -W error
PYTHONPATH=src .venv/bin/python scripts/quality_gate.py --check
ruff check src
```

Expected:

- `889 passed, 2 skipped`
- `quality gate: baseline reproduced exactly`
- ruff clean
