"""OpenAI Chat Completions adapter, also used for compatible APIs."""

from __future__ import annotations

import json
import random
import re
import time
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from nlqa.llm.base import LLMError, Usage, openai_tool
from nlqa.models import ToolCall

_RETRY_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)", re.IGNORECASE)


def _duration_seconds(value: str | None) -> float | None:
    """Parse a numeric or compound duration from an HTTP retry header."""
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        pass
    parts = list(_RETRY_PART.finditer(value.strip()))
    compact = re.sub(r"[\s,]", "", value.strip().lower())
    if not parts or "".join(match.group(0).lower() for match in parts) != compact:
        return None
    scale = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}
    return sum(float(match.group(1)) * scale[match.group(2).lower()] for match in parts)


def _retry_delay_seconds(exc: Exception, attempt: int) -> float:
    """Respect provider reset headers, with bounded exponential fallback."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {})
    delays = [
        parsed
        for name in ("retry-after", "x-ratelimit-reset-tokens")
        if (parsed := _duration_seconds(headers.get(name))) is not None
    ]
    if headers.get("x-ratelimit-remaining-requests") == "0":
        request_reset = _duration_seconds(headers.get("x-ratelimit-reset-requests"))
        if request_reset is not None:
            delays.append(request_reset)
    if delays:
        return min(max(max(delays), 0.25), 60.0)
    return min(0.5 * (2**attempt), 8.0)


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

    def ping(self) -> None:
        """Make the configured provider/model connectivity check with one output token."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Reply with the single digit 1."}],
                max_completion_tokens=1,
                temperature=0,
            )
            self.usage.add(response.usage)
        except Exception as exc:
            raise LLMError(f"The provider ping failed ({type(exc).__name__}).") from exc

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
        retried_tool_failure = False
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
                time.sleep(_retry_delay_seconds(exc, attempt))
                continue
            except APIStatusError as exc:
                last_status = exc.status_code
                if exc.code == "tool_use_failed":
                    if retried_tool_failure or attempt == 2:
                        raise LLMError(
                            "The model did not return a usable tool call after retry."
                        ) from exc
                    retried_tool_failure = True
                    time.sleep(0.25)
                    continue
                if exc.status_code < 500 and exc.status_code != 429:
                    raise LLMError(
                        f"The model rejected the request (HTTP {exc.status_code}). "
                        "Check provider configuration."
                    ) from exc
                if attempt == 2:
                    raise LLMError(
                        f"The model request failed after three attempts (HTTP {last_status})."
                    ) from exc
                time.sleep(_retry_delay_seconds(exc, attempt))
                continue
            except Exception as exc:
                if attempt == 2:
                    raise LLMError("The model request failed after three attempts.") from exc
            time.sleep(min(0.3 * (2**attempt) + random.random() * 0.1, 2.0))
        raise LLMError("The model request could not be completed.")
