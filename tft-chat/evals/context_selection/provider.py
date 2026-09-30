"""One-attempt context or skill evaluation for frozen experiments."""
from __future__ import annotations
import time
from typing import Any
from agents import Runner
from domain.assistants import create_assistant
from domain.assistants.constants import AssistantName
from domain.providers.context import MAX_CONTEXT_SNIPPETS, MAX_SELECTOR_CHARS, _rank_context_candidates, _ContextCandidate, _all_context_candidates, _context_selector_prompt, _selected_context_ids, _shortlist_context_candidates, discover_context_files
from domain.assistants.models import ContextSelection

from .utils import coverage, validate_cases, validate_payload, selected_candidates, local_selection

def evaluate(case: dict[str, Any], *, live: bool = False, model: str | None = None) -> dict[str, Any]:
    """Run one selector attempt; the experiment runner owns repeats and scoring."""
    validate_cases([case], _all_context_candidates(discover_context_files(), set_number=None))
    query = str(case["query"])
    required = list(case.get("required", []))
    forbidden = list(case.get("forbidden", []))
    context_files = discover_context_files()

    started = time.perf_counter()
    full = _all_context_candidates(context_files, set_number=None)
    shortlist = _shortlist_context_candidates(
        context_files,
        query,
        set_number=None,
        max_selected=MAX_CONTEXT_SNIPPETS,
    )
    full_prompt = _context_selector_prompt(
        query, full, max_selected=MAX_CONTEXT_SNIPPETS
    )
    shortlist_prompt = _context_selector_prompt(
        query, shortlist, max_selected=MAX_CONTEXT_SNIPPETS
    )
    validate_payload(shortlist_prompt, candidate_count=len(shortlist))
    local_selected = local_selection(_rank_context_candidates(
        context_files, query, set_number=None
    ))
    shortlist_hits, required_count = coverage(shortlist, required)
    local_hits, _ = coverage(local_selected, required)
    shortlist_forbidden_hits, forbidden_count = coverage(shortlist, forbidden)
    local_forbidden_hits, _ = coverage(local_selected, forbidden)
    reduction = 1.0 - (len(shortlist_prompt) / max(1, len(full_prompt)))
    result: dict[str, Any] = {
        "selected": [{"content": candidate.snippet.content} for candidate in local_selected],
        "name": case["name"],
        "query": query,
        "full_candidate_count": len(full),
        "candidate_count": len(shortlist),
        "selected_count": len(local_selected),
        "full_payload_chars": len(full_prompt),
        "shortlist_payload_chars": len(shortlist_prompt),
        "payload_reduction": reduction,
        "shortlist_required_hits": shortlist_hits,
        "final_required_hits": local_hits,
        "required_count": required_count,
        "shortlist_forbidden_hits": shortlist_forbidden_hits,
        "final_forbidden_hits": local_forbidden_hits,
        "forbidden_count": forbidden_count,
        "elapsed_ms": (time.perf_counter() - started) * 1000,
        "offline_passed": (
            shortlist_hits == required_count
            and local_hits == required_count
            and local_forbidden_hits == 0
            and (not case.get("expect_empty") or not local_selected)
            and (MAX_SELECTOR_CHARS is None or len(shortlist_prompt) <= MAX_SELECTOR_CHARS)
        ),
    }

    if live:
        # There is one complete catalogue now; a second model call would only
        # introduce stochastic differences into equivalent candidate inventories.
        selected = select_live(shortlist_prompt, shortlist, model=model)
        full_selected = selected
        hits, _ = coverage(selected, required)
        forbidden_hits, _ = coverage(selected, forbidden)
        result.update(
            selected=[{"content": candidate.snippet.content} for candidate in selected],
            full_live_required_hits=coverage(full_selected, required)[0],
            full_live_forbidden_hits=coverage(full_selected, forbidden)[0],
            live_passed=hits == required_count and forbidden_hits == 0,
            live_result={"selected_count": len(selected), "required_hits": hits,
                         "required_count": required_count, "forbidden_hits": forbidden_hits},
        )
    return result


def select_live(
    prompt: str, candidates: list[_ContextCandidate], model: str | None = None
) -> list[_ContextCandidate]:
    """Run one model-backed selector and decode its bounded candidate IDs."""
    output = Runner.run_sync(
        create_assistant(AssistantName.CONTEXT_SELECTOR, model=model, output_type=ContextSelection),
        input=prompt,
        max_turns=1,
    ).final_output
    selected_ids = _selected_context_ids(
        output,
        candidate_count=len(candidates),
        max_selected=MAX_CONTEXT_SNIPPETS,
    )
    return selected_candidates(candidates, selected_ids)
