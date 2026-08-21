import asyncio

import pytest

from opinion_search.app.contracts import SearchRequest
from opinion_search.app.service import build_offline_service
from opinion_search.runtime.lifecycle import RunStatus
from opinion_search.runtime.loop import CheckpointBoundary, RuntimeState


class InjectedCrash(RuntimeError):
    pass


class CrashOnFirstObservation:
    def __init__(self) -> None:
        self._crashed = False

    async def after_checkpoint(
        self,
        boundary: CheckpointBoundary,
        state: RuntimeState,
    ) -> None:
        if boundary is CheckpointBoundary.OBSERVATION_READY and not self._crashed:
            self._crashed = True
            raise InjectedCrash(boundary.value)


def test_offline_demo_resumes_from_persisted_observation(tmp_path) -> None:
    checkpoint_path = tmp_path / "resume.json"
    crashing = build_offline_service(
        checkpoint_path,
        hook=CrashOnFirstObservation(),
    )

    with pytest.raises(InjectedCrash):
        asyncio.run(
            crashing.investigate(
                SearchRequest(question="What happened?"),
                run_id="resume-demo",
            )
        )

    resumed = build_offline_service(checkpoint_path)
    outcome = asyncio.run(resumed.resume())

    assert outcome.status is RunStatus.COMPLETED
    assert len(outcome.source_urls) == 3
    assert outcome.remaining_gap_ids == ()
