"""Regression coverage for selector diagnostics preserved by evaluation runners."""
from __future__ import annotations
import logging
from evals.skill_selection import provider as skill_selection


def test_skill_selection_reports_unavailable_case_skills(monkeypatch, caplog) -> None:
    """Keep removed expectations visible while preserving existing normalization."""
    known = skill_selection.SkillDefinition(name="known-skill", description="Analyze known skill requests.",
        body="Known skill instructions.", path="known-skill/SKILL.md")
    monkeypatch.setattr(skill_selection, "_discover_skills", lambda: [known])
    case = {"name": "partially-available", "query": "Analyze known skill", "required": ["known-skill", "missing-required"],
            "forbidden": ["missing-forbidden"], "max_skills": 1, "exact": True}
    with caplog.at_level(logging.WARNING, logger="evals.skill_selection.utils"):
        result = skill_selection.evaluate(case)
    assert result["offline_passed"]
    assert result["required_count"] == 1
    assert result["forbidden_hits"] == 0
    assert result["ignored_skills"] == ["missing-forbidden", "missing-required"]
    assert "missing-required" in caplog.text
    assert "missing-forbidden" in caplog.text
