"""Capture only ready anonymous facts into reusable experiment-local snapshots."""

import random
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from sqlalchemy import select, text
from db.models import (
    AnalysisScope,
    AnalysisFactBuild,
    ANALYSIS_FACT_SCHEMA_VERSION,
    AnalysisBoard,
    AnalysisBoardUnit,
    AnalysisBoardItem,
    AnalysisBoardTrait,
)
from db.session import open_db
from domain.compositions.models import (
    BoardObservation,
    BoardOutcome,
    UnitOccurrence,
    ItemOccurrence,
    TraitObservation,
    EntityRef,
)
from domain.compositions.fixtures import fixture_boards, fixture_outcomes
from .models import SourceSummary, FrozenSource, FrozenBoard, FrozenUnit
from .storage import offline_enabled
from .utils import make_snapshot, write_frozen_source


def capture_source(request):
    """Read one consistent scope revision; never fall back to raw match/player rows."""
    if request.source_kind == "fixture":
        return make_snapshot(
            request, fixture_boards(), fixture_outcomes(), "fixture", 17, 1100
        )
    if offline_enabled():
        from .snapshot import capture_frozen_source

        return capture_frozen_source(request)
    with active_source() as (session, scope, keys):
        sample_keys = set(
            random.Random(request.seed).sample(keys, min(request.sample_size, len(keys)))
        )
        selected_keys = (
            keys if request.full_population else [key for key in keys if key in sample_keys]
        )
        boards, outcomes, sample_ids = [], [], []
        for key, board, outcome in read_fact_boards(session, scope, selected_keys):
            boards.append(board)
            outcomes.append(outcome)
            if key in sample_keys:
                sample_ids.append(board.observation_id)
        return make_snapshot(
            request,
            tuple(boards),
            tuple(outcomes),
            scope.patch,
            scope.tft_set_number,
            scope.queue_id,
            eligible=len(keys),
            sample_ids=tuple(sample_ids),
        )


@contextmanager
def active_source():
    """Hold a validated repeatable-read population for capture or development export."""
    with open_db() as session:
        # Freeze all fact reads in one database snapshot; a simultaneous rebuild
        # must not produce a mixture of old rosters and newly inserted items.
        if session.bind.dialect.name == "postgresql":
            session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            )
        scope = session.scalar(
            select(AnalysisScope).where(AnalysisScope.is_active.is_(True))
        )
        build = session.get(AnalysisFactBuild, scope.scope_id) if scope else None
        if (
            scope is None
            or scope.status != "ready"
            or build is None
            or build.status != "ready"
            or build.schema_version != ANALYSIS_FACT_SCHEMA_VERSION
        ):
            raise ValueError(
                "Active analysis facts are unavailable or not ready; publish a validated fact build first."
            )
        keys = list(
            session.scalars(
                select(AnalysisBoard.board_key)
                .where(AnalysisBoard.scope_id == scope.scope_id)
                .order_by(AnalysisBoard.board_key)
            )
        )
        eligible = len(keys)
        if eligible != build.board_count:
            raise ValueError(
                "Active fact counts are inconsistent; rebuild and validate facts."
            )
        yield session, scope, keys


def read_fact_boards(session, scope, selected_keys):
    """Stream occurrence-preserving anonymous boards within the caller's transaction.

    Args:
        session: Read-only source session held by active_source.
        scope: Validated ready scope whose occurrence facts are being read.
        selected_keys: Ordered scoped keys, used only during database projection.

    Yields:
        Private source key, anonymous observation, and separately held outcome.
    """
    index = 0
    for offset in range(0, len(selected_keys), 1000):
        batch = selected_keys[offset : offset + 1000]
        units, items, traits = (
            defaultdict(list),
            defaultdict(list),
            defaultdict(list),
        )
        for item in session.scalars(
            select(AnalysisBoardItem)
            .where(
                AnalysisBoardItem.scope_id == scope.scope_id,
                AnalysisBoardItem.board_key.in_(batch),
            )
            .order_by(AnalysisBoardItem.item_slot)
        ):
            items[(item.board_key, item.unit_idx)].append(
                ItemOccurrence(
                    slot=item.item_slot,
                    item=EntityRef(key=item.item_api_name, name=item.item_name),
                )
            )
        for unit in session.scalars(
            select(AnalysisBoardUnit)
            .where(
                AnalysisBoardUnit.scope_id == scope.scope_id,
                AnalysisBoardUnit.board_key.in_(batch),
            )
            .order_by(AnalysisBoardUnit.unit_idx)
        ):
            units[unit.board_key].append(
                UnitOccurrence(
                    occurrence_index=unit.unit_idx,
                    unit=EntityRef(key=unit.unit_name, name=unit.unit_name),
                    star_level=unit.star_level,
                    items=tuple(items[(unit.board_key, unit.unit_idx)]),
                )
            )
        for trait in session.scalars(
            select(AnalysisBoardTrait)
            .where(
                AnalysisBoardTrait.scope_id == scope.scope_id,
                AnalysisBoardTrait.board_key.in_(batch),
            )
            .order_by(AnalysisBoardTrait.trait_name)
        ):
            traits[trait.board_key].append(
                TraitObservation(
                    trait=EntityRef(key=trait.trait_name, name=trait.trait_name),
                    num_units=trait.num_units,
                    tier_current=trait.tier_current,
                    style=trait.style,
                )
            )
        for board in session.scalars(
            select(AnalysisBoard)
            .where(
                AnalysisBoard.scope_id == scope.scope_id,
                AnalysisBoard.board_key.in_(batch),
            )
            .order_by(AnalysisBoard.board_key)
        ):
            observation_id = f"observation-{index:08d}"
            observation = BoardObservation(
                observation_id=observation_id,
                level=board.level,
                units=tuple(units[board.board_key]),
                traits=tuple(traits[board.board_key]),
            )
            outcome = BoardOutcome(
                observation_id=observation_id, placement=board.placement
            )
            yield board.board_key, observation, outcome
            index += 1


def source_summary(source_kind):
    """Expose safe readiness and denominator metadata without capturing a snapshot."""
    if source_kind == "fixture":
        return SourceSummary(
            source_kind="fixture",
            ready=True,
            patch="fixture",
            set_number=17,
            queue_id=1100,
            eligible_boards=len(fixture_boards()),
            fact_revision="fixture.v1",
            warning="Illustrative synthetic facts.",
        )
    if offline_enabled():
        from .snapshot import frozen_source_summary

        return frozen_source_summary()
    try:
        with open_db() as session:
            scope = session.scalar(
                select(AnalysisScope).where(AnalysisScope.is_active.is_(True))
            )
            build = session.get(AnalysisFactBuild, scope.scope_id) if scope else None
            ready = bool(
                scope
                and scope.status == "ready"
                and build
                and build.status == "ready"
                and build.schema_version == ANALYSIS_FACT_SCHEMA_VERSION
            )
            return SourceSummary(
                source_kind="active",
                ready=ready,
                patch=scope.patch if scope else None,
                set_number=scope.tft_set_number if scope else None,
                queue_id=scope.queue_id if scope else None,
                eligible_boards=build.board_count if ready else None,
                fact_revision=f"facts.v{build.schema_version}:{build.ready_at.isoformat() if build.ready_at else 'ready'}"
                if ready
                else None,
                warning=None
                if ready
                else "Active analysis facts are unavailable or not ready.",
            )
    except Exception:
        return SourceSummary(
            source_kind="active",
            ready=False,
            patch=None,
            set_number=None,
            queue_id=None,
            eligible_boards=None,
            fact_revision=None,
            warning="Analysis database is unavailable. Saved experiments and fixture display are independent of source readiness.",
        )


def export_frozen_source(destination):
    """Export every eligible board from one consistent ready scope, without identities.

    Args:
        destination: Explicit JSON output path; replacement is atomic after validation.

    Returns:
        Validated complete source metadata and lossless occurrence catalogs.
    """
    unit_ids, trait_ids = {}, {}
    unit_entities, item_entities = {}, {}
    boards, placements = [], []
    with active_source() as (session, scope, keys):
        for _, board, outcome in read_fact_boards(session, scope, keys):
            # Whole occurrences are dictionary encoded, preserving holder items,
            # duplicate units, sparse slot indices, and unknown trait measurements.
            units = tuple(unit_ids.setdefault(unit, len(unit_ids)) for unit in board.units)
            traits = tuple(
                trait_ids.setdefault(trait, len(trait_ids)) for trait in board.traits
            )
            boards.append(FrozenBoard(level=board.level, units=units, traits=traits))
            placements.append(outcome.placement)
        source = FrozenSource(
            exported_at=datetime.now(timezone.utc).isoformat(),
            patch=scope.patch,
            set_number=scope.tft_set_number,
            queue_id=scope.queue_id,
            eligible_boards=len(keys),
            units=tuple(
                FrozenUnit(
                    occurrence_index=unit.occurrence_index,
                    unit=unit_entities.setdefault(unit.unit, len(unit_entities)),
                    star_level=unit.star_level,
                    items=tuple(
                        (item.slot, item_entities.setdefault(item.item, len(item_entities)))
                        for item in unit.items
                    ),
                )
                for unit in unit_ids
            ),
            unit_entities=tuple(unit_entities),
            item_entities=tuple(item_entities),
            traits=tuple(trait_ids),
            boards=tuple(boards),
            placements=tuple(placements),
        )
    write_frozen_source(destination, source)
    return source
