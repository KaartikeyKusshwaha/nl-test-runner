"""Environment-backed configuration for the command-line runner."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. API credentials are never included in repr output."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    llm_provider: Literal["openai", "anthropic", "openai_compatible", "fake"] = "openai"
    llm_model: str = ""
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    nlqa_max_steps: int = Field(default=30, ge=1, le=100)
    nlqa_max_seconds: int = Field(default=240, ge=1, le=1800)
    nlqa_action_timeout_ms: int = Field(default=10000, ge=100, le=60000)
    nlqa_headless: bool = True
    nlqa_judge: bool = True
    nlqa_assert_timeout_ms: int = Field(default=5000, ge=100, le=30000)
    nlqa_max_elements: int = Field(default=60, ge=10, le=500)
    nlqa_report_dir: str = "reports"
    nlqa_allow_domain: list[str] = Field(default_factory=list)
    nlqa_slowmo_ms: int = Field(default=0, ge=0, le=2000)
    nlqa_max_consecutive_errors: int = Field(default=4, ge=1, le=10)
    nlqa_max_tokens: int = Field(default=512, ge=128, le=8192)

    @field_validator("llm_model")
    @classmethod
    def strip_model(cls, value: str) -> str:
        return value.strip()

    def provider_error(self) -> str | None:
        """Return a safe setup hint when the selected provider is not configured."""
        if self.llm_provider == "fake":
            return None
        if not self.llm_model:
            return "LLM_MODEL is not set. Choose a model identifier in .env."
        if self.llm_provider == "openai" and not self.openai_api_key:
            return "OPENAI_API_KEY is not set. Add it to .env or the environment."
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            return "ANTHROPIC_API_KEY is not set. Add it to .env or the environment."
        if self.llm_provider == "openai_compatible" and not (
            self.openai_api_key and self.llm_base_url
        ):
            return "OpenAI-compatible mode needs OPENAI_API_KEY and LLM_BASE_URL."
        return None
