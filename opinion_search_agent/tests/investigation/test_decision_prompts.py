"""Decision prompts must ask for JSON: the model client always requests a JSON object."""

from opinion_search.investigation.context import INSTRUCTIONS
from opinion_search.investigation.service import PLAN_INSTRUCTIONS, REVIEW_INSTRUCTIONS


def test_every_decision_prompt_mentions_json() -> None:
    # gateways that enforce response_format=json_object reject a prompt without the word json
    for name, prompt in (
        ("planner", PLAN_INSTRUCTIONS),
        ("reviewer", REVIEW_INSTRUCTIONS),
        ("investigation", INSTRUCTIONS),
    ):
        assert "json" in prompt.casefold(), f"{name} prompt must ask for JSON"
