from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from opinion_search.tools.contracts import ToolDefinition


NonEmptyText = Annotated[str, Field(min_length=1)]
PublicUrl = Annotated[str, Field(pattern=r"^https?://")]


class SearchArguments(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    query: NonEmptyText
    max_results: Annotated[int, Field(ge=1, le=10)] = 5


class SearchHit(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    title: NonEmptyText
    url: PublicUrl
    snippet: NonEmptyText


class SearchResults(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: NonEmptyText
    items: tuple[SearchHit, ...]


class ReaderArguments(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    url: PublicUrl


class ReadResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    url: PublicUrl
    final_url: PublicUrl | None = None
    title: NonEmptyText
    content: NonEmptyText


def search_tool_definition() -> ToolDefinition:
    return ToolDefinition(
        name="search.web",
        description="Search the public web for candidate sources.",
        capability="search",
        input_model=SearchArguments,
    )


def reader_tool_definition() -> ToolDefinition:
    return ToolDefinition(
        name="read.web",
        description="Read a public web page by URL.",
        capability="read",
        input_model=ReaderArguments,
    )
