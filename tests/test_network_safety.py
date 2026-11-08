from __future__ import annotations

import socket

import pytest

from nlqa.network_safety import _host_resolves_only_publicly, validate_public_http_url


def test_public_http_url_accepts_public_ip() -> None:
    assert validate_public_http_url("https://8.8.8.8/status") == "https://8.8.8.8/status"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://192.168.1.2/",
        "http://localhost/",
        "file:///etc/passwd",
        "https://user:password@example.org/",
    ],
)
def test_private_or_unsupported_target_is_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        validate_public_http_url(url)


def test_hostname_is_rejected_if_any_dns_answer_is_private(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 0)),
    ]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: answers)
    assert not _host_resolves_only_publicly("mixed-addresses.test")


def test_hostname_is_accepted_when_all_dns_answers_are_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: answers)
    assert validate_public_http_url("https://public-destination.test/path") == (
        "https://public-destination.test/path"
    )
