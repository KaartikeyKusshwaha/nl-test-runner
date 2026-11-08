"""Safe, user-facing summaries for the optional hosted web interface."""

from __future__ import annotations

from typing import Any


def verification_details(report: dict[str, Any]) -> list[dict[str, str]]:
    """Return requested checks together with their latest browser evidence."""
    verifications = report.get("verification_status", {})
    spec = report.get("spec") if isinstance(report.get("spec"), dict) else {}
    spec_verifications = spec.get("verifications", [])
    assertions = report.get("assertions", [])
    latest_evidence: dict[str, str] = {}
    if isinstance(assertions, list):
        for assertion in assertions:
            if not isinstance(assertion, dict):
                continue
            verification_id = str(assertion.get("verification_id", "")).strip()
            detail = str(assertion.get("detail", "")).strip()
            if verification_id and detail:
                latest_evidence[verification_id] = detail[:500]

    details = []
    if not isinstance(spec_verifications, list) or not isinstance(verifications, dict):
        return details
    for verification in spec_verifications:
        if not isinstance(verification, dict):
            continue
        verification_id = str(verification.get("id", "")).strip()
        statement = str(verification.get("statement", "")).strip()
        if verification_id and statement:
            details.append(
                {
                    "statement": statement[:300],
                    "status": str(verifications.get(verification_id, "unverified")),
                    "evidence": latest_evidence.get(verification_id, ""),
                }
            )
    return details
