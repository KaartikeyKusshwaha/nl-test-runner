#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git clone --no-hardlinks "$ROOT" "$TMP/repo"
cd "$TMP/repo"
python -m pip install -e ".[dev]"
playwright install chromium
ruff check .
pytest -m "not live"
nlqa --help
echo "Clean-clone verification passed."
