import asyncio

import pytest
from pydantic import TypeAdapter

from opinion_search.app.contracts import SearchRequest
from opinion_search.domain.opinion.decisions import AgentDecision
from opinion_search.domain.opinion.reducer import reduce_opinion_state
from opinion_search.domain.opinion.state import (
    InvestigationGap,
    OpinionSearchState,
)
from opinion_search.models.fake import (
    DeterministicIdFactory,
    FakeActionExecutor,
    FakeActionResolver,
    FakeCompletionEvaluator,
    FakeDecisionValidator,
    FakeObservation,
    FakeObservationProcessor,
    MinimalContextCompiler,
    MinimalOpinionCompletionPolicy,
    OpinionRunState,
    ScriptedModelClient,
    default_script,
)
from opinion_search.runtime.checkpoint import JsonCheckpointStore
from opinion_search.runtime.journal import RuntimeJournal
from opinion_search.runtime.lifecycle import RunStatus
from opinion_search.runtime.loop import AgentLoop
from opinion_search.runtime.recording import (
    DecisionRecorder,
    JournalingCheckpointStore,
    RecordingModelClient,
)
from opinion_search.runtime.replay import (
    ReplayCodec,
    ReplayMissingRecordError,
    ReplayStatus,
    load_step_records,
    replay_records,
)
from opinion_search.runtime.replay_record import StepJournalRecord

CODEC = ReplayCodec(
    decision=TypeAdapter(AgentDecision),
    observation=TypeAdapter(FakeObservation),
)


def _initial_state() -> OpinionRunState:
    return OpinionRunState(
        run_id="run-replay",
        domain_state=OpinionSearchState(
            request=SearchRequest(question="What happened?"),
            gaps=(
                InvestigationGap(
                    gap_id="gap-primary",
                    question="Find the primary account.",
                    priority=5,
                ),
            ),
        ),
    )


def _components(model, executor, store):
    return AgentLoop(
        model=model,
        context_compiler=MinimalContextCompiler(),
        decision_validator=FakeDecisionValidator(),
        action_resolver=FakeActionResolver(MinimalOpinionCompletionPolicy()),
        action_executor=executor,
        observation_processor=FakeObservationProcessor(),
        completion_evaluator=FakeCompletionEvaluator(),
        reducer=reduce_opinion_state,
        checkpoint_store=store,
        id_factory=DeterministicIdFactory(),
        max_steps=10,
    )


def _live_loop(directory, *, store_wrapper=None):
    """Build a recorded live loop; returns (loop, journal_path, checkpoint_path)."""
    journal_path = directory / "run.journal"
    checkpoint_path = directory / "run.json"
    recorder = DecisionRecorder(journal_path)
    base_store = JsonCheckpointStore(checkpoint_path, OpinionRunState)
    inner = store_wrapper(base_store) if store_wrapper else base_store
    store = JournalingCheckpointStore(inner, recorder)
    model = RecordingModelClient(ScriptedModelClient(default_script()), recorder)
    loop = _components(model, FakeActionExecutor(), store)
    return loop, journal_path, checkpoint_path


def _replay(records):
    return asyncio.run(
        replay_records(
            records,
            initial_state=_initial_state(),
            codec=CODEC,
            build_loop=_components,
        )
    )


def test_recorded_run_replays_to_match(tmp_path) -> None:
    loop, journal_path, _ = _live_loop(tmp_path)

    result = asyncio.run(loop.run(_initial_state()))
    records = load_step_records(journal_path)

    assert result.status is RunStatus.COMPLETED
    assert len(records) == 5
    assert all(record.complete for record in records)

    report = _replay(records)
    assert report.status is ReplayStatus.MATCHED
    assert report.steps_checked == 5


def test_replay_is_repeatable(tmp_path) -> None:
    loop, journal_path, _ = _live_loop(tmp_path)
    asyncio.run(loop.run(_initial_state()))
    records = load_step_records(journal_path)

    reports = [_replay(records) for _ in range(3)]

    assert {report.model_dump_json() for report in reports} == {
        reports[0].model_dump_json()
    }


def _tampered(records, step_index, **changes):
    edited = []
    for record in records:
        if record.step_index == step_index:
            record = StepJournalRecord.model_validate(
                {**record.model_dump(), **changes}
            )
        edited.append(record)
    return edited


def test_context_hash_tamper_reports_first_divergence(tmp_path) -> None:
    loop, journal_path, _ = _live_loop(tmp_path)
    asyncio.run(loop.run(_initial_state()))
    records = load_step_records(journal_path)
    step_two = records[1]
    calls = list(step_two.model_calls)
    calls[0] = calls[0].model_copy(update={"context_hash": "0" * 64})
    tampered = _tampered(records, 2, model_calls=[c.model_dump() for c in calls])

    report = _replay(tampered)

    assert report.status is ReplayStatus.DIVERGED
    assert report.divergence is not None
    assert report.divergence.step_index == 2
    assert report.divergence.field == "model_calls[0].context_hash"


def test_state_fingerprint_tamper_is_detected_at_its_step(tmp_path) -> None:
    loop, journal_path, _ = _live_loop(tmp_path)
    asyncio.run(loop.run(_initial_state()))
    records = load_step_records(journal_path)
    tampered = _tampered(records, 3, state_fingerprint="f" * 64)

    report = _replay(tampered)

    assert report.status is ReplayStatus.DIVERGED
    assert report.divergence.step_index == 3
    assert report.divergence.field == "state_fingerprint"


def test_missing_recorded_call_is_an_error_not_a_live_call(tmp_path) -> None:
    loop, journal_path, _ = _live_loop(tmp_path)
    asyncio.run(loop.run(_initial_state()))
    records = load_step_records(journal_path)[:-1]

    with pytest.raises(ReplayMissingRecordError):
        _replay(records)


def test_crash_between_journal_and_checkpoint_resumes_consistently(tmp_path) -> None:
    class _CrashOnFirstCommitCheckpoint:
        """Fails the checkpoint write that persists the second committed step."""

        def __init__(self, inner):
            self._inner = inner
            self._armed = True

        async def save(self, state):
            committed_now = len(state.committed_steps) == 2
            if self._armed and committed_now and state.active_step is None:
                self._armed = False
                raise RuntimeError("injected crash before checkpoint")
            await self._inner.save(state)

        async def load(self):
            return await self._inner.load()

    loop, journal_path, checkpoint_path = _live_loop(
        tmp_path,
        store_wrapper=_CrashOnFirstCommitCheckpoint,
    )
    with pytest.raises(RuntimeError, match="injected crash"):
        asyncio.run(loop.run(_initial_state()))
    assert len(RuntimeJournal(journal_path).read()) == 2

    resumed, _, _ = _live_loop(tmp_path)
    result = asyncio.run(resumed.resume())
    records = load_step_records(journal_path)

    assert result.status is RunStatus.COMPLETED
    assert [record.step_index for record in records] == [1, 2, 3, 4, 5]
    assert all(record.complete for record in records)
    assert _replay(records).status is ReplayStatus.MATCHED
