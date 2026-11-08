from __future__ import annotations

import subprocess
import sys


def test_importing_cli_does_not_require_optional_anthropic_sdk() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import nlqa.cli; "
                "assert 'nlqa.llm.anthropic_client' not in sys.modules"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
