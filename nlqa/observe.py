"""Compact browser observations for the model's next bounded action."""

from __future__ import annotations

import hashlib
import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

SNAPSHOT_SCRIPT = Path(__file__).with_name("snapshot.js").read_text(encoding="utf-8")


@dataclass(slots=True)
class Observation:
    """Combined view of the main document and every attached frame."""

    title: str
    url: str
    elements: list[dict[str, Any]]
    lines: list[str]
    text: str
    headings: list[str]
    alerts: list[str]
    hash: str
    truncated: bool = False

    def prompt_section(self) -> str:
        """Render bounded page content as explicitly untrusted data."""
        return (
            f'<page url="{html.escape(self.url, quote=True)}" '
            f'title="{html.escape(self.title, quote=True)}">\n'
            f"INTERACTIVE ELEMENTS:\n{html.escape(chr(10).join(self.lines)) or '(none)'}\n"
            f"HEADINGS: {html.escape(json.dumps(self.headings, ensure_ascii=False))}\n"
            f"VISIBLE TEXT EXCERPT:\n{html.escape(self.text) or '(empty)'}\n"
            f"ALERTS/DIALOGS: {html.escape(json.dumps(self.alerts, ensure_ascii=False))}\n"
            f"ELEMENT LIST TRUNCATED: {self.truncated}\n</page>"
        )


def observe(page: Page, max_elements: int = 150) -> Observation:
    """Snapshot visible interactive elements across the main document and frames."""
    elements: list[dict[str, Any]] = []
    lines: list[str] = []
    texts: list[str] = []
    headings: list[str] = []
    alerts: list[str] = []
    hashes: list[str] = []
    truncated = False
    for frame_index, frame in enumerate(page.frames):
        prefix = f"f{frame_index}" if frame_index else ""
        try:
            snapshot = frame.evaluate(
                SNAPSHOT_SCRIPT, {"prefix": prefix, "maxElements": max_elements}
            )
        except Exception:
            continue
        elements.extend(snapshot.get("elements", []))
        lines.extend(snapshot.get("lines", []))
        if snapshot.get("text"):
            texts.append(snapshot["text"])
        headings.extend(snapshot.get("headings", []))
        alerts.extend(snapshot.get("alerts", []))
        hashes.append(snapshot.get("hash", ""))
        truncated |= bool(snapshot.get("truncated"))
    title = page.title()
    url = page.url
    signature = f"{url}|{title}|{'|'.join(hashes)}|{'|'.join(lines)}"
    digest = hashlib.blake2s(signature.encode("utf-8"), digest_size=8).hexdigest()
    return Observation(
        title,
        url,
        elements,
        lines,
        "\n".join(texts)[:2000],
        headings[:10],
        alerts[:20],
        digest,
        truncated,
    )
