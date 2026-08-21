from collections.abc import Mapping, Set
from pydantic import BaseModel, ConfigDict, Field

from opinion_search.tools.capabilities.web import (
    ReadResult,
    ReaderArguments,
    SearchArguments,
    SearchHit,
    SearchResults,
    reader_tool_definition,
    search_tool_definition,
)
from opinion_search.tools.contracts import (
    ToolAdapterError,
    ToolAdapterResponse,
    ToolDefinition,
    ToolErrorKind,
    ToolInvocation,
)


class FakePage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    artifact_ref: str = Field(min_length=1)


def fake_search_definition() -> ToolDefinition:
    return search_tool_definition()


def fake_reader_definition() -> ToolDefinition:
    return reader_tool_definition()


class FakeSearchAdapter:
    def __init__(
        self,
        results_by_query: Mapping[str, tuple[SearchHit, ...]],
    ) -> None:
        self._results_by_query = {
            query: tuple(results) for query, results in results_by_query.items()
        }
        self.invocations: list[ToolInvocation[SearchArguments]] = []

    async def invoke(
        self,
        invocation: ToolInvocation[SearchArguments],
    ) -> ToolAdapterResponse:
        self.invocations.append(invocation)
        arguments = invocation.arguments
        results = self._results_by_query.get(arguments.query, ())
        payload = SearchResults(
            query=arguments.query,
            items=results[: arguments.max_results],
        )
        return ToolAdapterResponse(payload=payload.model_dump(mode="json"))


class FakeReaderAdapter:
    def __init__(
        self,
        *,
        pages: Mapping[str, FakePage],
        unreadable_urls: Set[str] = frozenset(),
    ) -> None:
        self._pages = dict(pages)
        self._unreadable_urls = frozenset(unreadable_urls)
        self.invocations: list[ToolInvocation[ReaderArguments]] = []

    async def invoke(
        self,
        invocation: ToolInvocation[ReaderArguments],
    ) -> ToolAdapterResponse:
        self.invocations.append(invocation)
        url = invocation.arguments.url
        if url in self._unreadable_urls:
            raise ToolAdapterError(
                ToolErrorKind.UNREADABLE_CONTENT,
                "The page content could not be read.",
            )

        page = self._pages.get(url)
        if page is None:
            raise ToolAdapterError(
                ToolErrorKind.NOT_FOUND,
                "The requested page was not found.",
            )

        payload = ReadResult(
            url=url,
            title=page.title,
            content=page.content,
        )
        return ToolAdapterResponse(
            payload=payload.model_dump(mode="json", exclude_none=True),
            artifact_refs=(page.artifact_ref,),
        )
