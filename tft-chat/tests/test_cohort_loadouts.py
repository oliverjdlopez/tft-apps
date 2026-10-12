from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from db.models import AnalysisBoard, AnalysisBoardItem, AnalysisBoardUnit
from domain.tools.db_tools import cohort_tools
from domain.tools.db_tools.cohort_query import compile_filter_group
from domain.tools.db_tools.models import FilterGroup, MAX_FILTER_GROUP_PREDICATES
from conftest import _call_tool


ITEM_A = "TFT_Item_TestA"
ITEM_B = "TFT_Item_TestB"
HOLDER = "TFT17_Carry"


def _add_board(session, scope_id: int, board_key: str, placement: int) -> None:
    """Add one minimal anonymous board fixture."""
    session.add(
        AnalysisBoard(
            scope_id=scope_id,
            board_key=board_key,
            lobby_key=f"lobby-{scope_id}-{board_key}",
            placement=placement,
            level=9,
            region="na",
            platform="na1",
            game_length=1800,
            unit_count=1,
            completed_item_count=0,
        )
    )


def _add_unit(
    session,
    scope_id: int,
    board_key: str,
    unit_idx: int,
    *,
    star_level: int = 2,
    completed_item_count: int,
    items: tuple[str, ...] = (),
) -> None:
    """Add a unit occurrence and its exact item rows."""
    session.add(
        AnalysisBoardUnit(
            scope_id=scope_id,
            board_key=board_key,
            unit_idx=unit_idx,
            unit_name=HOLDER,
            star_level=star_level,
            completed_item_count=completed_item_count,
            loadout_key="|".join(items),
            item_1=items[0] if items else None,
            item_2=items[1] if len(items) > 1 else None,
            item_3=items[2] if len(items) > 2 else None,
        )
    )
    session.add_all(
        AnalysisBoardItem(
            scope_id=scope_id,
            board_key=board_key,
            unit_idx=unit_idx,
            item_slot=item_slot,
            item_api_name=item_name,
            item_name=item_name,
        )
        for item_slot, item_name in enumerate(items)
    )


def _loadout_filter(item_name: str, other_item: str) -> dict:
    """Return a full holder predicate for one side of an item comparison."""
    return {
        "unit_conditions": [
            {
                "name": HOLDER,
                "star_level": 2,
                "min_completed_items": 1,
                "max_completed_items": 1,
                "required_items": [item_name],
                "excluded_items": [other_item],
            }
        ]
    }


def test_compare_cohorts_binds_loadout_to_same_unit_occurrence(
    dev_session, monkeypatch
) -> None:
    """Compare same-copy loadouts and retain overlap from duplicate holders."""
    # One exact A holder, one exact B holder, and a board where separate copies
    # satisfy opposite sides. The final board demonstrates that per-copy
    # exclusions do not promise disjoint board cohorts.
    _add_board(dev_session, 1, "a-only", 1)
    _add_unit(dev_session, 1, "a-only", 0, completed_item_count=1, items=(ITEM_A,))
    _add_board(dev_session, 1, "b-only", 2)
    _add_unit(dev_session, 1, "b-only", 0, completed_item_count=1, items=(ITEM_B,))
    _add_board(dev_session, 1, "split-copies", 3)
    _add_unit(
        dev_session, 1, "split-copies", 0, completed_item_count=1, items=(ITEM_A,)
    )
    _add_unit(
        dev_session, 1, "split-copies", 1, completed_item_count=1, items=(ITEM_B,)
    )
    # A is on a 2-item copy, while the 1-item copy carries B. A board-level
    # ItemCondition used to match A independently of the unit count condition.
    _add_board(dev_session, 1, "different-count-copies", 4)
    _add_unit(
        dev_session,
        1,
        "different-count-copies",
        0,
        completed_item_count=1,
        items=(ITEM_B,),
    )
    _add_unit(
        dev_session,
        1,
        "different-count-copies",
        1,
        completed_item_count=2,
        items=(ITEM_A, ITEM_B),
    )
    _add_board(dev_session, 1, "no-a", 5)
    _add_unit(dev_session, 1, "no-a", 0, completed_item_count=1, items=(ITEM_B,))
    # Same board key and unit index in another scope must not satisfy scope 1.
    _add_board(dev_session, 2, "no-a", 1)
    _add_unit(dev_session, 2, "no-a", 0, completed_item_count=1, items=(ITEM_A,))
    # Same-scope, different board key is also isolated by the occurrence key.
    _add_board(dev_session, 1, "other-board", 1)
    _add_unit(dev_session, 1, "other-board", 0, completed_item_count=1, items=(ITEM_A,))
    dev_session.flush()

    monkeypatch.setattr(
        cohort_tools,
        "active_fact_scope",
        lambda _session: SimpleNamespace(scope_id=1),
    )
    monkeypatch.setattr(cohort_tools, "MIN_PUBLIC_BOARDS", 1)
    result = _call_tool(
        monkeypatch,
        dev_session,
        cohort_tools.compare_cohorts,
        target=_loadout_filter(ITEM_A, ITEM_B),
        baseline=_loadout_filter(ITEM_B, ITEM_A),
    )

    assert result["kind"] == "comparison"
    assert result["target"]["boards"] == 3  # a-only, split, and other-board
    assert result["baseline"]["boards"] == 4  # b-only, split, different-count, no-a
    assert result["overlap"]["boards"] == 1
    assert any(warning["code"] == "cohorts_overlap" for warning in result["warnings"])

    # The old split form could match A on the two-item copy while its unit
    # count constraint matched the separate one-item B copy.
    legacy_split = FilterGroup.model_validate(
        {
            "unit_conditions": [
                {
                    "name": HOLDER,
                    "star_level": 2,
                    "min_completed_items": 1,
                    "max_completed_items": 1,
                }
            ],
            "item_conditions": [
                {"name": ITEM_A, "holder": HOLDER, "holder_star_level": 2}
            ],
        }
    )
    unit = aliased(AnalysisBoard)
    assert dev_session.scalar(
        select(func.count())
        .select_from(unit)
        .where(
            unit.scope_id == 1,
            unit.board_key == "different-count-copies",
            compile_filter_group(legacy_split, unit),
        )
    ) == 1
    same_occurrence = FilterGroup.model_validate(
        _loadout_filter(ITEM_A, ITEM_B)
    )
    assert dev_session.scalar(
        select(func.count())
        .select_from(unit)
        .where(
            unit.scope_id == 1,
            unit.board_key == "different-count-copies",
            compile_filter_group(same_occurrence, unit),
        )
    ) == 0


def test_unit_item_constraints_keep_duplicates_and_isolate_aliased_boards(
    dev_session,
) -> None:
    """Count repeated required items on one copy under aliased board queries."""
    _add_board(dev_session, 1, "duplicate-items", 1)
    _add_unit(
        dev_session,
        1,
        "duplicate-items",
        0,
        completed_item_count=2,
        items=(ITEM_A, ITEM_A),
    )
    _add_board(dev_session, 1, "single-item", 2)
    _add_unit(dev_session, 1, "single-item", 0, completed_item_count=1, items=(ITEM_A,))
    dev_session.flush()

    board = aliased(AnalysisBoard)
    group = FilterGroup.model_validate(
        {
            "unit_conditions": [
                {
                    "name": HOLDER,
                    "required_items": [ITEM_A, ITEM_A],
                    "min_completed_items": 2,
                    "max_completed_items": 2,
                }
            ]
        }
    )
    matches = set(
        dev_session.scalars(
            select(board.board_key).where(
                board.scope_id == 1,
                compile_filter_group(group, board),
            )
        )
    )

    assert matches == {"duplicate-items"}


def test_zero_matching_copies_excludes_only_occurrences_with_required_item(
    dev_session,
) -> None:
    """A zero copy range can express absence of a matching item-bearing copy."""
    _add_board(dev_session, 1, "has-only-b", 1)
    _add_unit(dev_session, 1, "has-only-b", 0, completed_item_count=1, items=(ITEM_B,))
    _add_board(dev_session, 1, "has-a", 2)
    _add_unit(dev_session, 1, "has-a", 0, completed_item_count=1, items=(ITEM_A,))
    dev_session.flush()

    group = FilterGroup.model_validate(
        {
            "unit_conditions": [
                {
                    "name": HOLDER,
                    "required_items": [ITEM_A],
                    "min_copies": 0,
                    "max_copies": 0,
                }
            ]
        }
    )
    count = dev_session.scalar(
        select(func.count())
        .select_from(AnalysisBoard)
        .where(compile_filter_group(group, AnalysisBoard))
    )

    assert count == 1


def test_nested_item_predicates_count_toward_filter_budget() -> None:
    """Keep nested occurrence predicates within the shared compilation cap."""
    conditions = [
        {
            "name": f"TFT17_Unit{index}",
            "required_items": [f"TFT_Item_Required{index}"],
            "excluded_items": [f"TFT_Item_Excluded{index}"],
        }
        for index in range(21)
    ]
    at_limit = FilterGroup.model_validate(
        {
            "unit_conditions": conditions,
            "item_conditions": [{"name": "TFT_Item_Extra"}],
        }
    )
    assert MAX_FILTER_GROUP_PREDICATES == 64

    conditions.append(
        {
            "name": "TFT17_OverLimit",
            "required_items": ["TFT_Item_OverLimit"],
            "excluded_items": ["TFT_Item_OverLimitExcluded"],
        }
    )
    try:
        FilterGroup.model_validate({"unit_conditions": conditions})
    except ValueError as exc:
        assert "at most 64 predicates" in str(exc)
    else:  # pragma: no cover - assertion message is clearer than Pydantic's wrapper
        raise AssertionError("nested item predicates exceeded the filter budget")

    assert len(at_limit.unit_conditions or []) == 21


@pytest.mark.parametrize(
    ("condition", "message"),
    [
        ({"required_items": []}, "at least 1 item"),
        ({"required_items": ["A", "B", "C", "D"]}, "at most 3 items"),
        ({"excluded_items": []}, "at least 1 item"),
        ({"excluded_items": ["A", "A"]}, "excluded_items must not contain duplicate"),
        (
            {"required_items": ["A"], "excluded_items": ["A"]},
            "must not overlap",
        ),
    ],
)
def test_unit_item_constraint_validation(condition: dict, message: str) -> None:
    """Reject empty, overfull, duplicate-exclusion, and contradictory lists."""
    with pytest.raises(ValueError, match=message):
        FilterGroup.model_validate(
            {"unit_conditions": [{"name": HOLDER, **condition}]}
        )
