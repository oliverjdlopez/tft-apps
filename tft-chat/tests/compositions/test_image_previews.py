"""Bounded family navigation previews preserve defining alternatives."""

import pytest
from pydantic import ValidationError

from domain.compositions.fixtures import fixture_family
from domain.compositions.models import EntityRef, StructuralPattern, UnitRequirement, TraitRequirement
from services.compositions.utils import family_preview
from services.compositions.models import FamilyPatternPreview


def test_preview_bounds_requirements_without_merging_alternatives():
    """Retain unit-first ordering and expose omitted requirements and alternatives."""
    first = StructuralPattern(pattern_id="first", label="First", units=tuple(
        UnitRequirement(unit=EntityRef(key=f"u{i}", name=f"Unit {i}"), min_copies=2, itemized=True)
        for i in range(5)
    ), traits=tuple(
        TraitRequirement(trait=EntityRef(key=f"t{i}", name=f"Trait {i}"), min_tier_current=2)
        for i in range(3)
    ))
    other = first.model_copy(update={"pattern_id": "other", "label": "Other"})
    family = fixture_family().model_copy(update={"defining_patterns": (first, other)})
    preview = family_preview(family)
    assert preview.pattern.units == first.units
    assert preview.pattern.traits == first.traits[:1]
    assert preview.omitted_requirements == 2 and preview.alternative_patterns == 1
    with pytest.raises(ValidationError):
        FamilyPatternPreview(pattern=first, omitted_requirements=0, alternative_patterns=0)
    assert family_preview(family.model_copy(update={"defining_patterns": ()})) is None
