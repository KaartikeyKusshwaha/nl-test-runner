from nlqa.startup_errors import startup_failure_reason


def test_startup_error_identifies_invalid_provider_key_without_raw_output() -> None:
    reason = startup_failure_reason(
        "RESULT: ERROR The model rejected the request (HTTP 401). Check provider configuration.",
        "Authorization header redacted",
        2,
    )

    assert "HTTP 401" in reason
    assert "OPENAI_API_KEY" in reason
    assert "Authorization header" not in reason


def test_startup_error_identifies_invalid_model_configuration() -> None:
    reason = startup_failure_reason(
        "RESULT: ERROR The model rejected the request (HTTP 404). Check provider configuration.",
        "",
        2,
    )

    assert "LLM_MODEL" in reason
    assert "model request" in reason


def test_startup_error_does_not_return_unrecognized_model_output() -> None:
    reason = startup_failure_reason(
        "RESULT: ERROR The model returned an invalid test specification (ValidationError).",
        "private prompt text",
        2,
    )

    assert "valid test plan" in reason
    assert "private prompt text" not in reason


def test_startup_error_reports_exception_type_without_traceback_contents() -> None:
    reason = startup_failure_reason(
        "",
        "Traceback (most recent call last):\n  secret-bearing details\nRuntimeError: private value",
        1,
    )

    assert "RuntimeError" in reason
    assert "private value" not in reason
