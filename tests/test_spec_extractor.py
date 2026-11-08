import pytest

from nlqa.llm.fake import FakeLLM
from nlqa.spec_extractor import SpecExtractionError, extract_spec


def response(**overrides):
    value = {
        "goal": "Log in as a customer and verify the dashboard is shown",
        "start_url": None,
        "steps": ["Enter customer credentials", "Submit the login form"],
        "verifications": [
            {"id": "v1", "statement": "The customer dashboard is shown", "implicit": False}
        ],
        "data": {"username": "customer"},
    }
    return value | overrides


def test_extracts_valid_spec_and_keeps_unseen_site_generic() -> None:
    client = FakeLLM(json_responses=[response()])
    spec = extract_spec(client, "Log in as a customer and verify the dashboard is shown")
    assert spec.goal.startswith("Log in")
    assert spec.verifications[0].id == "v1"
    assert spec.start_url is None
    assert spec.data == {"username": "customer"}


def test_only_explicit_url_is_accepted() -> None:
    fabricated = response(start_url="https://example.invalid")
    spec = extract_spec(FakeLLM(json_responses=[fabricated]), "Open the sign-in page")
    assert spec.start_url is None
    explicit = response(start_url="https://example.test/login")
    spec = extract_spec(
        FakeLLM(json_responses=[explicit]), "Open https://example.test/login and sign in"
    )
    assert spec.start_url == "https://example.test/login"


def test_missing_expectation_is_not_replaced_with_a_generic_check() -> None:
    with pytest.raises(SpecExtractionError, match="Add the expected page behavior"):
        extract_spec(
            FakeLLM(
                json_responses=[
                    response(verifications=[], goal="Open the account page", steps=["Open account"])
                ]
            ),
            "Open the account page",
        )


def test_malformed_model_output_becomes_safe_error() -> None:
    with pytest.raises(SpecExtractionError, match="invalid test specification"):
        extract_spec(FakeLLM(json_responses=[{"goal": "too short"}]), "Check a page")


def test_empty_case_is_rejected_without_model_call() -> None:
    with pytest.raises(SpecExtractionError, match="empty"):
        extract_spec(FakeLLM(), "   ")
