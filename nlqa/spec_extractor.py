"""Validated plain-English test-case extraction using the configured LLM."""

from __future__ import annotations

import re
from typing import Any

from nlqa.llm.base import LLMClient, LLMError
from nlqa.models import TestSpec
from nlqa.prompts import SPEC_EXTRACTOR_SYSTEM

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

SPEC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "goal": {"type": "string", "minLength": 1},
        "start_url": {"type": ["string", "null"]},
        "steps": {"type": "array", "items": {"type": "string"}},
        "verifications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "statement": {"type": "string", "minLength": 3},
                    "implicit": {"type": "boolean"},
                },
                "required": ["id", "statement", "implicit"],
                "additionalProperties": False,
            },
            "minItems": 1,
        },
        "data": {"type": "object", "additionalProperties": {"type": "string"}},
    },
    "required": ["goal", "start_url", "steps", "verifications", "data"],
    "additionalProperties": False,
}


class SpecExtractionError(RuntimeError):
    """Readable failure while turning the user's test text into a specification."""


def extract_spec(client: LLMClient, test_case: str) -> TestSpec:
    """Extract a TestSpec, preventing fabricated URLs from becoming navigation targets."""
    text = test_case.strip()
    if not text:
        raise SpecExtractionError("Test case text is empty.")
    try:
        raw = client.complete_json(
            system=SPEC_EXTRACTOR_SYSTEM,
            user=f"TEST CASE (user-provided text):\n{text}",
            schema=SPEC_SCHEMA,
        )
        raw = dict(raw)
        required_fields = {"goal", "start_url", "steps", "verifications", "data"}
        if not required_fields.issubset(raw):
            raise ValueError("required fields are missing")
        if set(raw) - required_fields:
            raise ValueError("unexpected fields were returned")
        explicit_urls = {match.rstrip(".,);]") for match in URL_PATTERN.findall(text)}
        candidate_url = raw.get("start_url")
        if candidate_url not in explicit_urls:
            raw["start_url"] = None
        verifications = raw.get("verifications")
        if not isinstance(verifications, list) or not verifications:
            raise SpecExtractionError(
                "The model did not identify a result to check. Add the expected page behavior "
                "or visible outcome to your test sentence."
            )
        implicit_count = sum(
            1
            for item in verifications
            if isinstance(item, dict) and item.get("implicit") is True
        )
        if implicit_count not in {0, 1} or (implicit_count == 1 and len(verifications) != 1):
            raise ValueError("implicit verification must be the only verification")
        return TestSpec.model_validate(raw)
    except LLMError as exc:
        raise SpecExtractionError(str(exc)) from exc
    except SpecExtractionError:
        raise
    except Exception as exc:
        raise SpecExtractionError(
            f"The model returned an invalid test specification ({type(exc).__name__})."
        ) from exc
