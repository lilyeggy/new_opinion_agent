from opinion_search.app.contracts import SearchRequest
from opinion_search.context.catalog import (
    EvidenceCatalogPolicy,
    partition_evidence_catalog,
)
from opinion_search.domain.opinion.state import (
    CandidateSource,
    Claim,
    ClaimKind,
    ClaimStatus,
    Evidence,
    InvestigationGap,
    OpinionSearchState,
    Source,
)
from opinion_search.memory.projector import project_working_memory


def _state_with_unlinked_evidence(count: int) -> OpinionSearchState:
    candidates: list[CandidateSource] = []
    sources: list[Source] = []
    evidence: list[Evidence] = []
    for index in range(count):
        url = f"https://example.com/{index}"
        candidates.append(
            CandidateSource(
                source_id=url,
                url=url,
                title=f"S{index}",
                snippet=f"s{index}",
                discovered_for_gap_ids=("gap-primary",),
            )
        )
        sources.append(
            Source(source_id=url, url=url, title=f"S{index}")
        )
        evidence.append(
            Evidence(
                evidence_id=f"ev-{index}",
                source_id=url,
                acquired_for_gap_id="gap-primary",
                excerpt=f"Excerpt {index}.",
                locator="1.",
            )
        )
    return OpinionSearchState(
        request=SearchRequest(question="What happened?"),
        gaps=(
            InvestigationGap(
                gap_id="gap-primary",
                question="Primary.",
                priority=5,
            ),
        ),
        candidates=tuple(candidates),
        sources=tuple(sources),
        evidence=tuple(evidence),
    )


def _semantic_state() -> OpinionSearchState:
    # gap-primary is the current open gap; ev-semantic semantically covers it,
    # ev-acquired is acquired for it but semantically unlinked, ev-other is
    # acquired for another gap (also semantically unlinked) and is the newest.
    candidates = []
    sources = []
    evidence = []
    for eid in ("ev-semantic", "ev-acquired", "ev-other"):
        url = f"https://example.com/{eid}"
        candidates.append(
            CandidateSource(
                source_id=url,
                url=url,
                title=eid,
                snippet=eid,
                discovered_for_gap_ids=("gap-primary",),
            )
        )
        sources.append(Source(source_id=url, url=url, title=eid))
        evidence.append(
            Evidence(
                evidence_id=eid,
                source_id=url,
                acquired_for_gap_id=(
                    "gap-primary" if eid != "ev-other" else "gap-other"
                ),
                excerpt=f"Excerpt {eid}.",
                locator="1.",
            )
        )
    return OpinionSearchState(
        request=SearchRequest(question="What happened?"),
        gaps=(
            InvestigationGap(
                gap_id="gap-primary",
                question="Primary.",
                priority=5,
                evidence_ids=("ev-semantic",),
            ),
            InvestigationGap(
                gap_id="gap-other",
                question="Other.",
                priority=1,
            ),
        ),
        candidates=tuple(candidates),
        sources=tuple(sources),
        evidence=tuple(evidence),
        claims=(
            Claim(
                claim_id="claim-1",
                text="Acquired evidence supports a claim.",
                kind=ClaimKind.FACT,
                supporting_evidence_ids=("ev-acquired",),
                status=ClaimStatus.SUPPORTED,
            ),
        ),
    )


def test_zero_evidence_omits_both_tiers() -> None:
    state = _state_with_unlinked_evidence(0)
    assert state.evidence == ()
    memory = project_working_memory(state)
    partition = partition_evidence_catalog(
        memory,
        policy=EvidenceCatalogPolicy(),
        current_gap_id=memory.current_gap_id,
    )
    assert partition.required == ()
    assert partition.history == ()


def test_fewer_than_limit_puts_all_required_no_history() -> None:
    memory = project_working_memory(_state_with_unlinked_evidence(30))
    partition = partition_evidence_catalog(
        memory,
        policy=EvidenceCatalogPolicy(required_evidence_limit=64),
        current_gap_id=memory.current_gap_id,
    )
    assert len(partition.required) == 30
    assert partition.history == ()


def test_more_than_limit_produces_bounded_required_and_complete_history() -> None:
    memory = project_working_memory(_state_with_unlinked_evidence(300))
    partition = partition_evidence_catalog(
        memory,
        policy=EvidenceCatalogPolicy(
            required_evidence_limit=64,
            history_chunk_size=64,
        ),
        current_gap_id=memory.current_gap_id,
    )
    assert len(partition.required) == 64
    chunk_sizes = [len(chunk) for chunk in partition.history]
    assert chunk_sizes == [64, 64, 64, 44]
    assert sum(chunk_sizes) == 236

    seen: list[str] = []
    seen.extend(entry.evidence_id for entry in partition.required)
    for chunk in partition.history:
        seen.extend(entry.evidence_id for entry in chunk)
    assert len(seen) == len(set(seen)) == 300
    assert partition.state_order_ids == tuple(
        we.evidence_id for we in memory.evidence
    )


def test_results_are_byte_identical_across_calls() -> None:
    memory = project_working_memory(_state_with_unlinked_evidence(150))
    a = partition_evidence_catalog(
        memory,
        policy=EvidenceCatalogPolicy(),
        current_gap_id=memory.current_gap_id,
    )
    b = partition_evidence_catalog(
        memory,
        policy=EvidenceCatalogPolicy(),
        current_gap_id=memory.current_gap_id,
    )
    assert a.required == b.required
    assert a.history == b.history


def test_semantic_current_gap_evidence_outranks_acquisition_only() -> None:
    memory = project_working_memory(_semantic_state())
    partition = partition_evidence_catalog(
        memory,
        policy=EvidenceCatalogPolicy(required_evidence_limit=64),
        current_gap_id=memory.current_gap_id,
    )
    req_ids = [entry.evidence_id for entry in partition.required]
    # ev-semantic (group 1) and ev-other (newest unlinked group 2) are required;
    # ev-acquired (group 3, acquired-for-current but semantically unlinked) ranks
    # behind the newest unlinked evidence.
    assert req_ids[0] == "ev-semantic"
    assert "ev-acquired" in req_ids
    assert set(req_ids[-len(req_ids):]) >= {"ev-semantic", "ev-other"}


def test_latest_unlinked_evidence_remains_required_for_other_gap() -> None:
    memory = project_working_memory(_semantic_state())
    partition = partition_evidence_catalog(
        memory,
        policy=EvidenceCatalogPolicy(required_evidence_limit=64),
        current_gap_id=memory.current_gap_id,
    )
    req = {entry.evidence_id for entry in partition.required}
    assert "ev-other" in req  # acquired for gap-other but newest unlinked


def test_catalog_entries_contain_only_structural_relations() -> None:
    memory = project_working_memory(_semantic_state())
    partition = partition_evidence_catalog(
        memory,
        policy=EvidenceCatalogPolicy(),
        current_gap_id=memory.current_gap_id,
    )
    for entry in partition.required:
        assert set(entry.__dict__) == {
            "evidence_id",
            "source_id",
            "acquired_for_gap_id",
            "semantic_gap_ids",
        }
        assert "Excerpt" not in str(entry)
