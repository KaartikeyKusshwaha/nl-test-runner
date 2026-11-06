from nlqa.judge import guard_pass
from nlqa.llm.fake import FakeLLM
from nlqa.models import AssertionRecord, Outcome, TestSpec, Verification


def case() -> tuple[TestSpec, list[AssertionRecord]]:
    spec = TestSpec(
        goal="Customer signs in",
        verifications=[Verification(id="v1", statement="Dashboard is shown")],
    )
    records = [
        AssertionRecord(
            verification_id="v1",
            kind="text_visible",
            args={"text": "Customer dashboard"},
            passed=True,
            detail="text 'Customer dashboard' visible",
            step=3,
        )
    ]
    return spec, records


def test_judge_keeps_supported_candidate_pass() -> None:
    spec, records = case()
    result = guard_pass(
        FakeLLM(json_responses=[{"results": [{"id": "v1", "supports": True, "why": "matches"}]}]),
        spec,
        records,
        "Customer dashboard",
    )
    assert result.outcome is Outcome.PASS


def test_judge_only_downgrades_when_support_is_weak() -> None:
    spec, records = case()
    result = guard_pass(
        FakeLLM(
            json_responses=[{"results": [{"id": "v1", "supports": False, "why": "unrelated"}]}]
        ),
        spec,
        records,
        "Some unrelated page",
    )
    assert result.outcome is Outcome.ERROR
    assert "insufficient evidence" in result.reason


def test_judge_malformed_or_missing_response_downgrades() -> None:
    spec, records = case()
    result = guard_pass(FakeLLM(), spec, records, "Customer dashboard")
    assert result.outcome is Outcome.ERROR
