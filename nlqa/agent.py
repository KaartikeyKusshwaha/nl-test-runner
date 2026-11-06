"""Bounded observe-act browser runner with deterministic terminal outcomes."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

from nlqa.actions import BrowserController, ToolExecutionError
from nlqa.assertions import run_assertion
from nlqa.judge import guard_pass
from nlqa.llm.base import LLMClient, LLMError
from nlqa.models import (
    AssertionRecord,
    Outcome,
    RunResult,
    StepRecord,
    TestSpec,
    ToolCall,
)
from nlqa.prompts import AGENT_SYSTEM, build_step_prompt
from nlqa.secrets import PLACEHOLDER, SecretStore
from nlqa.tools import ASSERTION_TOOLS, TOOL_DEFINITIONS, validate_tool_call
from nlqa.verdict import abort_verdict, evaluate_finish, verification_statuses


class TestAgent:
    """Execute one natural-language browser test under fixed budgets."""

    __test__ = False

    def __init__(
        self,
        client: LLMClient,
        controller: BrowserController,
        *,
        secret_store: SecretStore | None = None,
        max_steps: int = 30,
        max_seconds: int = 240,
        max_consecutive_errors: int = 4,
        assertion_timeout_ms: int = 5000,
        max_elements: int = 150,
        judge_enabled: bool = True,
        llm_repair_attempts: int = 1,
    ) -> None:
        self.client = client
        self.controller = controller
        self.secret_store = secret_store or controller.secret_store
        self.controller.secret_store = self.secret_store
        self.max_steps = max_steps
        self.max_seconds = max_seconds
        self.max_consecutive_errors = max_consecutive_errors
        self.assertion_timeout_ms = assertion_timeout_ms
        self.max_elements = max_elements
        self.judge_enabled = judge_enabled
        self.llm_repair_attempts = llm_repair_attempts

    def run(
        self, spec: TestSpec, *, allowed_placeholders: set[str] | None = None
    ) -> RunResult:
        """Run until a gated finish, a failing verification, or a bounded stop."""
        started = time.monotonic()
        started_at = datetime.now(UTC).isoformat()
        steps: list[StepRecord] = []
        assertions: list[AssertionRecord] = []
        history: list[str] = []
        last_result = "No browser action has been taken yet."
        consecutive_errors = 0
        repeated_calls: dict[str, int] = {}
        last_observation = None

        for step_number in range(1, self.max_steps + 1):
            iteration_started = time.monotonic()
            if time.monotonic() - started >= self.max_seconds:
                decision = abort_verdict("time budget exhausted", spec, assertions)
                return self._result(
                    decision, spec, steps, assertions, started_at, started, last_observation
                )

            observation = self.controller.snapshot(self.max_elements)
            last_observation = observation
            statuses = verification_statuses(spec, assertions)
            prompt = build_step_prompt(
                goal=spec.goal,
                verifications=[item.model_dump() for item in spec.verifications],
                statuses=statuses,
                data_json=json.dumps(self.secret_store.mask_object(spec.data), ensure_ascii=False),
                steps=spec.steps,
                history=history,
                last_result=self.secret_store.mask(last_result),
                step=step_number,
                max_steps=self.max_steps,
                page_section=self.secret_store.mask(observation.prompt_section()),
            )
            call, repair_error = self._choose_valid_call(prompt, observation, spec)
            if time.monotonic() - started >= self.max_seconds:
                decision = abort_verdict("time budget exhausted", spec, assertions)
                return self._result(
                    decision, spec, steps, assertions, started_at, started, observation
                )
            if call is None:
                consecutive_errors += 1
                last_result = repair_error or "The model returned no usable tool call."
                history.append(f"{step_number}. rejected model response -> {last_result}")
                steps.append(
                    self._step(
                        step_number,
                        "invalid_model_response",
                        {},
                        False,
                        last_result,
                        observation.url,
                        iteration_started,
                    )
                )
                if consecutive_errors >= self.max_consecutive_errors:
                    decision = abort_verdict(
                        f"{consecutive_errors} consecutive invalid model responses",
                        spec,
                        assertions,
                    )
                    return self._result(
                        decision, spec, steps, assertions, started_at, started, observation
                    )
                continue

            safe_args = self.secret_store.mask_object(call.args)
            fingerprint = json.dumps(
                [observation.hash, call.name, safe_args], sort_keys=True, ensure_ascii=False
            )
            repeated_calls[fingerprint] = repeated_calls.get(fingerprint, 0) + 1
            if repeated_calls[fingerprint] >= 3:
                decision = abort_verdict(
                    "agent is stuck repeating the same tool on an unchanged page", spec, assertions
                )
                return self._result(
                    decision, spec, steps, assertions, started_at, started, observation
                )

            if call.name == "finish":
                decision = evaluate_finish(
                    str(call.args["verdict"]),
                    self.secret_store.mask(str(call.args["reason"])),
                    spec,
                    assertions,
                )
                steps.append(
                    self._step(
                        step_number,
                        call.name,
                        safe_args,
                        decision.accepted,
                        decision.feedback or decision.reason,
                        observation.url,
                        iteration_started,
                    )
                )
                if not decision.accepted:
                    consecutive_errors += 1
                    last_result = decision.feedback or "Finish was rejected by evidence validation."
                    history.append(f"{step_number}. finish rejected -> {last_result}")
                    if consecutive_errors >= self.max_consecutive_errors:
                        aborted = abort_verdict(
                            f"{consecutive_errors} consecutive finish/validation errors",
                            spec,
                            assertions,
                        )
                        return self._result(
                            aborted, spec, steps, assertions, started_at, started, observation
                        )
                    continue

                if decision.outcome is Outcome.PASS and self.judge_enabled:
                    reviewed = guard_pass(
                        self.client, spec, assertions, self.secret_store.mask(observation.text)
                    )
                    decision.outcome = reviewed.outcome
                    if reviewed.outcome is Outcome.ERROR:
                        decision.reason = reviewed.reason
                return self._result(
                    decision, spec, steps, assertions, started_at, started, observation
                )

            try:
                actual_args, safe_args = self.secret_store.substitute_args(
                    call.args,
                    allowed_names=_placeholder_names(spec) | (allowed_placeholders or set()),
                )
                if call.name in ASSERTION_TOOLS:
                    record = run_assertion(
                        ToolCall(name=call.name, args=actual_args),
                        self.controller,
                        step=step_number,
                        safe_args=safe_args,
                        timeout_ms=self.assertion_timeout_ms,
                    )
                    assertions.append(record)
                    succeeded = True
                    detail = record.detail
                    screenshot = record.screenshot
                else:
                    action = self.controller.perform(
                        ToolCall(name=call.name, args=actual_args), observation, step_number
                    )
                    succeeded = action.ok
                    detail = self.secret_store.mask(action.detail)
                    screenshot = self.controller.screenshot(step_number, call.name)
            except ValueError as exc:
                decision = abort_verdict(str(exc), spec, assertions)
                steps.append(
                    self._step(
                        step_number,
                        call.name,
                        safe_args,
                        False,
                        decision.reason,
                        self.secret_store.mask(self.controller.page.url),
                        iteration_started,
                    )
                )
                return self._result(
                    decision, spec, steps, assertions, started_at, started, observation
                )
            except ToolExecutionError as exc:
                succeeded = False
                detail = self.secret_store.mask(str(exc))
                screenshot = self.controller.screenshot(step_number, call.name)
            except Exception as exc:
                succeeded = False
                detail = f"Browser tool failed: {type(exc).__name__}."
                screenshot = self.controller.screenshot(step_number, call.name)

            steps.append(
                self._step(
                    step_number,
                    call.name,
                    safe_args,
                    succeeded,
                    detail,
                    self.secret_store.mask(self.controller.page.url),
                    iteration_started,
                    screenshot=screenshot,
                )
            )
            history.append(
                f"{step_number}. {call.name}({json.dumps(safe_args, ensure_ascii=False)}) "
                f"-> {'ok' if succeeded else 'error'} | {self.secret_store.mask(detail)}"
            )
            last_result = self.secret_store.mask(detail)
            consecutive_errors = 0 if succeeded else consecutive_errors + 1
            if consecutive_errors >= self.max_consecutive_errors:
                decision = abort_verdict(
                    f"{consecutive_errors} consecutive browser tool errors", spec, assertions
                )
                return self._result(
                    decision, spec, steps, assertions, started_at, started, observation
                )

        decision = abort_verdict("step budget exhausted", spec, assertions)
        return self._result(
            decision, spec, steps, assertions, started_at, started, last_observation
        )

    def _choose_valid_call(
        self, prompt: str, observation: Any, spec: TestSpec
    ) -> tuple[ToolCall | None, str | None]:
        """Repair an absent/malformed tool response once; validate without executing it."""
        verification_ids = {item.id for item in spec.verifications}
        current_prompt = prompt
        last_error: str | None = None
        for attempt in range(self.llm_repair_attempts + 1):
            try:
                call = self.client.choose_tool(
                    system=AGENT_SYSTEM,
                    user=current_prompt,
                    tools=TOOL_DEFINITIONS,
                )
            except LLMError as exc:
                return None, str(exc)
            if call is None:
                last_error = "The model returned no usable tool call."
            else:
                error = validate_tool_call(call, observation, verification_ids)
                if error is None:
                    return call, None
                last_error = error
            if attempt < self.llm_repair_attempts:
                current_prompt = (
                    f"{prompt}\nThe previous tool response was invalid: {last_error} "
                    "Return one corrected tool call using the current observation."
                )
        return None, last_error

    def _step(
        self,
        number: int,
        tool: str,
        args: dict[str, Any],
        ok: bool,
        result: str,
        url: str,
        started: float,
        *,
        screenshot: str | None = None,
    ) -> StepRecord:
        return StepRecord(
            n=number,
            tool=tool,
            args=self.secret_store.mask_object(args),
            ok=ok,
            result=self.secret_store.mask(result),
            url_after=self.secret_store.mask(url),
            screenshot=screenshot,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    def _result(
        self,
        decision: Any,
        spec: TestSpec,
        steps: list[StepRecord],
        assertions: list[AssertionRecord],
        started_at: str,
        started: float,
        observation: Any,
    ) -> RunResult:
        usage = self.client.usage
        return RunResult(
            outcome=decision.outcome or Outcome.ERROR,
            reason=self.secret_store.mask(decision.reason),
            spec=spec,
            steps=steps,
            assertions=assertions,
            verification_status=decision.verification_status,
            llm_usage={
                "calls": usage.calls,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
            },
            model=self.client.model,
            provider=self.client.provider,
            started_at=started_at,
            duration_ms=int((time.monotonic() - started) * 1000),
            artifacts={
                "page_url": self.secret_store.mask(observation.url) if observation else None,
                "page_text": self.secret_store.mask(observation.text) if observation else None,
            },
        )


def _placeholder_names(spec: TestSpec) -> set[str]:
    """Allow substitution only for placeholders present in the user's extracted test."""
    source = [spec.goal, *spec.steps, *spec.data.values()]
    if spec.start_url:
        source.append(spec.start_url)
    source.extend(item.statement for item in spec.verifications)
    return {match.group(1) for value in source for match in PLACEHOLDER.finditer(value)}
