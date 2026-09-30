"""Tests for the one-off persisted unit-cost repair command."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.build_query_tables import AnalysisScopeIdentity
from db.models import (
    AnalysisFactBuild,
    AnalysisScope,
    Base,
    BoardUnit,
    PlayerBoard,
    RawMatch,
)
from scripts import repair_unit_costs as repair


class StaticResolver:
    """Provide deterministic exact-patch costs for repair tests."""

    def unit_cost(self, unit_name: str) -> int | None:
        """Return the known test cost for a named unit."""
        return {"Blitzcrank": 5, "Maokai": 3}.get(unit_name)


def seed_cost_rows(session: Session) -> AnalysisScopeIdentity:
    """Create one configured scope with one bad and one correct unit cost."""
    identity = AnalysisScopeIdentity(
        patch="16.10",
        queue_id=1100,
        tft_set_number=15,
    )
    raw = RawMatch(
        match_id="m1",
        region="americas",
        game_datetime=1,
        game_length=1800.0,
        game_version="Version 16.10.1",
        patch=identity.patch,
        queue_id=identity.queue_id,
        tft_set_number=identity.tft_set_number,
        ingested_at=1,
    )
    board = PlayerBoard(match_id="m1", puuid="p1", placement=1)
    board.units.extend(
        [
            BoardUnit(
                match_id="m1",
                puuid="p1",
                unit_idx=0,
                unit_name="Blitzcrank",
                star_level=1,
                cost=7,
            ),
            BoardUnit(
                match_id="m1",
                puuid="p1",
                unit_idx=1,
                unit_name="Maokai",
                star_level=1,
                cost=3,
            ),
        ]
    )
    raw.boards.append(board)
    scope = AnalysisScope(
        patch=identity.patch,
        queue_id=identity.queue_id,
        tft_set_number=identity.tft_set_number,
        is_active=True,
        status="ready",
    )
    session.add_all([raw, scope])
    session.flush()
    session.add(
        AnalysisFactBuild(
            scope_id=scope.scope_id,
            status="ready",
        )
    )
    session.commit()
    return identity


def test_repair_unit_costs_dry_run_does_not_mutate_or_rebuild(monkeypatch) -> None:
    """Report Blitzcrank's mismatch without changing raw or derived state."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        identity = seed_cost_rows(session)
        monkeypatch.setattr(
            repair,
            "resolve_configured_scope",
            lambda *_args, **_kwargs: identity,
        )

        def unexpected_rebuild(*_args, **_kwargs):
            """Fail if the dry-run reaches the rebuild operation."""
            raise AssertionError("dry-run unexpectedly rebuilt analytics")

        result = repair.repair_unit_costs(
            session,
            apply=False,
            resolver_factory=lambda _patch, _set: StaticResolver(),
            rebuild_function=unexpected_rebuild,
        )

        blitz = session.get(BoardUnit, ("m1", "p1", 0))
        assert blitz is not None and blitz.cost == 7
        assert result["mode"] == "dry-run"
        assert result["before"]["mismatched_rows"] == 1
        assert result["before"]["mismatches"] == [
            {
                "unit_name": "Blitzcrank",
                "static_cost": 5,
                "stored_costs": [{"cost": 7, "rows": 1}],
                "mismatched_rows": 1,
            }
        ]
        assert result["rebuild"] is None
    engine.dispose()


def test_repair_unit_costs_applies_and_rebuilds(monkeypatch) -> None:
    """Repair raw Blitzcrank cost, dirty the scope, and invoke full rebuild."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        identity = seed_cost_rows(session)
        monkeypatch.setattr(
            repair,
            "resolve_configured_scope",
            lambda *_args, **_kwargs: identity,
        )
        rebuild_calls: list[dict[str, object]] = []

        def fake_rebuild(active_session: Session, **kwargs: object) -> dict[str, int]:
            """Record the requested full rebuild without replacing test rows."""
            rebuild_calls.append({"session": active_session, **kwargs})
            return {"matches": 1, "unit_stats": 2, "processed_matches": 1}

        result = repair.repair_unit_costs(
            session,
            apply=True,
            batch_size=25,
            resolver_factory=lambda _patch, _set: StaticResolver(),
            rebuild_function=fake_rebuild,
        )

        session.expire_all()
        blitz = session.get(BoardUnit, ("m1", "p1", 0))
        maokai = session.get(BoardUnit, ("m1", "p1", 1))
        scope = session.scalar(
            repair.select(AnalysisScope).where(AnalysisScope.is_active.is_(True))
        )
        assert blitz is not None and blitz.cost == 5
        assert maokai is not None and maokai.cost == 3
        assert scope is not None and scope.status == "dirty"
        assert result["repaired_rows"] == 1
        assert result["scope_marked_dirty"] is True
        assert result["after"]["mismatched_rows"] == 0
        assert rebuild_calls == [
            {
                "session": session,
                "patch": "16.10",
                "batch_size": 25,
            }
        ]
    engine.dispose()


def test_repair_unit_costs_leaves_scope_dirty_when_rebuild_fails(monkeypatch) -> None:
    """Keep committed raw repairs visibly dirty when projection rebuild fails."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        identity = seed_cost_rows(session)
        monkeypatch.setattr(
            repair,
            "resolve_configured_scope",
            lambda *_args, **_kwargs: identity,
        )

        def failing_rebuild(
            active_session: Session,
            **_kwargs: object,
        ) -> dict[str, int]:
            """Verify the durable safety state before simulating rebuild failure."""
            active_session.expire_all()
            blitz = active_session.get(BoardUnit, ("m1", "p1", 0))
            scope = active_session.scalar(
                repair.select(AnalysisScope).where(AnalysisScope.is_active.is_(True))
            )
            assert blitz is not None and blitz.cost == 5
            assert scope is not None and scope.status == "dirty"
            raise RuntimeError("rebuild failed")

        with pytest.raises(RuntimeError, match="rebuild failed"):
            repair.repair_unit_costs(
                session,
                apply=True,
                resolver_factory=lambda _patch, _set: StaticResolver(),
                rebuild_function=failing_rebuild,
            )

        session.expire_all()
        blitz = session.get(BoardUnit, ("m1", "p1", 0))
        scope = session.scalar(
            repair.select(AnalysisScope).where(AnalysisScope.is_active.is_(True))
        )
        assert blitz is not None and blitz.cost == 5
        assert scope is not None and scope.status == "dirty"
    engine.dispose()


def test_parser_defaults_to_non_mutating_audit() -> None:
    """Require an explicit apply flag before repair and rebuild."""
    args = repair.build_parser().parse_args([])

    assert args.apply is False
    assert args.batch_size == 500
