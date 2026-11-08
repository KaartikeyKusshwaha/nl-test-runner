"""Public HTTP URL checks for the hosted browser runner."""

from __future__ import annotations

import ipaddress
import socket
import threading
import time
from urllib.parse import urlsplit

_HOST_CACHE: dict[str, tuple[float, bool]] = {}
_HOST_CACHE_LOCK = threading.Lock()
_HOST_CACHE_SECONDS = 60


def _host_resolves_only_publicly(hostname: str) -> bool:
    """Reject hostnames that resolve to any private, local, or reserved address."""
    now = time.monotonic()
    with _HOST_CACHE_LOCK:
        cached = _HOST_CACHE.get(hostname)
        if cached and now < cached[0]:
            return cached[1]

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
            result = False
        else:
            try:
                answers = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
            except OSError:
                result = False
            else:
                addresses = {answer[4][0] for answer in answers}
                result = bool(addresses) and all(
                    ipaddress.ip_address(item).is_global for item in addresses
                )
    else:
        result = address.is_global

    with _HOST_CACHE_LOCK:
        _HOST_CACHE[hostname] = (time.monotonic() + _HOST_CACHE_SECONDS, result)
        if len(_HOST_CACHE) > 512:
            for old_host, (expires_at, _) in list(_HOST_CACHE.items()):
                if expires_at <= time.monotonic():
                    del _HOST_CACHE[old_host]
    return result


def validate_public_http_url(value: str) -> str:
    """Return a public HTTP(S) URL, or raise ValueError with a safe hint."""
    value = value.strip()
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Enter a valid public HTTP or HTTPS URL.") from exc
    if parsed.scheme.casefold() not in {"http", "https"} or not hostname:
        raise ValueError("Use a full http:// or https:// URL.")
    if parsed.username or parsed.password:
        raise ValueError("Do not put credentials in the URL.")
    if not _host_resolves_only_publicly(hostname.rstrip(".").casefold()):
        raise ValueError("The hosted runner accepts public website URLs only.")
    return value
