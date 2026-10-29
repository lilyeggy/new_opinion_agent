from typing import Annotated
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


NonEmptyText = Annotated[str, Field(min_length=1)]


class SearchRequest(BaseModel):
    """User-provided scope and constraints for one search run."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    question: NonEmptyText
    topic: NonEmptyText | None = None
    time_range: NonEmptyText | None = None
    focus: NonEmptyText | None = None
    language: NonEmptyText = "zh"
    include_domains: tuple[NonEmptyText, ...] = ()
    exclude_domains: tuple[NonEmptyText, ...] = ()

    @field_validator("include_domains", "exclude_domains", mode="before")
    @classmethod
    def normalize_domain_constraints(cls, value: object) -> object:
        if value is None:
            return ()
        if isinstance(value, str):
            value = (value,)
        if not isinstance(value, (tuple, list)):
            return value
        return tuple(_normalize_domain_constraint(item) for item in value)


def _normalize_domain_constraint(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("domain constraint must be a non-empty hostname")
    candidate = value.strip().rstrip(".").casefold()
    parsed = urlsplit(f"//{candidate}")
    if (
        parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("domain constraint must contain only a hostname")
    try:
        return parsed.hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("domain constraint is not a valid hostname") from exc
