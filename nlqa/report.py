"""Self-contained JSON and HTML reports for one browser test run."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from nlqa.models import RunResult

TEMPLATE_DIR = Path(__file__).with_name("templates")
TEMPLATE_ENV = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)


def write_report(result: RunResult, directory: str | Path) -> tuple[Path, Path]:
    """Write `report.json` and an autoescaped `report.html` into the run directory."""
    target = Path(directory).resolve()
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "report.json"
    html_path = target / "report.html"
    result.artifacts["report_json"] = str(json_path)
    result.artifacts["report_html"] = str(html_path)
    result.artifacts.setdefault("trace_zip", None)
    data = result.model_dump(mode="json")
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    template = TEMPLATE_ENV.get_template("report.html.j2")
    html_path.write_text(
        template.render(
            result=data,
            generated_at=datetime.now(UTC).isoformat(),
            steps=_with_relative_screenshots(data.get("steps", []), target),
            assertions=_with_relative_screenshots(data.get("assertions", []), target),
        ),
        encoding="utf-8",
    )
    return json_path, html_path


def create_run_directory(root: str | Path, goal: str) -> Path:
    """Create an isolated UTC timestamp + slug directory for a single run."""
    import re

    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    slug = re.sub(r"[^a-z0-9]+", "-", goal.casefold()).strip("-")[:48] or "browser-test"
    target = Path(root).resolve() / f"{timestamp}-{slug}"
    target.mkdir(parents=True, exist_ok=False)
    return target


def redact_trace(path: str | Path, secrets: set[str]) -> None:
    """Mask known values in text files inside a Playwright trace archive."""
    import zipfile

    trace = Path(path)
    if not trace.exists() or not secrets:
        return
    replacements = sorted((item.encode("utf-8") for item in secrets if item), key=len, reverse=True)
    temp_path = trace.with_suffix(".redacted.zip")
    try:
        with (
            zipfile.ZipFile(trace, "r") as source,
            zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as target,
        ):
            for entry in source.infolist():
                data = source.read(entry.filename)
                if not entry.filename.lower().endswith(
                    (".png", ".jpg", ".jpeg", ".webm", ".woff", ".woff2", ".ttf", ".otf")
                ):
                    for secret in replacements:
                        data = data.replace(secret, b"****")
                target.writestr(entry, data)
        for attempt in range(8):
            try:
                temp_path.replace(trace)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(min(0.2 * (2**attempt), 2.0))
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _with_relative_screenshots(records: list[dict[str, Any]], root: Path) -> list[dict[str, Any]]:
    result = []
    for record in records:
        item = dict(record)
        screenshot = item.get("screenshot")
        if screenshot:
            try:
                item["screenshot_relative"] = (
                    Path(screenshot).resolve().relative_to(root).as_posix()
                )
            except ValueError:
                item["screenshot_relative"] = None
        result.append(item)
    return result
