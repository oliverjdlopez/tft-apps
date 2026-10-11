"""Verify catalogue selection stays independent of stored match patch labels."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.routes.ingest import IngestionOptions, _default_args
from core.config import AppConfig, IngestConfig, load_config
from db import insert as insert_module
from db.models import Base, RawMatch
from scripts.ingestion import ingest, utils


@pytest.mark.parametrize("setting", [None, "", "   ", "16.20"])
def test_catalogue_config_and_cli_override(tmp_path: Path, setting: str | None) -> None:
    """Load absent, blank, and pinned catalogues without altering stored labels."""
    path = tmp_path / "chat_tft.ini"
    value = "" if setting is None else f"cdragon_patch_override = {setting}\n"
    path.write_text(f"[ingest]\npatch_override = 18.4\n{value}", encoding="utf-8")

    config = load_config(path)
    expected = (setting.strip() or None) if setting is not None else None
    assert config.ingest.cdragon_patch_override == expected
    assert config.ingest.patch_override == "18.4"
    args = utils.parse_args(["--config", str(path)])
    assert args.cdragon_patch_override == expected
    assert args.patch_override == "18.4"

    pinned = utils.parse_args(["--config", str(path), "--cdragon-patch-override", "pbe"])
    assert pinned.cdragon_patch_override == "pbe"
    assert pinned.patch_override == "18.4"
    blank = utils.parse_args(["--config", str(path), "--cdragon-patch-override", ""])
    assert blank.cdragon_patch_override == ""


def test_api_catalogue_config_and_request_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the configured catalogue unless the API caller overrides it."""
    config = AppConfig(ingest=IngestConfig(patch_override="18.4", cdragon_patch_override="16.20"))
    monkeypatch.setattr("core.config.load_config", lambda: config)

    for option, expected in [(None, "16.20"), ("pbe", "pbe"), ("", "")]:
        args = _default_args(IngestionOptions(cdragon_patch_override=option))
        assert args.cdragon_patch_override == expected
        assert args.patch_override == "18.4"


@pytest.mark.parametrize("catalogue", [None, "", "   ", "16.20"])
@pytest.mark.parametrize("stored_patch", [None, "18.4"])
def test_writer_uses_catalogue_and_preserves_match_patch(
    monkeypatch: pytest.MonkeyPatch, catalogue: str | None, stored_patch: str | None
) -> None:
    """Persist two match versions with one catalogue fetch and independent labels."""
    requested: list[tuple[str, int | None]] = []
    resolver = object()

    async def fetch(*, patch: str, set_number: int | None) -> object:
        """Record catalogue requests without contacting the upstream."""
        requested.append((patch, set_number))
        return resolver

    monkeypatch.setattr(ingest.TFTNameResolver, "from_latest", fetch)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            args = argparse.Namespace(
                patch_override=stored_patch,
                cdragon_patch_override=catalogue,
                insert_to_db=True,
            )
            writer = ingest._DatabaseWriter(args, session)
            for index, version in enumerate(["Version 16.19.1", "Version 16.20.1"]):
                payload = {
                    "metadata": {"match_id": f"NA1_catalogue_{index}"},
                    "info": {"game_version": version, "tft_set_number": 17},
                }
                item = ingest._FetchedMatch("na1", "americas", payload["metadata"]["match_id"], payload)
                writer.persist([item])
            session.commit()

            matches = session.query(RawMatch).order_by(RawMatch.match_id).all()
            assert [match.patch for match in matches] == (
                [stored_patch, stored_patch] if stored_patch else ["16.19", "16.20"]
            )
            assert [match.game_version for match in matches] == ["Version 16.19.1", "Version 16.20.1"]
            assert requested == [((catalogue or "").strip() or "latest", 17)]
            assert not writer.stats["na1"].errors
    finally:
        engine.dispose()


@pytest.mark.parametrize("catalogue", [None, "16.20"])
def test_direct_insert_catalogue_default(
    monkeypatch: pytest.MonkeyPatch, catalogue: str | None
) -> None:
    """Default direct inserts to the configured catalogue instead of the label."""
    config = AppConfig(ingest=IngestConfig(cdragon_patch_override=catalogue))
    monkeypatch.setattr(insert_module, "load_config", lambda: config)
    requested = []
    resolver = object()

    def resolve(patch: str, set_number: int | None) -> object:
        """Capture the catalogue passed to the existing resolver cache."""
        requested.append((patch, set_number))
        return resolver

    monkeypatch.setattr(insert_module, "get_patch_resolver", resolve)
    assert insert_module._get_resolver("18.4", 17) is resolver
    assert requested == [(catalogue or "latest", 17)]
