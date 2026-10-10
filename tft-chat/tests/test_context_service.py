import asyncio
import json
import pytest
from pathlib import Path
from types import SimpleNamespace

from domain.providers.context import (
    CONTEXT_DIR,
    ContextFile,
    DEFAULT_CONTEXT_PROVIDER,
    RepositoryContextProvider,
    discover_context_files,
    load_context_file,
    render_context_files,
    select_context_snippets,
)
from domain.assistants.constants import AssistantName


@pytest.fixture(autouse=True)
def offline_context_selection(monkeypatch):
    """Keep provider tests deterministic unless a test supplies its own runner."""
    monkeypatch.setattr(
        "domain.providers.context.load_config",
        lambda: SimpleNamespace(secrets=SimpleNamespace(openai_api_key="")),
    )


def test_context_resources_support_markdown_and_json_files() -> None:
    assert CONTEXT_DIR.parent.name == "resources"
    files = [path for path in CONTEXT_DIR.rglob("*") if path.is_file()]
    assert files
    assert all(path.suffix in {".md", ".json"} for path in files)


def test_load_context_file_reads_consolidated_description(tmp_path: Path) -> None:
    path = tmp_path / "units.md"
    path.write_text(
        """---
name: current-units
description: Current unit facts covering champion roles. Use for unit questions.
sets: 18, 18.5
---

# Units

- **Karma** — adaptive bruiser
""",
        encoding="utf-8",
    )

    context_file = load_context_file(path, relative_to=tmp_path)

    assert context_file.name == "current-units"
    assert context_file.description == (
        "Current unit facts covering champion roles. Use for unit questions."
    )
    assert context_file.sets == ("18", "18.5")
    assert context_file.path == "units.md"


def test_selects_only_task_relevant_context_excerpts() -> None:
    context_files = discover_context_files()

    snippets = select_context_snippets(
        context_files,
        "Compare Karma in Blossom with a Blossom Emblem",
        set_number=18,
    )
    rendered = render_context_files(snippets)

    assert snippets
    assert all(not snippet.content.startswith("---\n") for snippet in snippets)
    assert "score" not in rendered.casefold()


def test_context_selection_recognizes_common_compound_name_aliases(tmp_path: Path) -> None:
    """Exercise compound aliases independently of the current champion roster."""
    (tmp_path / "units.md").write_text(
        "# Units\n\n- **Aurelion Sol** — AP caster\n", encoding="utf-8"
    )
    snippets = RepositoryContextProvider(tmp_path).select("Asol")

    assert any("**Aurelion Sol**" in snippet.content for snippet in snippets)


def test_context_selection_routes_artifacts_to_the_catalogue() -> None:
    """Route exact Artifact questions to the retained item reference."""
    snippets = select_context_snippets(
        discover_context_files(),
        "What does Zhonya's Paradox Artifact do?",
        set_number=18,
    )

    assert snippets
    assert all(snippet.content for snippet in snippets)


def test_context_selection_returns_nothing_for_unrelated_task_or_set() -> None:
    context_files = discover_context_files()

    assert select_context_snippets(context_files, "Hello, how are you?", set_number=18) == []
    assert (
        select_context_snippets(
            context_files,
            "What role does Karma play?",
            set_number=16,
        )
        == []
    )


def test_provider_selects_from_one_normalized_query() -> None:
    snippets = select_context_snippets(
        discover_context_files(),
        "What role does Karma play?",
        set_number=18,
    )

    assert any("Karma" in snippet.content for snippet in snippets)
    assert DEFAULT_CONTEXT_PROVIDER.select("Hello, how are you?", set_number=18) == []


def test_provider_selects_and_renders_multiple_context_files(tmp_path: Path) -> None:
    (tmp_path / "units.md").write_text(
        "# Units\n\n- **Riven** — adaptive bruiser\n",
        encoding="utf-8",
    )
    (tmp_path / "traits.md").write_text(
        "# Traits\n\n- **Space Groove** — a ramp trait\n",
        encoding="utf-8",
    )
    provider = RepositoryContextProvider(tmp_path)

    selected = provider.select("Riven Space Groove")

    assert len(selected) == 2
    rendered = provider.render(selected)
    assert "Riven" in rendered
    assert "Space Groove" in rendered
    assert provider.select_and_render("Riven Space Groove") == rendered


def test_context_provider_async_selection_uses_async_selector(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "units.md").write_text(
        "# Units\n\n- **Riven** — adaptive bruiser\n",
        encoding="utf-8",
    )
    provider = RepositoryContextProvider(tmp_path)

    monkeypatch.setattr(
        "domain.providers.context.load_config",
        lambda: SimpleNamespace(
            secrets=SimpleNamespace(openai_api_key="configured")
        ),
    )
    monkeypatch.setattr(
        "domain.providers.context._selector_agent",
        lambda: SimpleNamespace(name=AssistantName.CONTEXT_SELECTOR),
    )

    async def fake_run(agent, prompt, *, max_turns):
        assert agent.name == AssistantName.CONTEXT_SELECTOR
        assert '"query": "What role does Riven play?"' in prompt
        assert max_turns == 1
        return SimpleNamespace(final_output='{"selected_ids": [0]}')

    monkeypatch.setattr("domain.providers.context.Runner.run", fake_run)

    selected = asyncio.run(provider.aselect("What role does Riven play?"))

    assert [snippet.content for snippet in selected] == [
        "# Units\n\n- **Riven** — adaptive bruiser\n"
    ]


def test_context_provider_exposes_common_provider_lifecycle(tmp_path: Path) -> None:
    path = tmp_path / "facts.md"
    path.write_text("# Facts\n\nA fact about Riven.\n", encoding="utf-8")
    provider = RepositoryContextProvider(tmp_path)

    loaded = provider.load(path)

    assert loaded == provider.discover()[0]
    assert provider.select_and_render("Riven")


def test_context_file_is_the_canonical_context_model_name(tmp_path: Path) -> None:
    path = tmp_path / "facts.md"
    path.write_text("# Facts\n\nA fact about Riven.\n", encoding="utf-8")

    context_file = discover_context_files(tmp_path)[0]

    assert isinstance(context_file, ContextFile)


def test_context_selection_enforces_prompt_budget(tmp_path: Path) -> None:
    path = tmp_path / "facts.md"
    path.write_text(
        """# Facts

- **Alpha** — first relevant fact
- **Beta** — second relevant fact
""",
        encoding="utf-8",
    )
    context_file = load_context_file(path, relative_to=tmp_path)

    snippets = select_context_snippets(
        [context_file],
        "Compare Alpha and Beta",
        max_snippets=1,
        max_chars=1_000,
    )

    assert len(snippets) == 1
    assert snippets[0].content == (
        "# Facts\n\n- **Alpha** — first relevant fact\n"
        "- **Beta** — second relevant fact\n"
    )


def test_set18_context_is_retrievable_only_for_supported_set() -> None:
    """Keep the new factual corpus usable under the existing set filter."""
    context_files = discover_context_files()
    snippets = select_context_snippets(
        context_files,
        "Cinderling Blossom Wisps Guinsoo's Rageblade",
        set_number=18,
    )
    rendered = render_context_files(snippets)

    assert snippets
    assert all(not snippet.content.startswith("---\n") for snippet in snippets)
    assert all("set18" in snippet.path for snippet in snippets)
    assert select_context_snippets(context_files, "Cinderling", set_number=16) == []
    assert select_context_snippets(
        context_files, "Hello, how are you?", set_number=18
    ) == []


def test_set18_wisp_selection_preserves_offer_conditions_without_citations() -> None:
    """Ensure a selected Wisp fact retains eligibility without citations."""
    snippets = select_context_snippets(
        discover_context_files(),
        "Major Polymorph Wisp offer conditions",
        set_number=18,
    )
    assert all("https://" not in snippet.content for snippet in snippets)
    assert all("[Source]" not in snippet.content for snippet in snippets)


def test_json_collection_is_returned_in_full(tmp_path: Path) -> None:
    """Retrieve every JSON key, including entries with no lexical query overlap."""
    path = tmp_path / "set18" / "facts.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "string": "  exact string  ",
                "nested": {"items": [1, True]},
                "empty": "",
            }
        ),
        encoding="utf-8",
    )

    provider = RepositoryContextProvider(tmp_path)
    selected = provider.select("string nested empty", set_number=18)

    assert len(selected) == 1
    assert json.loads(selected[0].content) == {
        "string": "  exact string  ", "nested": {"items": [1, True]}, "empty": "",
    }
    assert provider.select("string", set_number=17) == []


def test_json_sources_reject_duplicate_keys_and_non_objects(tmp_path: Path) -> None:
    """Ignore invalid JSON sources without disabling valid context discovery."""
    (tmp_path / "valid.json").write_text('{"valid": "yes"}', encoding="utf-8")
    (tmp_path / "empty.json").write_text("{}", encoding="utf-8")
    (tmp_path / "duplicate.json").write_text('{"x": 1, "x": 2}', encoding="utf-8")
    (tmp_path / "array.json").write_text("[]", encoding="utf-8")

    files = discover_context_files(tmp_path)

    assert [context_file.name for context_file in files] == ["empty.json", "valid.json"]
    assert files[0].json_values == ()


def test_selector_receives_only_complete_file_and_key_options(tmp_path: Path, monkeypatch) -> None:
    """Keep both selector entry points on indivisible source units."""
    body = '# Alpha\n\nFirst paragraph.\n\n## Beta\n\n- second\n- third'
    (tmp_path / 'reference.md').write_text(
        '---\nname: reference\ndescription: Alpha Beta facts\n---\n' + body,
        encoding='utf-8',
    )
    values = {'Alpha': {'nested': ['first', {'deep': 'second'}]}, 'Beta': [1, 2, 3]}
    (tmp_path / 'facts.json').write_text(json.dumps(values), encoding='utf-8')
    provider = RepositoryContextProvider(tmp_path)
    monkeypatch.setattr(
        'domain.providers.context.load_config',
        lambda: SimpleNamespace(secrets=SimpleNamespace(openai_api_key='configured')),
    )
    monkeypatch.setattr('domain.providers.context._selector_agent', lambda: None)

    def select_all(agent, prompt, *, max_turns):
        """Inspect the real selector payload before selecting all complete units."""
        from evals.context_selection.utils import validate_payload

        payload = json.loads(prompt)
        validate_payload(prompt, candidate_count=2)
        parts = payload['parts']
        assert len(parts) == 2
        assert {part['type'] for part in parts} == {'markdown_file', 'json_collection'}
        assert next(part['catalogue']['entries'] for part in parts if part['type'] == 'json_collection') == list(values)
        for part in parts:
            assert not {'summary', 'entities', 'aliases', 'topics', 'key_terms'} & part.keys()
            assert 'content' not in part
        return SimpleNamespace(final_output=json.dumps({
            'selections': [{'need': 'Both facts', 'part_ids': [part['id'] for part in parts]}],
        }))

    async def async_select_all(agent, prompt, *, max_turns):
        """Exercise identical options through the async SDK boundary."""
        return select_all(agent, prompt, max_turns=max_turns)

    monkeypatch.setattr('domain.providers.context.Runner.run_sync', select_all)
    monkeypatch.setattr('domain.providers.context.Runner.run', async_select_all)
    selected = provider.select('Alpha Beta')
    assert len(selected) == 2
    assert asyncio.run(provider.aselect('Alpha Beta')) == selected
    assert 'description: Alpha Beta facts' not in provider.render(selected)


def test_explicit_limits_reject_incomplete_context(tmp_path: Path) -> None:
    """Report a budget failure rather than silently returning an incomplete collection."""
    (tmp_path / 'large.md').write_text('# Alpha\n\n' + 'Alpha ' * 200, encoding='utf-8')
    (tmp_path / 'facts.json').write_text(json.dumps({
        'Alpha large': {'nested': 'Alpha ' * 200}, 'Alpha small': 'complete fact',
    }), encoding='utf-8')
    with pytest.raises(ValueError, match="Complete context requires"):
        select_context_snippets(discover_context_files(tmp_path), 'Alpha', max_chars=100)

def test_markdown_body_preserves_indentation_and_all_sections(tmp_path: Path) -> None:
    """Frontmatter removal must not turn an indented code block into prose."""
    body = "\n    Alpha code\n\n# Other section\n\nUnrelated text stays.\n\n"
    for prefix in ("", "---\nname: reference\n---\n"):
        path = tmp_path / "reference.md"
        path.write_text(prefix + body, encoding="utf-8")
        source = load_context_file(path, relative_to=tmp_path)
        assert source.body == body
        assert select_context_snippets([source], "Alpha")[0].content == body


@pytest.mark.parametrize("query", [
    "Assuming uniform distribution what are the odds of getting an Econ charm on stage2? Assume optimal conditions such as flipping heads, killing all enemy units, etc. assume a team size of 4",
    "List every artifact available to tanks and compare their effects",
    "Which units can appear in a shop and what fraction cost two gold?",
])
def test_every_source_reaches_selector_without_lexical_gate(query: str) -> None:
    """Broad or informal questions must expose the full set-scoped catalogue."""
    from domain.providers.utils import _shortlist_context_candidates

    files = discover_context_files()
    candidates = _shortlist_context_candidates(files, query, set_number=18, max_selected=None)
    assert {candidate.snippet.path for candidate in candidates} == {
        source.path for source in files if source.format != "json" or source.json_values
    }
    assert any(candidate.snippet.path.endswith("wisps-goldxp.md") for candidate in candidates)
    assert _shortlist_context_candidates(files, query, set_number=16, max_selected=None) == []


def test_complete_wisp_pool_survives_selection_sync_and_async(monkeypatch) -> None:
    """Keep all Wisp collections and every variant beyond the former budgets."""
    monkeypatch.setattr(
        "domain.providers.context.load_config",
        lambda: SimpleNamespace(secrets=SimpleNamespace(openai_api_key="configured")),
    )
    monkeypatch.setattr("domain.providers.context._selector_agent", lambda: None)

    def select_wisps(agent, prompt, *, max_turns):
        """Select the entire population, as needed for a probability denominator."""
        payload = json.loads(prompt)
        assert payload["max_selected"] is None
        ids = [part["id"] for part in payload["parts"] if "wisps" in part["source_id"]]
        assert len(ids) > 12
        return SimpleNamespace(final_output={"selections": [{"need": "Complete eligible pool", "part_ids": ids}]})

    # Use the actual structured output type returned by the SDK.
    from domain.assistants.models import ContextSelection

    def run_sync(agent, prompt, *, max_turns):
        """Return a validated source selection without making network calls."""
        result = select_wisps(agent, prompt, max_turns=max_turns)
        result.final_output = ContextSelection.model_validate(result.final_output)
        return result

    async def run_async(agent, prompt, *, max_turns):
        """Mirror the same selection through the tool's asynchronous entry point."""
        return run_sync(agent, prompt, max_turns=max_turns)

    monkeypatch.setattr("domain.providers.context.Runner.run_sync", run_sync)
    monkeypatch.setattr("domain.providers.context.Runner.run", run_async)
    provider = RepositoryContextProvider()
    selected = provider.select("Econ charm stage2 uniform odds", set_number=18)
    assert asyncio.run(provider.aselect("Econ charm stage2 uniform odds", set_number=18)) == selected
    assert len(provider.render(selected)) > 6000
    sources = {source.path: source for source in provider.discover()}
    for path, source in sources.items():
        if "wisps" in path and source.format == "json":
            recovered = {}
            for snippet in selected:
                if snippet.path == path:
                    recovered.update(json.loads(snippet.content))
            assert recovered == dict(source.json_values)
    gold = next(snippet for snippet in selected if snippet.path.endswith("wisps-goldxp.json") and snippet.key == "stage-2")
    assert "Coin Flip (base)" in json.loads(gold.content)
    assert "Barter (base)" not in json.loads(gold.content)


def test_large_documents_cannot_evict_collection_catalogue(tmp_path: Path) -> None:
    """A huge unrelated source must not hide a source needed for an exhaustive query."""
    from domain.providers.utils import _context_selector_prompt, _shortlist_context_candidates

    (tmp_path / "large.md").write_text("# Large\n" + "unrelated " * 10000)
    (tmp_path / "rewards.json").write_text(json.dumps({f"Reward {i}": i for i in range(150)}))
    candidates = _shortlist_context_candidates(
        discover_context_files(tmp_path), "all economic outcomes", set_number=None, max_selected=None,
    )
    assert len(candidates) == 2
    payload = json.loads(_context_selector_prompt("all economic outcomes", candidates, max_selected=None))
    rewards = next(part for part in payload["parts"] if part["type"] == "json_collection")
    assert len(rewards["catalogue"]["entries"]) == 150


def test_json_companions_inherit_category_metadata_without_losing_facts(tmp_path: Path) -> None:
    """Retain semantic routing descriptions and separately preserve divergent companions."""
    (tmp_path / "rewards.md").write_text("---\nname: rewards\ndescription: Economic payouts\nkind: mechanic\n---\n# Rewards\nMarkdown-only fact")
    (tmp_path / "rewards.json").write_text('{"Unique JSON fact": "extra reward"}')
    files = discover_context_files(tmp_path)
    assert len(files) == 2
    assert all(source.description == "Economic payouts" for source in files)
    selected = select_context_snippets(files, "Economic payouts")
    assert len(selected) == 2
    assert "Markdown-only fact" in render_context_files(selected)
    assert "extra reward" in render_context_files(selected)


def test_context_evaluation_measures_coverage_instead_of_compression() -> None:
    """The offline evaluator must use runtime fallback and allow the full catalogue."""
    from evals.context_selection.provider import evaluate

    result = evaluate({
        "name": "complete_goldxp", "query": "GoldXP Wisp reference",
        "required": [{"path": "wisps-goldxp.json", "content": ["Coin Flip", "Truce"]}],
    })
    assert result["offline_passed"]
    assert result["candidate_count"] == result["full_candidate_count"]
    unrelated = evaluate({"name": "greeting", "query": "Hello, how are you?", "expect_empty": True})
    assert unrelated["offline_passed"]
    assert unrelated["selected_count"] == 0


def test_selector_cannot_silently_exceed_explicit_collection_limit(tmp_path: Path, monkeypatch) -> None:
    """An over-limit model result must raise instead of dropping selected sources."""
    (tmp_path / "one.md").write_text("# One\nRelevant alpha")
    (tmp_path / "two.md").write_text("# Two\nRelevant beta")
    monkeypatch.setattr(
        "domain.providers.context.load_config",
        lambda: SimpleNamespace(secrets=SimpleNamespace(openai_api_key="configured")),
    )
    monkeypatch.setattr("domain.providers.context._selector_agent", lambda: None)
    monkeypatch.setattr(
        "domain.providers.context.Runner.run_sync",
        lambda *args, **kwargs: SimpleNamespace(final_output='{"selected_ids": [0, 1]}'),
    )
    with pytest.raises(ValueError, match="explicit context limit"):
        RepositoryContextProvider(tmp_path).select("compare alpha beta", max_snippets=1)


@pytest.mark.parametrize("window, expected", [
    ("2-1–2-7", (2,)),
    ("3-5–4-1", (3, 4)),
    ("6-1–10-1", (6, 7, 8, 9, 10)),
    ("2-1–2-7, 4-2–4-7", (2, 4)),
    ("All bands (no round-band tag)", ("all",)),
    ("2-1–2-7, unknown", ()),
    ("4-7–3-1", ()),
])
def test_wisp_stage_windows_preserve_overlap_and_unknowns(window, expected) -> None:
    """Recognize exact stage intersections without guessing missing eligibility."""
    from domain.providers.utils import wisp_entry_stages

    assert wisp_entry_stages(f"effect; offer windows {window}; Conditions: four units.") == expected


def test_wisp_stage2_chunks_include_every_matching_variant_and_conditions() -> None:
    """Check corpus-wide stage membership, including cross-stage and all-band entries."""
    from domain.providers.utils import _all_context_candidates

    files = discover_context_files()
    candidates = _all_context_candidates(files, set_number=18)
    for source in files:
        if source.format != "json" or "/wisps-" not in source.path:
            continue
        chunks = [c for c in candidates if c.snippet.path == source.path]
        assert chunks and all(c.snippet.key for c in chunks)
        stage2 = next(c for c in chunks if c.snippet.key == "stage-2")
        expected = {k: v for k, v in source.json_values if "2-1–2-7" in v}
        assert json.loads(stage2.snippet.content) == expected
        for chunk in chunks:
            assert all(dict(source.json_values)[k] == v for k, v in json.loads(chunk.snippet.content).items())
    gold_all = next(c for c in candidates if c.snippet.path.endswith("wisps-goldxp.json") and c.snippet.key == "stage-all")
    assert list(json.loads(gold_all.snippet.content)) == ["Truce (prismatic)"]
    general = [c for c in candidates if c.snippet.path.endswith("/wisps.json")]
    assert len(general) == 1 and general[0].snippet.key is None


def test_unrecognized_wisp_window_preserves_original_collection(tmp_path: Path) -> None:
    """New or malformed eligibility syntax must not silently drop any entries."""
    from domain.providers.utils import _all_context_candidates

    values = {"Known": "offer windows 2-1–2-7;", "Unknown": "offer windows special;"}
    (tmp_path / "wisps-goldxp.json").write_text(json.dumps(values))
    candidates = _all_context_candidates(discover_context_files(tmp_path), set_number=None)
    assert len(candidates) == 1
    assert candidates[0].snippet.key is None
    assert json.loads(candidates[0].snippet.content) == values


def test_wisp_stage_markdown_preserves_introduction_and_entry_text(tmp_path: Path) -> None:
    """Keep complete conditions and continuation lines when forming a stage chunk."""
    from domain.providers.utils import _all_context_candidates

    intro = "# GoldXP\n\nShared rules.\n\n"
    early = "- **Early** — offer windows 2-1–2-7; Conditions: four units.\n  Extra condition.\n"
    crossing = "- **Crossing** — offer windows 3-5–4-1; Modes: Standard.\n"
    (tmp_path / "wisps-goldxp.md").write_text(intro + early + crossing)
    chunks = _all_context_candidates(discover_context_files(tmp_path), set_number=None)
    assert {c.snippet.key for c in chunks} == {"stage-2", "stage-3", "stage-4"}
    assert next(c.snippet.content for c in chunks if c.snippet.key == "stage-2") == intro + early
    assert next(c.snippet.content for c in chunks if c.snippet.key == "stage-4") == intro + crossing
