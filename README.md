# Natural Language Browser Test Runner

`nlqa` accepts a test written in plain English, uses a configured language model to choose browser actions, and uses Playwright assertions to decide whether the result is **PASS**, **FAIL**, or **ERROR**. It is site-agnostic: the page is discovered at runtime, and the test sentence supplies the intended behavior.

## How it works

```text
English test -> LLM extracts goal and verifications -> Playwright observes current page
     -> LLM proposes one validated action -> deterministic assertion records evidence
     -> verdict gate checks every verification -> JSON + HTML + trace + screenshots
```

- The extractor turns the sentence into a goal, advisory steps, test data, and observable verifications.
- A compact page snapshot covers visible controls, open shadow roots, and frames. Password fields are masked.
- The model proposes one action at a time. The runner validates arguments, uses fresh element references, and bounds time, steps, retries, and navigation.
- Playwright executes assertions and stores read-back evidence. The model cannot declare a test passed by itself.
- PASS requires every verification to have a passing assertion. FAIL requires an assertion that did not hold. Missing evidence, blocked execution, or budget exhaustion is ERROR.
- A second model call may downgrade a weakly supported PASS to ERROR; it cannot create a PASS or FAIL.

## Prerequisites

- Python 3.11 or later
- Git
- Internet for model API calls and live demo sites
- A provider account and API key for real runs (OpenAI, Anthropic, or an OpenAI-compatible endpoint)

## Install

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
playwright install chromium
Copy-Item .env.example .env
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
playwright install chromium
cp .env.example .env
```

Edit `.env` and set `LLM_PROVIDER`, the provider's current `LLM_MODEL`, and the matching API key. The model identifier has no source-code default. Never commit `.env`.

```dotenv
LLM_PROVIDER=openai
LLM_MODEL=<provider-model-id>
OPENAI_API_KEY=<your-key>
```

Groq's OpenAI-compatible endpoint can use the same adapter. For example, with a model currently available on Groq's Free plan:

```dotenv
LLM_PROVIDER=openai_compatible
LLM_MODEL=openai/gpt-oss-120b
OPENAI_API_KEY=<your-Groq-key>
LLM_BASE_URL=https://api.groq.com/openai/v1
```

Free-plan quotas and model availability can change. The client honors provider retry headers and retries one malformed tool response.

For other adapters, use `LLM_PROVIDER=anthropic`, or `LLM_PROVIDER=openai_compatible` with `LLM_BASE_URL` and `OPENAI_API_KEY`. Provider libraries are installed by the development extra; a minimum installation can use `pip install -e ".[openai]"` or `pip install -e ".[anthropic]"`.

## Check setup

```bash
nlqa doctor
```

It checks Python, Playwright/Chromium, provider configuration, then sends a small connectivity ping. It never prints the key. It exits `2` if setup or ping fails.

## Run a test

One plain-English sentence:

```bash
nlqa run "Log in as a customer and verify the dashboard is shown" --url https://example.test/login
```

The start URL can also appear in the sentence. The extractor accepts only URLs explicitly present in the test text. If no URL can be found, pass `--url`.

Run a test case file or directory:

```bash
nlqa run-file cases/other/herokuapp_login.txt
nlqa run-dir cases/other
nlqa selfcheck
```

Test file format:

```text
# name: Customer login
# url: https://example.test/login
# expect: pass
Log in with the provided customer details and verify the dashboard is shown.
```

The optional `# expect:` field supports `pass`, `fail`, and `error`; `selfcheck` compares actual outcomes to it. `--url` overrides a file's URL. Files can use `{{NAME}}` placeholders. The value comes from the environment or `.env`, is substituted only when the browser action runs, and is masked in prompts, console output, reports, and trace text. Never include real passwords in command history or test files.

### Run options

`nlqa run --help` shows all options. Common flags:

- `--headed` shows Chromium; `--slowmo 300` slows actions for a demo.
- `--max-steps 30` and `--max-seconds 240` bound each run.
- `--provider` / `--model` override `.env` settings.
- `--no-judge` disables the optional evidence-sufficiency review.
- `--report-dir reports` changes where run artifacts are written.
- Repeat `--allow-domain example.test` to restrict navigation.
- `--video` records a browser video; handle video artifacts like screenshots because a page may display personal data.
- `-v` prints additional run details with secrets masked.

## Included test cases

- `cases/phptravels/`: customer login, wrong password, deliberate false claim, and hotel search.
- `cases/other/`: Sauce Demo cart flow and successful/failed example logins on The Internet.

PHPTravels account credentials and the customer/storefront URLs are configured via `.env` as `PHPTRAVELS_CUSTOMER_URL`, `PHPTRAVELS_STOREFRONT_URL`, `PHPTRAVELS_CUSTOMER_EMAIL`, and `PHPTRAVELS_CUSTOMER_PASSWORD`; use the site's current demo access flow and only its shared test data. Never enter real customer/payment information. The project has been live-tested on a provided PHPTravels customer account and separate practice sites; see `NOTES.md` for outcomes and limits. The provided account is separate from credentials generated by the public `phptravels.com/demo` form.

## Development without an API key

Offline tests use local mini-sites and `FakeLLM`:

```bash
pytest -m "not live"
ruff check .
```

An optional end-to-end CLI test uses a JSON script file:

```json
{
  "spec": {
    "goal": "Sign in and verify the customer dashboard",
    "start_url": null,
    "steps": ["Enter credentials", "Submit the form"],
    "verifications": [
      {"id": "v1", "statement": "The customer dashboard is shown", "implicit": false}
    ],
    "data": {}
  },
  "tool_calls": [
    {"name": "assert_text_visible", "args": {"text": "Sign in", "verification_id": "v1"}},
    {"name": "finish", "args": {"verdict": "pass", "reason": "The heading is visible"}}
  ],
  "judge": [
    {"results": [{"id": "v1", "supports": true, "why": "The heading is visible"}]}
  ]
}
```

Set `NLQA_FAKE_SCRIPT=path/to/script.json` and `LLM_PROVIDER=fake`, then run against a local site. This development-only switch does not run real live cases.

## Reports and exit codes

Each run creates `reports/<UTC timestamp>-<goal>/` containing:

- `report.json`: extracted test, each action, assertion evidence, verdict, usage, and artifact paths.
- `report.html`: readable, autoescaped summary with screenshots and assertion details.
- `trace.zip`: Playwright trace with known secret values masked in text entries.
- `screenshots/`: JPEG snapshots taken during the run.
- Optional `video/`: browser video when `--video` is enabled.

Exit codes: `0` PASS, `1` evidence-backed FAIL or selfcheck mismatch, `2` ERROR/setup/configuration. An ERROR is never reported as a passing test.

## Limitations

- The model can choose a poor action or weak assertion; the evidence gate reduces but cannot eliminate that risk.
- Vague requirements can produce a poor extracted spec. Review the extracted verifications in the report.
- No vision-based interaction, CAPTCHA/MFA bypass, drag-and-drop, file upload/download, or closed-shadow-root support.
- External demo sites can change or block automation; hotel search and live credentials may be flaky or unavailable.
- Prompt-injection defenses and navigation restrictions reduce risk but cannot guarantee safety on arbitrary sites. Avoid destructive actions and never test with real customer data.

See [NOTES.md](NOTES.md) for implementation decisions, verified results, live-site findings, and current open items.
