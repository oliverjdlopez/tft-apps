import asyncio
from pathlib import Path
from types import SimpleNamespace

from domain.providers.skills import (
    RepositorySkillProvider,
    SKILLS_DIR,
    SkillDefinition,
    select_skills,
)
from domain.assistants.constants import AssistantName


def test_skill_resources_are_raw_markdown_files() -> None:
    assert SKILLS_DIR.parent.name == "resources"
    files = [path for path in SKILLS_DIR.rglob("*") if path.is_file()]
    assert files
    assert all(path.suffix == ".md" for path in files)


def _write_skill(
    root: Path,
    directory: str,
    *,
    name: str,
    description: str,
) -> None:
    skill_dir = root / directory
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                "---",
                "",
                f"# {name}",
                "",
                "Follow this focused workflow.",
            ]
        ),
        encoding="utf-8",
    )


def test_repository_skill_provider_discovers_and_selects_for_task(
    tmp_path: Path,
) -> None:
    _write_skill(
        tmp_path,
        "cohort-comparison",
        name="cohort-comparison",
        description="Compare two board cohorts. Use for versus and delta questions.",
    )
    _write_skill(
        tmp_path,
        "meta-analysis",
        name="meta-analysis",
        description="Rank the current meta. Use for strongest composition questions.",
    )
    provider = RepositorySkillProvider(tmp_path)

    skills = provider.discover()
    selected = provider.select("Compare these board variants")

    assert [skill.name for skill in skills] == ["cohort-comparison", "meta-analysis"]
    assert skills[0].path == "cohort-comparison/SKILL.md"
    assert [skill.name for skill in selected] == ["cohort-comparison"]


def test_repository_skill_provider_honors_explicit_selection(tmp_path: Path) -> None:
    _write_skill(
        tmp_path,
        "meta-analysis",
        name="meta-analysis",
        description="Rank the current meta. Use for ranking questions.",
    )
    provider = RepositorySkillProvider(tmp_path)

    selected = provider.select("/skill meta-analysis tell me something else")

    assert [skill.name for skill in selected] == ["meta-analysis"]


def test_repository_skill_provider_filters_candidates_by_allowlist(
    tmp_path: Path,
) -> None:
    """Selection cannot return an explicit skill outside the caller's allowlist."""
    _write_skill(
        tmp_path,
        "allowed",
        name="allowed",
        description="Allowed workflow.",
    )
    _write_skill(
        tmp_path,
        "denied",
        name="denied",
        description="Denied workflow.",
    )
    provider = RepositorySkillProvider(tmp_path)

    assert provider.select("/skill denied", allowed_names=("allowed",)) == []
    assert [
        skill.name
        for skill in provider.select("/skill allowed", allowed_names=("allowed",))
    ] == ["allowed"]


def test_skill_selection_returns_best_matches_or_empty() -> None:
    skills = [
        SkillDefinition(
            name="first",
            description="Analyze item builds.",
            body="First workflow.",
            path="first/SKILL.md",
        ),
        SkillDefinition(
            name="second",
            description="Analyze item holders.",
            body="Second workflow.",
            path="second/SKILL.md",
        ),
    ]

    assert [
        skill.name for skill in select_skills(skills, "Analyze this item", max_skills=1)
    ] == ["first"]
    assert select_skills(skills, "Hello there") == []
    assert select_skills(skills, "/skill missing") == []


def test_provider_selects_and_renders_multiple_skills(
    tmp_path: Path, monkeypatch
) -> None:
    _write_skill(
        tmp_path,
        "comparison",
        name="comparison",
        description="Compare board variants. Use for comparison questions.",
    )
    _write_skill(
        tmp_path,
        "item-analysis",
        name="item-analysis",
        description="Analyze item choices. Use for item questions.",
    )
    monkeypatch.setattr(
        "domain.providers.skills.load_config",
        lambda: SimpleNamespace(secrets=SimpleNamespace(openai_api_key="")),
    )
    provider = RepositorySkillProvider(tmp_path)

    selected = provider.select("Compare item choices", max_skills=2)

    assert {skill.name for skill in selected} == {"item-analysis", "comparison"}
    rendered = provider.render(selected)
    assert "Follow this focused workflow." in rendered
    assert rendered.count("<skill_instructions>") == 2
    assert provider.select_and_render("Compare item choices", max_skills=2) == rendered


def test_skill_provider_async_selection_uses_async_selector(
    tmp_path: Path, monkeypatch
) -> None:
    _write_skill(
        tmp_path,
        "comparison",
        name="comparison",
        description="Compare board variants. Use for comparison questions.",
    )
    provider = RepositorySkillProvider(tmp_path)

    monkeypatch.setattr(
        "domain.providers.skills.load_config",
        lambda: SimpleNamespace(
            secrets=SimpleNamespace(openai_api_key="configured")
        ),
    )
    monkeypatch.setattr(
        "domain.providers.skills._selector_agent",
        lambda: SimpleNamespace(name=AssistantName.SKILL_SELECTOR),
    )

    async def fake_run(agent, prompt, *, max_turns):
        assert agent.name == AssistantName.SKILL_SELECTOR
        assert '"query": "Compare board variants"' in prompt
        assert max_turns == 1
        return SimpleNamespace(final_output='{"selected_ids": [0]}')

    monkeypatch.setattr("domain.providers.skills.Runner.run", fake_run)

    selected = asyncio.run(provider.aselect("Compare board variants"))

    assert [skill.name for skill in selected] == ["comparison"]


def test_skill_provider_exposes_common_provider_lifecycle(tmp_path: Path) -> None:
    _write_skill(
        tmp_path,
        "comparison",
        name="comparison",
        description="Compare board variants. Use for comparison questions.",
    )
    provider = RepositorySkillProvider(tmp_path)
    path = tmp_path / "comparison" / "SKILL.md"

    loaded = provider.load(path)

    assert loaded == provider.discover()[0]
    assert provider.select_and_render("Compare board variants")
