# Approach and limitations

## Approach

The tool uses a stateless observe-act loop. The LLM extracts a test specification, then proposes one browser action from a shared, validated tool set. Playwright captures visible controls and text across frames and open shadow roots, assigns fresh short-lived references, and executes actions. Assertions poll the browser directly and create evidence records. The verdict engine requires the latest assertion for every verification to pass before it accepts PASS; a failed assertion is required for FAIL. Once every verification has passing evidence, the code finalizes without asking the model to say `finish`; the optional judge can only downgrade PASS to ERROR.

## Why observe-act with deterministic verdicts

The model needs a current view to handle unfamiliar page structures and test sentences. Reobserving after each action limits stale references. Deterministic Playwright assertions keep the LLM from deciding the test outcome based on its own narration. The report shows the extracted expectations and actual evidence so a reviewer can spot weak specifications.

## Prompts and safety

The spec-extraction prompt requires observable conditions, only accepts URLs present in the user's text, and asks the model not to invent credentials or expected copy. The browser prompt says page contents are untrusted data. Page text is escaped within a bounded `<page>` delimiter, all tools use JSON schemas with runtime validation, and navigation accepts only HTTP(S), with an optional domain allowlist. Placeholders are substituted only at the browser-action boundary; unlisted placeholders are rejected. Password values are masked in prompts, logs, reports, and trace text.

## Environment

- Checked 2026-11-07 (Asia/Kolkata). Python 3.12.10, isolated `.venv`, Playwright 1.64.1, and managed Chromium are installed.
- The `.venv` and `.env` are ignored by Git. No API key or password is committed.
- `ruff check .` passes. Latest offline run: `pytest -m "not live" -q` reports 80 passed, 1 live test deselected.
- The latest Groq key was accepted by the read-only `/models` endpoint. An inherited shell `OPENAI_API_KEY` overrode the project `.env` and was rejected; removing that shell variable let the runner use the `.env` key. Nothing secret was printed or added to GitHub/Render.
- PHPTravels' official demo form requests personal/contact details and a security check to generate credentials. I did not submit it or enter real contact details.

## Evidence

| Check | Result |
|---|---|
| False PHPTravels greeting | Real Qwen runner returned the expected `FAIL` after proving `Welcome back Zebra Unicorn` was absent from `https://phptravels.com/demo`. It used 2 model calls and did not interact with the page. |
| PHPTravels hotel search | Real Qwen runner selected Dubai and exact nationality India, reached `/stays/dubai/07-11-2026/08-11-2026/IN/1/2-0`, and proved the combined URL fragments plus visible `20 stays found`. No hotel was opened or booked. The old `No Stays found` expectation was stale and is now replaced with a result-summary check that also matches the empty-state wording. |
| Hotel-run final outcome | That live run ended `ERROR` only because Groq returned `Retry-After: 1889` on the extra `finish` request, after both required assertions were proven. The runner now finalizes once all verifications are proven, so `--no-judge` needs no extra model call. The new behavior is covered by an offline regression test; the full live case was not rerun after this change because of the provider cooldown. |
| PHPTravels demo page | Read-only page check passed; no demo contact form was submitted. |
| The Internet practice login | A prior live runner pass is recorded. |
| SauceDemo add-to-cart | Direct Playwright inspection showed the cart change from empty to one. The runner assertion was fixed to compare exact badge text, but a fresh real-model PASS remains unverified because of Groq quota. |
| Offline browser pipeline | FakeLLM-backed tests cover deterministic PASS/FAIL evidence, finalization, placeholder masking, and reports. |
| `ruff check .` | Pass |
| `pytest -m "not live" -q` | 80 passed, 1 live test deselected |

Groq returned long free-tier cooldowns across live runs (including 590 seconds and 1889 seconds). The 1889-second cooldown is the only remaining obstacle to replaying the complete hotel flow under the updated finalization logic; the real browser assertions already prove its two conditions. The implementation now waits once for explicit cooldowns up to 60 seconds and stops cleanly on longer ones.

## Decisions

- Keep model and provider selection entirely in configuration; `LLM_MODEL` has no code default.
- Keep the local defaults at 60 observed elements and 512 completion tokens per response. Tune the hosted Render instance to 30 observed elements, the same 512 completion-token budget, and its 360-second maximum run window to reduce prompt use and give longer flows more time.
- Keep provider SDKs optional for end users and include them in the development extra for adapter tests.
- Store reports, traces, screenshots, and secret values only in ignored local paths.
- The clean-clone verification creates its own `.venv` inside the temporary clone so it does not install dependencies into the machine's default Python environment.
- Bound OpenAI-compatible model requests to two attempts and a 20-second timeout. Explicit provider cooldowns up to 60 seconds are honored once; longer `Retry-After` values stop immediately and are reported instead of being shortened. Network/5xx fallback waits remain capped at two seconds.

## Limitations

- The language model may choose a weak action or assertion; the evidence gate reduces but does not eliminate that risk.
- Free model-provider rate limits or slow responses can still prevent a live run from finishing, even when the same browser flow works manually.
- Vague requirements may produce an incomplete extracted spec. Review the expected conditions in each report.
- No vision, CAPTCHA/MFA bypass, file upload/download, drag-and-drop, or closed-shadow-root support.
- Arbitrary external sites can change, block automation, or display controls that the snapshot cannot use. Hotel search and shared demo accounts may be flaky.
- The prompt-injection defense and navigation restrictions are best-effort. Avoid destructive actions and never test with real customer/payment information.

## Submission follow-up

- The user plans to record the required video later; no recording is included in the repository.
- The PHPTravels login pass used the provided account on `app.phptravels.com`, not credentials generated by the public demo form. The real-model false-claim case records the expected FAIL. A real-model hotel search proved the required Dubai/India URL and visible result summary; its run stopped only on a Groq cooldown after those assertions. The current code finalizes from complete proof without another `finish` call, covered by the 80-test offline suite. A fresh live replay is deferred to Groq quota availability.
