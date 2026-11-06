from tempfile import TemporaryDirectory
from pathlib import Path

import pytest

from nlqa.secrets import SecretStore


def test_placeholder_values_are_substituted_only_at_execution_boundary() -> None:
    store = SecretStore({"CUSTOMER_PASSWORD": "S3cr3t!", "CUSTOMER_EMAIL": "qa@example.test"})
    actual, safe = store.substitute_args({"text": "{{CUSTOMER_PASSWORD}}", "email": "{{CUSTOMER_EMAIL}}"})
    assert actual == {"text": "S3cr3t!", "email": "qa@example.test"}
    assert safe == {"text": "{{CUSTOMER_PASSWORD}}", "email": "{{CUSTOMER_EMAIL}}"}
    assert store.mask("typed S3cr3t! and qa@example.test") == "typed **** and ****"


def test_missing_placeholder_has_clear_error() -> None:
    with pytest.raises(ValueError, match="env var CUSTOMER_PASSWORD is not set"):
        SecretStore({}).substitute("{{CUSTOMER_PASSWORD}}")


def test_dotenv_values_are_loaded_without_printing_them() -> None:
    with TemporaryDirectory(dir=".", prefix="secret-test-") as directory:
        env_file = Path(directory) / ".env"
        env_file.write_text("CUSTOMER_PASSWORD=private-value\n", encoding="utf-8")
        store = SecretStore.from_environment(env_file, environ={})
        assert store.substitute("{{CUSTOMER_PASSWORD}}") == "private-value"
        assert store.mask("private-value") == "****"


def test_nested_report_data_is_masked() -> None:
    store = SecretStore({"OPENAI_API_KEY": "key-value"})
    assert store.mask_object({"steps": [{"result": "used key-value"}]}) == {"steps": [{"result": "used ****"}]}
