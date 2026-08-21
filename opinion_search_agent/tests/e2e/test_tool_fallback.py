import asyncio

from opinion_search.app.contracts import SearchRequest
from opinion_search.app.service import (
    build_offline_fallback_service,
)
from opinion_search.runtime.lifecycle import RunStatus
from opinion_search.tools.adapters.fake import (
    FakePage,
    FakeReaderAdapter,
    FakeSearchAdapter,
)
from opinion_search.tools.capabilities.web import SearchHit
from opinion_search.tools.contracts import (
    ToolAdapterError,
    ToolErrorKind,
    ToolInvocation,
)


OFFICIAL_URL = "https://example.org/official-announcement"
REPORT_URL = "https://news.example.org/independent-report"
ALTERNATE_URL = "https://analysis.example.org/correction"

OFFICIAL_QUERY = "example event official announcement"
REPORT_QUERY = "example event independent report"
ALTERNATE_QUERY = "example event correction alternative account"


class FailingProbeAdapter:
    def __init__(self, kind: ToolErrorKind, message: str) -> None:
        self._kind = kind
        self._message = message
        self.invocations: list[ToolInvocation] = []

    async def invoke(self, invocation: ToolInvocation):
        self.invocations.append(invocation)
        raise ToolAdapterError(self._kind, self._message)


class CountingSearchAdapter(FakeSearchAdapter):
    pass


class CountingReaderAdapter(FakeReaderAdapter):
    pass


def _search_secondary() -> FakeSearchAdapter:
    return CountingSearchAdapter(
        {
            OFFICIAL_QUERY: (
                SearchHit(
                    title="Official announcement",
                    url=OFFICIAL_URL,
                    snippet="Official account of the event.",
                ),
            ),
            REPORT_QUERY: (
                SearchHit(
                    title="Independent report",
                    url=REPORT_URL,
                    snippet="Independent reporting on the disruption.",
                ),
            ),
            ALTERNATE_QUERY: (
                SearchHit(
                    title="Later correction analysis",
                    url=ALTERNATE_URL,
                    snippet="Alternative account of the claimed cause.",
                ),
            ),
        }
    )


def _reader_secondary() -> FakeReaderAdapter:
    return CountingReaderAdapter(
        pages={
            OFFICIAL_URL: FakePage(
                title="Official announcement",
                content=(
                    "The organization announced that the example event occurred "
                    "on 20 August and attributed the disruption to a technical fault."
                ),
                artifact_ref="artifact-official",
            ),
            REPORT_URL: FakePage(
                title="Independent report",
                content=(
                    "Independent reporting confirms the 20 August disruption and "
                    "notes that the technical cause has not been independently "
                    "verified."
                ),
                artifact_ref="artifact-report",
            ),
            ALTERNATE_URL: FakePage(
                title="Later correction analysis",
                content=(
                    "A later analysis agrees that disruption occurred but disputes "
                    "whether the available records establish a single technical cause."
                ),
                artifact_ref="artifact-alternate",
            ),
        }
    )


def test_offline_fallback_service_proves_provider_fallback(tmp_path) -> None:
    search_primary = FailingProbeAdapter(
        ToolErrorKind.SERVER_ERROR,
        "Primary search provider unavailable.",
    )
    search_secondary = _search_secondary()
    reader_primary = FailingProbeAdapter(
        ToolErrorKind.SERVER_ERROR,
        "Primary reader provider unavailable.",
    )
    reader_secondary = _reader_secondary()

    service = build_offline_fallback_service(
        tmp_path / "fallback.json",
        search_primary=search_primary,
        search_secondary=search_secondary,
        reader_primary=reader_primary,
        reader_secondary=reader_secondary,
    )

    outcome = asyncio.run(
        service.investigate(
            SearchRequest(question="What happened in the example event?"),
            run_id="fallback-demo",
        )
    )

    assert outcome.status is RunStatus.COMPLETED
    assert len(search_primary.invocations) > 0
    assert len(reader_primary.invocations) > 0
    assert len(search_secondary.invocations) == 3
    assert len(reader_secondary.invocations) == 3
    assert len(outcome.source_urls) == 3
    # agent decisions carry no provider identity
    assert "secondary" not in outcome.markdown
