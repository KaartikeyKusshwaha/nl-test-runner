"""OpenAI Chat Completions adapter, also used for compatible APIs."""

from __future__ import annotations

import json
import random
import time
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from nlqa.llm.base import LLMError, Usage, openai_tool
from nlqa.models import ToolCall


class OpenAIClient:
    """Provider adapter using forced function calls and bounded retries."""

    provider = "openai"

    def __init__(
        self, *, api_key: str, model: str, base_url: str | None = None, max_tokens: int = 1200
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0, timeout=30)
        self.usage = Usage()

    def choose_tool(
        self, *, system: str, user: str, tools: list[dict[str, Any]]
    ) -> ToolCall | None:
        response = self._request(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            tools=[openai_tool(tool) for tool in tools],
            tool_choice="required",
            temperature=0,
            max_completion_tokens=self.max_tokens,
        )
        message = response.choices[0].message
        if not message.tool_calls:
            return None
        call = message.tool_calls[0]
        try:
            return ToolCall(name=call.function.name, args=json.loads(call.function.arguments))
        except (ValueError, TypeError):
            return None

    def complete_json(self, *, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        tool = {
            "name": "return_json",
            "description": "Return the requested structured JSON object.",
            "parameters": schema,
        }
        response = self._request(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            tools=[openai_tool(tool)],
            tool_choice={"type": "function", "function": {"name": "return_json"}},
            temperature=0,
            max_completion_tokens=self.max_tokens,
        )
        message = response.choices[0].message
        if not message.tool_calls:
            raise LLMError("The model did not return the required JSON tool call.")
        try:
            parsed = json.loads(message.tool_calls[0].function.arguments)
        except (ValueError, TypeError) as exc:
            raise LLMError("The model returned invalid JSON.") from exc
        if not isinstance(parsed, dict):
            raise LLMError("The model returned JSON with the wrong top-level type.")
        return parsed

    def _request(self, **kwargs: Any) -> Any:
        last_status: int | None = None
        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(model=self.model, **kwargs)
                self.usage.add(response.usage)
                return response
            except (RateLimitError, APITimeoutError, APIConnectionError) as exc:
                if attempt == 2:
                    raise LLMError(
                        "The model request failed after three retryable attempts."
                    ) from exc
            except APIStatusError as exc:
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
