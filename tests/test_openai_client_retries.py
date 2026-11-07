from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from openai import BadRequestError, RateLimitError

from nlqa.llm.base import LLMError, LLMRateLimitError
from nlqa.llm.openai_client import OpenAIClient, _duration_seconds, _retry_delay_seconds


def test_duration_seconds_parses_provider_reset_formats() -> None:
    assert _duration_seconds("7.66s") == pytest.approx(7.66)
    assert _duration_seconds("2m59.56s") == pytest.approx(179.56)
    assert _duration_seconds("invalid") is None


def test_retry_delay_uses_longest_token_reset_header() -> None:
    response = SimpleNamespace(
        status_code=429,
        request=SimpleNamespace(method="POST", url="https://api.example.test"),
        headers={
            "retry-after": "2",
            "x-ratelimit-reset-tokens": "7.25s",
            "x-ratelimit-remaining-requests": "12",
        },
    )
    error = RateLimitError(
        "rate limited",
        response=response,
        body={"error": {"code": "rate_limit_exceeded"}},
    )

    assert _retry_delay_seconds(error, 0) == pytest.approx(7.25)


def test_tool_use_failed_gets_one_quiet_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    client = OpenAIClient(api_key="test", model="test-model")
    response = SimpleNamespace(
        status_code=400,
        headers={},
        request=SimpleNamespace(method="POST", url="https://api.example.test"),
    )
    error = BadRequestError(
        "tool call could not be parsed",
        response=response,
        body={"error": {"code": "tool_use_failed", "message": "invalid tool response"}},
    )
    error.code = "tool_use_failed"
    success = SimpleNamespace(usage=None)
    create = Mock(side_effect=[error, success])
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    monkeypatch.setattr("nlqa.llm.openai_client.time.sleep", Mock())

    assert client._request(messages=[]) is success
    assert create.call_count == 2


def test_tool_use_failed_stops_after_one_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    client = OpenAIClient(api_key="test", model="test-model")
    response = SimpleNamespace(
        status_code=400,
        headers={},
        request=SimpleNamespace(method="POST", url="https://api.example.test"),
    )
    error = BadRequestError(
        "tool call could not be parsed",
        response=response,
        body={"error": {"code": "tool_use_failed", "message": "invalid tool response"}},
    )
    error.code = "tool_use_failed"
    create = Mock(side_effect=[error, error])
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    monkeypatch.setattr("nlqa.llm.openai_client.time.sleep", Mock())

    with pytest.raises(LLMError, match="usable tool call after retry"):
        client._request(messages=[])
    assert create.call_count == 2


def test_long_server_cooldown_stops_without_retry_or_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = OpenAIClient(api_key="test", model="test-model")
    response = SimpleNamespace(
        status_code=429,
        headers={"retry-after": "481"},
        request=SimpleNamespace(method="POST", url="https://api.example.test"),
    )
    error = RateLimitError(
        "rate limited",
        response=response,
        body={"error": {"code": "rate_limit_exceeded"}},
    )
    create = Mock(side_effect=[error])
    sleep = Mock()
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    monkeypatch.setattr("nlqa.llm.openai_client.time.sleep", sleep)

    with pytest.raises(LLMRateLimitError, match="retry in 481 seconds"):
        client._request(messages=[])

    assert create.call_count == 1
    sleep.assert_not_called()


def test_short_server_cooldown_retries_with_bounded_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    client = OpenAIClient(api_key="test", model="test-model")
    response = SimpleNamespace(
        status_code=429,
        headers={"retry-after": "1"},
        request=SimpleNamespace(method="POST", url="https://api.example.test"),
    )
    error = RateLimitError(
        "rate limited",
        response=response,
        body={"error": {"code": "rate_limit_exceeded"}},
    )
    success = SimpleNamespace(usage=None)
    create = Mock(side_effect=[error, success])
    sleep = Mock()
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    monkeypatch.setattr("nlqa.llm.openai_client.time.sleep", sleep)

    assert client._request(messages=[]) is success
    assert create.call_count == 2
    sleep.assert_called_once_with(1.0)
