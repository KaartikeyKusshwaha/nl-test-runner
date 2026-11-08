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
    if "No start URL was provided" in detail:
        return "The test has no website URL. Enter a public URL in the Website URL field."
    if "did not return the required JSON" in detail or "invalid test specification" in detail:
        return "The AI could not create a valid test plan. Simplify the instruction and retry."
    if "browser setup failed" in detail:
        return "The browser could not start. Check Render logs for its startup error."
    if detail:
        return "The runner stopped before browser actions. Check Render application logs."
    if returncode not in {0, 1, 2}:
        return (
            f"The runner exited before producing a report (exit code {returncode}). "
            "Check Render application logs."
        )
    return "The runner stopped before producing a report. Check Render application logs."
