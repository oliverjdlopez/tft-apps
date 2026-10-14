"""Historical selectors are retired from live execution."""
import pytest


@pytest.mark.parametrize('family', ['context', 'skill'])
def test_historical_selectors_report_retirement(family):
    """A retired selector cannot silently route through a new assistant."""
    if family == 'context':
        from evals.context_selection.provider import select_live
        with pytest.raises(ValueError, match='retired'):
            select_live('Select one', [])
    else:
        from evals.skill_selection.provider import select_live
        with pytest.raises(ValueError, match='retired'):
            select_live('Select one', [], max_skills=1)
