# Frozen synthetic replay cases

These two cases replay the complete offline fixture kits through the production
manager and workbench projection:

- `night-bus-rule`: rule change and transition arrangement.
- `water-billing-remedy`: billing basis, handling path, deadline and remedy commitment.

Each `index.json` entry freezes the request, expected subject/facet module,
structured fields, sources, components, search purposes and the targeted-update
field. `test_replay_cases.py` runs the manager end to end and asserts those
contracts, so a case cannot silently pull in the other event's materials or
collapse into a generic report.

Boundary: these are synthetic mechanism-replay cases. Passing them is not live
search quality, not a human 90%/95% assertion check, and does not change the
status of `tests/investigation/cases/registry.json`, whose ten real-material
slots stay `blocked` until genuine public snapshots and annotations exist.

## Fixed-material live-model replay

`opinion_search.investigation.replay` adds a developer/acceptance harness for
the next evaluation layer: a real model and reviewer run through the normal
investigation loop while Brave/Jina discovery is replaced by local frozen
materials. A material manifest may inline `content`, or point at
`snapshot_path` with a `sha256` that the loader verifies before the run.

Example manifest shape:

```json
{
  "case_id": "example-case",
  "request_question": "某公开事件的最新进展与争议",
  "focus": "机构回应与执行情况",
  "clarification_answers": ["某市"],
  "materials": [
    {
      "url": "https://example.org/notice",
      "final_url": "https://example.org/notice",
      "title": "公告",
      "snapshot_path": "materials/notice.txt",
      "sha256": "hex digest of the exact UTF-8 snapshot",
      "published_at": "2026-01-01T00:00:00+00:00",
      "role": "original"
    }
  ]
}
```

Manual execution requires a configured model and an explicit budget decision:

```python
from opinion_search.investigation.replay import run_replay_case

snapshot = run_replay_case(
    root=...,             # run directory
    case_path=...,        # manifest path
    env_file=Path(".env"),  # optional dotenv for model credentials
    timeout_seconds=2400,
)
```

The harness never fetches Brave/Jina pages for replay runs. The planner,
decisions, reviewer, evidence verification and report pipeline are production
code, so the result is fixed-material model evidence rather than synthetic
mechanism evidence. Web search discovery and human 90%/95% scoring remain
separate P5 steps.
