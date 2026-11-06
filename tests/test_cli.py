import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from nlqa.cli import read_case_file


def test_cli_fake_script_runs_browser_and_writes_artifacts(site_server: str) -> None:
    case_data = {
        "spec": {
            "goal": "Sign in and verify the customer dashboard",
            "start_url": None,
            "steps": ["Enter credentials", "Submit the form"],
            "verifications": [
                {"id": "v1", "statement": "The customer dashboard is shown", "implicit": False}
            ],
            "data": {"password": "{{CUSTOMER_PASSWORD}}"},
        },
        "tool_calls": [
            {"name": "type", "args": {"ref": "e1", "text": "customer"}},
            {"name": "type", "args": {"ref": "e2", "text": "{{CUSTOMER_PASSWORD}}"}},
            {"name": "click", "args": {"ref": "e3"}},
            {
                "name": "assert_text_visible",
                "args": {"text": "Customer dashboard", "verification_id": "v1"},
            },
            {"name": "finish", "args": {"verdict": "pass", "reason": "Dashboard verified"}},
        ],
        "judge": [
            {
                "results": [
                    {"id": "v1", "supports": True, "why": "The dashboard heading is visible."}
                ]
            }
        ],
    }
    with TemporaryDirectory(dir=".", prefix="cli-run-") as directory:
        root = Path(directory)
        script = root / "fake-script.json"
        script.write_text(json.dumps(case_data), encoding="utf-8")
        run_env = os.environ.copy()
        run_env.update(
            {
                "NLQA_FAKE_SCRIPT": str(script.resolve()),
                "NLQA_REPORT_DIR": str((root / "reports").resolve()),
                "CUSTOMER_PASSWORD": "correct-horse",
            }
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "nlqa",
                "run",
                "Log in as a customer and verify the dashboard is shown",
                "--url",
                f"{site_server}/login_basic.html",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=40,
            env=run_env,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        console_output = completed.stdout + completed.stderr
        assert "RESULT: PASS" in console_output
        assert "correct-horse" not in console_output
        run_dir = next((root / "reports").iterdir())
        report_json = (run_dir / "report.json").read_text(encoding="utf-8")
        report_html = (run_dir / "report.html").read_text(encoding="utf-8")
        assert "correct-horse" not in report_json
        assert "correct-horse" not in report_html
        assert (run_dir / "trace.zip").is_file()
        with zipfile.ZipFile(run_dir / "trace.zip") as archive:
            entries = [archive.read(name) for name in archive.namelist()]
        assert all(b"correct-horse" not in data for data in entries)
        assert list((run_dir / "screenshots").glob("*.jpg"))


def test_read_case_file_extracts_headers() -> None:
    with TemporaryDirectory(dir=".", prefix="case-file-") as directory:
        path = Path(directory) / "case.txt"
        path.write_text(
            "# name: Customer login\n# url: https://example.test/login\n# expect: pass\n"
            "Log in and verify the dashboard is shown.\n",
            encoding="utf-8",
        )
        case = read_case_file(path)
        assert case.name == "Customer login"
        assert case.url == "https://example.test/login"
        assert case.expected == "pass"
        assert "verify the dashboard" in case.body
