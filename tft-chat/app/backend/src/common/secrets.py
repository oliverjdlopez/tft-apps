"""Helpers for rendering secret-bearing values safely."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SENSITIVE_QUERY_KEYS = frozenset({"password", "pass", "pwd"})


def redact_url_credentials(value: str) -> str:
    """Redact URL passwords and password-like query parameters."""

    try:
        parts = urlsplit(value)
    except ValueError:
        return value

    netloc = parts.netloc
    changed = False
    if "@" in netloc:
        userinfo, hostinfo = netloc.rsplit("@", 1)
        if ":" in userinfo:
            username, _password = userinfo.rsplit(":", 1)
            netloc = f"{username}:<redacted>@{hostinfo}"
            changed = True

    query = parts.query
    if query:
        query_items = parse_qsl(query, keep_blank_values=True)
        redacted_items = [
            (
                key,
                "<redacted>"
                if key.casefold() in _SENSITIVE_QUERY_KEYS
                or "password" in key.casefold()
                else item_value,
            )
            for key, item_value in query_items
        ]
        if redacted_items != query_items:
            query = urlencode(redacted_items)
            changed = True

    if not changed:
        return value
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


__all__ = ["redact_url_credentials"]
