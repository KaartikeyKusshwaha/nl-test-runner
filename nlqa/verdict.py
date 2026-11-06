"""Deterministic outcome gating based on the latest recorded evidence."""

from __future__ import annotations

from dataclasses import dataclass

from nlqa.models import AssertionRecord, Outcome, TestSpec


@dataclass(slots=True)
class VerdictDecision:
    """Result of validating a proposed terminal action."""

    accepted: bool
    outcome: Outcome | None
    reason: str
    verification_status: dict[str, str]
    feedback: str | None = None


def verification_statuses(spec: TestSpec, assertions: list[AssertionRecord]) -> dict[str, str]:
    """Use the last assertion for each requested verification."""
    latest: dict[str, AssertionRecord] = {}
    for record in assertions:
        latest[record.verification_id] = record
    return {
        verification.id: (
            "unproven"
            if verification.id not in latest
            else "proven"
            if latest[verification.id].passed
            else "failed"
        )
        for verification in spec.verifications
    }


def evaluate_finish(
    proposed: str,
    reason: str,
    spec: TestSpec,
    assertions: list[AssertionRecord],
) -> VerdictDecision:
    """Accept or reject the LLM's finish proposal without trusting its claims."""
    statuses = verification_statuses(spec, assertions)
    latest: dict[str, AssertionRecord] = {}
    for record in assertions:
        latest[record.verification_id] = record

    if proposed == "pass":
        missing = [identifier for identifier, status in statuses.items() if status != "proven"]
        if missing:
            first = missing[0]
            return VerdictDecision(
                False,
                None,
                "",
                statuses,
                f"Cannot finish: missing proof for {first}. Assert it first.",
            )
        return VerdictDecision(
            True, Outcome.PASS, "All verifications have passing evidence.", statuses
        )

    if proposed == "fail":
        failed = [identifier for identifier, status in statuses.items() if status == "failed"]
        if not failed:
            return VerdictDecision(
                False,
                None,
                "",
                statuses,
                "Prove the failure: run the assert_* for the expected condition; "
                "if it does not hold, that is your evidence.",
            )
        identifier = failed[0]
        verification = next(item for item in spec.verifications if item.id == identifier)
        evidence = latest[identifier]
        detail = evidence.detail or "the expected condition was not observed"
        return VerdictDecision(
            True,
            Outcome.FAIL,
            f'FAIL: {identifier} "{verification.statement}": {detail}',
            statuses,
        )

    if proposed == "blocked":
        safe_reason = reason.strip() or "The browser test could not continue."
        return VerdictDecision(True, Outcome.ERROR, f"ERROR: {safe_reason}", statuses)

    return VerdictDecision(
        False,
        None,
        "",
        statuses,
        "Unknown finish verdict. Choose pass, fail, or blocked.",
    )


def abort_verdict(
    reason: str, spec: TestSpec, assertions: list[AssertionRecord]
) -> VerdictDecision:
    """Produce ERROR for budget, stuck, provider, or repeated-tool failures."""
    statuses = verification_statuses(spec, assertions)
    unproven = [identifier for identifier, status in statuses.items() if status == "unproven"]
    suffix = f"; unproven: {', '.join(unproven)}" if unproven else ""
    return VerdictDecision(True, Outcome.ERROR, f"ERROR: {reason}{suffix}", statuses)
