import pytest

from opinion_search.app.config import LiveConfig


def test_live_config_uses_deepseek_flash_and_keeps_keys_secret() -> None:
    config = LiveConfig.from_env(
        {
            "OPINION_MODEL_API_KEY": "model-secret",
            "BRAVE_SEARCH_API_KEY": "search-secret",
        }
    )

    assert config.model_name == "deepseek-v4-flash"
    assert config.model_base_url == "https://opencode.ai/zen/go/v1"
    assert "model-secret" not in repr(config)
    assert "search-secret" not in repr(config)


def test_live_config_reports_all_missing_required_keys() -> None:
    with pytest.raises(ValueError) as captured:
        LiveConfig.from_env({})

    assert "OPINION_MODEL_API_KEY" in str(captured.value)
    assert "BRAVE_SEARCH_API_KEY" in str(captured.value)


def test_live_config_requires_explicit_boolean_for_insecure_loopback() -> None:
    config = LiveConfig.from_env(
        {
            "OPINION_MODEL_API_KEY": "model-secret",
            "BRAVE_SEARCH_API_KEY": "search-secret",
            "OPINION_ALLOW_INSECURE_MODEL_ENDPOINT": "true",
        }
    )

    assert config.allow_insecure_model_endpoint is True
    with pytest.raises(ValueError, match="boolean flag"):
        LiveConfig.from_env(
            {
                "OPINION_MODEL_API_KEY": "model-secret",
                "BRAVE_SEARCH_API_KEY": "search-secret",
                "OPINION_ALLOW_INSECURE_MODEL_ENDPOINT": "sometimes",
            }
        )


def test_live_config_accepts_legacy_baseurl_variable_spelling() -> None:
    config = LiveConfig.from_env(
        {
            "OPINION_MODEL_API_KEY": "model-secret",
            "BRAVE_SEARCH_API_KEY": "search-secret",
            "OPINION_MODEL_BASEURL": "https://models.example.com/v1",
        }
    )

    assert config.model_base_url == "https://models.example.com/v1"


def test_live_config_parses_extra_model_headers_from_json() -> None:
    config = LiveConfig.from_env(
        {
            "OPINION_MODEL_API_KEY": "model-secret",
            "BRAVE_SEARCH_API_KEY": "search-secret",
            "OPINION_MODEL_EXTRA_HEADERS": '{"x-opencode-session": "session-123"}',
        }
    )

    assert config.model_extra_headers == {"x-opencode-session": "session-123"}
    assert LiveConfig.from_env(
        {
            "OPINION_MODEL_API_KEY": "model-secret",
            "BRAVE_SEARCH_API_KEY": "search-secret",
        }
    ).model_extra_headers == {}


def test_live_config_rejects_malformed_extra_model_headers() -> None:
    for value in ("not-json", '["a"]', '{"x": 1}'):
        with pytest.raises(ValueError, match="OPINION_MODEL_EXTRA_HEADERS"):
            LiveConfig.from_env(
                {
                    "OPINION_MODEL_API_KEY": "model-secret",
                    "BRAVE_SEARCH_API_KEY": "search-secret",
                    "OPINION_MODEL_EXTRA_HEADERS": value,
                }
            )


def test_live_config_reads_timeout_and_transport_attempts_from_env() -> None:
    config = LiveConfig.from_env(
        {
            "OPINION_MODEL_API_KEY": "model-secret",
            "BRAVE_SEARCH_API_KEY": "search-secret",
            "OPINION_MODEL_TIMEOUT_SECONDS": "120",
            "OPINION_MODEL_TRANSPORT_ATTEMPTS": "4",
        }
    )

    assert config.model_timeout_seconds == 120
    assert config.model_transport_attempts == 4
    assert LiveConfig.from_env(
        {"OPINION_MODEL_API_KEY": "model-secret", "BRAVE_SEARCH_API_KEY": "search-secret"}
    ).model_transport_attempts == 3


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("OPINION_MODEL_TIMEOUT_SECONDS", "0"),
        ("OPINION_MODEL_TIMEOUT_SECONDS", "soon"),
        ("OPINION_MODEL_TRANSPORT_ATTEMPTS", "0"),
        ("OPINION_MODEL_TRANSPORT_ATTEMPTS", "many"),
    ],
)
def test_live_config_rejects_invalid_timeout_and_attempt_values(key: str, value: str) -> None:
    with pytest.raises(ValueError):
        LiveConfig.from_env(
            {
                "OPINION_MODEL_API_KEY": "model-secret",
                "BRAVE_SEARCH_API_KEY": "search-secret",
                key: value,
            }
        )


def test_live_config_tunes_decision_budget_and_output_cap_from_env() -> None:
    config = LiveConfig.from_env(
        {
            "OPINION_MODEL_API_KEY": "model-secret",
            "BRAVE_SEARCH_API_KEY": "search-secret",
            "OPINION_MAX_DECISION_ATTEMPTS": "4",
            "OPINION_MODEL_MAX_OUTPUT_TOKENS": "8192",
        }
    )

    assert config.max_decision_attempts == 4
    assert config.model_max_output_tokens == 8192
    defaults = LiveConfig.from_env(
        {"OPINION_MODEL_API_KEY": "model-secret", "BRAVE_SEARCH_API_KEY": "search-secret"}
    )
    assert defaults.max_decision_attempts == 3
    assert defaults.model_max_output_tokens == 4096
