"""Safe summaries for failures that happen before a browser report exists."""

from __future__ import annotations

import re


def startup_failure_reason(stdout: str, stderr: str, returncode: int) -> str:
    """Map safe CLI startup failures to useful UI text without exposing raw output."""
    output = f"{stdout}\n{stderr}"
    match = re.search(r"RESULT:\s*ERROR\s+([^\r\n]+)", output)
    detail = " ".join(match.group(1).split()) if match else ""

    if "LLM_MODEL is not set" in detail:
        return "The AI model is not configured. Set LLM_MODEL in the hosting environment."
    if "OPENAI_API_KEY is not set" in detail or "needs OPENAI_API_KEY" in detail:
        return (
            "The AI provider key is not configured. "
            "Check OPENAI_API_KEY in the hosting environment."
        )
    if "HTTP 401" in detail:
        return (
            "The AI provider rejected the API key (HTTP 401). "
            "Check OPENAI_API_KEY in the hosting environment."
        )
    if "HTTP 429" in detail or "rate limit" in detail.casefold():
        return (
            "The AI provider rate-limited this run. "
            "Wait for its quota window to reset, then retry."
        )
    if "HTTP 400" in detail or "HTTP 404" in detail:
        return "The AI provider rejected the model request. Check LLM_MODEL and provider settings."
    if "did not return a usable tool call" in detail:
        return (
            "The AI could not turn this instruction into a test plan. "
            "Use a complete sentence, balanced quotation marks, and a clear expected result."
        )
    if "No start URL was provided" in detail:
        return "The test has no website URL. Enter a public URL in the Website URL field."
    if "did not return the required JSON" in detail or "invalid test specification" in detail:
        return "The AI could not create a valid test plan. Simplify the instruction and retry."
    if "browser setup failed" in detail:
        return "The browser could not start. Check Render logs for its startup error."
    if detail:
        return "The runner stopped before browser actions. Check Render application logs."

    missing_module = re.search(r"No module named ['\"]([^'\"]+)['\"]", output)
    if missing_module:
        return f"The hosted runner is missing its {missing_module.group(1)} Python dependency."
    if re.search(r"^usage:", output, re.IGNORECASE | re.MULTILINE):
        return "The hosted runner rejected its command arguments before browser startup."
    if "Traceback (most recent call last)" in output:
        last_line = next(
            (line.strip() for line in reversed(output.splitlines()) if line.strip()), ""
        )
        exception = re.match(r"([A-Za-z_][A-Za-z0-9_.]*)", last_line)
        if exception:
            return (
                "The hosted runner crashed before producing a report "
                f"({exception.group(1)}). Check Render application logs."
            )
    if stdout or stderr:
        return (
            "The hosted runner exited before producing a report "
            f"(exit code {returncode}; output captured). Check Render application logs."
        )
    if returncode not in {0, 1, 2}:
        return (
            f"The runner exited before producing a report (exit code {returncode}). "
            "Check Render application logs."
        )
    return "The runner stopped before producing a report. Check Render application logs."
