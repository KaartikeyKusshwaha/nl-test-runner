"""Scripted, deterministic model for offline tests and local demos."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nlqa.llm.base import Usage
from nlqa.models import ToolCall


class FakeLLM:
    """Model stub that records prompts and returns a fixed script or callback result."""

    provider = "fake"
    model = "scripted"

    def __init__(
        self,
        tool_calls: list[ToolCall | dict[str, Any]]
        | Callable[[str, str], ToolCall | dict[str, Any] | None]
        | None = None,
        json_responses: list[dict[str, Any]] | None = None,
    ) -> None:
        self._tool_calls = (
            [ToolCall.model_validate(item) for item in tool_calls]
            if isinstance(tool_calls, list)
            else []
        )
        self._callable = tool_calls if callable(tool_calls) else None
        self._json_responses = list(json_responses or [])
        self.prompts: list[tuple[str, str]] = []
        self.usage = Usage()

    def choose_tool(
        self, *, system: str, user: str, tools: list[dict[str, Any]]
    ) -> ToolCall | None:
        self.prompts.append((system, user))
        self.usage.calls += 1
        if self._callable:
            response = self._callable(system, user)
            return ToolCall.model_validate(response) if response is not None else None
        return self._tool_calls.pop(0) if self._tool_calls else None

    def complete_json(self, *, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.prompts.append((system, user))
        self.usage.calls += 1
        return self._json_responses.pop(0) if self._json_responses else {}
