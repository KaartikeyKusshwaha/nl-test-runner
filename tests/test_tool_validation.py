from nlqa.models import ToolCall
from nlqa.observe import Observation
from nlqa.tools import validate_tool_call


def observation() -> Observation:
    return Observation(
        title="",
        url="https://example.test/",
        elements=[{"ref": "e1"}],
        lines=["[e1] link: 1"],
        text="1",
        headings=[],
        alerts=[],
        hash="test",
    )


def test_numeric_counter_assertions_allow_short_values() -> None:
    call = ToolCall(
        name="assert_element_text",
        args={"ref": "e1", "contains": "1", "verification_id": "v1"},
    )

    assert validate_tool_call(call, observation(), {"v1"}) is None


def test_short_non_numeric_assertions_remain_rejected() -> None:
    call = ToolCall(
        name="assert_text_visible",
        args={"text": "a", "verification_id": "v1"},
    )

    assert "distinctive" in (validate_tool_call(call, observation(), {"v1"}) or "")
