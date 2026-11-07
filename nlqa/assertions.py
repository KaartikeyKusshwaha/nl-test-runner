"""Polled browser assertions that record actual evidence for each verification."""

from __future__ import annotations

import time
from typing import Any

from nlqa.actions import BrowserController
from nlqa.models import AssertionRecord, ToolCall
from nlqa.observe import observe


def run_assertion(
    call: ToolCall,
    controller: BrowserController,
    *,
    step: int,
    safe_args: dict[str, Any] | None = None,
    timeout_ms: int = 5000,
) -> AssertionRecord:
    """Evaluate one assertion deterministically and include the observed result."""
    name = call.name
    args = call.args
    verification_id = str(args["verification_id"])
    window_ms = min(timeout_ms, 1500) if name == "assert_text_absent" else timeout_ms
    deadline = time.monotonic() + window_ms / 1000
    passed = False
    observed = ""
    if name == "assert_text_absent":
        text = str(args["text"])
        passed = True
        while time.monotonic() < deadline:
            if controller.text_is_visible(text):
                passed = False
                observed = (
                    f"text {controller.secret_store.mask(text)!r} became visible; "
                    f"url={controller.page.url}"
                )
                break
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))
        if passed:
            observed = (
                f"text {controller.secret_store.mask(text)!r} stayed absent for {window_ms}ms; "
                f"url={controller.page.url}"
            )
    else:
        while True:
            passed, observed = _evaluate_once(name, args, controller)
            if passed or time.monotonic() >= deadline:
                break
            time.sleep(0.25)
    detail = controller.secret_store.mask(observed)
    screenshot = controller.screenshot(step, f"assert-{verification_id}")
    kinds = {
        "assert_text_visible": "text_visible",
        "assert_text_absent": "text_absent",
        "assert_url_contains": "url_contains",
        "assert_element_visible": "element_visible",
        "assert_element_text": "element_text",
        "assert_element_state": "element_state",
        "assert_value": "value_equals",
    }
    return AssertionRecord(
        verification_id=verification_id,
        kind=kinds[name],
        args=safe_args if safe_args is not None else args,
        passed=passed,
        detail=detail,
        step=step,
        screenshot=screenshot,
    )


def _evaluate_once(
    name: str, args: dict[str, Any], controller: BrowserController
) -> tuple[bool, str]:
    if name == "assert_text_visible":
        text = str(args["text"])
        visible = controller.text_is_visible(text)
        return (
            visible,
            f"text {controller.secret_store.mask(text)!r} "
            f"{'visible' if visible else 'not visible'}; url={controller.page.url}",
        )
    if name == "assert_text_absent":
        text = str(args["text"])
        visible = controller.text_is_visible(text)
        return (
            not visible,
            f"text {controller.secret_store.mask(text)!r} "
            f"{'visible' if visible else 'absent'}; url={controller.page.url}",
        )
    if name == "assert_url_contains":
        expected = [str(args["substring"]), *map(str, args.get("also_contains", []))]
        actual = controller.page.url
        missing = [
            fragment for fragment in expected if fragment.casefold() not in actual.casefold()
        ]
        return (
            not missing,
            f"url={actual}; expected substrings="
            f"{controller.secret_store.mask_object(expected)!r}; "
            f"missing={controller.secret_store.mask_object(missing)!r}",
        )

    observation = observe(controller.page)
    _, locator = controller.resolve_ref(str(args["ref"]), observation)
    try:
        if name == "assert_element_visible":
            visible = locator.is_visible(timeout=500)
            return visible, f"element {args['ref']} visible={visible}"
        if name == "assert_element_text":
            expected = str(args["text"])
            actual = locator.inner_text(timeout=500)
            normalized_actual = " ".join(actual.split()).casefold()
            normalized_expected = " ".join(expected.split()).casefold()
            exact = args.get("exact", False)
            matched = (
                normalized_actual == normalized_expected
                if exact
                else normalized_expected in normalized_actual
            )
            return (
                matched,
                f"element text={controller.secret_store.mask(actual[:300])!r}; "
                f"expected={controller.secret_store.mask(expected)!r}; "
                f"match={'exact' if exact else 'contains'}",
            )
        if name == "assert_element_state":
            expected = str(args["state"])
            if expected == "enabled":
                actual = locator.is_enabled(timeout=500)
                return actual, f"element {args['ref']} enabled={actual}"
            if expected == "disabled":
                actual = not locator.is_enabled(timeout=500)
                return actual, f"element {args['ref']} disabled={actual}"
            try:
                checked = locator.is_checked(timeout=500)
            except Exception:
                checked = locator.get_attribute("aria-checked") == "true"
            actual = checked if expected == "checked" else not checked
            return actual, f"element {args['ref']} checked={checked}; expected={expected}"
        if name == "assert_value":
            expected = str(args["expected"])
            actual = locator.input_value(timeout=500)
            return (
                actual == expected,
                f"field value={controller.secret_store.mask(actual)!r}; "
                f"expected={controller.secret_store.mask(expected)!r}",
            )
    except Exception as exc:
        return (
            False,
            f"could not inspect {args.get('ref', 'element')}: {type(exc).__name__}; "
            f"url={controller.page.url}",
        )
    raise ValueError(f"Unsupported assertion tool: {name}")
