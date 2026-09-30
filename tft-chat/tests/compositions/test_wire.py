"""Cross-language fixture acceptance and configurable route protection."""

import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from services.compositions import models as wire
from domain.compositions import models as domain
from api.routes import compositions
from core.config import ChatConfig, load_config

CASES = json.loads((Path(__file__).parent / "fixtures/contracts.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_shared_wire_cases(case):
    """Require Pydantic to accept exactly the same JSON fixtures as frontend Zod."""
    model = getattr(wire, case["schema"], None) or getattr(domain, case["schema"])
    if case["valid"]:
        model.model_validate_json(json.dumps(case["value"]))
    else:
        with pytest.raises(ValidationError):
            model.model_validate_json(json.dumps(case["value"]))


def test_json_schema_export_is_current():
    """Keep exported schemas authoritative for response_model contract checks."""
    schemas = json.loads((Path(__file__).parent / "fixtures/schemas.json").read_text())
    for name, schema in schemas.items():
        model = getattr(wire, name, None) or getattr(domain, name)
        assert model.model_json_schema() == schema


def test_gate_blocks_all_private_operations(monkeypatch):
    """Disabled installations cannot invoke fixtures, persistence, or algorithms."""
    monkeypatch.setattr(
        compositions,
        "load_config",
        lambda: SimpleNamespace(chat=SimpleNamespace(composition_workbench=False)),
    )
    app = FastAPI()
    app.include_router(compositions.router)
    client = TestClient(app)
    for path in (
        "fixtures",
        "fixtures/fixture-jinx",
        "algorithms",
        "experiments",
        "experiments/missing",
        "compare?left=a&right=b",
    ):
        assert client.get(f"/api/developer/compositions/{path}").status_code == 404
    assert (
        client.post(
            "/api/developer/compositions/experiments",
            json={"algorithm_id": "hierarchical"},
        ).status_code
        == 404
    )
    monkeypatch.setattr(
        compositions,
        "load_config",
        lambda: SimpleNamespace(chat=SimpleNamespace(composition_workbench=True)),
    )
    response = client.get("/api/developer/compositions/fixtures/fixture-jinx")
    assert response.status_code == 200
    assert wire.CompositionDetailResponse.model_validate(response.json())
    assert app.openapi()["paths"]["/api/developer/compositions/fixtures"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "CompositionListResponse"
    )


def test_algorithm_catalog_is_singleton_and_removed_requests_are_rejected():
    """Expose only HDBSCAN parameters and reject retired IDs at the API boundary."""
    catalog = compositions.algorithms()
    assert [algorithm.algorithm_id for algorithm in catalog.algorithms] == ["hdbscan"]
    request = wire.ExperimentRequest(algorithm_id="hierarchical")
    with pytest.raises(HTTPException) as error:
        compositions.create_experiment(request)
    assert getattr(error.value, "status_code", None) == 422


def test_setting_defaults_and_overrides(tmp_path):
    """Enable the workbench by default while requiring an offline opt-in."""
    assert ChatConfig().composition_workbench
    assert not ChatConfig().composition_offline
    path = tmp_path / "chat_tft.ini"
    path.write_text("[chat]\n")
    assert load_config(path).chat.composition_workbench
    assert not load_config(path).chat.composition_offline
    path.write_text("[chat]\ncomposition_workbench = false\ncomposition_offline = false\n")
    assert not load_config(path).chat.composition_workbench
    assert not load_config(path).chat.composition_offline
    path.write_text("[chat]\ncomposition_workbench = true\ncomposition_offline = true\n")
    assert load_config(path).chat.composition_workbench
    assert load_config(path).chat.composition_offline
