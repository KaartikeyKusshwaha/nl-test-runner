#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git clone --no-hardlinks "$ROOT" "$TMP/repo"
cd "$TMP/repo"
python -m venv .venv
PY=".venv/bin/python"
if [[ -x ".venv/Scripts/python.exe" ]]; then PY=".venv/Scripts/python.exe"; fi
"$PY" -m pip install -e ".[dev]"
"$PY" -m playwright install chromium
"$PY" -m ruff check .
"$PY" -m pytest -m "not live"
"$PY" -m nlqa --help
echo "Clean-clone verification passed."
