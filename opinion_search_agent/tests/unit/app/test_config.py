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
