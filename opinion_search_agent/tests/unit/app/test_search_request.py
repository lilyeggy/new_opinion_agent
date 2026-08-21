import pytest
from pydantic import ValidationError

from opinion_search.app.contracts import SearchRequest


def test_minimal_request_uses_expected_defaults() -> None:
    request = SearchRequest(question=" What happened? ")

    assert request.question == "What happened?"
    assert request.topic is None
    assert request.time_range is None
    assert request.focus is None
    assert request.language == "zh"
    assert request.include_domains == ()
    assert request.exclude_domains == ()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"question": ""},
        {"question": "   "},
        {"question": "\n\t"},
    ],
)
def test_request_rejects_missing_or_blank_question(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        SearchRequest.model_validate(payload)


def test_request_accepts_and_serializes_all_supported_fields() -> None:
    payload = {
        "question": "What did the organization announce?",
        "topic": "Example Organization",
        "time_range": "2026-08-01 to 2026-08-05",
        "focus": "official announcement",
        "language": "en",
        "include_domains": ["example.gov", "example.org"],
        "exclude_domains": ["spam.example"],
    }

    request = SearchRequest.model_validate(payload)

    assert request.include_domains == ("example.gov", "example.org")
    assert request.exclude_domains == ("spam.example",)
    assert request.model_dump(mode="json") == payload


def test_domain_constraints_are_normalized_and_reject_urls() -> None:
    request = SearchRequest(
        question="What happened?",
        include_domains=("NEWS.Example.COM.", "例子.测试"),
    )

    assert request.include_domains == (
        "news.example.com",
        "xn--fsqu00a.xn--0zwm56d",
    )
    with pytest.raises(ValidationError, match="only a hostname"):
        SearchRequest(
            question="What happened?",
            exclude_domains=("https://example.com/path",),
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "budget_profile",
        "output_mode",
    ],
)
def test_request_rejects_legacy_control_fields(
    field_name: str,
) -> None:
    payload = {
        "question": "What happened?",
        field_name: "legacy-value",
    }

    with pytest.raises(ValidationError):
        SearchRequest.model_validate(payload)


def test_domain_collections_are_isolated_between_requests() -> None:
    first = SearchRequest(
        question="First question",
        include_domains=["example.com"],
    )
    second = SearchRequest(question="Second question")

    assert first.include_domains == ("example.com",)
    assert second.include_domains == ()


def test_request_rejects_unknown_fields() -> None:
    payload = {
        "question": "What happened?",
        "budegt_profile": "fast",
    }

    with pytest.raises(ValidationError):
        SearchRequest.model_validate(payload)


def test_request_is_immutable_after_creation() -> None:
    request = SearchRequest(question="What happened?")

    with pytest.raises(ValidationError):
        request.question = "A different question"
