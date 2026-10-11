# ChatTFT code-grounded evaluation cases

69 cases across 16 lanes, reconciled from the final player-needs research into ChatTFT tool operations, metrics, checks and explicit capability limits. Original authoring was isolated to this brainstorming directory. Subsequent requests integrated the cases into Langfuse and distributed them among the four expert datasets.

- [Original combined authoring JSON](dataset.json)
- [Capability and evidence contract](docs/capabilities.md)
- [Validation and usage](docs/validation-and-use.md)
- [Source inspection and documentation mismatches](docs/source-map.md)
- [Coordinator decisions and final content review](docs/coordinator-review.md)
- [Offline validation report](validation/dataset-validation.json)
- [Langfuse integration verification](validation/langfuse-integration.json)
- [Top-level dataset rename verification](validation/dataset-flattening.json)
- [Current expert datasets and lane allocation](experts/README.md)
- [Expert distribution verification](validation/expert-distribution.json)
- [Original case lineage](source-lineage.json)

These are investigation-behavior and answer-coverage benchmarks. No database or live model outcomes were measured; numerical gold is not fabricated. The current native judge does not receive all analytical tool outputs, so independent numerical verification needs a frozen aggregate reference or full-trace audit. All 69 cases now live in `item-expert`, `unit-expert`, `comp-expert` and `trait-expert`, with Custom Experiment and native grading configuration. The combined live dataset was deleted after verification; `meta-expert` remains empty. Earlier integration and rename receipts describe historical stages. The original combined JSON and lane artifacts remain the authored source record.

| Lane | Cases | Reconciled cases | Langfuse JSON | Authoring review |
| --- | ---: | --- | --- | --- |
| IT-1 — Completed-item alternatives across comparable holders and builds | 2 | [Cases](lanes/it-1/cases.md) | [Dataset](lanes/it-1/dataset.json) | [Report](lanes/it-1/authoring-report.md) |
| IT-2 — Fixed-inventory holder comparisons and item allocation | 3 | [Cases](lanes/it-2/cases.md) | [Dataset](lanes/it-2/dataset.json) | [Report](lanes/it-2/authoring-report.md) |
| IT-3 — How item performance varies with board and trait context | 6 | [Cases](lanes/it-3/cases.md) | [Dataset](lanes/it-3/dataset.json) | [Report](lanes/it-3/authoring-report.md) |
| IT-4 — Special-item comparisons across carry and frontline roles | 6 | [Cases](lanes/it-4/cases.md) | [Dataset](lanes/it-4/dataset.json) | [Report](lanes/it-4/authoring-report.md) |
| UN4-1 — Unit investment, carry versions and alternative holders | 4 | [Cases](lanes/un4-1/cases.md) | [Dataset](lanes/un4-1/dataset.json) | [Report](lanes/un4-1/authoring-report.md) |
| UN4-2 — Unit build alternatives and their board conditions | 4 | [Cases](lanes/un4-2/cases.md) | [Dataset](lanes/un4-2/dataset.json) | [Report](lanes/un4-2/authoring-report.md) |
| UN4-3 — Unit partnerships and fit across board contexts | 6 | [Cases](lanes/un4-3/cases.md) | [Dataset](lanes/un4-3/dataset.json) | [Report](lanes/un4-3/authoring-report.md) |
| UN4-4 — Alternative units within similar board structures | 3 | [Cases](lanes/un4-4/cases.md) | [Dataset](lanes/un4-4/dataset.json) | [Report](lanes/un4-4/authoring-report.md) |
| CO4-1 — Composition repertoires and statistical claims | 3 | [Cases](lanes/co4-1/cases.md) | [Dataset](lanes/co4-1/dataset.json) | [Report](lanes/co4-1/authoring-report.md) |
| CO4-2 — Recurring final-board cores and flexible slots | 6 | [Cases](lanes/co4-2/cases.md) | [Dataset](lanes/co4-2/dataset.json) | [Report](lanes/co4-2/authoring-report.md) |
| CO4-3 — Composition variants with alternative partner packages | 5 | [Cases](lanes/co4-3/cases.md) | [Dataset](lanes/co4-3/dataset.json) | [Report](lanes/co4-3/authoring-report.md) |
| CO4-4 — Finished-board package comparisons and caps | 4 | [Cases](lanes/co4-4/cases.md) | [Dataset](lanes/co4-4/dataset.json) | [Report](lanes/co4-4/authoring-report.md) |
| TR-1 — Trait performance within composition families | 3 | [Cases](lanes/tr-1/cases.md) | [Dataset](lanes/tr-1/dataset.json) | [Report](lanes/tr-1/authoring-report.md) |
| TR-2 — Vertical breakpoints versus conditional splashes | 6 | [Cases](lanes/tr-2/cases.md) | [Dataset](lanes/tr-2/dataset.json) | [Report](lanes/tr-2/authoring-report.md) |
| TR-3 — Emblem-enabled board variants | 4 | [Cases](lanes/tr-3/cases.md) | [Dataset](lanes/tr-3/dataset.json) | [Report](lanes/tr-3/authoring-report.md) |
| TR-4 — Trait combinations and conditional splashes | 4 | [Cases](lanes/tr-4/cases.md) | [Dataset](lanes/tr-4/dataset.json) | [Report](lanes/tr-4/authoring-report.md) |

Each case preserves its stable ID, player need and proposal lineage. Original provisional web answers remain provenance, not expected numeric values. Two website-panel questions are explicitly adapted to scoped ChatTFT comparisons; the historical Cassiopeia question has an explicit single-scope execution limit. The missing TR-3-C03 ID is inherited from the final source collection and is not a dropped case.

The coordinator wrote the reconciled cases first. Each lane was then separately delegated to GPT-6 Luna at high reasoning, following the repository instructions. The combined JSON is a lossless concatenation of lane items. See lane reports and the validation record for what was verified.
Authoring-stage verification: all 69 cases and 154 trace checks passed importer/semantic validation and applicable synthetic witnesses. All 32 proposal lineages remain represented. SHA-256 checks found no changes in 78 original research files or 676 inspected source/documentation/evaluation/test files at that stage. Local Markdown links were checked for missing destinations. Subsequent registration changed only the evaluation catalog, added immutable snapshots and updated relevant documentation; application source remains unchanged. No live model evaluation or database query was performed.
