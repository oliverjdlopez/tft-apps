"""Export Pydantic wire schemas and shared valid/invalid JSON contract fixtures."""

import copy
import json
from pathlib import Path
from services.compositions.fixtures import fixture_detail, fixture_list
from services.compositions.models import (
    CompositionDetailResponse,
    CompositionListResponse,
)
from domain.compositions.models import BoardAssignment, MatchScore, OutcomeSummary


def export_contracts(destination: Path):
    """Write reproducible schemas and adversarial cases consumed by Python and Zod."""
    detail = fixture_detail().model_dump(mode="json")
    detail["examples"] = detail["examples"][:1]
    cases = [
        {
            "name": "detail",
            "schema": "CompositionDetailResponse",
            "valid": True,
            "value": detail,
        },
        {
            "name": "list",
            "schema": "CompositionListResponse",
            "valid": True,
            "value": fixture_list().model_dump(mode="json"),
        },
    ]
    for key in ("schema_version", "context", "profile", "warnings"):
        missing = copy.deepcopy(detail)
        del missing[key]
        cases.append(
            {
                "name": f"missing-{key}",
                "schema": "CompositionDetailResponse",
                "valid": False,
                "value": missing,
            }
        )
    paths = [
        (),
        ("context",),
        ("family",),
        ("family", "defining_patterns", 0),
        ("family", "defining_patterns", 0, "units", 0),
        ("profile",),
        ("profile", "outcomes"),
        ("examples", 0),
        ("examples", 0, "board"),
        ("examples", 0, "board", "units", 0),
        ("examples", 0, "board", "units", 0, "unit"),
        ("examples", 0, "board", "units", 0, "items", 0),
        ("examples", 0, "board", "traits", 0),
        ("examples", 0, "assignment"),
        ("examples", 0, "outcome"),
    ]
    for path in paths:
        value = copy.deepcopy(detail)
        target = value
        for key in path:
            target = target[key]
        target["unexpected"] = "must reject"
        cases.append(
            {
                "name": f"unknown-{path}",
                "schema": "CompositionDetailResponse",
                "valid": False,
                "value": value,
            }
        )
    changes = [
        (("examples", 0, "board", "units", 1, "occurrence_index"), 0),
        (("examples", 0, "board", "units", 0, "items", 1, "slot"), 0),
        (("examples", 0, "board", "units", 0, "items", 1, "slot"), 3),
        (("examples", 0, "board", "traits", 0, "tier_current"), -1),
        (("examples", 0, "board", "units", 0, "star_level"), 0),
        (("examples", 0, "assignment", "family_id"), None),
        (("profile", "play_share"), 0),
        (("profile", "outcomes", "observed_boards"), 999),
        (("profile", "outcomes", "state"), "suppressed"),
        (("profile", "outcomes", "top4_rate"), 1.2),
        (("profile", "joint_patterns", 0, "matching_boards"), 999),
    ]
    for path, replacement in changes:
        value = copy.deepcopy(detail)
        target = value
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = replacement
        cases.append(
            {
                "name": f"invalid-{path}",
                "schema": "CompositionDetailResponse",
                "valid": False,
                "value": value,
            }
        )
    for state in ("empty", "suppressed", "unavailable"):
        value = OutcomeSummary(
            state=state,
            observed_boards=0,
            placement_counts=None,
            avg_placement=None,
            top4_rate=None,
            win_rate=None,
        ).model_dump(mode="json")
        cases.append(
            {"name": state, "schema": "OutcomeSummary", "valid": True, "value": value}
        )
    for probability in (-0.1, 0.5, 1.1):
        cases.append(
            {
                "name": f"probability-{probability}",
                "schema": "MatchScore",
                "valid": 0 <= probability <= 1,
                "value": {
                    "name": "responsibility",
                    "value": probability,
                    "kind": "model_probability",
                    "higher_is_better": True,
                },
            }
        )
    schemas = {
        model.__name__: model.model_json_schema()
        for model in (
            CompositionDetailResponse,
            CompositionListResponse,
            OutcomeSummary,
            MatchScore,
        )
    }
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "contracts.json").write_text(json.dumps(cases, indent=2) + "\n")
    (destination / "schemas.json").write_text(
        json.dumps(schemas, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    export_contracts(Path("tests/compositions/fixtures"))
