# Approach and evidence

## Environment

- Checked 2026-11-06 (Asia/Kolkata).
- Python 3.12.10 and Git 2.51.0 are available.
- Created an isolated `.venv` and installed the declared Task 2 dependencies; the environment is ignored by Git.
- Playwright 1.64.1 and its managed Chromium are installed; local browser integration tests run offline.
- Milestone C-M0 evidence: `nlqa --help` exits successfully; `ruff check .` reports `All checks passed!`.
- Milestones C-M1–C-M8: `python -m pytest -q` passes all 47 offline tests; `ruff check .` passes.
- C-M5 verdict tests cover the finish rules; the judge can only downgrade a candidate PASS.
- C-M6 extraction tests cover explicit URLs, implicit expectations, malformed output, and generic cases. Page-controlled content is HTML-escaped inside the untrusted prompt boundary.
- C-M7 FakeLLM tests cover pass/fail evidence, premature pass rejection, one repair, secret placeholder allowlisting, and bounded stop conditions.
- C-M8 subprocess demo runs the CLI against the local login mini-site and writes `report.json`, autoescaped `report.html`, a redacted `trace.zip`, and screenshots. `nlqa --help` lists all commands. `nlqa doctor` currently exits 2 because no Task 2 model is configured; it confirms Chromium launches successfully.
- `nlqa doctor` confirms the browser install; no model is configured yet, so live LLM runs remain pending.

## Decisions

- Keep model and provider selection entirely in configuration; `LLM_MODEL` has no code default.
- Keep provider SDKs optional for end users and include them in the development extra for adapter tests.
- Store reports, traces, screenshots, and secret values only in ignored local paths.

## Open items

- Add the PHPTravels and other-site cases, then run `selfcheck` after a fresh Task 2 model key and PHPTravels credentials are configured.
- Complete README, clean-clone checks, CI, and the final submission checklist.
