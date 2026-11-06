from pathlib import Path
from tempfile import TemporaryDirectory

from nlqa.actions import BrowserController
from nlqa.assertions import run_assertion
from nlqa.models import ToolCall


def test_text_url_value_and_element_state_assertions(page) -> None:
    page.set_content(
        """<h1>Customer dashboard</h1><input value="ready"><button disabled>Continue</button>"""
    )
    controller = BrowserController(page)
    snapshot = controller.snapshot()
    heading_ref = next(item["ref"] for item in snapshot.elements if item["ref"].startswith("e"))
    results = [
        run_assertion(
            ToolCall(
                name="assert_text_visible",
                args={"text": "Customer dashboard", "verification_id": "v1"},
            ),
            controller,
            step=1,
            timeout_ms=100,
        ),
        run_assertion(
            ToolCall(
                name="assert_url_contains",
                args={"substring": "about:blank", "verification_id": "v1"},
            ),
            controller,
            step=2,
            timeout_ms=100,
        ),
    ]
    # Find the actual text input and disabled button refs from the current observation.
    input_ref = next(
        line.split("]", 1)[0][1:] for line in snapshot.lines if 'input "ready"' in line
    )
    button_ref = next(line.split("]", 1)[0][1:] for line in snapshot.lines if "disabled" in line)
    results.extend(
        [
            run_assertion(
                ToolCall(
                    name="assert_value",
                    args={"ref": input_ref, "expected": "ready", "verification_id": "v1"},
                ),
                controller,
                step=3,
                timeout_ms=100,
            ),
            run_assertion(
                ToolCall(
                    name="assert_element_state",
                    args={"ref": button_ref, "state": "disabled", "verification_id": "v1"},
                ),
                controller,
                step=4,
                timeout_ms=100,
            ),
        ]
    )
    assert all(result.passed for result in results)
    assert heading_ref


def test_absent_assertion_must_remain_absent_for_the_window(page) -> None:
    page.set_content(
        "<body><h1>Waiting</h1><script>setTimeout(() => {\n"
        "const e = document.createElement('p');\n"
        "e.textContent = 'Dashboard ready';\n"
        "document.body.append(e);\n"
        "}, 100);</script></body>"
    )
    controller = BrowserController(page)
    with TemporaryDirectory(dir=".", prefix="assertion-artifacts-") as directory:
        controller.report_dir = Path(directory)
        result = run_assertion(
            ToolCall(
                name="assert_text_absent", args={"text": "Dashboard ready", "verification_id": "v1"}
            ),
            controller,
            step=1,
            timeout_ms=500,
        )
        assert result.passed is False
