"""Anthropic Messages adapter with forced tool use and bounded retries."""

from __future__ import annotations

import random
import time
from typing import Any

import anthropic
from anthropic import Anthropic

from nlqa.llm.base import LLMError, Usage
from nlqa.models import ToolCall


class AnthropicClient:
    """Anthropic provider adapter."""

    provider = "anthropic"

    def __init__(self, *, api_key: str, model: str, max_tokens: int = 512) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.client = Anthropic(api_key=api_key, max_retries=0, timeout=30)
        self.usage = Usage()

    def choose_tool(
        self, *, system: str, user: str, tools: list[dict[str, Any]]
    ) -> ToolCall | None:
        response = self._request(
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[
                {
                    "name": item["name"],
                    "description": item["description"],
                    "input_schema": item["parameters"],
                }
                for item in tools
            ],
            tool_choice={"type": "any"},
        )
        block = next(
            (item for item in response.content if getattr(item, "type", "") == "tool_use"), None
        )
        if block is None:
            return None
        try:
            return ToolCall(name=block.name, args=block.input)
        except (ValueError, TypeError):
            return None

    def ping(self) -> None:
        """Make the configured provider/model connectivity check with one output token."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1,
                temperature=0,
                messages=[{"role": "user", "content": "Reply with the single digit 1."}],
            )
            self.usage.calls += 1
            self.usage.input_tokens += int(response.usage.input_tokens or 0)
            self.usage.output_tokens += int(response.usage.output_tokens or 0)
        except Exception as exc:
            raise LLMError(f"The provider ping failed ({type(exc).__name__}).") from exc

    def complete_json(self, *, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        response = self._request(
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[
                {
                    "name": "return_json",
                    "description": "Return the requested structured JSON object.",
                    "input_schema": schema,
                }
            ],
            tool_choice={"type": "tool", "name": "return_json"},
        )
        block = next(
            (
                item
                for item in response.content
                if getattr(item, "type", "") == "tool_use" and item.name == "return_json"
            ),
            None,
        )
        if block is None or not isinstance(block.input, dict):
            raise LLMError("The model did not return the required JSON tool call.")
        return block.input

    def _request(self, **kwargs: Any) -> Any:
        last_status: int | None = None
        for attempt in range(3):
            try:
                response = self.client.messages.create(
                    model=self.model, max_tokens=self.max_tokens, temperature=0, **kwargs
                )
                self.usage.calls += 1
                self.usage.input_tokens += int(response.usage.input_tokens or 0)
                self.usage.output_tokens += int(response.usage.output_tokens or 0)
                return response
            except (
                anthropic.RateLimitError,
                anthropic.APITimeoutError,
                anthropic.APIConnectionError,
            ) as exc:
                if attempt == 2:
                    raise LLMError(
                        "The model request failed after three retryable attempts."
                    ) from exc
            except anthropic.APIStatusError as exc:
                last_status = exc.status_code
                if exc.status_code < 500 and exc.status_code != 429:
                    raise LLMError(
                        f"The model rejected the request (HTTP {exc.status_code}). "
                        "Check provider configuration."
                    ) from exc
                if attempt == 2:
                    raise LLMError(
                        f"The model request failed after three attempts (HTTP {last_status})."
                    ) from exc
            except Exception as exc:
                if attempt == 2:
                    raise LLMError("The model request failed after three attempts.") from exc
            time.sleep(min(0.3 * (2**attempt) + random.random() * 0.1, 2.0))
        raise LLMError("The model request could not be completed.")
