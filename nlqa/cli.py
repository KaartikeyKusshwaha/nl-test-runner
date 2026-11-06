"""Command-line entry point for the plain-English browser test runner."""

from __future__ import annotations

import argparse
import importlib.metadata
import sys
from pathlib import Path

from nlqa.config import Settings


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser."""
    parser = argparse.ArgumentParser(
        prog="nlqa",
        description="Run plain-English QA test cases in a browser with evidence-based results.",
    )
    parser.add_argument("--version", action="version", version="nl-test-runner 0.1.0")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser(
        "doctor", help="Check Python, Playwright, browser, and model configuration"
    )
    return parser


def _doctor() -> int:
    settings = Settings()
    print(f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    try:
        print(f"Playwright: {importlib.metadata.version('playwright')}")
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser_path = Path(playwright.chromium.executable_path)
            browser_status = "installed" if browser_path.exists() else "not installed"
            print(f"Chromium: {browser_status} ({browser_path})")
    except Exception as exc:  # doctor reports setup rather than failing with an import trace
        print(f"Playwright: unavailable ({type(exc).__name__})")
    print(f"Provider: {settings.llm_provider}")
    print(f"Model: {settings.llm_model or '(not set)'}")
    error = settings.provider_error()
    if error:
        print(f"LLM configuration: {error}")
        return 1
    print("LLM configuration: configured")
    return 0


def main() -> int:
    """Run a CLI command."""
    args = build_parser().parse_args()
    if args.command == "doctor":
        return _doctor()
    return 2
