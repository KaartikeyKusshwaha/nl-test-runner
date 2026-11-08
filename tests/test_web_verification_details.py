from nlqa.web_summary import verification_details


def test_verification_details_uses_latest_assertion_evidence() -> None:
    report = {
        "verification_status": {"heading": "failed", "button": "proven"},
        "spec": {
            "verifications": [
                {"id": "heading", "statement": 'The heading says "Welcome"'},
                {"id": "button", "statement": "The Continue button is visible"},
            ]
        },
        "assertions": [
            {"verification_id": "heading", "detail": "initial observation"},
            {"verification_id": "heading", "detail": 'found heading "Sign in"'},
            {"verification_id": "button", "detail": "Continue button is visible"},
        ],
    }

    assert verification_details(report) == [
        {
            "statement": 'The heading says "Welcome"',
            "status": "failed",
            "evidence": 'found heading "Sign in"',
        },
        {
            "statement": "The Continue button is visible",
            "status": "proven",
            "evidence": "Continue button is visible",
        },
    ]
