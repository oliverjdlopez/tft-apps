from __future__ import annotations

from pathlib import Path
from typing import Any

import asyncio
import logging

import pytest

from scripts.ingestion import main as ingestion_cli
from scripts.ingestion import riot_fetch


def test_progress_logger_waits_for_interval(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    times = iter([0.0, 60.0, 181.0])
    monkeypatch.setattr(ingestion_cli.time, "monotonic", lambda: next(times))

    progress = ingestion_cli.ProgressLogger(label="test-ingest", interval_seconds=180)

    with caplog.at_level(logging.INFO, logger="tft-ingest"):
        progress.maybe("inserted=%d", 1)
        progress.maybe("inserted=%d", 2)

    assert len(caplog.records) == 1
    assert caplog.records[0].message == (
        "test-ingest still running after 3m01s: inserted=2"
    )


def test_explicit_config_supplies_ingest_defaults(tmp_path: Path) -> None:
    config = tmp_path / "chat_tft.ini"
    config.write_text(
        """
[ingest]
platform = kr
queue = RANKED_TFT
max_new_matches = 125
matches_per_player = 15
player_batch_size = 10
tiers = challenger,grandmaster
insert_to_db = false
analysis_every = 400
""".strip(),
        encoding="utf-8",
    )

    args = ingestion_cli.parse_args(["--config", str(config)])

    assert args.platform == "kr"
    assert args.max_new_matches == 125
    assert args.matches_per_player == 15
    assert args.player_batch_size == 10
    assert args.tiers == "challenger,grandmaster"
    assert args.insert_to_db is False
    assert args.analysis_every == 400


def test_cli_flags_override_config_values(tmp_path: Path) -> None:
    config = tmp_path / "chat_tft.ini"
    config.write_text(
        """
[ingest]
platform = euw1
max_new_matches = 125
matches_per_player = 15
""".strip(),
        encoding="utf-8",
    )

    args = ingestion_cli.parse_args(
        [
            "--config",
            str(config),
            "--platform",
            "na1",
            "--max-new-matches",
            "20",
        ]
    )

    assert args.platform == "na1"
    assert args.max_new_matches == 20
    assert args.matches_per_player == 15


def test_platforms_config_and_cli_parse(tmp_path: Path) -> None:
    config = tmp_path / "chat_tft.ini"
    config.write_text("[ingest]\nplatforms = na1, euw1, kr\n", encoding="utf-8")

    args = ingestion_cli.parse_args(["--config", str(config)])

    assert args.platforms == "na1, euw1, kr"
    assert ingestion_cli.ingest_platforms(args) == ["na1", "euw1", "kr"]

    override = ingestion_cli.parse_args(
        ["--config", str(config), "--platforms", "br1,na1,br1"]
    )

    assert ingestion_cli.ingest_platforms(override) == ["br1", "na1"]

    single = ingestion_cli.parse_args(
        ["--config", str(config), "--platform", "kr"]
    )
    assert ingestion_cli.ingest_platforms(single) == ["kr"]


def test_player_batch_size_cli_overrides_config(tmp_path: Path) -> None:
    config = tmp_path / "chat_tft.ini"
    config.write_text("[ingest]\nplayer_batch_size = 10\n", encoding="utf-8")

    args = ingestion_cli.parse_args(
        ["--config", str(config), "--player-batch-size", "3"]
    )

    assert args.player_batch_size == 3


def test_project_config_overrides_user_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_config = tmp_path / "user.ini"
    project_config = tmp_path / "project.ini"
    user_config.write_text("[ingest]\nmax_new_matches = 10\nplatform = kr\n", encoding="utf-8")
    project_config.write_text("[ingest]\nmax_new_matches = 25\n", encoding="utf-8")
    monkeypatch.setattr(
        ingestion_cli,
        "DEFAULT_CONFIG_PATHS",
        (user_config, project_config),
    )

    config = ingestion_cli.load_ingest_config()

    assert config["platform"] == "kr"
    assert config["max_new_matches"] == 25


def test_legacy_max_matches_config_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "chat_tft.ini"
    config.write_text("[ingest]\nmax_matches = 25\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="Unknown"):
        ingestion_cli.parse_args(["--config", str(config)])


def test_unknown_config_key_fails_fast(tmp_path: Path) -> None:
    config = tmp_path / "chat_tft.ini"
    config.write_text("[ingest]\nmax_games = 10\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="Unknown"):
        ingestion_cli.parse_args(["--config", str(config)])


def test_no_insert_to_db_flag_parses() -> None:
    args = ingestion_cli.parse_args(["--no-insert-to-db"])

    assert args.insert_to_db is False


def test_endless_defaults_off_and_flag_enables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingestion_cli, "DEFAULT_CONFIG_PATHS", ())

    default = ingestion_cli.parse_args([])
    assert default.endless is False
    assert default.cycle_delay == 60

    enabled = ingestion_cli.parse_args(["--endless", "--cycle-delay", "5"])
    assert enabled.endless is True
    assert enabled.cycle_delay == 5


def test_endless_config_booleans_parse(tmp_path: Path) -> None:
    config = tmp_path / "chat_tft.ini"
    config.write_text("[ingest]\nendless = true\ncycle_delay = 30\n", encoding="utf-8")

    args = ingestion_cli.parse_args(["--config", str(config)])

    assert args.endless is True
    assert args.cycle_delay == 30
    # CLI flag still wins over config when explicitly absent the config holds.
    assert ingestion_cli.parse_args(["--config", str(config)]).endless is True


def test_endless_config_rejects_garbage_boolean(tmp_path: Path) -> None:
    config = tmp_path / "chat_tft.ini"
    config.write_text("[ingest]\nendless = maybe\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="endless"):
        ingestion_cli.parse_args(["--config", str(config)])


def test_endless_cycle_args_walk_all_players_with_five_games(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion_cli, "DEFAULT_CONFIG_PATHS", ())

    args = ingestion_cli.parse_args(["--endless"])

    cycle = ingestion_cli.endless_cycle_args(args)

    # No per-cycle cap, every player's five most recent games, batched for
    # incremental progress.
    assert cycle.max_new_matches is None
    assert cycle.matches_per_player == ingestion_cli.ENDLESS_MATCHES_PER_PLAYER == 5
    assert cycle.player_batch_size == ingestion_cli.ENDLESS_PLAYER_BATCH_SIZE


def test_endless_cycle_args_respect_explicit_player_batch_size() -> None:
    args = ingestion_cli.parse_args(["--endless", "--player-batch-size", "7"])

    cycle = ingestion_cli.endless_cycle_args(args)

    assert cycle.player_batch_size == 7
    assert cycle.max_new_matches is None


def test_endless_analytics_catch_up_runs_initially_and_periodically() -> None:
    assert ingestion_cli.endless_analytics_catch_up_due(1) is True
    assert ingestion_cli.endless_analytics_catch_up_due(2) is False
    assert ingestion_cli.endless_analytics_catch_up_due(9) is False
    assert ingestion_cli.endless_analytics_catch_up_due(10) is True
    assert ingestion_cli.endless_analytics_catch_up_due(20) is True


def _match_payload(
    match_id: str, *, game_version: str = "Version 14.10.1"
) -> dict[str, Any]:
    return {
        "metadata": {"match_id": match_id, "participants": ["p1"]},
        "info": {
            "game_datetime": 1710000000000,
            "game_length": 1800.0,
            "game_version": game_version,
            "queue_id": 1100,
            "tft_set_number": 11,
            "participants": [
                {
                    "puuid": "p1",
                    "placement": 1,
                    "level": 9,
                    "last_round": 35,
                    "players_eliminated": 3,
                    "total_damage_to_players": 140,
                    "gold_left": 2,
                    "units": [],
                    "traits": [],
                }
            ],
        },
    }


class _FakeRiot:
    def __init__(self) -> None:
        self.match_calls: list[str] = []

    async def league_top(self, tier: str, platform: str, queue: str) -> dict[str, Any]:
        return {"entries": [{"puuid": "p1"}]}

    async def get_tft_match_v1_match_ids_by_puuid(
        self, *, region: str, puuid: str, queries: dict[str, Any]
    ) -> list[str]:
        return ["NA1_existing", "NA1_new"]

    async def get_tft_match_v1_match(self, *, region: str, id: str) -> dict[str, Any]:
        self.match_calls.append(id)
        return _match_payload(id)


class _FakeResolver:
    def display_name(self, value: str) -> str | None:
        return value

    def trait_name(self, value: str) -> str | None:
        return value


async def _fake_resolver_from_latest(*args: Any, **kwargs: Any) -> _FakeResolver:
    return _FakeResolver()


class _BatchingFakeRiot:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def league_top(self, tier: str, platform: str, queue: str) -> dict[str, Any]:
        return {
            "entries": [
                {"puuid": "p1"},
                {"puuid": "p2"},
                {"puuid": "p3"},
                {"puuid": "p4"},
            ]
        }

    async def get_tft_match_v1_match_ids_by_puuid(
        self, *, region: str, puuid: str, queries: dict[str, Any]
    ) -> list[str]:
        self.events.append(f"ids:{puuid}")
        return [f"NA1_{puuid}_1"]

    async def get_tft_match_v1_match(self, *, region: str, id: str) -> dict[str, Any]:
        self.events.append(f"match:{id}")
        return _match_payload(id)


def _run_args(**overrides: Any) -> Any:
    import argparse

    merged = dict(ingestion_cli.INGEST_DEFAULTS)
    merged.update(overrides)
    return argparse.Namespace(**merged)


def test_endless_writer_skips_catch_up_but_finalizes_changed_analytics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.ingestion import ingest as ingestion_pipeline

    class FakeSession:
        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

    writer = ingestion_pipeline._DatabaseWriter(
        _run_args(endless=True, force_analytics_catch_up=False),
        FakeSession(),
    )
    writer.stats["na1"].analytics_processed_matches = 1
    calls = {"catch_up": 0, "finalize": 0}

    def unexpected_catch_up(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        calls["catch_up"] += 1
        return {"processed_matches": 0, "boards": 0, "remaining_matches": 0}

    def fake_finalize(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        calls["finalize"] += 1
        return {"processed_matches": 1, "boards": 8}

    monkeypatch.setattr(ingestion_pipeline, "catch_up_query_tables", unexpected_catch_up)
    monkeypatch.setattr(ingestion_pipeline, "finalize_query_tables", fake_finalize)

    writer.finalize()

    assert calls == {"catch_up": 0, "finalize": 1}
    assert writer.catch_up_result["performed"] is False


def test_endless_writer_runs_catch_up_after_analytics_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.ingestion import ingest as ingestion_pipeline

    class FakeSession:
        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

    writer = ingestion_pipeline._DatabaseWriter(
        _run_args(endless=True, force_analytics_catch_up=False),
        FakeSession(),
    )
    writer.stats["na1"].analytics_errors.append(
        {"stage": "analytics", "error": "synthetic"}
    )
    calls = {"catch_up": 0, "finalize": 0}

    def fake_catch_up(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        calls["catch_up"] += 1
        assert _kwargs["finalize"] is False
        return {"processed_matches": 2, "boards": 16, "remaining_matches": 0}

    def fake_finalize(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        calls["finalize"] += 1
        return {"processed_matches": 2, "boards": 16}

    monkeypatch.setattr(ingestion_pipeline, "catch_up_query_tables", fake_catch_up)
    monkeypatch.setattr(ingestion_pipeline, "finalize_query_tables", fake_finalize)

    writer.finalize()

    assert calls == {"catch_up": 1, "finalize": 1}
    assert writer.catch_up_result["performed"] is True


def test_run_ingest_platforms_combines_pipeline_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.ingestion import ingest as ingestion_pipeline

    seen_platforms: list[str] = []

    async def _fake_pipeline(
        args: Any,
        platforms: list[str],
        conn: Any,
        *,
        riot_client_factory: Any,
    ) -> list[dict[str, Any]]:
        seen_platforms.extend(platforms)
        return [
            {
                "platform": platform,
                "region": ingestion_cli.PLATFORM_TO_REGION[platform],
                "queue": args.queue,
                "max_new_matches": args.max_new_matches,
                "player_batch_size": args.player_batch_size,
                "fetch_concurrency": args.fetch_concurrency,
                "matches_considered": 1,
                "inserted": 1,
                "duplicates": 0,
                "skipped_existing": 0,
                "skipped_filtered": 0,
                "insert_to_db": args.insert_to_db,
                "filters": {},
                "riot_match_fetches": 1,
                "errors": [],
                "error_count": 0,
                "ladders": [],
            }
            for platform in platforms
        ]

    monkeypatch.setenv("RIOT_API_KEY", "test-key")
    monkeypatch.setattr(ingestion_pipeline, "_ingest_platforms", _fake_pipeline)

    result = asyncio.run(
        ingestion_cli.run_ingest_platforms(
            _run_args(platforms="na1,euw1,br1", max_new_matches=1)
        )
    )

    assert result["platforms"] == ["na1", "euw1", "br1"]
    assert result["inserted"] == 3
    assert seen_platforms == ["na1", "euw1", "br1"]


def test_persist_failure_rolls_back_and_continues(
    monkeypatch: pytest.MonkeyPatch,
    clean_db,
) -> None:
    from scripts.ingestion import ingest as ingest_module

    monkeypatch.setenv("RIOT_API_KEY", "test-key")
    fake_riot = _FakeRiot()
    monkeypatch.setattr(
        ingestion_cli, "ChatTftRiotClient", lambda: fake_riot
    )

    calls: list[str] = []

    def _insert_or_fail(
        session: Any,
        payload: dict[str, Any],
        *,
        region: str,
        platform: str | None = None,
        resolver: Any = None,
        commit: bool = True,
    ) -> bool:
        match_id = payload["metadata"]["match_id"]
        calls.append(match_id)
        if match_id == "NA1_existing":
            raise RuntimeError("synthetic persist failure")
        return True

    monkeypatch.setattr(ingest_module, "insert_match_payload", _insert_or_fail)
    monkeypatch.setattr(
        ingest_module.TFTNameResolver, "from_latest", _fake_resolver_from_latest
    )

    conn = ingestion_cli.open_db()
    rollbacks = 0
    original_rollback = conn.rollback

    def _rollback() -> None:
        nonlocal rollbacks
        rollbacks += 1
        original_rollback()

    monkeypatch.setattr(conn, "rollback", _rollback)
    try:
        result = asyncio.run(
            ingestion_cli.ingest_top_matches(
                _run_args(max_new_matches=2, matches_per_player=2),
                conn,
            )
        )
    finally:
        conn.close()

    assert calls == ["NA1_existing", "NA1_new"]
    # The nested transaction rolls back the failed match without resetting the
    # outer session, so the next payload can still commit.
    assert rollbacks == 0
    assert result["inserted"] == 1
    assert result["error_count"] == 1
    assert result["errors"][0]["match_id"] == "NA1_existing"


def test_collect_ladder_puuids_takes_all_players_when_uncapped() -> None:
    fake_riot = _BatchingFakeRiot()

    puuids, _ = asyncio.run(
        riot_fetch.collect_ladder_puuids(
            fake_riot,
            platform="na1",
            queue="RANKED_TFT",
            tiers=["challenger"],
            max_new_matches=None,
            matches_per_player=5,
        )
    )

    # All four ladder entries are kept; nothing is dropped to hit a budget.
    assert sorted(puuids) == ["p1", "p2", "p3", "p4"]


def test_uncapped_run_ingests_every_player(
    monkeypatch: pytest.MonkeyPatch,
    clean_db,
) -> None:
    monkeypatch.setenv("RIOT_API_KEY", "test-key")
    fake_riot = _BatchingFakeRiot()
    monkeypatch.setattr(
        ingestion_cli, "ChatTftRiotClient", lambda: fake_riot
    )
    from scripts.ingestion import ingest as ingest_module

    monkeypatch.setattr(
        ingest_module.TFTNameResolver, "from_latest", _fake_resolver_from_latest
    )

    conn = ingestion_cli.open_db()
    try:
        result = asyncio.run(
            ingestion_cli.ingest_top_matches(
                _run_args(max_new_matches=None, matches_per_player=5),
                conn,
            )
        )
    finally:
        conn.close()

    # Every one of the four players contributes their match with no cap applied.
    assert result["inserted"] == 4
    assert sorted(call for call in fake_riot.events if call.startswith("match:")) == [
        "match:NA1_p1_1",
        "match:NA1_p2_1",
        "match:NA1_p3_1",
        "match:NA1_p4_1",
    ]


def test_player_batch_size_processes_players_in_batches(
    monkeypatch: pytest.MonkeyPatch,
    clean_db,
) -> None:
    monkeypatch.setenv("RIOT_API_KEY", "test-key")
    fake_riot = _BatchingFakeRiot()
    monkeypatch.setattr(
        ingestion_cli, "ChatTftRiotClient", lambda: fake_riot
    )
    from scripts.ingestion import ingest as ingest_module

    monkeypatch.setattr(
        ingest_module.TFTNameResolver, "from_latest", _fake_resolver_from_latest
    )

    conn = ingestion_cli.open_db()
    try:
        result = asyncio.run(
            ingestion_cli.ingest_top_matches(
                _run_args(
                    max_new_matches=4,
                    matches_per_player=1,
                    player_batch_size=2,
                ),
                conn,
            )
        )
    finally:
        conn.close()

    # Calls inside a batch are concurrent, but the next batch cannot start
    # until both ID and match fetches from the current batch complete.
    first_ids = set(fake_riot.events[:2])
    second_ids = set(fake_riot.events[4:6])
    assert all(event.startswith("ids:") for event in first_ids | second_ids)
    assert first_ids | second_ids == {"ids:p1", "ids:p2", "ids:p3", "ids:p4"}
    assert set(fake_riot.events[2:4]) == {
        f"match:NA1_{event.removeprefix('ids:')}_1" for event in first_ids
    }
    assert set(fake_riot.events[6:8]) == {
        f"match:NA1_{event.removeprefix('ids:')}_1" for event in second_ids
    }
    assert result["player_batch_size"] == 2
    assert result["matches_considered"] == 4
    assert result["inserted"] == 4
