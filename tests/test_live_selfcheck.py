"""Opt-in network test; the default offline suite does not need credentials or the internet."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("NLQA_RUN_LIVE") != "1", reason="set NLQA_RUN_LIVE=1 to run live cases"
)
def test_selfcheck_cases_on_live_sites() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "nlqa", "selfcheck"],
        capture_output=True,
        text=True,
        check=False,
        timeout=1800,
    )
    assert result.returncode == 0, result.stdout + result.stderr
