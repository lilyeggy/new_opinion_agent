import asyncio
import json
from pathlib import Path

from opinion_search.app.contracts import SearchRequest
from opinion_search.app.service import (
    OpinionRunState,
    build_offline_service,
)
from opinion_search.runtime.checkpoint import JsonCheckpointStore
from opinion_search.runtime.lifecycle import RunStatus


EXPECTED = json.loads(
    (Path(__file__).parents[1] / "fixtures/opinion_case/expected.json").read_text(
        encoding="utf-8"
    )
)


def test_offline_demo_produces_cited_contested_brief_without_keys(
    tmp_path,
) -> None:
    checkpoint_path = tmp_path / "offline.json"
    service = build_offline_service(checkpoint_path)

    outcome = asyncio.run(
        service.investigate(
            SearchRequest(
                question="What happened in the example event?",
                topic="Example event",
                focus="Compare event facts and causal accounts.",
            ),
            run_id="offline-demo",
        )
    )
    checkpoint = asyncio.run(
        JsonCheckpointStore(checkpoint_path, OpinionRunState).load()
    )

    assert outcome.status is RunStatus.COMPLETED
    assert len(checkpoint.committed_steps) == EXPECTED["committed_steps"]
    assert len(checkpoint.domain_state.sources) == EXPECTED["source_count"]
    assert len(checkpoint.domain_state.evidence) == EXPECTED["evidence_count"]
    assert (
        list(checkpoint.domain_state.resolved_gap_ids) == (EXPECTED["resolved_gap_ids"])
    )
    assert any(
        claim.status.value == "contested" for claim in checkpoint.domain_state.claims
    )
    assert "[S1]" in outcome.markdown
    assert "[S2]" in outcome.markdown
    assert "[S3]" in outcome.markdown
    assert all(
        fragment in outcome.markdown
        for fragment in EXPECTED["required_brief_fragments"]
    )
    assert outcome.remaining_gap_ids == ()


def test_offline_checkpoint_and_cache_contain_no_credential_fields(
    tmp_path,
) -> None:
    checkpoint_path = tmp_path / "offline.json"
    service = build_offline_service(checkpoint_path)

    asyncio.run(
        service.investigate(
            SearchRequest(question="What happened?"),
            run_id="offline-secret-check",
        )
    )

    cache_dir = tmp_path / "action_results"
    assert cache_dir.is_dir()
    cache_files = list(cache_dir.glob("*.json"))
    assert cache_files

    checkpoint_raw = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert "state" in checkpoint_raw
    for field in ("call", "result"):
        body = (json.loads(cache_files[0].read_text(encoding="utf-8"))).get(field)
        assert set(body) <= {
            "action_id",
            "tool_name",
            "arguments",
            "payload",
            "artifact_refs",
            "attempts",
        }, f"cache {field} must not carry provider credentials"
