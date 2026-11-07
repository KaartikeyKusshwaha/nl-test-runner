"""Bounded Playwright actions, fresh-ref resolution, and safe navigation."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Frame, Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from nlqa.models import ToolCall
from nlqa.observe import Observation, observe
from nlqa.secrets import SecretStore


class ToolExecutionError(RuntimeError):
    """Readable action failure safe to return to the model."""


_OVERLAY_DISMISSAL = re.compile(
    r"\b(accept|agree|understand|continue|dismiss|close|got it|okay|ok)\b", re.I
)


@dataclass(slots=True)
class ActionResult:
    """Outcome of a non-assertion browser tool."""

    ok: bool
    detail: str
    page_url: str


class BrowserController:
    """Playwright action facade that resolves only refs from the latest snapshot."""

    def __init__(
        self,
        page: Page,
        *,
        report_dir: str | Path = "reports",
        secret_store: SecretStore | None = None,
        allow_domains: list[str] | None = None,
        timeout_ms: int = 7000,
    ) -> None:
        self.page = page
        self.context = page.context
        self.report_dir = Path(report_dir)
        self.secret_store = secret_store or SecretStore({})
        self.allow_domains = [domain.lower().lstrip(".") for domain in (allow_domains or [])]
        self.timeout_ms = timeout_ms
        self.dialog_messages: list[str] = []
        self._new_pages: list[Page] = []
        self.context.on("page", self._on_new_page)
        for existing_page in self.context.pages:
            self._attach_dialog_handler(existing_page)

    def snapshot(self, max_elements: int = 150) -> Observation:
        """Capture the current page and frame state."""
        return observe(self.page, max_elements=max_elements)

    def resolve_ref(self, ref: str, observation: Observation) -> tuple[Frame, Locator]:
        """Resolve exactly one element by a fresh observation reference."""
        item = next((item for item in observation.elements if item["ref"] == ref), None)
        if item is None:
            raise ToolExecutionError(
                f"ref {ref} is stale or missing; use refs from the latest observation."
            )
        frame_index = int(item["frameIndex"])
        frames = self.page.frames
        if frame_index >= len(frames):
            raise ToolExecutionError(
                f"ref {ref} is stale or missing; use refs from the latest observation."
            )
        frame = frames[frame_index]
        local_ref = ref.rsplit(":", 1)[-1]
        locator = frame.locator(f'[data-nlqa-ref="{local_ref}"]')
        try:
            count = locator.count()
        except Exception as exc:
            raise ToolExecutionError(
                f"ref {ref} is stale or missing; use refs from the latest observation."
            ) from exc
        if count != 1:
            raise ToolExecutionError(
                f"ref {ref} is stale or missing; use refs from the latest observation."
            )
        return frame, locator

    def perform(self, call: ToolCall, observation: Observation, step: int) -> ActionResult:
        """Run one action from the shared tool vocabulary."""
        name, args = call.name, call.args
        if name == "navigate":
            url = str(args["url"])
            self._validate_navigation(url)
            self.page.goto(url, wait_until="commit", timeout=self.timeout_ms)
            self.wait_for_page_ready()
            return ActionResult(True, "navigated to the requested URL", self.page.url)
        if name == "click":
            _, locator = self.resolve_ref(str(args["ref"]), observation)
            ref_line = next(
                (line for line in observation.lines if line.startswith(f"[{args['ref']}] ")), ""
            )
            dismisses_overlay = "top-overlay" in ref_line and bool(
                _OVERLAY_DISMISSAL.search(ref_line)
            )
            target = (locator.get_attribute("target") or "").casefold()
            if target == "_blank":
                try:
                    with self.page.expect_popup(timeout=self.timeout_ms) as popup_info:
                        self._click(locator)
                    self.page = popup_info.value
                    self._attach_dialog_handler(self.page)
                except PlaywrightTimeoutError:
                    # The click may be a normal same-tab action; it has already run.
                    self._switch_to_new_page_if_any()
            else:
                try:
                    self._click(locator)
                except ToolExecutionError:
                    if dismisses_overlay or not self._dismiss_new_top_overlay():
                        raise
                    return ActionResult(
                        False,
                        "A new blocking notice was dismissed; refresh the page observation "
                        "and retry.",
                        self.page.url,
                    )
                if dismisses_overlay:
                    self._wait_for_overlay_to_clear()
                self._switch_to_new_page_if_any()
            self._bounded_load_wait()
            return ActionResult(True, f"clicked {args['ref']}{self._page_notice()}", self.page.url)
        if name == "type":
            _, locator = self.resolve_ref(str(args["ref"]), observation)
            text = str(args["text"])
            if args.get("clear_first", True):
                locator.fill(text, timeout=self.timeout_ms)
            else:
                locator.press_sequentially(text, timeout=self.timeout_ms)
            # Let autocomplete menus and other input-driven widgets render before
            # the next observation is captured, so the agent can act on fresh options.
            self.page.wait_for_timeout(1500)
            if args.get("press_enter", False):
                locator.press("Enter", timeout=self.timeout_ms)
                self._bounded_load_wait()
            return ActionResult(True, f"typed into {args['ref']}", self.page.url)
        if name == "select_option":
            _, locator = self.resolve_ref(str(args["ref"]), observation)
            try:
                locator.select_option(label=str(args["option_label"]), timeout=self.timeout_ms)
            except Exception as exc:
                raise ToolExecutionError(
                    "select_option works with native select elements; use click for a custom menu."
                ) from exc
            return ActionResult(
                True, f"selected the requested option in {args['ref']}", self.page.url
            )
        if name == "press_key":
            key = str(args["key"])
            self.page.keyboard.press(key)
            self._bounded_load_wait()
            return ActionResult(True, f"pressed {key}", self.page.url)
        if name == "hover":
            _, locator = self.resolve_ref(str(args["ref"]), observation)
            locator.hover(timeout=self.timeout_ms)
            return ActionResult(True, f"hovered over {args['ref']}", self.page.url)
        if name == "scroll":
            direction = str(args["direction"])
            amount = min(2000, max(1, int(args.get("amount", 600))))
            self.page.evaluate(
                "({direction, amount}) => window.scrollBy(0, direction === 'down' "
                "? amount : -amount)",
                {"direction": direction, "amount": amount},
            )
            return ActionResult(True, f"scrolled {direction} by {amount}px", self.page.url)
        if name == "go_back":
            try:
                self.page.go_back(wait_until="commit", timeout=self.timeout_ms)
            except PlaywrightTimeoutError:
                return ActionResult(False, "no previous page was available", self.page.url)
            self._bounded_load_wait()
            return ActionResult(True, f"went back to {self.page.url}", self.page.url)
        if name == "wait":
            seconds = min(5.0, max(0.0, float(args["seconds"])))
            time.sleep(seconds)
            return ActionResult(True, f"waited {seconds:g}s", self.page.url)
        if name == "wait_for_text":
            text = str(args["text"])
            deadline = time.monotonic() + min(10.0, float(args.get("timeout_s", 5)))
            while time.monotonic() < deadline:
                if self.text_is_visible(text):
                    return ActionResult(
                        True, f"text became visible: {self.secret_store.mask(text)}", self.page.url
                    )
                time.sleep(0.25)
            return ActionResult(
                False, f"text did not become visible: {self.secret_store.mask(text)}", self.page.url
            )
        raise ToolExecutionError(f"'{name}' is not a browser action handled by the action runner.")

    def text_is_visible(self, text: str) -> bool:
        """Search visible body text across attached frames."""
        expected = " ".join(text.casefold().split())
        for frame in self.page.frames:
            try:
                actual = " ".join(frame.locator("body").inner_text(timeout=1000).casefold().split())
                if expected in actual:
                    return True
            except Exception:
                continue
        return False

    def screenshot(self, step: int, label: str = "step") -> str | None:
        """Save one JPEG screenshot for reports; return its path when successful."""
        directory = Path(self.report_dir) / "screenshots"
        directory.mkdir(parents=True, exist_ok=True)
        safe_label = (
            "".join(character.lower() if character.isalnum() else "-" for character in label).strip(
                "-"
            )[:40]
            or "step"
        )
        path = directory / f"{step:03d}-{safe_label}.jpg"
        try:
            self.page.screenshot(
                path=str(path), type="jpeg", quality=60, full_page=False, timeout=5000
            )
            return str(path)
        except Exception:
            return None

    def _validate_navigation(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ToolExecutionError("Only absolute http:// and https:// navigation is allowed.")
        if self.allow_domains:
            host = parsed.hostname.lower()
            allowed = any(
                host == domain or host.endswith(f".{domain}") for domain in self.allow_domains
            )
            if not allowed:
                raise ToolExecutionError(
                    f"Navigation to domain '{host}' is outside --allow-domain."
                )

    def _click(self, locator: Locator) -> None:
        try:
            locator.scroll_into_view_if_needed(timeout=self.timeout_ms)
            locator.click(timeout=self.timeout_ms)
        except Exception as exc:
            raise ToolExecutionError(f"Click failed: {type(exc).__name__}.") from exc

    def _on_new_page(self, page: Page) -> None:
        self._new_pages.append(page)
        self._attach_dialog_handler(page)

    def _attach_dialog_handler(self, page: Page) -> None:
        page.on("dialog", lambda dialog: self._accept_dialog(dialog))

    def _accept_dialog(self, dialog: Any) -> None:
        self.dialog_messages.append(self.secret_store.mask(dialog.message))
        try:
            dialog.accept()
        except Exception:
            pass

    def _switch_to_new_page_if_any(self) -> None:
        pages = [page for page in self._new_pages if not page.is_closed()]
        if pages:
            self.page = pages[-1]
            self._new_pages = [page for page in self._new_pages if page is not self.page]

    def _page_notice(self) -> str:
        return (
            f"; switched to new tab: {self.page.url}"
            if self._new_pages and self._new_pages[-1] is self.page
            else ""
        )

    def _bounded_load_wait(self) -> None:
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=2000)
        except PlaywrightTimeoutError:
            pass
        try:
            self.page.wait_for_load_state("networkidle", timeout=3000)
        except PlaywrightTimeoutError:
            pass

    def wait_for_page_ready(self) -> None:
        """Give the current page a bounded chance to finish its initial render."""
        self._bounded_load_wait()

    def _wait_for_overlay_to_clear(self) -> None:
        """Wait through a dismiss animation before allowing clicks behind an overlay."""
        script = """() => ![...document.querySelectorAll(
          'dialog[open],[role="dialog"],[aria-modal="true"],body *'
        )].some(element => {
          const style = getComputedStyle(element);
          if (style.display === 'none' || style.visibility === 'hidden' ||
              style.pointerEvents === 'none') return false;
          if (element.matches('dialog[open],[role="dialog"],[aria-modal="true"]')) return true;
          const rect = element.getBoundingClientRect();
          const zIndex = Number.parseInt(style.zIndex, 10);
          return style.position === 'fixed' && Number.isFinite(zIndex) && zIndex >= 10 &&
            rect.width >= innerWidth * 0.75 && rect.height >= innerHeight * 0.5;
        })"""
        try:
            self.page.wait_for_function(script, timeout=min(self.timeout_ms, 4000))
        except PlaywrightTimeoutError as exc:
            raise ToolExecutionError(
                "The acknowledgement control was clicked, but the blocking overlay stayed open."
            ) from exc

    def _dismiss_new_top_overlay(self) -> bool:
        """Dismiss a newly appeared, blocking acknowledgement after a click timeout."""
        fresh = self.snapshot()
        line = next(
            (
                item
                for item in fresh.lines
                if "top-overlay" in item and _OVERLAY_DISMISSAL.search(item)
            ),
            None,
        )
        if line is None:
            return False
        ref = line.split("]", 1)[0][1:]
        _, dismiss_button = self.resolve_ref(ref, fresh)
        self._click(dismiss_button)
        self._wait_for_overlay_to_clear()
        return True
