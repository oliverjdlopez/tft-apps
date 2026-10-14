import asyncio
from pathlib import Path
from types import SimpleNamespace

from domain.providers.skills import (
    SKILLS_DIR,
    SkillDefinition,
    select_skills,
)


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








def test_skill_discovery_validates_name_and_preserves_complete_body(tmp_path):
    """Discovery reads portable skill metadata without selecting workflows."""
    from domain.providers.utils import discover_skills
    _write_skill(tmp_path, 'workflow', name='workflow', description='Use for comparisons.')
    skills = discover_skills(tmp_path, relative_to=tmp_path)
    assert len(skills) == 1
    assert skills[0].description == 'Use for comparisons.'
    assert 'Follow this focused workflow.' in skills[0].body
    _write_skill(tmp_path, 'invalid', name='different-name', description='Invalid identity.')
    assert len(discover_skills(tmp_path, relative_to=tmp_path)) == 1
