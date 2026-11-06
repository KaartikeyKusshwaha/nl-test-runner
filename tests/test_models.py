import pytest
from pydantic import ValidationError

from nlqa.models import TestSpec, Verification


def test_test_spec_requires_at_least_one_verification() -> None:
    with pytest.raises(ValidationError):
        TestSpec(goal="Check a page", verifications=[])


def test_verification_ids_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="unique"):
        TestSpec(
            goal="Check a page",
            verifications=[
                Verification(id="v1", statement="Heading is shown"),
                Verification(id="v1", statement="Button is enabled"),
            ],
        )


def test_defaults_are_per_instance_and_implicit_is_available() -> None:
    first = TestSpec(
        goal="Search",
        verifications=[Verification(id="v1", statement="Results are shown", implicit=True)],
    )
    second = TestSpec(
        goal="Login", verifications=[Verification(id="v1", statement="Dashboard is shown")]
    )
    first.steps.append("click search")
    assert second.steps == []
    assert first.verifications[0].implicit is True
