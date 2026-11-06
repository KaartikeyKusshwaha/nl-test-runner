"""Command-line interface for natural-language browser tests."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.table import Table

from nlqa.actions import BrowserController
from nlqa.agent import TestAgent
from nlqa.config import Settings
from nlqa.llm.base import LLMError
from nlqa.llm.factory import create_client
from nlqa.llm.fake import FakeLLM
from nlqa.models import Outcome, RunResult
from nlqa.report import create_run_directory, redact_trace, write_report
from nlqa.secrets import PLACEHOLDER, SecretStore
from nlqa.spec_extractor import SpecExtractionError, extract_spec
from nlqa.verdict import abort_verdict

console = Console()


@dataclass(slots=True)
class TestCaseFile:
    """Plain-English test body and optional selfcheck metadata."""

    name: str
    body: str
    url: str | None = None
    expected: str = "pass"


def build_parser() -> argparse.ArgumentParser:
    """Build the supported CLI commands and common run flags."""
    parser = argparse.ArgumentParser(
        prog="nlqa",
        description="Run plain-English QA test cases in a browser with evidence-based results.",
    )
    parser.add_argument("--version", action="version", version="nl-test-runner 0.1.0")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser(
        "doctor", help="Check Python, Playwright, browser, and model configuration"
    )
    run = subcommands.add_parser("run", help="Run one plain-English test case")
    run.add_argument("test_case", help="Natural-language test steps and expected result")
    _add_run_options(run)
    run_file = subcommands.add_parser("run-file", help="Run one .txt test-case file")
    run_file.add_argument("path", type=Path)
    _add_run_options(run_file)
    run_dir = subcommands.add_parser("run-dir", help="Run every .txt test in a directory")
    run_dir.add_argument("path", type=Path)
    _add_run_options(run_dir)
    selfcheck = subcommands.add_parser("selfcheck", help="Run cases/ and compare expected outcomes")
    selfcheck.add_argument("--cases", type=Path, default=_default_cases_dir())
    _add_run_options(selfcheck)
    return parser


def _add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", help="Start URL; overrides a test file URL header")
    parser.add_argument("--headed", action="store_true", help="Show the Chromium window")
    parser.add_argument("--slowmo", type=int, help="Slow browser actions by N milliseconds")
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--max-seconds", type=int)
    parser.add_argument("--provider", choices=["openai", "anthropic", "openai_compatible", "fake"])
    parser.add_argument("--model", help="Provider model identifier")
    parser.add_argument(
        "--no-judge", action="store_true", help="Skip the evidence-sufficiency call"
    )
    parser.add_argument(
        "--video", action="store_true", help="Record browser video in the run folder"
    )
    parser.add_argument("--report-dir", type=Path, help="Root directory for run artifacts")
    parser.add_argument("--allow-domain", action="append", help="Restrict navigation; repeatable")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print masked run details")


def _default_cases_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "cases"


def _doctor() -> int:
    settings = Settings()
    all_ok = True
    console.print(
        f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    if sys.version_info < (3, 11):  # noqa: UP036 - doctor must report unsupported interpreters
        console.print("[red]Python 3.11 or later is required.[/red]")
        all_ok = False
    try:
        console.print(f"Playwright: {importlib.metadata.version('playwright')}")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            browser.close()
        console.print("Chromium: installed and launchable")
    except Exception as exc:
        console.print(f"[red]Chromium is not ready ({type(exc).__name__}).[/red]")
        console.print("Run: playwright install chromium")
        all_ok = False
    console.print(f"Provider: {settings.llm_provider}")
    console.print(f"Model: {settings.llm_model or '(not set)'}")
    error = settings.provider_error()
    if error:
        console.print(f"[red]LLM configuration: {error}[/red]")
        all_ok = False
    elif settings.llm_provider == "fake":
        console.print("LLM configuration: fake provider; external ping skipped")
    else:
        try:
            client = create_client(settings)
            client.ping()
            console.print("LLM ping: passed (one output token requested)")
        except Exception as exc:
            console.print(
                f"[red]LLM ping failed ({type(exc).__name__}). "
                "Check provider, model, network, and key.[/red]"
            )
            all_ok = False
    return 0 if all_ok else 2


def _settings_for(args: argparse.Namespace) -> Settings:
    settings = Settings()
    updates: dict[str, Any] = {}
    if args.provider:
        updates["llm_provider"] = args.provider
    if args.model:
        updates["llm_model"] = args.model
    if args.headed:
        updates["nlqa_headless"] = False
    if args.slowmo is not None:
        updates["nlqa_slowmo_ms"] = max(0, min(2000, args.slowmo))
    if args.max_steps is not None:
        updates["nlqa_max_steps"] = max(1, min(100, args.max_steps))
    if args.max_seconds is not None:
        updates["nlqa_max_seconds"] = max(1, min(1800, args.max_seconds))
    if args.no_judge:
        updates["nlqa_judge"] = False
    if args.report_dir:
        updates["nlqa_report_dir"] = str(args.report_dir)
    if args.allow_domain:
        updates["nlqa_allow_domain"] = args.allow_domain
    return settings.model_copy(update=updates)


def read_case_file(path: str | Path) -> TestCaseFile:
    """Read a test body and the optional name/url/expect header fields."""
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"Test file does not exist: {source}")
    metadata: dict[str, str] = {}
    body_lines: list[str] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*#\s*(name|url|expect)\s*:\s*(.*?)\s*$", line, re.IGNORECASE)
        if match:
            metadata[match.group(1).lower()] = match.group(2)
        else:
            body_lines.append(line)
    body = "\n".join(body_lines).strip()
    if not body:
        raise ValueError(f"Test file has no plain-English case text: {source}")
    expected = metadata.get("expect", "pass").casefold()
    if expected not in {"pass", "fail", "error"}:
        raise ValueError(f"Invalid # expect header in {source}; use pass, fail, or error.")
    return TestCaseFile(metadata.get("name", source.stem), body, metadata.get("url"), expected)


def _fake_client(settings: Settings) -> tuple[Settings, FakeLLM | None]:
    """Load the opt-in dev-only scripted FakeLLM from NLQA_FAKE_SCRIPT."""
    path = os.environ.get("NLQA_FAKE_SCRIPT")
    if not path:
        if settings.llm_provider == "fake":
            raise LLMError("LLM_PROVIDER=fake needs NLQA_FAKE_SCRIPT for a run.")
        return settings, None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        spec_response = data["spec"]
        calls = data.get("tool_calls", [])
        judge_responses = data.get("judge", [])
        fake = FakeLLM(tool_calls=calls, json_responses=[spec_response, *judge_responses])
    except Exception as exc:
        raise LLMError(f"Could not read NLQA_FAKE_SCRIPT ({type(exc).__name__}).") from exc
    return settings.model_copy(update={"llm_provider": "fake"}), fake


def _run_text(
    text: str, *, file_url: str | None, args: argparse.Namespace
) -> tuple[int, RunResult | None]:
    settings = _settings_for(args)
    secret_store = SecretStore.from_environment()
    try:
        settings, fake = _fake_client(settings)
        error = settings.provider_error()
        if error:
            raise LLMError(error)
        client = create_client(settings, fake=fake)
        spec = extract_spec(client, text)
        requested_url = args.url or file_url or spec.start_url
        if not requested_url:
            raise SpecExtractionError(
                "No start URL was provided. Pass --url or include one in the test case."
            )
        allowed_url_names = set(PLACEHOLDER.findall(requested_url))
        start_url = secret_store.substitute(requested_url, allowed_names=allowed_url_names)
        spec = spec.model_copy(update={"start_url": secret_store.mask(requested_url)})
    except (LLMError, SpecExtractionError) as exc:
        console.print(f"[bold red]RESULT: ERROR[/bold red] {exc}")
        return 2, None
    except ValueError as exc:
        console.print(f"[bold red]RESULT: ERROR[/bold red] {secret_store.mask(str(exc))}")
        return 2, None

    run_dir = create_run_directory(settings.nlqa_report_dir, spec.goal)
    result: RunResult | None = None
    trace_path = run_dir / "trace.zip"
    video_dir = run_dir / "video"
    if args.video:
        video_dir.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=settings.nlqa_headless, slow_mo=settings.nlqa_slowmo_ms
            )
            context_options: dict[str, Any] = {"viewport": {"width": 1366, "height": 900}}
            if args.video:
                context_options["record_video_dir"] = str(video_dir)
                context_options["record_video_size"] = {"width": 1366, "height": 900}
            context = browser.new_context(**context_options)
            context.tracing.start(screenshots=True, snapshots=True, sources=False)
            page = context.new_page()
            controller = BrowserController(
                page,
                report_dir=run_dir,
                secret_store=secret_store,
                allow_domains=settings.nlqa_allow_domain,
                timeout_ms=settings.nlqa_action_timeout_ms,
            )
            try:
                controller._validate_navigation(start_url)
                page.goto(
                    start_url,
                    wait_until="commit",
                    timeout=settings.nlqa_action_timeout_ms,
                )
                controller.wait_for_page_ready()
                agent = TestAgent(
                    client,
                    controller,
                    secret_store=secret_store,
                    max_steps=settings.nlqa_max_steps,
                    max_seconds=settings.nlqa_max_seconds,
                    max_consecutive_errors=settings.nlqa_max_consecutive_errors,
                    assertion_timeout_ms=settings.nlqa_assert_timeout_ms,
                    max_elements=settings.nlqa_max_elements,
                    judge_enabled=settings.nlqa_judge,
                )
                result = agent.run(
                    spec, allowed_placeholders=set(PLACEHOLDER.findall(text))
                )
            except Exception as exc:
                decision = abort_verdict(f"browser setup failed ({type(exc).__name__})", spec, [])
                result = RunResult(
                    outcome=Outcome.ERROR,
                    reason=decision.reason,
                    spec=spec,
                    verification_status=decision.verification_status,
                    llm_usage={
                        "calls": client.usage.calls,
                        "input_tokens": client.usage.input_tokens,
                        "output_tokens": client.usage.output_tokens,
                    },
                    model=client.model,
                    provider=client.provider,
                    started_at=datetime.now(UTC).isoformat(),
                    duration_ms=0,
                    artifacts={
                        "page_url": secret_store.mask(page.url),
                        "page_text": "",
                    },
                )
            finally:
                try:
                    context.tracing.stop(path=str(trace_path))
                except Exception:
                    trace_path.unlink(missing_ok=True)
                context.close()
                browser.close()
        if result is None:
            raise RuntimeError("Browser run ended without a result.")
        if trace_path.exists():
            redact_trace(trace_path, secret_store.sensitive_values)
            result.artifacts["trace_zip"] = str(trace_path)
        videos = sorted(video_dir.glob("*.webm")) if args.video else []
        if videos:
            result.artifacts["video"] = [str(path) for path in videos]
    except Exception as exc:
        safe_message = secret_store.mask(str(exc))[:240]
        console.print(
            f"[bold red]RESULT: ERROR[/bold red] browser setup failed "
            f"({type(exc).__name__}): {safe_message}"
        )
        return 2, None

    json_path, html_path = write_report(result, run_dir)
    _print_result(text, result, json_path, html_path, verbose=args.verbose)
    code = {Outcome.PASS: 0, Outcome.FAIL: 1, Outcome.ERROR: 2}[result.outcome]
    return code, result


def _print_result(
    text: str, result: RunResult, json_path: Path, html_path: Path, *, verbose: bool
) -> None:
    console.print(f"[bold]TEST[/bold] {text}")
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right")
    table.add_column("Tool")
    table.add_column("Arguments")
    table.add_column("Result")
    for step in result.steps:
        table.add_row(
            str(step.n),
            step.tool,
            json.dumps(step.args, ensure_ascii=False),
            ("ok" if step.ok else "error") + f" · {step.result}",
        )
    console.print(table)
    color = {Outcome.PASS: "green", Outcome.FAIL: "red", Outcome.ERROR: "yellow"}[result.outcome]
    status = " ".join(f"{key} {value}" for key, value in result.verification_status.items())
    console.print(
        f"[bold {color}]RESULT: {result.outcome}[/bold {color}] {result.reason} "
        f"· verifications: {status or 'none'} · steps: {len(result.steps)} "
        f"· LLM calls: {result.llm_usage.get('calls', 0)} · time: {result.duration_ms} ms"
    )
    console.print(f"Reports: {json_path} | {html_path}")
    if verbose:
        console.print(f"Artifacts: {result.artifacts}")


def _run_file(path: Path, args: argparse.Namespace) -> tuple[int, RunResult | None, TestCaseFile]:
    case = read_case_file(path)
    code, result = _run_text(case.body, file_url=case.url, args=args)
    return code, result, case


def _run_collection(path: Path, args: argparse.Namespace) -> int:
    if not path.is_dir():
        console.print(f"[red]Case directory does not exist: {path}[/red]")
        return 2
    files = sorted(path.rglob("*.txt"))
    if not files:
        console.print(f"[red]No .txt test cases found in {path}[/red]")
        return 2
    table = Table(title=f"Selfcheck: {path}", header_style="bold cyan")
    table.add_column("Case")
    table.add_column("Expected")
    table.add_column("Actual")
    table.add_column("Result")
    mismatches = 0
    for file in files:
        try:
            code, result, case = _run_file(file, args)
            actual = result.outcome.value.casefold() if result else "error"
            matched = actual == case.expected
            if not matched:
                mismatches += 1
            table.add_row(case.name, case.expected, actual, "MATCH" if matched else "MISMATCH")
        except Exception as exc:
            mismatches += 1
            table.add_row(file.stem, "unknown", "error", type(exc).__name__)
    console.print(table)
    console.print(f"Cases: {len(files)} · mismatches: {mismatches}")
    return 0 if mismatches == 0 else 1


def main() -> int:
    """Parse arguments and run one of the supported commands."""
    args = build_parser().parse_args()
    if args.command == "doctor":
        return _doctor()
    if args.command == "run":
        code, _ = _run_text(args.test_case, file_url=None, args=args)
        return code
    if args.command == "run-file":
        try:
            code, _, _ = _run_file(args.path, args)
            return code
        except Exception as exc:
            console.print(f"[bold red]RESULT: ERROR[/bold red] {exc}")
            return 2
    if args.command == "run-dir":
        return _run_collection(args.path, args)
    if args.command == "selfcheck":
        return _run_collection(args.cases, args)
    return 2
