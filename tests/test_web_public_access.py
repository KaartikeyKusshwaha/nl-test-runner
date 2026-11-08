from __future__ import annotations

from importlib import import_module
from types import SimpleNamespace

import pytest
from starlette.requests import Request

web = import_module("nlqa.web")


def _configure_public_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "validate_public_http_url", lambda value: value)
    monkeypatch.setattr(web, "_jobs", {})
    monkeypatch.setattr(web, "_run_times_by_client", {})
    monkeypatch.setattr(web, "_executor", SimpleNamespace(submit=lambda *_args: None))


def test_health_reports_deployed_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_GIT_COMMIT", "1234567890abcdef")

    assert web.health() == {"status": "ok", "revision": "1234567890ab"}


def test_web_run_and_poll_work_without_an_access_code(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_public_run(monkeypatch)
    request = Request(
        {"type": "http", "method": "POST", "path": "/api/runs", "client": ("203.0.113.5", 1)}
    )
    started = web.create_run(
        web.RunRequest(
            url="https://any-site.example/", test_case="Verify its title is visible"
        ),
        request,
    )
    status = web.get_run(started["id"])
    assert status["status"] == "queued"


def test_public_web_run_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_public_run(monkeypatch)
    monkeypatch.setenv("WEB_MAX_RUNS_PER_HOUR", "1")
    request = Request(
        {"type": "http", "method": "POST", "path": "/api/runs", "client": ("203.0.113.5", 1)}
    )
    payload = web.RunRequest(
        url="https://any-site.example/", test_case="Verify its title is visible"
    )

    web.create_run(payload, request)
    with pytest.raises(web.HTTPException) as limited:
        web.create_run(payload, request)
    assert limited.value.status_code == 429
    assert "run limit" in limited.value.detail.lower()
