"""Small public web front end for the nlqa command-line runner."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator

from nlqa.network_safety import validate_public_http_url
from nlqa.startup_errors import startup_failure_reason
from nlqa.web_summary import verification_details

app = FastAPI(title="Natural Language Browser Test Runner")
_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_executor = ThreadPoolExecutor(max_workers=1)
_JOB_ID = re.compile(r"^[a-f0-9]{32}$")
_run_times_by_client: dict[str, list[float]] = {}
_RATE_WINDOW_SECONDS = 60 * 60


class RunRequest(BaseModel):
    """User-supplied test sentence and public start URL."""

    test_case: str = Field(min_length=8, max_length=3000)
    url: str = Field(min_length=8, max_length=2048)

    @field_validator("test_case")
    @classmethod
    def trim_test_case(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 8:
            raise ValueError("Enter a test case with at least 8 characters.")
        return value

    @field_validator("url")
    @classmethod
    def validate_public_http_url(cls, value: str) -> str:
        return validate_public_http_url(value)


def _positive_setting(name: str, default: int, maximum: int) -> int:
    try:
        configured = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        configured = default
    return max(1, min(maximum, configured))


def _run_job(job_id: str, test_case: str, url: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job["status"] = "running"

    max_steps = _positive_setting("WEB_MAX_STEPS", 24, 40)
    max_seconds = _positive_setting("WEB_MAX_SECONDS", 180, 600)
    report_root = Path(os.environ.get("NLQA_REPORT_DIR", "reports/web")).resolve()
    run_root = (report_root / job_id).resolve()
    summary: dict[str, Any] = {
        "outcome": "ERROR",
        "reason": "The hosted runner could not produce a result.",
        "duration_ms": 0,
        "step_count": 0,
        "verification_status": {},
    }
    try:
        run_root.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["NLQA_REPORT_DIR"] = str(run_root)
        env["NLQA_PUBLIC_ONLY"] = "true"
        command = [
            sys.executable,
            "-m",
            "nlqa",
            "run",
            test_case,
            "--url",
            url,
            "--max-steps",
            str(max_steps),
            "--max-seconds",
            str(max_seconds),
            "--report-dir",
            str(run_root),
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max_seconds + 45,
            check=False,
            env=env,
        )
        reports = sorted(run_root.rglob("report.json"), key=lambda path: path.stat().st_mtime)
        if reports:
            import json

            report = json.loads(reports[-1].read_text(encoding="utf-8"))
            verifications = report.get("verification_status", {})
            spec = report.get("spec") if isinstance(report.get("spec"), dict) else {}
            details = verification_details(report)
            summary = {
                "outcome": str(report.get("outcome", "ERROR")).upper(),
                "reason": str(report.get("reason", "No result reason was recorded."))[:500],
                "duration_ms": max(0, int(report.get("duration_ms", 0))),
                "step_count": len(report.get("steps") or []),
                "verification_status": verifications if isinstance(verifications, dict) else {},
                "verification_details": details,
                "goal": str(spec.get("goal", ""))[:300],
            }
            if completed.returncode not in {0, 1, 2}:
                summary["notice"] = "The runner process exited unexpectedly; see server logs."
        else:
            summary = {
                "outcome": "ERROR",
                "reason": startup_failure_reason(
                    completed.stdout, completed.stderr, completed.returncode
                ),
                "duration_ms": 0,
                "step_count": 0,
                "verification_status": {},
                "model": "",
            }
    except subprocess.TimeoutExpired:
        summary = {
            "outcome": "ERROR",
            "reason": "The run exceeded the hosted runner's time limit.",
            "duration_ms": max_seconds * 1000,
            "step_count": 0,
            "verification_status": {},
            "model": "",
        }
    except Exception as exc:
        summary = {
            "outcome": "ERROR",
            "reason": f"The hosted runner could not finish ({type(exc).__name__}).",
            "duration_ms": 0,
            "step_count": 0,
            "verification_status": {},
            "model": "",
        }
    finally:
        # Reports can contain test data and page text. Keep them off the public host filesystem.
        if run_root.parent == report_root:
            shutil.rmtree(run_root, ignore_errors=True)

    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job["summary"] = summary
            job["status"] = "completed"
            job["finished_at"] = datetime.now(UTC).isoformat()


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    """Serve the same-origin interface while keeping the model key server-side."""
    page = Path(__file__).parent / "templates" / "web.html"
    return page.read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict[str, str]:
    """Render health check; does not spend model quota."""
    return {"status": "ok", "revision": os.environ.get("RENDER_GIT_COMMIT", "local")[:12]}


@app.post("/api/runs", status_code=202)
def create_run(payload: RunRequest, request: Request) -> dict[str, str]:
    """Queue a bounded test run for this client's supplied URL and instruction."""
    client_key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _lock:
        recent = [
            timestamp
            for timestamp in _run_times_by_client.get(client_key, [])
            if now - timestamp < _RATE_WINDOW_SECONDS
        ]
        if len(recent) >= _positive_setting("WEB_MAX_RUNS_PER_HOUR", 10, 100):
            _run_times_by_client[client_key] = recent
            raise HTTPException(
                status_code=429,
                detail="This browser has reached the run limit. Try again in about an hour.",
            )
        active = sum(job["status"] in {"queued", "running"} for job in _jobs.values())
        if active >= 1:
            raise HTTPException(
                status_code=429, detail="A test is already running. Try again soon."
            )
        job_id = uuid.uuid4().hex
        _jobs[job_id] = {
            "id": job_id,
            "status": "queued",
            "created_at": datetime.now(UTC).isoformat(),
            "summary": None,
        }
        _run_times_by_client[client_key] = [*recent, now]
        for old_id in list(_jobs)[:-20]:
            if _jobs[old_id]["status"] == "completed":
                del _jobs[old_id]
        _executor.submit(_run_job, job_id, payload.test_case, payload.url)
    return {"id": job_id, "status": "queued"}


@app.get("/api/runs/{job_id}")
def get_run(job_id: str) -> dict[str, Any]:
    """Return the status and a scrubbed summary for a known run."""
    if not _JOB_ID.fullmatch(job_id):
        raise HTTPException(status_code=404, detail="Run not found.")
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(
                status_code=404, detail="Run not found; the service may have restarted."
            )
        return dict(job)
