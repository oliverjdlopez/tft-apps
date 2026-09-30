from __future__ import annotations

from db.session import database_label


def test_database_label_redacts_embedded_password() -> None:
    label = database_label(
        "postgresql://postgres:D%21ablo377377@example.us-east-1.rds.amazonaws.com:5432/postgres"
    )

    assert label == (
        "postgresql://postgres:<redacted>@example.us-east-1.rds.amazonaws.com:5432/postgres"
    )
    assert "D%21ablo377377" not in label


def test_database_label_redacts_password_query_params() -> None:
    label = database_label(
        "postgresql://postgres@example.us-east-1.rds.amazonaws.com/postgres"
        "?sslmode=require&password=secret"
    )

    assert label == (
        "postgresql://postgres@example.us-east-1.rds.amazonaws.com/postgres"
        "?sslmode=require&password=%3Credacted%3E"
    )
    assert "secret" not in label


def test_database_label_leaves_passwordless_urls_readable() -> None:
    assert database_label("postgresql:///chat_tft") == "postgresql:///chat_tft"
