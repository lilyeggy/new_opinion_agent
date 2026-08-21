from __future__ import annotations

import os
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class LiveConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_api_key: SecretStr
    brave_search_api_key: SecretStr
    jina_api_key: SecretStr | None = None
    model_base_url: str = "https://opencode.ai/zen/go/v1"
    model_name: str = "deepseek-v4-flash"
    model_timeout_seconds: float = Field(default=60, gt=0)
    tool_timeout_seconds: float = Field(default=30, gt=0)
    max_steps: int = Field(default=20, ge=1)
    max_decision_attempts: int = Field(default=2, ge=1)
    max_context_tokens: int = Field(default=32_000, ge=2_000)
    output_headroom_tokens: int = Field(default=2_000, ge=256)
    allow_insecure_model_endpoint: bool = False

    @model_validator(mode="after")
    def validate_context_window(self) -> "LiveConfig":
        if self.output_headroom_tokens >= self.max_context_tokens:
            raise ValueError("output headroom must be smaller than the context window")
        return self

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "LiveConfig":
        values = os.environ if environ is None else environ
        model_key = values.get("OPINION_MODEL_API_KEY", "").strip()
        brave_search_key = values.get("BRAVE_SEARCH_API_KEY", "").strip()
        missing = []
        if not model_key:
            missing.append("OPINION_MODEL_API_KEY")
        if not brave_search_key:
            missing.append("BRAVE_SEARCH_API_KEY")
        if missing:
            raise ValueError(
                "live mode requires environment variables: " + ", ".join(missing)
            )
        return cls(
            model_api_key=model_key,
            brave_search_api_key=brave_search_key,
            jina_api_key=(values.get("JINA_API_KEY") or None),
            model_base_url=(
                values.get("OPINION_MODEL_BASE_URL")
                or values.get("OPINION_MODEL_BASEURL")
                or "https://opencode.ai/zen/go/v1"
            ),
            model_name=values.get(
                "OPINION_MODEL_NAME",
                "deepseek-v4-flash",
            ),
            allow_insecure_model_endpoint=_env_flag(
                values.get("OPINION_ALLOW_INSECURE_MODEL_ENDPOINT")
            ),
        )


def _env_flag(value: str | None) -> bool:
    if value is None or not value.strip():
        return False
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("OPINION_ALLOW_INSECURE_MODEL_ENDPOINT must be a boolean flag")
