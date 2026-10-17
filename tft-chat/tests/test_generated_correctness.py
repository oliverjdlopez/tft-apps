"""Independent small-population oracles for cohort SQL and shop probabilities."""

from collections import Counter

from hypothesis import given, settings, strategies as st
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.models import Base, AnalysisScope, AnalysisBoard, AnalysisBoardUnit, AnalysisBoardItem
from domain.tools.db_tools.cohort_query import compile_filter_group
from domain.tools.db_tools.models import FilterGroup
from domain.tools import rolldown

UNIT = st.tuples(st.sampled_from(["TFT18_TestCarry", "TFT18_TestTank"]), st.integers(1, 3),
                 st.lists(st.sampled_from(["ItemA", "ItemB"]), max_size=3))
POPULATION = st.lists(st.lists(UNIT, max_size=4), min_size=1, max_size=6)


@settings(max_examples=40, deadline=None, derandomize=True)
@given(boards=POPULATION, stars=st.one_of(st.none(), st.integers(1, 3)),
       required=st.integers(0, 3), excluded=st.booleans(), minimum=st.integers(0, 3))
def test_cohort_sql_matches_independent_occurrence_counter(boards, stars, required, excluded, minimum):
    """Count exact equipped occurrences without sharing SQL/compiler helpers."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            scopes = [AnalysisScope(patch=f"synthetic-current-{index}", queue_id=1100, tft_set_number=18,
                                    is_active=index == 0, status="ready", universe_boards=len(boards)) for index in range(2)]
            session.add_all(scopes)
            session.flush()
            for scope in scopes:
                for index, units in enumerate(boards):
                    key = f"board-{index}"
                    session.add(AnalysisBoard(scope_id=scope.scope_id, board_key=key, lobby_key="lobby",
                                              placement=index % 8 + 1, level=8, region="fixture", game_length=100,
                                              unit_count=len(units), completed_item_count=sum(len(unit[2]) for unit in units)))
                    for unit_idx, (name, star, items) in enumerate(units):
                        session.add(AnalysisBoardUnit(scope_id=scope.scope_id, board_key=key, unit_idx=unit_idx,
                                                      unit_name=name, star_level=star, completed_item_count=len(items), loadout_key="|".join(items)))
                        for slot, item in enumerate(items):
                            session.add(AnalysisBoardItem(scope_id=scope.scope_id, board_key=key, unit_idx=unit_idx,
                                                          item_slot=slot, item_api_name=item, item_name=item))
            session.flush()
            condition = {"name": "TFT18_TestCarry", "star_level": stars, "min_copies": minimum,
                         "required_items": ["ItemA"] * required or None,
                         "excluded_items": ["ItemB"] if excluded else None}
            group = FilterGroup(unit_conditions=[condition])
            actual = set(session.scalars(select(AnalysisBoard.board_key).where(
                AnalysisBoard.scope_id == scopes[0].scope_id, compile_filter_group(group))))
            expected = set()
            for index, units in enumerate(boards):
                copies = sum(name == "TFT18_TestCarry" and (stars is None or star == stars)
                             and Counter(items)["ItemA"] >= required
                             and (not excluded or "ItemB" not in items) for name, star, items in units)
                if copies >= minimum:
                    expected.add(f"board-{index}")
            assert actual == expected
    finally:
        engine.dispose()


@settings(max_examples=12, deadline=None, derandomize=True)
@given(roster=st.integers(1, 5), removed=st.integers(0, 29), rolls=st.integers(1, 4))
def test_seeded_simulation_agrees_with_exact_one_slot_probability(roster, removed, rolls):
    """Compare independent repeated draws with an exact finite-pool calculation."""
    previous = rolldown.SHOP_SIZE
    rolldown.SHOP_SIZE = 1
    try:
        arguments = dict(level=1, budget=rolls, budget_type="rolls", targets=[("Synthetic carry", 1, 1, removed)],
                         roster_counts={1: roster, 2: 1, 3: 1, 4: 1, 5: 1}, simulations=12_000, seed=9182)
        result = rolldown.calculate_rolldown(**arguments)
        probability = (30 - removed) / (30 * roster - removed)
        exact = 1 - (1 - probability) ** rolls
        assert abs(result["probability_find_all_targets"] - exact) < 0.025
        distribution = result["targets"][0]["copies_found_distribution"]
        assert abs(sum(distribution.values()) - 1) < 1e-8
        assert result == rolldown.calculate_rolldown(**arguments)
    finally:
        rolldown.SHOP_SIZE = previous
