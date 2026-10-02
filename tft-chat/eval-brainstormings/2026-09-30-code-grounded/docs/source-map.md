# Source inspection and documentation mismatches

All paths below are relative to the ChatTFT repository root and were read as implementation evidence. They are not model-facing schema or raw-data access instructions.

| Concern | Authoritative source |
| --- | --- |
| Tool registry and rounding boundary | `app/backend/src/domain/tools/__init__.py` |
| Ranking and exact name/loadout discovery | `app/backend/src/domain/tools/db_tools/ranking_tools.py` |
| Input/result contracts and bounds | `app/backend/src/domain/tools/db_tools/models.py` |
| Grouped result grain and comparison uncertainty | `app/backend/src/domain/tools/db_tools/cohort_tools.py` |
| Conjunctive compiler and entity absence | `app/backend/src/domain/tools/db_tools/cohort_query.py`, `app/backend/src/domain/tools/db_tools/utils.py` |
| Frequency-first contextual delta tools | `app/backend/src/domain/tools/db_tools/deltas.py` |
| Scope and anonymous board fields | `app/backend/src/db/models/analysis.py` |
| Fact construction, unit-record count and normalized patch | `app/backend/src/db/build_query_tables.py`, `app/backend/src/db/utils.py` |
| Direct/reachable assistant access | `app/backend/src/domain/assistant_specs/chat/agent.json`, `app/backend/src/domain/assistant_specs/data_analyst/agent.json` |
| Corpus identity/freshness | `app/backend/src/resources/context/set18/unit_context.md`, `app/backend/src/resources/context/set18/items/catalogue.md`, `docs/content_providers/set18-context.md` |
| Native import shape and normalization | `evals/langfuse/dataset_registration.py` |
| String input, expected output and grading metadata | `evals/langfuse/contracts.py`, `evals/langfuse/content.py` |
| Supported deterministic checks and argument matching | `evals/trace.py`, `evals/utils.py` |
| Quality mapping and evidence available to judge | `evals/langfuse/grading.py`, `evals/langfuse/experiments.py`, `evals/utils.py:execution_evidence` |
| Existing regression examples inspected | `tests/test_cohort_facts.py`, `tests/test_ranking_tools.py`, `tests/test_agent_workflow_evals.py`, `evals/langfuse/tests/test_dataset_registration.py` |

Routing documentation read: root AGENTS.md, relevant nested DB/spec instructions, testing/evals, tools overview, change-assistant workflow, cohort/delta tool documentation, analysis/persistence, assistant architecture, context provider and Langfuse content contracts. The research entry points, all lane case questions/reference requirements and lane indexes ground the translation. External source records remain original provenance; no new online outcome research was needed.

Observed mismatches and limits, recorded here because writes outside brainstorming were forbidden:

- The testing guide mentions bounded SQL smoke coverage, but the current registered assistant tools expose no arbitrary SQL tool. No case requires one.
- The tools guide's focused command names `tests/test_cohort_tools.py`, which is absent in this checkout; `tests/test_cohort_facts.py` contains the relevant cohort regressions.
- The private wide feature tables remain explicitly Set 17-specific. Public cohort tools use normalized anonymous unit/item/trait facts; this deliverable does not use wide feature columns as a Set 18 reference or infer a populated Set 18 fact build.
- The local Set 18 corpus has 18.1 baseline and 18.2 supplements. It does not certify the original research's 18.3B/hotfix rules or unresolved double-Blue legality.
- The quality profile asks for grounding, but its bound evidence payload omits full numerical query outputs. Authored fidelity requirements are review criteria, not a newly implemented numerical comparator.

The user's explicit all-writes-under-brainstorming instruction governs this deliverable. Documentation synchronization is provided in this run's `docs/`; application documentation and behavior are unchanged.
