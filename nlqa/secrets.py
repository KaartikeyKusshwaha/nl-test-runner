"""Placeholder substitution and secret masking at the browser-action boundary."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

PLACEHOLDER = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")


@dataclass(slots=True)
class SecretStore:
    """Resolve `{{NAME}}` only for execution and mask it from logs and reports."""

    values: dict[str, str]
    sensitive_values: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.sensitive_values.update(
            value
            for key, value in self.values.items()
            if key.upper().endswith(("PASSWORD", "TOKEN", "KEY", "SECRET")) and value
        )

    @classmethod
    def from_environment(
        cls, env_file: str | Path = ".env", environ: dict[str, str] | None = None
    ) -> SecretStore:
        values = {key: value for key, value in dotenv_values(env_file).items() if value is not None}
        values.update(environ if environ is not None else os.environ)
        normalized = {str(key): str(value) for key, value in values.items()}
        sensitive = {
            value
            for key, value in normalized.items()
            if key.upper().endswith(("PASSWORD", "TOKEN", "KEY", "SECRET")) and value
        }
        return cls(normalized, sensitive)

    def substitute(self, value: str, *, allowed_names: set[str] | None = None) -> str:
        """Replace placeholders with configured values or fail with the missing name."""

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if allowed_names is not None and name not in allowed_names:
                raise ValueError(f"placeholder {name} is not present in the test case")
            if name not in self.values:
                raise ValueError(f"env var {name} is not set")
            self.sensitive_values.add(self.values[name])
            return self.values[name]

        return PLACEHOLDER.sub(replace, value)

    def substitute_args(
        self, args: dict[str, Any], *, allowed_names: set[str] | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return execution args and separately masked args for traces/reports."""
        actual: dict[str, Any] = {}
        safe: dict[str, Any] = {}
        for key, value in args.items():
            if isinstance(value, str):
                actual[key] = self.substitute(value, allowed_names=allowed_names)
                safe[key] = self.mask(value)
            else:
                actual[key] = value
                safe[key] = value
        return actual, safe

    def mask(self, text: str) -> str:
        result = text
        secrets = sorted((value for value in self.sensitive_values if value), key=len, reverse=True)
        for secret in secrets:
            result = result.replace(secret, "****")
        return result

    def mask_object(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.mask(value)
        if isinstance(value, list):
            return [self.mask_object(item) for item in value]
        if isinstance(value, dict):
            return {key: self.mask_object(item) for key, item in value.items()}
        return value
