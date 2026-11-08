"""OpenAI Chat Completions adapter, also used for compatible APIs."""

from __future__ import annotations

import json
import random
import re
import time
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from nlqa.llm.base import LLMError, LLMRateLimitError, Usage, openai_tool
from nlqa.models import ToolCall

_RETRY_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)", re.IGNORECASE)
_MAX_ATTEMPTS = 2
_MAX_RETRY_DELAY_SECONDS = 2.0
_MAX_SERVER_COOLDOWN_SECONDS = 60.0
_API_KEY_PATTERN = re.compile(r"(?i)(?:gsk_|sk-)[A-Za-z0-9_-]{12,}")


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


def _server_retry_after_seconds(exc: RateLimitError) -> float | None:
    """Return the provider's explicit cooldown without shortening it."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {})
    return _duration_seconds(headers.get("retry-after"))


def _safe_provider_error(exc: APIStatusError) -> str:
    """Extract a short provider hint while removing key-shaped strings."""
    body = getattr(exc, "body", None)
    response = getattr(exc, "response", None)
    if not isinstance(body, dict) and response is not None:
        try:
            body = response.json()
        except Exception:
            body = None
    message = ""
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("code") or "")
        elif isinstance(error, str):
            message = error
    if not message:
        message = str(getattr(exc, "message", ""))
    if message.startswith("Error code:") and response is not None:
        try:
            text = str(response.text).strip()
        except Exception:
            text = ""
        if text:
            message = text
    message = " ".join(message.split())
    message = _API_KEY_PATTERN.sub("[redacted]", message)
    return message[:240]


class OpenAIClient:
    """Provider adapter using forced function calls and bounded retries."""

    provider = "openai"

    def __init__(
        self, *, api_key: str, model: str, base_url: str | None = None, max_tokens: int = 512
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.base_url = base_url
        self.client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0, timeout=20)
        self.usage = Usage()

    def _reasoning_kwargs(self) -> dict[str, Any]:
        """Hide GPT-OSS reasoning using the SDK's supported arbitrary-body option."""
        if self.base_url and "groq.com" in self.base_url.casefold():
            return {"extra_body": {"reasoning_format": "hidden"}}
        return {}

    def choose_tool(
        self, *, system: str, user: str, tools: list[dict[str, Any]]
    ) -> ToolCall | None:
        response = self._request(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            tools=[openai_tool(tool) for tool in tools],
            tool_choice="required",
            **self._reasoning_kwargs(),
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
            self._request(
                messages=[{"role": "user", "content": "Reply with the single digit 1."}],
                max_completion_tokens=1,
                temperature=0,
            )
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(f"The provider ping failed ({type(exc).__name__}).") from exc

    def complete_json(self, *, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        schema_text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        response = self._request(
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"{system}\n\nReturn one JSON object only. "
                        "It must match the supplied schema."
                    ),
                },
                {
                    "role": "user",
                    "content": f"{user}\n\nJSON SCHEMA:\n{schema_text}",
                },
            ],
            response_format={"type": "json_object"},
            **self._reasoning_kwargs(),
            temperature=0,
            max_completion_tokens=self.max_tokens,
        )
        message = response.choices[0].message
        try:
            parsed = json.loads(message.content)
        except (ValueError, TypeError) as exc:
            raise LLMError("The model returned invalid JSON.") from exc
        if not isinstance(parsed, dict):
            raise LLMError("The model returned JSON with the wrong top-level type.")
        return parsed

    def _request(self, **kwargs: Any) -> Any:
        last_status: int | None = None
        retried_tool_failure = False
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = self.client.chat.completions.create(model=self.model, **kwargs)
                self.usage.add(response.usage)
                return response
            except (RateLimitError, APITimeoutError, APIConnectionError) as exc:
                if isinstance(exc, RateLimitError):
                    retry_after = _server_retry_after_seconds(exc)
                    if retry_after is not None and retry_after > _MAX_SERVER_COOLDOWN_SECONDS:
                        raise LLMRateLimitError(retry_after) from exc
                if attempt == _MAX_ATTEMPTS - 1:
                    if isinstance(exc, RateLimitError):
                        raise LLMRateLimitError(_server_retry_after_seconds(exc)) from exc
                    raise LLMError(
                        "The model request failed after two retryable attempts "
                        f"({type(exc).__name__})."
                    ) from exc
                delay = (
                    _server_retry_after_seconds(exc) if isinstance(exc, RateLimitError) else None
                )
                max_delay = (
                    _MAX_SERVER_COOLDOWN_SECONDS if delay is not None else _MAX_RETRY_DELAY_SECONDS
                )
                time.sleep(
                    min(
                        delay if delay is not None else _retry_delay_seconds(exc, attempt),
                        max_delay,
                    )
                )
                continue
            except APIStatusError as exc:
                last_status = exc.status_code
                if exc.code == "tool_use_failed":
                    if retried_tool_failure or attempt == _MAX_ATTEMPTS - 1:
                        raise LLMError(
                            "The model did not return a usable tool call after retry."
                        ) from exc
                    retried_tool_failure = True
                    time.sleep(0.25)
                    continue
                if exc.status_code < 500 and exc.status_code != 429:
                    hint = _safe_provider_error(exc)
                    suffix = f": {hint}" if hint else ""
                    raise LLMError(
                        f"The model rejected the request (HTTP {exc.status_code}){suffix}."
                    ) from exc
                if attempt == _MAX_ATTEMPTS - 1:
                    raise LLMError(
                        f"The model request failed after two attempts (HTTP {last_status})."
                    ) from exc
                time.sleep(min(_retry_delay_seconds(exc, attempt), _MAX_RETRY_DELAY_SECONDS))
                continue
            except Exception as exc:
                if attempt == _MAX_ATTEMPTS - 1:
                    raise LLMError(
                        f"The model request failed after two attempts ({type(exc).__name__})."
                    ) from exc
            time.sleep(min(0.3 * (2**attempt) + random.random() * 0.1, 2.0))
        raise LLMError("The model request could not be completed.")
