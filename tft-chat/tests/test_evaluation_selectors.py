"""Exercise selector evaluation calls through the prepared Assistant runtime."""
from types import SimpleNamespace

import pytest

from domain.assistants.models import CandidateIdSelection, ContextSelection, ContextSelectionNeed
from domain.providers.models import ContextCandidate, ContextSnippet, SkillDefinition
from domain.runtime.models import AssistantRunContext


@pytest.mark.parametrize('family', ['context', 'skill'])
def test_selector_model_calls_use_prepared_state_without_recursive_selection(monkeypatch, family):
    """Selectors use typed state and a one-turn limit without invoking selectors again."""
    async def forbidden_selection(*args, **kwargs):
        """Fail immediately if preparing a selector recursively selects resources."""
        pytest.fail('Selector preparation recursively selected resources')

    monkeypatch.setattr('domain.providers.context.RepositoryContextProvider.aselect', forbidden_selection)
    monkeypatch.setattr('domain.providers.skills.RepositorySkillProvider.aselect', forbidden_selection)
    output = (ContextSelection(selections=[ContextSelectionNeed(need='Facts', part_ids=[0])])
              if family == 'context' else CandidateIdSelection(selected_ids=[0]))

    async def run(agent, *, input, context, hooks, max_turns, **kwargs):
        """Check the SDK boundary while returning deterministic structured IDs."""
        assert isinstance(context, AssistantRunContext)
        assert context.runtime.surface == 'eval'
        assert context.resources.references == () and context.resources.skills == ()
        assert input == 'Select one' and max_turns == 1
        assert hooks is not None and callable(agent.instructions)
        return SimpleNamespace(final_output=output)

    monkeypatch.setattr('domain.assistants.assistant.Runner.run', run)
    if family == 'context':
        from evals.context_selection.provider import select_live
        candidate = ContextCandidate(snippet=ContextSnippet(context_file='facts', path='facts.md',
            content='Facts', line=1, score=1), kind='reference', description='Facts', part_type='markdown', title='Facts')
        assert select_live('Select one', [candidate]) == [candidate]
    else:
        from evals.skill_selection.provider import select_live
        skill = SkillDefinition(name='workflow', description='Workflow', body='Body', path='workflow/SKILL.md')
        assert select_live('Select one', [skill], max_skills=1) == [skill]
