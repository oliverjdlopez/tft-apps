"""Render coordinator-authored case translations inside the brainstorming run.

This script reads the preserved research collection and the authored translation
files. It never invokes runtime tools or writes application/evaluation state.
"""

from pathlib import Path
import hashlib
import json
import re


ROOT = Path(__file__).resolve().parents[3]
RUN = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "eval-brainstormings/2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes"


def build() -> None:
    """Join every original case with its authored tool-level reconciliation.

    Writes human-readable and machine-readable lane handoffs plus lineage into
    this run, retaining original questions and their stable identifiers.
    """
    translations = {}
    for path in sorted((RUN / "translations").glob("*.json")):
        translations.update(json.loads(path.read_text()))
    index = json.loads((SOURCE / "case-index.json").read_text())
    manifest = []
    lineage = []
    for lane in index["lanes"]:
        original_path = SOURCE / lane["case_file"]
        source_text = original_path.read_text()
        sections = {part.split(" — ")[0].split("\n")[0]: part for part in re.split(r"\n## ", source_text)[1:]}
        source_cases = json.loads((SOURCE / lane["case_index"]).read_text())["cases"]
        directory = RUN / "lanes" / lane["id"].lower()
        directory.mkdir(parents=True, exist_ok=True)
        cases = []
        for original in source_cases:
            case_id = original["id"]
            authored = translations.pop(case_id)
            case = {
                "id": case_id, "title": original["title"], "lane": lane["id"],
                "subject": lane["subject"], "original_question": original["question"],
                "question": authored.pop("question", original["question"]),
                "source_case_file": str(original_path.relative_to(ROOT)),
                "source_status": original["status"],
                "source_answer_status": original.get("answer_status"),
                "proposal_lineage": original.get("proposal_lineage", []),
                "benchmark_type": "evidence_relative_investigation",
                "data_readiness": "not_measured_scope_and_samples_require_preflight",
                **authored,
            }
            cases.append(case)
            lineage.append({"id": case_id, "source_index_entry": original,
                            "source_case_file": case["source_case_file"],
                            "source_case_sha256": hashlib.sha256(sections[case_id].encode()).hexdigest()})
        (directory / "reconciled-cases.json").write_text(json.dumps({"lane": lane["id"], "title": lane["title"], "cases": cases}, indent=2, ensure_ascii=False) + "\n")
        text = [f"# {lane['id']} — {lane['title']}", "",
                "Coordinator reconciliation. Read [the common capability contract](../../docs/capabilities.md) with these cases. No outcome winner or exact stored identifier has been assumed. The original source remains the provenance for motivation and historical observations; its web numbers are not gold for ChatTFT.", ""]
        for case in cases:
            text.extend([f"## {case['id']} — {case['title']}", "", "### Question", "", case["question"], "",
                         "### Concrete analytical scenario", "", case["scenario"], "",
                         "### Reference requirements translated to ChatTFT", "", case["plan"], "",
                         "### Metrics and acceptance checks", "", case["checks"], "",
                         "### Capability limits and preparation", "", case["limits"], "",
                         "### Reference answer contract", "",
                         "Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.", "",
                         f"Source: [{case['id']} original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/{lane['case_file']}) · original status {case['source_status']}/{case['source_answer_status']}. Proposal lineage: {', '.join(case['proposal_lineage']) or 'none'}.", ""])
            if case.get("adaptation"):
                text.extend(["Adaptation: " + case["adaptation"], "", "Original question: " + case["original_question"], ""])
        (directory / "cases.md").write_text("\n".join(text))
        manifest.append({"lane": lane["id"], "subject": lane["subject"], "title": lane["title"], "case_count": len(cases), "cases": [c["id"] for c in cases], "directory": str(directory.relative_to(RUN))})
    if translations:
        raise ValueError(f"Unexpected translations: {list(translations)}")
    (RUN / "source-lineage.json").write_text(json.dumps(lineage, indent=2, ensure_ascii=False) + "\n")
    (RUN / "manifest.json").write_text(json.dumps({"case_count": sum(x["case_count"] for x in manifest), "lanes": manifest}, indent=2) + "\n")


if __name__ == "__main__":
    build()
