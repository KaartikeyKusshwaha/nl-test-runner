from nlqa.actions import BrowserController
from nlqa.agent import TestAgent
from nlqa.llm.base import LLMError, LLMRateLimitError
from nlqa.llm.fake import FakeLLM
from nlqa.models import Outcome, TestSpec, ToolCall, Verification
from nlqa.secrets import SecretStore


def spec(*statements: str, data: dict[str, str] | None = None) -> TestSpec:
    return TestSpec(
        goal="Log in as a customer",
        steps=["Enter credentials", "Submit the form"],
        verifications=[
            Verification(id=f"v{index}", statement=statement)
            for index, statement in enumerate(statements, start=1)
        ],
        data=data or {},
    )


def login_script(*, password: str = "{{CUSTOMER_PASSWORD}}") -> list[ToolCall]:
    return [
        ToolCall(name="type", args={"ref": "e1", "text": "customer"}),
        ToolCall(name="type", args={"ref": "e2", "text": password}),
        ToolCall(name="click", args={"ref": "e3"}),
        ToolCall(
            name="assert_text_visible",
            args={"text": "Customer dashboard", "verification_id": "v1"},
        ),
        ToolCall(
            name="assert_text_visible",
            args={"text": "Signed in successfully", "verification_id": "v2"},
        ),
        ToolCall(name="finish", args={"verdict": "pass", "reason": "All visible"}),
    ]


def test_successful_login_is_passed_with_assertion_evidence(page, site_server: str) -> None:
    page.goto(f"{site_server}/login_basic.html")
    fake = FakeLLM(
        tool_calls=login_script(),
        json_responses=[
            {
                "results": [
                    {"id": "v1", "supports": True, "why": "The dashboard heading is visible."},
                    {"id": "v2", "supports": True, "why": "The success message is visible."},
                ]
            }
        ],
    )
    controller = BrowserController(page)
    secret_store = SecretStore({"CUSTOMER_PASSWORD": "correct-horse"})
    agent = TestAgent(
        fake,
        controller,
        secret_store=secret_store,
        judge_enabled=True,
        max_steps=12,
    )
    result = agent.run(
        spec(
            "The customer dashboard is shown",
            "Login success is confirmed",
            data={"password": "{{CUSTOMER_PASSWORD}}"},
        )
    )
    assert result.outcome is Outcome.PASS
    assert result.verification_status == {"v1": "proven", "v2": "proven"}
    assert len(result.assertions) == 2
    assert "CUSTOMER_PASSWORD" in str(result.steps)
    assert "correct-horse" not in str(result.model_dump())
    assert "correct-horse" not in str(fake.prompts)


def test_expected_dashboard_missing_is_evidence_backed_fail(page, site_server: str) -> None:
    page.goto(f"{site_server}/login_basic.html")
    fake = FakeLLM(
        tool_calls=[
            ToolCall(name="type", args={"ref": "e1", "text": "customer"}),
            ToolCall(name="type", args={"ref": "e2", "text": "wrong-password"}),
            ToolCall(name="click", args={"ref": "e3"}),
            ToolCall(
                name="assert_text_visible",
                args={"text": "Customer dashboard", "verification_id": "v1"},
            ),
            ToolCall(name="finish", args={"verdict": "fail", "reason": "Claimed failure"}),
        ]
    )
    result = TestAgent(fake, BrowserController(page), judge_enabled=False).run(
        spec("The customer dashboard is shown")
    )
    assert result.outcome is Outcome.FAIL
    assert "not visible" in result.reason
    assert fake.usage.calls == 4  # It stops as soon as the failed assertion proves FAIL.


def test_waiting_for_the_expected_text_records_a_failing_assertion(page) -> None:
    page.set_content("<h1>Public homepage</h1>")
    fake = FakeLLM(
        tool_calls=[
            ToolCall(
                name="wait_for_text",
                args={"text": "Welcome back Zebra Unicorn", "timeout_s": 5},
            )
        ]
    )
    test_spec = TestSpec(
        goal="The homepage shows the claimed greeting",
        steps=["Check the public homepage"],
        verifications=[
            Verification(
                id="v1",
                statement='The homepage shows the exact greeting "Welcome back Zebra Unicorn"',
                implicit=False,
            )
        ],
    )

    result = TestAgent(fake, BrowserController(page), judge_enabled=False).run(test_spec)

    assert result.outcome is Outcome.FAIL
    assert result.steps[-1].tool == "assert_text_visible"
    assert result.assertions[0].passed is False


def test_action_is_discarded_when_page_changes_during_model_turn(page) -> None:
    page.set_content(
        """<button id="stays">Stays</button><p id="result"></p>
        <script>document.querySelector('#stays').addEventListener('click', () => {
          document.querySelector('#result').textContent = 'Stays selected';
        });</script>"""
    )
    calls = 0

    def answer(_system: str, user: str) -> ToolCall:
        nonlocal calls
        calls += 1
        if calls == 1:
            page.evaluate(
                """() => {
                  const overlay = document.createElement('div');
                  overlay.style.cssText = 'position:fixed;inset:0;z-index:9999';
                  const button = document.createElement('button');
                  button.textContent = 'I Understand and Continue';
                  button.onclick = () => overlay.remove();
                  overlay.append(button);
                  document.body.append(overlay);
                }"""
            )
            return ToolCall(name="click", args={"ref": "e1"})
        if calls == 2:
            assert "top-overlay" in user
            return ToolCall(name="click", args={"ref": "e1"})
        if calls == 3:
            return ToolCall(name="click", args={"ref": "e1"})
        if calls == 4:
            return ToolCall(
                name="assert_text_visible",
                args={"text": "Stays selected", "verification_id": "v1"},
            )
        return ToolCall(name="finish", args={"verdict": "pass", "reason": "Stays selected"})

    test_spec = TestSpec(
        goal="Choose Stays",
        steps=["Click the Stays tab"],
        verifications=[Verification(id="v1", statement="Stays is selected", implicit=False)],
    )
    result = TestAgent(
        FakeLLM(tool_calls=answer), BrowserController(page), judge_enabled=False
    ).run(test_spec)

    assert result.outcome is Outcome.PASS
    assert result.steps[0].tool == "stale_observation"
    assert result.steps[1].tool == "click"
    assert result.steps[2].tool == "click"


def test_premature_pass_is_rejected_then_model_proves_verification(page, site_server: str) -> None:
    page.goto(f"{site_server}/login_basic.html")
    fake = FakeLLM(
        tool_calls=[
            ToolCall(name="finish", args={"verdict": "pass", "reason": "Looks fine"}),
            ToolCall(
                name="assert_text_visible",
                args={"text": "Sign in", "verification_id": "v1"},
            ),
            ToolCall(name="finish", args={"verdict": "pass", "reason": "Verified"}),
        ],
        json_responses=[
            {"results": [{"id": "v1", "supports": True, "why": "The heading is visible."}]}
        ],
    )
    result = TestAgent(fake, BrowserController(page), judge_enabled=True).run(
        spec("The sign-in heading is shown")
    )
    assert result.outcome is Outcome.PASS
    assert result.steps[0].ok is False
    assert result.verification_status["v1"] == "proven"


def test_invalid_tool_gets_one_repair_call(page, site_server: str) -> None:
    page.goto(f"{site_server}/login_basic.html")
    responses = iter(
        [
            ToolCall(name="click", args={"ref": "stale-ref"}),
            ToolCall(
                name="assert_text_visible",
                args={"text": "Sign in", "verification_id": "v1"},
            ),
            ToolCall(name="finish", args={"verdict": "pass", "reason": "Checked"}),
        ]
    )
    fake = FakeLLM(
        tool_calls=lambda _system, _user: next(responses, None),
        json_responses=[{"results": [{"id": "v1", "supports": True, "why": "Visible heading."}]}],
    )
    result = TestAgent(fake, BrowserController(page), judge_enabled=True).run(
        spec("The sign-in heading is shown")
    )
    assert result.outcome is Outcome.PASS
    assert fake.usage.calls == 4
    assert "stale or missing" in fake.prompts[1][1]


def test_empty_model_response_is_repaired_once(page, site_server: str) -> None:
    page.goto(f"{site_server}/login_basic.html")
    responses = iter(
        [
            None,
            ToolCall(
                name="assert_text_visible",
                args={"text": "Sign in", "verification_id": "v1"},
            ),
            ToolCall(name="finish", args={"verdict": "pass", "reason": "Checked"}),
        ]
    )
    fake = FakeLLM(
        tool_calls=lambda _system, _user: next(responses, None),
        json_responses=[{"results": [{"id": "v1", "supports": True, "why": "Visible."}]}],
    )
    result = TestAgent(fake, BrowserController(page), judge_enabled=True).run(
        spec("The sign-in heading is shown")
    )
    assert result.outcome is Outcome.PASS
    assert fake.usage.calls == 4
    assert "previous tool response was invalid" in fake.prompts[1][1]


def test_step_budget_exhaustion_is_error(page, site_server: str) -> None:
    page.goto(f"{site_server}/login_basic.html")
    fake = FakeLLM(tool_calls=[ToolCall(name="wait", args={"seconds": 0})])
    result = TestAgent(fake, BrowserController(page), max_steps=1, judge_enabled=False).run(
        spec("The dashboard is shown")
    )
    assert result.outcome is Outcome.ERROR
    assert "step budget exhausted" in result.reason


def test_page_cannot_request_unlisted_secret_placeholder(page) -> None:
    page.set_content('<input aria-label="Name">')
    secret_store = SecretStore({"OPENAI_API_KEY": "api-key-value-that-must-not-leak"})
    fake = FakeLLM(
        tool_calls=[ToolCall(name="type", args={"ref": "e1", "text": "{{OPENAI_API_KEY}}"})]
    )
    controller = BrowserController(page, secret_store=secret_store)
    result = TestAgent(fake, controller, secret_store=secret_store, judge_enabled=False).run(
        spec("Enter the customer's name")
    )
    assert result.outcome is Outcome.ERROR
    assert "not present in the test case" in result.reason
    assert "api-key-value-that-must-not-leak" not in str(result.model_dump())
    assert "api-key-value-that-must-not-leak" not in str(fake.prompts)


def test_time_budget_exhaustion_is_error_before_model_call(page) -> None:
    fake = FakeLLM(tool_calls=[])
    result = TestAgent(fake, BrowserController(page), max_seconds=0, judge_enabled=False).run(
        spec("The dashboard is shown")
    )
    assert result.outcome is Outcome.ERROR
    assert "time budget exhausted" in result.reason
    assert fake.usage.calls == 0


def test_consecutive_provider_errors_stop_as_error(page) -> None:
    def fail_request(_system: str, _user: str):
        raise LLMError("provider unavailable")

    fake = FakeLLM(tool_calls=fail_request)
    result = TestAgent(
        fake,
        BrowserController(page),
        max_consecutive_errors=2,
        judge_enabled=False,
    ).run(spec("The dashboard is shown"))
    assert result.outcome is Outcome.ERROR
    assert "consecutive invalid model responses" in result.reason


def test_provider_rate_limit_stops_run_without_repeating_model_call(page) -> None:
    def rate_limited(_system: str, _user: str):
        raise LLMRateLimitError(481)

    fake = FakeLLM(tool_calls=rate_limited)
    result = TestAgent(fake, BrowserController(page), judge_enabled=False).run(
        spec("The dashboard is shown")
    )

    assert result.outcome is Outcome.ERROR
    assert "retry in 481 seconds" in result.reason
    assert len(result.steps) == 1
    assert result.steps[0].tool == "model_rate_limited"
    assert fake.usage.calls == 1


def test_repeating_same_action_on_unchanged_page_is_stopped(page) -> None:
    page.set_content("<button>Continue</button>")
    fake = FakeLLM(tool_calls=[ToolCall(name="click", args={"ref": "e1"})] * 4)
    result = TestAgent(fake, BrowserController(page), max_steps=10, judge_enabled=False).run(
        spec("The next page is shown")
    )
    assert result.outcome is Outcome.ERROR
    assert "stuck repeating" in result.reason


def test_same_engine_passes_a_differently_structured_shop_site(page, site_server: str) -> None:
    page.goto(f"{site_server}/shop_basic.html")
    controller = BrowserController(page)
    observation = controller.snapshot()
    add_line = next(line for line in observation.lines if "Add item" in line)
    add_ref = add_line.split("]", 1)[0][1:]
    fake = FakeLLM(
        tool_calls=[
            ToolCall(name="click", args={"ref": add_ref}),
            ToolCall(
                name="assert_text_visible",
                args={"text": "Cart: 1", "verification_id": "v1"},
            ),
            ToolCall(name="finish", args={"verdict": "pass", "reason": "Cart verified"}),
        ],
        json_responses=[{"results": [{"id": "v1", "supports": True, "why": "Cart count is one."}]}],
    )
    result = TestAgent(fake, controller, judge_enabled=True).run(
        TestSpec(
            goal="Add the first item to the cart",
            steps=["Add the notebook"],
            verifications=[Verification(id="v1", statement="The cart shows one item")],
        )
    )
    assert result.outcome is Outcome.PASS
    assert result.verification_status["v1"] == "proven"
