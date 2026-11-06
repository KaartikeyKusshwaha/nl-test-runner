"""Provider-neutral language-model interface and usage counters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from nlqa.models import ToolCall


@dataclass(slots=True)
class Usage:
    """Cumulative model usage without retaining request or credential contents."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, response_usage: Any) -> None:
        self.calls += 1
        self.input_tokens += int(
            getattr(response_usage, "prompt_tokens", None)
            or getattr(response_usage, "input_tokens", 0)
            or 0
        )
        self.output_tokens += int(
            getattr(response_usage, "completion_tokens", None)
            or getattr(response_usage, "output_tokens", 0)
            or 0
        )


class LLMError(RuntimeError):
    """Safe, provider-neutral model error that never includes a credential."""


class LLMClient(Protocol):
    """Operations needed by spec extraction, tool selection, and evidence review."""

    provider: str
    model: str
    usage: Usage

    def ping(self) -> None: ...

    def choose_tool(
        self, *, system: str, user: str, tools: list[dict[str, Any]]
    ) -> ToolCall | None: ...

    def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]: ...


def openai_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Convert the shared tool contract to the OpenAI Chat Completions format."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"],
        },
    }
