# Approach and limitations

## Approach

The tool uses a stateless observe-act loop. The LLM extracts a test specification, then proposes one browser action from a shared, validated tool set. Playwright captures visible controls and text across frames and open shadow roots, assigns fresh short-lived references, and executes actions. Assertions poll the browser directly and create evidence records. The verdict engine requires the latest assertion for every verification to pass before it accepts PASS; a failed assertion is required for FAIL. Any blocked or unproven flow is ERROR. A separate model judge can only downgrade PASS to ERROR.

## Why observe-act with deterministic verdicts

The model needs a current view to handle unfamiliar page structures and test sentences. Reobserving after each action limits stale references. Deterministic Playwright assertions keep the LLM from deciding the test outcome based on its own narration. The report shows the extracted expectations and actual evidence so a reviewer can spot weak specifications.

## Prompts and safety

The spec-extraction prompt requires observable conditions, only accepts URLs present in the user's text, and asks the model not to invent credentials or expected copy. The browser prompt says page contents are untrusted data. Page text is escaped within a bounded `<page>` delimiter, all tools use JSON schemas with runtime validation, and navigation accepts only HTTP(S), with an optional domain allowlist. Placeholders are substituted only at the browser-action boundary; unlisted placeholders are rejected. Password values are masked in prompts, logs, reports, and trace text.

## Environment

- Checked 2026-11-06 (Asia/Kolkata).
- Python 3.12.10 and Git 2.51.0 are available.
- Created an isolated `.venv` and installed the declared Task 2 dependencies; the environment is ignored by Git.
- Playwright 1.64.1 and its managed Chromium are installed; local browser integration tests run offline.
- Milestone C-M0 evidence: `nlqa --help` exits successfully; `ruff check .` reports `All checks passed!`.
- Milestones C-M1–C-M8: `ruff check .` passes; latest offline run `pytest -m "not live" -q` reports 49 passed and 1 live test deselected.
- C-M5 verdict tests cover the finish rules; the judge can only downgrade a candidate PASS.
- C-M6 extraction tests cover explicit URLs, implicit expectations, malformed output, and generic cases. Page-controlled content is HTML-escaped inside the untrusted prompt boundary.
- C-M7 FakeLLM tests cover pass/fail evidence, premature pass rejection, one repair, secret placeholder allowlisting, and bounded stop conditions.
- C-M8 subprocess demo runs the CLI against the local login mini-site and writes `report.json`, autoescaped `report.html`, a redacted `trace.zip`, and screenshots. `nlqa --help` lists all commands. `nlqa doctor` exits 2 because no Task 2 model is configured; it confirms Chromium launches successfully.
- The official [PHPTravels live demo page](https://phptravels.com/demo) currently asks for first/last name, business, country, WhatsApp number, work email, and a security check before showing generated customer/storefront credentials. I did not submit a contact form or fabricate the user's details. The site says shared demo data is periodically reset and must not contain real customer information.
- PHPTravels cases are configured for environment placeholders; Task 2 live selfcheck has not been run because no Task 2 LLM key or PHPTravels test credentials were configured.

## Facts from PHPTravels demo preflight

The official demo page lists customer, admin, agent, and supplier logins, but the credentials are revealed only after submitting a form with a name, business, country, WhatsApp number, and work email plus a security check. It says the shared demo data resets regularly and warns not to enter real customer information. No contact details were submitted and no credentials were captured.

## Evidence

| Check | Result |
|---|---|
| `ruff check .` | Pass |
| `pytest -m "not live" -q` | 49 passed, 1 live test deselected |
| Local FakeLLM browser CLI | Pass; JSON/HTML, trace, and screenshots verified; secret absent from captured outputs |
| `nlqa doctor` | Chromium launches; external LLM check not configured, so command exits nonzero |
| PHPTravels + other-site live selfcheck | Not run; no Task 2 API key or PHPTravels credentials |

## Decisions

- Keep model and provider selection entirely in configuration; `LLM_MODEL` has no code default.
- Keep provider SDKs optional for end users and include them in the development extra for adapter tests.
- Store reports, traces, screenshots, and secret values only in ignored local paths.

## Limitations

- The language model may choose a weak action or assertion; the evidence gate reduces but does not eliminate that risk.
- Vague requirements may produce an incomplete extracted spec. Review the expected conditions in each report.
- No vision, CAPTCHA/MFA bypass, file upload/download, drag-and-drop, or closed-shadow-root support.
- Arbitrary external sites can change, block automation, or display controls that the snapshot cannot use. Hotel search and shared demo accounts may be flaky.
- The prompt-injection defense and navigation restrictions are best-effort. Avoid destructive actions and never test with real customer/payment information.

## Open items

- Run at least three PHPTravels and two other-site cases with a Task 2 model key and generated PHPTravels demo credentials; report outcomes/flakiness in the evidence table.
- Run the clean-clone script and inspect GitHub Actions after the repositories are pushed.
