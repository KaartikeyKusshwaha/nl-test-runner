"""Factory for configured provider adapters."""

from __future__ import annotations

from nlqa.config import Settings
from nlqa.llm.anthropic_client import AnthropicClient
from nlqa.llm.base import LLMClient, LLMError
from nlqa.llm.fake import FakeLLM
from nlqa.llm.openai_client import OpenAIClient


def create_client(settings: Settings, *, fake: FakeLLM | None = None) -> LLMClient:
    """Construct an LLM adapter from environment-backed settings."""
    error = settings.provider_error()
    if error:
        raise LLMError(error)
    if settings.llm_provider == "fake":
        if fake is None:
            raise LLMError("Fake provider needs a scripted FakeLLM instance.")
        return fake
    if settings.llm_provider == "anthropic":
        assert settings.anthropic_api_key is not None
        return AnthropicClient(
            api_key=settings.anthropic_api_key.get_secret_value(),
            model=settings.llm_model,
            max_tokens=settings.nlqa_max_tokens,
        )
    assert settings.openai_api_key is not None
    base_url = settings.llm_base_url if settings.llm_provider == "openai_compatible" else None
    return OpenAIClient(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.llm_model,
        base_url=base_url,
        max_tokens=settings.nlqa_max_tokens,
    )
