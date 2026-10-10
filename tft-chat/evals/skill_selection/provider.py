"""One-attempt context or skill evaluation for frozen experiments."""
from __future__ import annotations
import time
from typing import Any
from agents import Runner
from domain.assistants import create_assistant
from domain.assistants.constants import AssistantName
from domain.providers.skills import (
    MAX_SELECTED_SKILLS,
    SkillDefinition,
    _discover_skills,
    selected_skill_ids as _selected_skill_ids,
    skill_selector_prompt as _skill_selector_prompt,
    select_skills,
)
from domain.assistants.models import CandidateIdSelection

from .utils import ignore_unknown_skill_references, validate_cases, selection_metrics

def evaluate(case: dict[str, Any], *, live: bool = False, model: str | None = None) -> dict[str, Any]:
    """Run one selector attempt; the experiment runner owns repeats and scoring."""
    skills = _discover_skills()
    original = case
    case = ignore_unknown_skill_references([case], skills)[0]
    validate_cases([case], skills)
    query = str(case["query"])
    max_skills = int(case.get("max_skills", MAX_SELECTED_SKILLS))
    prompt = _skill_selector_prompt(query, skills, max_selected=max_skills)

    started = time.perf_counter()
    selected = select_skills(skills, query, max_skills=max_skills)
    result: dict[str, Any] = {
        "selected": [skill.name for skill in selected],
        "name": case["name"],
        "query": query,
        "candidate_count": len(skills),
        "payload_chars": len(prompt),
        "elapsed_ms": (time.perf_counter() - started) * 1000,
        **selection_metrics(selected, case),
    }
    result["offline_passed"] = result.pop("passed")

    result["ignored_skills"] = sorted((set(original.get("required", [])) | set(original.get("forbidden", []))) - {s.name for s in skills})
    if live:
        live_selected = selected if case.get("explicit") else select_live(prompt, skills, max_skills=max_skills, model=model)
        metrics = selection_metrics(live_selected, case)
        result.update(selected=[skill.name for skill in live_selected], live_passed=metrics["passed"], live_result=metrics)
    return result


def select_live(
    prompt: str,
    skills: list[SkillDefinition],
    *,
    max_skills: int,
    model: str | None = None,
) -> list[SkillDefinition]:
    """Run one model-backed selector and decode its bounded candidate IDs."""
    output = Runner.run_sync(
        create_assistant(AssistantName.SKILL_SELECTOR, model=model, output_type=CandidateIdSelection),
        input=prompt,
        max_turns=1,
    ).final_output
    selected_ids = _selected_skill_ids(
        output,
        candidate_count=len(skills),
        max_selected=max_skills,
    )
    return [skills[index] for index in selected_ids]
