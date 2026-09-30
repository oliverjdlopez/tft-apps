"""Freeze and replay the full eligible population without a source database."""

import random
from common.paths import find_repo_root
from domain.compositions.models import BoardObservation, BoardOutcome, UnitOccurrence, ItemOccurrence
from .models import SourceSummary
from .utils import make_snapshot, read_frozen_source


def frozen_source_path():
    """Locate the portable Git-owned input independently of the working directory."""
    return find_repo_root() / "dev" / "compositions" / "eligible-boards.json"


def load_frozen_source():
    """Cache validated inputs until an atomic refresh replaces the source file."""
    path = frozen_source_path()
    stat = path.stat()
    return read_frozen_source(path, stat.st_mtime_ns, stat.st_size)


def capture_frozen_source(request):
    """Expand only requested observations and retain deterministic population sampling."""
    source, _ = load_frozen_source()
    sample = set(random.Random(request.seed).sample(
        range(source.eligible_boards), min(request.sample_size, source.eligible_boards)
    ))
    selected = range(source.eligible_boards) if request.full_population else sorted(sample)
    # Expand shared occurrences only once even when many boards reuse them.
    units = {}
    boards, outcomes, sample_ids = [], [], []
    for index in selected:
        row = source.boards[index]
        for unit_index in row.units:
            if unit_index not in units:
                unit = source.units[unit_index]
                units[unit_index] = UnitOccurrence(
                    occurrence_index=unit.occurrence_index,
                    unit=source.unit_entities[unit.unit], star_level=unit.star_level,
                    items=tuple(ItemOccurrence(slot=slot, item=source.item_entities[item]) for slot, item in unit.items),
                )
        observation_id = f"observation-{len(boards):08d}"
        boards.append(BoardObservation(
            observation_id=observation_id, level=row.level,
            units=tuple(units[i] for i in row.units),
            traits=tuple(source.traits[i] for i in row.traits),
        ))
        outcomes.append(BoardOutcome(
            observation_id=observation_id, placement=source.placements[index]
        ))
        if index in sample:
            sample_ids.append(observation_id)
    return make_snapshot(
        request, tuple(boards), tuple(outcomes), source.patch, source.set_number,
        source.queue_id, eligible=source.eligible_boards, sample_ids=tuple(sample_ids),
    )


def frozen_source_summary():
    """Identify offline inputs visibly and fail closed when the checked-in JSON is bad."""
    try:
        source, revision = load_frozen_source()
        return SourceSummary(
            source_kind="active", ready=True, patch=source.patch,
            set_number=source.set_number, queue_id=source.queue_id,
            eligible_boards=source.eligible_boards, fact_revision=f"frozen.v1:{revision}",
            warning=f"Offline development: checked-in boards frozen {source.exported_at}. Experiments are saved locally.",
        )
    except (OSError, ValueError):
        return SourceSummary(
            source_kind="active", ready=False, patch=None, set_number=None,
            queue_id=None, eligible_boards=None, fact_revision=None,
            warning="Offline development source is missing or invalid. Restore dev/compositions/eligible-boards.json or refresh it on a database-connected machine.",
        )
