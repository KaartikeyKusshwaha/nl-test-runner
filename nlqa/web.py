"""Small authenticated web front end for the nlqa command-line runner."""

from __future__ import annotations

import ipaddress
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator

from nlqa.startup_errors import startup_failure_reason
from nlqa.web_summary import verification_details

app = FastAPI(title="Natural Language Browser Test Runner")
_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_executor = ThreadPoolExecutor(max_workers=1)
_JOB_ID = re.compile(r"^[a-f0-9]{32}$")


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
        value = value.strip()
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Use a full http:// or https:// URL.")
        if parsed.username or parsed.password:
            raise ValueError("Do not put credentials in the URL.")
        hostname = parsed.hostname.rstrip(".").casefold()
        if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
            raise ValueError("The hosted runner accepts public website URLs only.")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            if not address.is_global:
                raise ValueError("The hosted runner accepts public website URLs only.")
        return value


def _require_access_token(authorization: str | None) -> None:
    configured = os.environ.get("APP_ACCESS_TOKEN", "").strip()
    if not configured:
        raise HTTPException(status_code=503, detail="The hosted runner is not configured yet.")
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.casefold() != "bearer" or not secrets.compare_digest(supplied, configured):
        raise HTTPException(
            status_code=401, detail="Enter the access code configured by the owner."
        )


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
    return {"status": "ok"}


@app.post("/api/runs", status_code=202)
def create_run(
    request: RunRequest, authorization: str | None = Header(default=None)
) -> dict[str, str]:
    """Queue a bounded test run after checking the owner access code."""
    _require_access_token(authorization)
    with _lock:
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
        for old_id in list(_jobs)[:-20]:
            if _jobs[old_id]["status"] == "completed":
                del _jobs[old_id]
        _executor.submit(_run_job, job_id, request.test_case, request.url)
    return {"id": job_id, "status": "queued"}


@app.get("/api/runs/{job_id}")
def get_run(job_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Return the status and a scrubbed summary for a known run."""
    _require_access_token(authorization)
    if not _JOB_ID.fullmatch(job_id):
        raise HTTPException(status_code=404, detail="Run not found.")
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(
                status_code=404, detail="Run not found; the service may have restarted."
            )
        return dict(job)
