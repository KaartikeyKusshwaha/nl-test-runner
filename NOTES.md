# Approach and evidence

## Environment

- Checked 2026-11-06 (Asia/Kolkata).
- Python 3.12.10 and Git 2.51.0 are available.
- Created an isolated `.venv` and installed the declared Task 2 dependencies; the environment is ignored by Git.
- Playwright 1.64.1 is installed. Its managed Chromium still needs to be installed before browser tests.
- Milestone C-M0 evidence: `nlqa --help` exits successfully; `ruff check .` reports `All checks passed!`.

## Decisions

- Keep model and provider selection entirely in configuration; `LLM_MODEL` has no code default.
- Keep provider SDKs optional for end users and include them in the development extra for adapter tests.
- Store reports, traces, screenshots, and secret values only in ignored local paths.

## Open items

- Implement the observation/action loop, deterministic verdict gating, provider adapters, offline mini-sites, and live cases.
- Complete PHPTravels findings and selfcheck evidence after the generic runner works.
