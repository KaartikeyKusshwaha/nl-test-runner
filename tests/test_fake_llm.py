from nlqa.llm.fake import FakeLLM
from nlqa.models import ToolCall


def test_fake_llm_returns_scripted_tools_and_json() -> None:
    fake = FakeLLM(
        tool_calls=[ToolCall(name="click", args={"ref": "e1"})],
        json_responses=[{"goal": "Search", "verifications": []}],
    )
    call = fake.choose_tool(system="system", user="page", tools=[])
    json_value = fake.complete_json(system="extract", user="test", schema={})
    assert call == ToolCall(name="click", args={"ref": "e1"})
    assert json_value == {"goal": "Search", "verifications": []}
    assert fake.usage.calls == 2
    assert fake.prompts == [("system", "page"), ("extract", "test")]


def test_fake_llm_returns_none_when_script_is_exhausted() -> None:
    fake = FakeLLM()
    assert fake.choose_tool(system="s", user="u", tools=[]) is None
