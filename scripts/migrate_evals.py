"""Export authored Langfuse definitions read-only and restore into the suite instance."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import os
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "tft-chat"
sys.path[:0] = [str(CHAT), str(CHAT / "app/backend/src")]

if sys.prefix != str(CHAT / ".venv"):
    os.execv(str(CHAT / ".venv/bin/python"), [str(CHAT / ".venv/bin/python"), __file__, *sys.argv[1:]])

from dotenv import dotenv_values
from evals.langfuse.native import NativeWorkspace
from evals.langfuse.workspace import Workspace
from evals.langfuse.utils import canonical_json

EXPORT = ROOT / ".migration/langfuse-content.json"


def connection(source: bool = False) -> tuple[Workspace, NativeWorkspace]:
    """Create content transports for the fixed source or fixed destination service.

    Args:
        source: Select read-only original port 15500; otherwise destination 15510.

    Returns:
        Authenticated public and native clients with separate platform credentials.
    """
    app = Path("/home/oliverjdlopez/tft-chat") if source else CHAT
    values = dotenv_values(app / "evals/langfuse/.env")
    url = "http://localhost:15500" if source else "http://localhost:15510"
    public = Workspace(url, values["LANGFUSE_PUBLIC_KEY"], values["LANGFUSE_SECRET_KEY"])
    native = NativeWorkspace(url, values["LANGFUSE_INIT_USER_EMAIL"],
        values["LANGFUSE_INIT_USER_PASSWORD"], "chattft-evals" if source else "tft-apps-evals")
    return public, native


def capture(public: Workspace, native: NativeWorkspace) -> dict:
    """Read only authored datasets, archived cases and required grading resources.

    Args:
        public: Content transport used exclusively for GET requests.
        native: Authenticated read transport needed to include archived items.

    Returns:
        Portable definitions, excluding runs, traces, observations and scores.
    """
    result = {"schema_version": 1, "datasets": [], "prompts": [],
              "evaluators": [], "rules": [], "unavailable": []}
    for dataset in public.list("v2/datasets"):
        details = public.request("GET", "v2/datasets/" + quote(dataset["name"], safe=""))
        details["items"] = native.items(dataset["id"])
        # Native items can contain execution history; retain authored case fields only.
        details["items"] = [{key: item.get(key) for key in
            ("id", "input", "expectedOutput", "metadata", "status")} for item in details["items"]]
        result["datasets"].append(details)
    for prompt in public.list("v2/prompts"):
        for version in sorted(prompt["versions"]):
            result["prompts"].append(public.request("GET", "v2/prompts/" + quote(prompt["name"], safe=""), params={"version": version}))
    for key, endpoint in [("evaluators", "v2/evaluators"), ("rules", "v2/evaluation-rules"),
                          ("score_configs", "score-configs"), ("llm_connections", "llm-connections")]:
        try:
            result[key] = public.list(endpoint, cursor=key in {"evaluators", "rules"})
            if key == "evaluators":
                for evaluator in result[key]:
                    evaluator["versions"] = public.list(f"v2/evaluators/{evaluator['id']}/versions", cursor=True)
        except Exception as error:
            result["unavailable"].append({"resource": key, "reason": type(error).__name__})
    return result


def export_content() -> None:
    """Save a private immutable source export without changing original content."""
    if EXPORT.exists():
        raise FileExistsError("Export already exists; use verify or select a new audit directory")
    public, native = connection(source=True)
    try:
        content = capture(public, native)
    finally:
        native.close()
        public.close()
    content["exported_at"] = datetime.now(timezone.utc).isoformat()
    EXPORT.parent.mkdir(parents=True, exist_ok=True)
    EXPORT.write_bytes(canonical_json(content))
    EXPORT.chmod(0o600)
    print(json.dumps({"datasets": len(content["datasets"]),
        "cases": sum(len(dataset["items"]) for dataset in content["datasets"]),
        "archived": sum(item["status"] == "ARCHIVED" for dataset in content["datasets"] for item in dataset["items"]),
        "prompts": len(content["prompts"]), "unavailable": content["unavailable"],
        "sha256": hashlib.sha256(EXPORT.read_bytes()).hexdigest()}))


def authored(value: dict, keys: tuple[str, ...]) -> dict:
    """Select semantically authored fields, ignoring platform-generated identities."""
    return {key: value.get(key) for key in keys}


def verify_cases(content: dict, public: Workspace, native: NativeWorkspace) -> dict:
    """Compare destination case content and archived status with the immutable export."""
    total = 0
    for dataset in content["datasets"]:
        target = public.request("GET", "v2/datasets/" + quote(dataset["name"], safe=""))
        keys = ("name", "description", "metadata", "inputSchema", "expectedOutputSchema")
        if authored(target, keys) != authored(dataset, keys):
            raise ValueError(f"Dataset definitions differ: {dataset['name']}")
        actual = {item["id"]: item for item in native.items(target["id"])}
        if len(actual) != len(dataset["items"]):
            raise ValueError(f"Case count differs: {dataset['name']}")
        for item in dataset["items"]:
            identity = str(uuid5(NAMESPACE_URL, "tft-apps:" + item["id"]))
            keys = ("input", "expectedOutput", "metadata", "status")
            if identity not in actual or authored(actual[identity], keys) != authored(item, keys):
                raise ValueError(f"Case content differs: {dataset['name']} {item['id']}")
        total += len(actual)
    return {"datasets": len(content["datasets"]), "cases": total}


def import_content() -> None:
    """Restore content only into localhost:15510, with stable case IDs for repeatability."""
    content = json.loads(EXPORT.read_bytes())
    if content["unavailable"]:
        raise ValueError(f"Source definitions unavailable: {content['unavailable']}")
    public, native = connection()
    mapping = {"datasets": {}, "evaluators": {}}
    try:
        existing = {dataset["name"]: dataset for dataset in public.list("v2/datasets")}
        for dataset in content["datasets"]:
            payload = authored(dataset, ("name", "description", "metadata", "inputSchema", "expectedOutputSchema"))
            # Optional null schemas are omitted on create but remain null on readback.
            payload = {key: value for key, value in payload.items() if value is not None}
            target = existing.get(dataset["name"]) or public.request("POST", "v2/datasets", json=payload)
            mapping["datasets"][dataset["id"]] = target["id"]
            current = {item["id"]: item for item in native.items(target["id"])}
            for item in dataset["items"]:
                identity = str(uuid5(NAMESPACE_URL, "tft-apps:" + item["id"]))
                if identity in current:
                    keys = ("input", "expectedOutput", "metadata", "status")
                    if authored(current[identity], keys) != authored(item, keys):
                        raise ValueError("Existing destination case changed; refusing to overwrite")
                    continue
                payload = {**authored(item, ("input", "metadata", "status")),
                           "id": identity, "datasetName": dataset["name"]}
                if item.get("expectedOutput") is not None:
                    payload["expectedOutput"] = item["expectedOutput"]
                public.request("POST", "dataset-items", json=payload)
        for prompt in sorted(content["prompts"], key=lambda value: (value["name"], value["version"])):
            endpoint = "v2/prompts/" + quote(prompt["name"], safe="")
            response = public.http.get("/api/public/" + endpoint, params={"version": prompt["version"]})
            keys = ("name", "type", "prompt", "config", "tags")
            if response.status_code == 200:
                if authored(response.json(), keys) != authored(prompt, keys):
                    raise ValueError("Existing destination prompt version differs")
                continue
            if response.status_code != 404:
                response.raise_for_status()
            public.request("POST", "v2/prompts", json={**authored(prompt, keys), "labels": prompt.get("labels", [])})
        evaluators = {row["name"]: row for row in public.list("v2/evaluators", cursor=True)}
        for evaluator in content["evaluators"]:
            keys = ("name", "description", "type", "prompt", "variableMapping", "modelConfig", "outputDefinition")
            payload = authored(evaluator, keys)
            target = evaluators.get(evaluator["name"])
            if target is None:
                target = public.request("POST", "v2/evaluators", json=payload)
            elif authored(target, keys) != payload:
                raise ValueError("Existing evaluator differs; refusing to overwrite")
            # Creation before runner setup can pause a judge with no provider
            # connection. Reapplying the identical definition after setup clears
            # only that known condition and never invokes a model.
            if evaluator.get("status") == "active" and target.get("status") == "paused" and target.get("pausedReason") == "LLM_CONNECTION_MISSING":
                providers = {row["provider"] for row in public.list("llm-connections")}
                if evaluator["modelConfig"]["provider"] in providers:
                    target = public.request("PATCH", "v2/evaluators/" + target["id"], json=payload)
            mapping["evaluators"][evaluator["id"]] = target["id"]
        rules = {row["name"]: row for row in public.list("v2/evaluation-rules", cursor=True)}
        for rule in content["rules"]:
            payload = authored(rule, ("name", "enabled", "sampling", "filter", "evaluatorAssignments"))
            for condition in payload["filter"]:
                if condition["column"] == "datasetId":
                    condition["value"] = [mapping["datasets"][identity] for identity in condition["value"]]
            for assignment in payload["evaluatorAssignments"]:
                assignment["evaluatorId"] = mapping["evaluators"][assignment["evaluatorId"]]
            current = rules.get(rule["name"])
            if current is None:
                public.request("POST", "v2/evaluation-rules", json=payload)
            elif authored(current, tuple(payload)) != payload:
                raise ValueError("Existing evaluation rule differs; refusing to overwrite")
        configurations = {row["name"]: row for row in public.list("score-configs")}
        for configuration in content.get("score_configs", []):
            payload = {key: value for key, value in authored(configuration,
                ("name", "dataType", "minValue", "maxValue", "categories", "description")).items() if value is not None}
            if configuration["dataType"] != "CATEGORICAL":
                payload.pop("categories", None)
            if configuration["dataType"] != "NUMERIC":
                payload.pop("minValue", None)
                payload.pop("maxValue", None)
            if configuration["name"] not in configurations:
                public.request("POST", "score-configs", json=payload)
        result = verify_cases(content, public, native)
        (ROOT / ".migration/langfuse-mapping.json").write_bytes(canonical_json(mapping))
        (ROOT / ".migration/langfuse-verification.json").write_bytes(canonical_json(result))
        print(json.dumps(result))
    finally:
        native.close()
        public.close()


def verify_definitions(content: dict, public: Workspace) -> dict:
    """Verify required evaluator, rule and prompt content without running models."""
    mapping = json.loads((ROOT / ".migration/langfuse-mapping.json").read_text())
    evaluators = {row["name"]: row for row in public.list("v2/evaluators", cursor=True)}
    for original in content["evaluators"]:
        keys = ("name", "description", "type", "prompt", "variableMapping", "modelConfig", "outputDefinition", "status")
        if authored(evaluators[original["name"]], keys) != authored(original, keys):
            raise ValueError("Imported evaluator definition differs")
    rules = {row["name"]: row for row in public.list("v2/evaluation-rules", cursor=True)}
    for original in content["rules"]:
        payload = authored(original, ("name", "enabled", "sampling", "filter", "evaluatorAssignments"))
        for condition in payload["filter"]:
            if condition["column"] == "datasetId":
                condition["value"] = [mapping["datasets"][identity] for identity in condition["value"]]
        for assignment in payload["evaluatorAssignments"]:
            assignment["evaluatorId"] = mapping["evaluators"][assignment["evaluatorId"]]
        if authored(rules[original["name"]], tuple(payload)) != payload:
            raise ValueError("Imported evaluation rule differs")
    for original in content["prompts"]:
        target = public.request("GET", "v2/prompts/" + quote(original["name"], safe=""), params={"version": original["version"]})
        keys = ("name", "type", "prompt", "config", "tags", "labels")
        if authored(target, keys) != authored(original, keys):
            raise ValueError("Imported prompt content or labels differ")
    return {"evaluators": len(content["evaluators"]), "rules": len(content["rules"]), "prompt_versions": len(content["prompts"])}


def main() -> None:
    """Dispatch explicit export, import or verification without running evaluations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["export", "import", "verify"])
    args = parser.parse_args()
    if args.command == "export":
        export_content()
    elif args.command == "import":
        import_content()
    else:
        public, native = connection()
        try:
            content = json.loads(EXPORT.read_bytes())
            print(json.dumps({**verify_cases(content, public, native), **verify_definitions(content, public)}))
        finally:
            native.close()
            public.close()


if __name__ == "__main__":
    main()
