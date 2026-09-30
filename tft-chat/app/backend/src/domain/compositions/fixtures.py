"""Deterministic immutable examples with duplicate champions and unknown traits."""

from .models import (
    BoardObservation,
    BoardOutcome,
    EntityRef,
    ItemOccurrence,
    UnitOccurrence,
    TraitObservation,
    FamilyDefinition,
    StructuralPattern,
    UnitRequirement,
)


def fixture_boards() -> tuple[BoardObservation, ...]:
    """Return outcome-free families with shared frontlines and itemized anchors."""
    boards = []
    for i in range(24):
        anchor = "Jinx" if i < 12 else "Karma"
        item = EntityRef(
            key="fixture:blade" if i < 12 else "fixture:staff",
            name="Blade" if i < 12 else "Staff",
        )
        units = (
            UnitOccurrence(
                occurrence_index=0,
                unit=EntityRef(key=anchor, name=anchor),
                star_level=2,
                items=(
                    ItemOccurrence(slot=0, item=item),
                    ItemOccurrence(slot=1, item=item),
                ),
            ),
            UnitOccurrence(
                occurrence_index=1,
                unit=EntityRef(key="Leona", name="Leona"),
                star_level=2,
                items=(),
            ),
            UnitOccurrence(
                occurrence_index=2,
                unit=EntityRef(
                    key=anchor if i % 3 == 0 else "Bard",
                    name=anchor if i % 3 == 0 else "Bard",
                ),
                star_level=1,
                items=(),
            ),
        )
        boards.append(
            BoardObservation(
                observation_id=f"example-{i:03}",
                level=7 if i % 4 else None,
                units=units,
                traits=(
                    TraitObservation(
                        trait=EntityRef(key="Bastion", name="Bastion"),
                        num_units=2,
                        tier_current=1,
                        style=1,
                    ),
                    TraitObservation(
                        trait=EntityRef(key="Unknown", name="Unreported trait"),
                        num_units=None,
                        tier_current=None,
                        style=None,
                    ),
                ),
            )
        )
    return tuple(boards)


def fixture_outcomes() -> tuple[BoardOutcome, ...]:
    """Keep fixture outcomes outside the adapter inputs."""
    return tuple(
        BoardOutcome(
            observation_id=b.observation_id, placement=(i % 8) + 1 if i % 5 else None
        )
        for i, b in enumerate(fixture_boards())
    )


def fixture_family() -> FamilyDefinition:
    """Show a jointly verified structure without implying board positioning."""
    return FamilyDefinition(
        family_id="fixture-jinx",
        label="Jinx investment",
        description="Illustrative fixture; final-board observations do not encode positioning.",
        defining_patterns=(
            StructuralPattern(
                pattern_id="jinx-leona",
                label="Itemized Jinx with Leona",
                units=(
                    UnitRequirement(
                        unit=EntityRef(key="Jinx", name="Jinx"),
                        min_copies=1,
                        itemized=True,
                    ),
                    UnitRequirement(
                        unit=EntityRef(key="Leona", name="Leona"),
                        min_copies=1,
                        itemized=None,
                    ),
                ),
                traits=(),
            ),
        ),
        representative_observation_ids=("example-000",),
        variations=(),
    )
