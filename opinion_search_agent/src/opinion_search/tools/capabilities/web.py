from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opinion_search.tools.contracts import ToolDefinition


NonEmptyText = Annotated[str, Field(min_length=1)]
PublicUrl = Annotated[str, Field(pattern=r"^https?://")]


class PublicationTimeStatus(StrEnum):
    REPORTED = "reported"
    UNAVAILABLE = "unavailable"


class SearchArguments(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    query: NonEmptyText
    max_results: Annotated[int, Field(ge=1, le=10)] = 5
    freshness: str | None = None
    search_lang: str | None = None
    country: str | None = None
    offset: Annotated[int, Field(ge=0, le=9)] = 0


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
    published_at: datetime | None = None
    updated_at: datetime | None = None
    publication_time_status: PublicationTimeStatus = PublicationTimeStatus.UNAVAILABLE

    @model_validator(mode="after")
    def validate_publication_time(self) -> Self:
        expected = (
            PublicationTimeStatus.REPORTED
            if self.published_at is not None
            else PublicationTimeStatus.UNAVAILABLE
        )
        if self.publication_time_status is not expected:
            raise ValueError("publication time status must match published_at")
        return self


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
