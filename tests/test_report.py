import json
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import nlqa.report as report_module
from nlqa.models import Outcome, RunResult, TestSpec, Verification
from nlqa.report import redact_trace, write_report


def make_result() -> RunResult:
    return RunResult(
        outcome=Outcome.PASS,
        reason="All verifications have passing evidence.",
        spec=TestSpec(
            goal="Confirm the welcome panel is shown",
            verifications=[Verification(id="v1", statement="Welcome panel is shown")],
        ),
        verification_status={"v1": "proven"},
        started_at="2026-11-06T00:00:00+00:00",
        duration_ms=1250,
        artifacts={"page_url": "https://example.test", "page_text": "Welcome panel"},
    )


def test_report_writes_json_and_autoescaped_html() -> None:
    with TemporaryDirectory(dir=".", prefix="report-test-") as directory:
        result = make_result()
        result.spec.goal = "Check <script>alert('x')</script>"
        json_path, html_path = write_report(result, directory)
        data = json.loads(json_path.read_text(encoding="utf-8"))
        html = html_path.read_text(encoding="utf-8")
        assert data["outcome"] == "PASS"
        assert "&lt;script&gt;" in html
        assert "report_json" in result.artifacts


def test_trace_redactor_masks_known_values(monkeypatch) -> None:
    with TemporaryDirectory(dir=".", prefix="trace-test-") as directory:
        trace = Path(directory) / "trace.zip"
        with zipfile.ZipFile(trace, "w") as archive:
            archive.writestr("trace.trace", '{"typed":"secret-password"}')
        original_replace = Path.replace
        attempts = 0

        def replace_with_one_temporary_lock(source: Path, target: Path) -> Path:
            nonlocal attempts
            if source.name == "trace.redacted.zip" and attempts == 0:
                attempts += 1
                raise PermissionError("temporary Windows file lock")
            return original_replace(source, target)

        monkeypatch.setattr(Path, "replace", replace_with_one_temporary_lock)
        monkeypatch.setattr(report_module.time, "sleep", lambda _seconds: None)
        redact_trace(trace, {"secret-password"})
        with zipfile.ZipFile(trace) as archive:
            content = archive.read("trace.trace").decode()
        assert "secret-password" not in content
        assert "****" in content
        assert attempts == 1
