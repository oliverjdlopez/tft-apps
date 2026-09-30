"""Small SQL text helpers that do not perform or authorize queries."""

from __future__ import annotations


def quote_identifier(identifier: str) -> str:
    """Quote one SQL identifier by escaping embedded double quotes."""

    return '"' + identifier.replace('"', '""') + '"'


__all__ = ["quote_identifier"]
