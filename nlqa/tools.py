"""Shared JSON-schema definitions and defensive argument validation."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from nlqa.models import ToolCall
from nlqa.observe import Observation

_EMPTY = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _string(description: str, *, enum: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string", "description": description}
    if enum is not None:
        schema["enum"] = enum
    return schema


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "navigate",
        "description": "Open an HTTP or HTTPS URL.",
        "parameters": _object({"url": _string("Destination URL")}, ["url"]),
    },
    {
        "name": "click",
        "description": "Click a current interactive element reference.",
        "parameters": _object({"ref": _string("Current [eN] or [fN:eN] reference")}, ["ref"]),
    },
    {
        "name": "type",
        "description": "Type text into a current input reference.",
        "parameters": _object(
            {
                "ref": _string("Current element reference"),
                "text": _string("Text or {{ENV_VAR}} placeholder"),
                "clear_first": {"type": "boolean"},
                "press_enter": {"type": "boolean"},
            },
            ["ref", "text"],
        ),
    },
    {
        "name": "select_option",
        "description": "Choose a label in a native select element.",
        "parameters": _object(
            {
                "ref": _string("Current select reference"),
                "option_label": _string("Visible option label"),
            },
            ["ref", "option_label"],
        ),
    },
    {
        "name": "press_key",
        "description": "Press a keyboard key on the focused page.",
        "parameters": _object({"key": _string("Playwright key name")}, ["key"]),
    },
    {
        "name": "hover",
        "description": "Hover over a current interactive element reference.",
        "parameters": _object({"ref": _string("Current element reference")}, ["ref"]),
    },
    {
        "name": "scroll",
        "description": "Scroll the page a bounded amount.",
        "parameters": _object(
            {
                "direction": _string("Scroll direction", enum=["up", "down"]),
                "amount": {"type": "integer", "minimum": 1, "maximum": 2000},
            },
            ["direction"],
        ),
    },
    {"name": "go_back", "description": "Navigate back one history entry.", "parameters": _EMPTY},
    {
        "name": "wait",
        "description": "Wait briefly for asynchronous page updates.",
        "parameters": _object(
            {"seconds": {"type": "number", "minimum": 0, "maximum": 5}}, ["seconds"]
        ),
    },
    {
        "name": "wait_for_text",
        "description": "Wait for visible text without creating verdict evidence.",
        "parameters": _object(
            {
                "text": _string("Visible text"),
                "timeout_s": {"type": "number", "minimum": 0.1, "maximum": 10},
            },
            ["text"],
        ),
    },
    {
        "name": "assert_text_visible",
        "description": "Record whether exact text is visible in any frame.",
        "parameters": _object(
            {
                "text": _string("Distinctive visible text"),
                "verification_id": _string("Verification id"),
            },
            ["text", "verification_id"],
        ),
    },
    {
        "name": "assert_text_absent",
        "description": "Record whether text remains absent during a short poll window.",
        "parameters": _object(
            {
                "text": _string("Distinctive text that should be absent"),
                "verification_id": _string("Verification id"),
            },
            ["text", "verification_id"],
        ),
    },
    {
        "name": "assert_url_contains",
        "description": "Record whether the current URL contains a substring.",
        "parameters": _object(
            {"substring": _string("URL substring"), "verification_id": _string("Verification id")},
            ["substring", "verification_id"],
        ),
    },
    {
        "name": "assert_element_visible",
        "description": "Record whether a current element reference is visible.",
        "parameters": _object(
            {
                "ref": _string("Current element reference"),
                "verification_id": _string("Verification id"),
            },
            ["ref", "verification_id"],
        ),
    },
    {
        "name": "assert_element_text",
        "description": "Record whether the referenced element contains text.",
        "parameters": _object(
            {
                "ref": _string("Current element reference"),
                "contains": _string("Expected text"),
                "verification_id": _string("Verification id"),
            },
            ["ref", "contains", "verification_id"],
        ),
    },
    {
        "name": "assert_element_state",
        "description": "Record a checkable control state.",
        "parameters": _object(
            {
                "ref": _string("Current element reference"),
                "state": _string(
                    "Expected state", enum=["enabled", "disabled", "checked", "unchecked"]
                ),
                "verification_id": _string("Verification id"),
            },
            ["ref", "state", "verification_id"],
        ),
    },
    {
        "name": "assert_value",
        "description": "Record whether a field value equals expected text.",
        "parameters": _object(
            {
                "ref": _string("Current element reference"),
                "expected": _string("Expected value"),
                "verification_id": _string("Verification id"),
            },
            ["ref", "expected", "verification_id"],
        ),
    },
    {
        "name": "finish",
        "description": "Finish with a gated pass, fail, or blocked verdict.",
        "parameters": _object(
            {
                "verdict": _string("Proposed outcome", enum=["pass", "fail", "blocked"]),
                "reason": _string("Brief reason"),
            },
            ["verdict", "reason"],
        ),
    },
]

TOOL_BY_NAME = {tool["name"]: tool for tool in TOOL_DEFINITIONS}
ASSERTION_TOOLS = {
    "assert_text_visible",
    "assert_text_absent",
    "assert_url_contains",
    "assert_element_visible",
    "assert_element_text",
    "assert_element_state",
    "assert_value",
}


def validate_tool_call(
    call: ToolCall, observation: Observation, verification_ids: set[str]
) -> str | None:
    """Return a safe validation error or `None` when a call is safe to execute."""
    tool = TOOL_BY_NAME.get(call.name)
    if tool is None:
        return f"Unknown tool '{call.name}'. Use one of the provided tools."
    properties = tool["parameters"].get("properties", {})
    required = tool["parameters"].get("required", [])
    unknown = set(call.args) - set(properties)
    missing = set(required) - set(call.args)
    if unknown:
        return f"Unexpected argument(s): {', '.join(sorted(unknown))}."
    if missing:
        return f"Missing required argument(s): {', '.join(sorted(missing))}."
    for key, value in call.args.items():
        spec = properties[key]
        expected_type = spec.get("type")
        valid_type = {
            "string": lambda item: isinstance(item, str),
            "boolean": lambda item: isinstance(item, bool),
            "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
            "number": lambda item: isinstance(item, int | float) and not isinstance(item, bool),
        }.get(expected_type, lambda _item: True)
        if not valid_type(value):
            return f"Argument '{key}' must be {expected_type}."
        if "enum" in spec and value not in spec["enum"]:
            return f"Argument '{key}' must be one of: {', '.join(spec['enum'])}."
        if isinstance(value, int | float) and not isinstance(value, bool):
            if (
                "minimum" in spec
                and value < spec["minimum"]
                or "maximum" in spec
                and value > spec["maximum"]
            ):
                return f"Argument '{key}' is outside the allowed range."
    if call.name == "navigate":
        parsed = urlparse(call.args["url"])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return "navigate only accepts absolute http:// or https:// URLs."
    if call.name in ASSERTION_TOOLS:
        verification_id = call.args.get("verification_id")
        if verification_id not in verification_ids:
            return f"Unknown verification_id '{verification_id}'."
        text = call.args.get("text", call.args.get("substring", call.args.get("contains", "")))
        if isinstance(text, str) and (
            len(text.strip()) < 3 or text.strip().lower() in {"the", "a", "an", "yes", "no"}
        ):
            return "Assertion text must be at least 3 distinctive characters and not a stop-word."
    if "ref" in call.args and call.args["ref"] not in {
        item["ref"] for item in observation.elements
    }:
        return f"ref {call.args['ref']} is stale or missing; use refs from the latest observation."
    return None
