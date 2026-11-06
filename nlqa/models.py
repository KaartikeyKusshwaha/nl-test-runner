"""Validated data contracts shared by the agent, adapters, and reporting layer."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Verification(BaseModel):
    """One condition that needs observable browser evidence."""

    id: str = Field(min_length=1)
    statement: str = Field(min_length=3)
    implicit: bool = False


class TestSpec(BaseModel):
    """Structured form of a plain-English browser test."""

    __test__ = False

    goal: str = Field(min_length=1)
    start_url: str | None = None
    steps: list[str] = Field(default_factory=list)
    verifications: list[Verification] = Field(min_length=1)
    data: dict[str, str] = Field(default_factory=dict)

    @field_validator("verifications")
    @classmethod
    def unique_verification_ids(cls, values: list[Verification]) -> list[Verification]:
        ids = [item.id for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError("verification ids must be unique")
        return values


class ToolCall(BaseModel):
    """One proposed browser tool call."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)


class AssertionRecord(BaseModel):
    """Deterministic evidence collected for one verification."""

    verification_id: str
    kind: str
    args: dict[str, Any] = Field(default_factory=dict)
    passed: bool
    detail: str
    step: int
    screenshot: str | None = None


class StepRecord(BaseModel):
    """Result of one browser action or assertion."""

    n: int
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    ok: bool
    result: str
    url_after: str
    screenshot: str | None = None
    duration_ms: int = 0
    llm_note: str | None = None


class Outcome(StrEnum):
    """User-facing terminal state."""

    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


class RunResult(BaseModel):
    """Complete machine-readable result and evidence for one test case."""

    outcome: Outcome
    reason: str
    spec: TestSpec
    steps: list[StepRecord] = Field(default_factory=list)
    assertions: list[AssertionRecord] = Field(default_factory=list)
    verification_status: dict[str, str] = Field(default_factory=dict)
    llm_usage: dict[str, int] = Field(default_factory=dict)
    model: str = ""
    provider: str = ""
    started_at: str
    duration_ms: int
    artifacts: dict[str, str | list[str] | None] = Field(default_factory=dict)
