# Approach and evidence

## Environment

- Checked 2026-11-06 (Asia/Kolkata).
- Python 3.12.10 and Git 2.51.0 are available.
- Created an isolated `.venv` and installed the declared Task 2 dependencies; the environment is ignored by Git.
- Playwright 1.64.1 and its managed Chromium are installed; local browser integration tests run offline.
- Milestone C-M0 evidence: `nlqa --help` exits successfully; `ruff check .` reports `All checks passed!`.
- Milestones C-M1–C-M4: `python -m pytest -q` passes all 17 offline tests; `ruff check .` passes.
- `nlqa doctor` confirms the browser install; no model is configured yet, so live LLM runs remain pending.

## Decisions

- Keep model and provider selection entirely in configuration; `LLM_MODEL` has no code default.
- Keep provider SDKs optional for end users and include them in the development extra for adapter tests.
- Store reports, traces, screenshots, and secret values only in ignored local paths.

## Open items

- Implement the bounded agent loop, deterministic verdict gating, report generation, and CLI run commands.
- Complete PHPTravels findings and live selfcheck evidence after a Task 2 model key is configured.
