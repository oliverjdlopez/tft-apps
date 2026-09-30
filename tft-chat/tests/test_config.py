from __future__ import annotations

from pathlib import Path

import pytest

from core.config import AppConfig, load_config, resolve_database_target


def test_load_config_returns_dataclass_with_ini_and_env_values(
    monkeypatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "chat_tft.ini"
    config_path.write_text(
        """
[models]
openai_model = gpt-test

[chat]
ui_port = 9999
patch = 16.10
set_number = 15

[rds-upgrade]
instance_id = upgrade-instance

[ingest]
queue = 1090
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("CHAT_TFT_S3_UPLOAD", "true")
    monkeypatch.setenv("CHAT_TFT_S3_BUCKET", "test-bucket")

    config = load_config(config_path)

    assert isinstance(config, AppConfig)
    assert config.models.openai_model == "gpt-test"
    assert config.chat.ui_port == 9999
    assert config.chat.patch == "16.10"
    assert config.chat.set_number == 15
    assert config.rds_upgrade.instance_id == "upgrade-instance"
    assert config.ingest.queue == "1090"
    assert config.secrets.openai_api_key == "test-openai-key"
    assert config.s3.upload is True
    assert config.s3.bucket == "test-bucket"


def test_load_config_rejects_unknown_ini_keys(tmp_path: Path) -> None:
    path = tmp_path / "chat_tft.ini"
    path.write_text("[chat]\nretired_setting = true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown INI key"):
        load_config(path)


def test_database_targets_are_isolated_and_redacted(monkeypatch) -> None:
    monkeypatch.setattr("core.config.load_dotenv", lambda *_args, **_kwargs: None)
    monkeypatch.setenv("RDS_HOST", "app.example")
    monkeypatch.setenv("RDS_ADMIN", "app-user")
    monkeypatch.setenv("RDS_DB", "chat_tft")
    monkeypatch.setenv("RDS_PASSWORD", "secret")
    monkeypatch.setenv("RDS_EVAL_HOST", "eval.example")
    monkeypatch.setenv("RDS_EVAL_ADMIN", "eval-user")
    monkeypatch.setenv("RDS_EVAL_DB", "chat_tft_eval")
    monkeypatch.delenv("RDS_EVAL_PASSWORD", raising=False)
    monkeypatch.setenv("RDS_TEST_HOST", "test.example")
    monkeypatch.setenv("RDS_TEST_ADMIN", "test-user")
    monkeypatch.setenv("RDS_TEST_DB", "chat_tft_test")

    app = resolve_database_target("app")
    evaluation = resolve_database_target("eval")
    test = resolve_database_target("test")

    assert app.auth_mode == "password"
    assert evaluation.auth_mode == "password"
    assert test.purpose == "test"
    assert "secret" not in app.url
    assert app.host != evaluation.host != test.host


def test_eval_target_defaults_to_app_rds_when_eval_env_is_missing(monkeypatch) -> None:
    monkeypatch.setattr("core.config.load_dotenv", lambda *_args, **_kwargs: None)
    monkeypatch.setenv("RDS_INSTANCE_ID", "app-instance")
    monkeypatch.setenv("RDS_HOST", "app.example")
    monkeypatch.setenv("RDS_PORT", "5434")
    monkeypatch.setenv("RDS_ADMIN", "app-user")
    monkeypatch.setenv("RDS_DB", "chat_tft")
    monkeypatch.setenv("RDS_PASSWORD", "secret")

    for name in (
        "INSTANCE_ID", "HOST", "PORT", "ADMIN", "DB", "PASSWORD",
        "SYNC_LOCAL_IP", "SECURITY_GROUP_ID", "SECURITY_GROUP_RULE_DESCRIPTION",
        "IP_CACHE_FILE", "IP_CHECK_URL",
    ):
        monkeypatch.delenv(f"RDS_EVAL_{name}", raising=False)

    app = resolve_database_target("app")
    evaluation = resolve_database_target("eval")

    assert evaluation.host == app.host
    assert evaluation.port == app.port
    assert evaluation.admin == app.admin
    assert evaluation.database == app.database
    assert evaluation.password == app.password
    assert evaluation.instance_id == app.instance_id
