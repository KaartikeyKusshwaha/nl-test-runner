from nlqa.models import AssertionRecord, Outcome, TestSpec, Verification
from nlqa.verdict import abort_verdict, evaluate_finish, verification_statuses


def make_spec() -> TestSpec:
    return TestSpec(
        goal="Check a customer login",
        verifications=[
            Verification(id="v1", statement="The dashboard is shown"),
            Verification(id="v2", statement="The welcome message is visible"),
        ],
    )


def record(identifier: str, passed: bool, detail: str = "observed text") -> AssertionRecord:
    return AssertionRecord(
        verification_id=identifier,
        kind="text_visible",
        args={"text": "dashboard"},
        passed=passed,
        detail=detail,
        step=1,
    )


def test_latest_assertion_controls_status() -> None:
    spec = make_spec()
    assert verification_statuses(spec, [record("v1", False), record("v1", True)]) == {
        "v1": "proven",
        "v2": "unproven",
    }
    assert verification_statuses(spec, [record("v1", True), record("v1", False)])["v1"] == "failed"


def test_finish_pass_needs_every_verification_proven() -> None:
    result = evaluate_finish("pass", "looks good", make_spec(), [record("v1", True)])
    assert result.accepted is False
    assert result.outcome is None
    assert "v2" in (result.feedback or "")


def test_finish_pass_accepts_all_proven_records() -> None:
    result = evaluate_finish("pass", "done", make_spec(), [record("v1", True), record("v2", True)])
    assert result.accepted is True
    assert result.outcome is Outcome.PASS


def test_finish_fail_requires_failed_evidence_and_uses_its_detail() -> None:
    rejected = evaluate_finish("fail", "model guess", make_spec(), [record("v1", True)])
    assert rejected.accepted is False
    assert "Prove the failure" in (rejected.feedback or "")
    accepted = evaluate_finish(
        "fail", "model claim", make_spec(), [record("v1", False, "dashboard stayed hidden")]
    )
    assert accepted.accepted is True
    assert accepted.outcome is Outcome.FAIL
    assert "dashboard stayed hidden" in accepted.reason


def test_finish_blocked_maps_to_error() -> None:
    result = evaluate_finish("blocked", "browser unavailable", make_spec(), [])
    assert result.accepted is True
    assert result.outcome is Outcome.ERROR
    assert result.reason.startswith("ERROR:")


def test_abort_is_error_and_includes_unproven_ids() -> None:
    result = abort_verdict("budget exhausted", make_spec(), [record("v1", True)])
    assert result.outcome is Outcome.ERROR
    assert "v2" in result.reason


def test_unknown_finish_is_rejected() -> None:
    result = evaluate_finish("pass-ish", "", make_spec(), [])
    assert result.accepted is False
