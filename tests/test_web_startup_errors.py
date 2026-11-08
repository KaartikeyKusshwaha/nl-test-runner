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


def test_startup_error_parses_rich_colored_output() -> None:
    reason = startup_failure_reason(
        "\x1b[1;31mRESULT: ERROR\x1b[0m The model rejected the request (HTTP 401). "
        "Check provider configuration.",
        "",
        2,
    )

    assert "provider rejected the API key" in reason


def test_startup_error_explains_invalid_json_without_exposing_model_output() -> None:
    reason = startup_failure_reason(
        "RESULT: ERROR The model returned invalid JSON.",
        "private response text",
        2,
    )

    assert "malformed test plan" in reason
    assert "private response text" not in reason


def test_startup_error_identifies_invalid_model_configuration() -> None:
    reason = startup_failure_reason(
        "RESULT: ERROR The model rejected the request (HTTP 404). Check provider configuration.",
        "",
        2,
    )

    assert "LLM_MODEL" in reason
    assert "model request" in reason


def test_startup_error_explains_unusable_test_instruction() -> None:
    reason = startup_failure_reason(
        "RESULT: ERROR The model did not return a usable tool call after retry.",
        "",
        2,
    )

    assert "complete sentence" in reason
    assert "balanced quotation marks" in reason


def test_startup_error_does_not_return_unrecognized_model_output() -> None:
    reason = startup_failure_reason(
        "RESULT: ERROR The model returned an invalid test specification (ValidationError).",
        "private prompt text",
        2,
    )

    assert "valid test plan" in reason
    assert "private prompt text" not in reason


def test_startup_error_shows_safe_unrecognized_cli_diagnostic() -> None:
    reason = startup_failure_reason(
        "RESULT: ERROR The model request failed after two attempts (HTTP 503).",
        "",
        2,
    )

    assert "HTTP 503" in reason


def test_startup_error_preserves_provider_rejection_hint() -> None:
    reason = startup_failure_reason(
        "RESULT: ERROR The model rejected the request (HTTP 400): "
        "response_format is not supported.",
        "",
        2,
    )

    assert "response_format is not supported" in reason


def test_startup_error_identifies_silent_child_exit() -> None:
    reason = startup_failure_reason("", "", 2)

    assert "no report or diagnostic output" in reason
    assert "exit code 2" in reason


def test_startup_error_reports_exception_type_without_traceback_contents() -> None:
    reason = startup_failure_reason(
        "",
        "Traceback (most recent call last):\n  secret-bearing details\nRuntimeError: private value",
        1,
    )

    assert "RuntimeError" in reason
    assert "private value" not in reason
