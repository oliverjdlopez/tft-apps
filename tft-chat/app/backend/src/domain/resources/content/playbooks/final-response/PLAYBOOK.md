---
name: final-response
description: Turn verified analytical results into a concise final answer with the user's constraints, relevant evidence, and material uncertainty. Use after an investigation or lookup, including when choosing a supported evidence display; this guide does not gather evidence or supply game facts.
---
# Final response

Answer the user's original question from the verified results and supplied context. Lead with the conclusion the evidence supports, retain the requested scope and format, and write like a concise peer. Include only the population, dimensions, sample, and metric needed to interpret the result. Use plain prose for a simple fact and a compact comparison when that helps; avoid fixed row counts and generic strategy advice.

If the evidence is incomplete, give the useful supported result and name the unresolved boundary. Ask one focused clarification only when the missing input could materially change the answer. Missing or suppressed data does not mean zero or absence. Distinguish observed final-board associations from causation and advice about acquisition order or game timing. Never invent numbers, game mechanics, references, or private identifiers.

## Present evidence when useful

When `present_evidence` is available and a display materially helps, select one display from evidence metadata returned during this invocation. Use `static_table` for a small fixed comparison, `interactive_table` for useful exploration, and `distribution` only for a reportable placement histogram. A mean cannot establish a distribution.

Pass `evidence_ref` and `dataset_ref` from the current results. Choose at most eight unique visible table fields, a visible numeric `primary_metric`, and any visible `sort_by` with direction `asc` or `desc`. Only an interactive table may use a visible groupable `group_by` field. For a distribution, leave columns empty and optional table fields null. Give the display a clear title and a short takeaway without repeating its cells.

The backend owns values, units, reporting restrictions, and coverage. Never rebuild numerical display payloads or invent references. If a selection is rejected, correct it from the actual results; if no valid display or presentation tool is available, answer in prose or Markdown. Local sorting covers only the retrieved slice, popularity is not performance, and histogram zeroes require explicit counts.

Read any additional permitted reference or skill needed to support a claim; catalogue descriptions alone are not facts or instructions.
