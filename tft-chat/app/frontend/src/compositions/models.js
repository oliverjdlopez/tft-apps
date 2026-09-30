/** Runtime contracts. Pydantic owns the corresponding server and wire models. */
import { z } from "zod";
const id = z.string().min(1),
  count = z.number().int().nonnegative(),
  positive = z.number().int().min(1);
const finite = z.number().finite(),
  rate = finite.min(0).max(1);
const strict = (shape) => z.object(shape).strict();
const unique = (values) => new Set(values).size === values.length;
export const EntityRefSchema = strict({ key: id, name: id });
export const ItemOccurrenceSchema = strict({
  slot: count.max(2),
  item: EntityRefSchema,
});
export const UnitOccurrenceSchema = strict({
  occurrence_index: count,
  unit: EntityRefSchema,
  star_level: positive,
  items: z.array(ItemOccurrenceSchema).max(3),
}).refine((v) => unique(v.items.map((i) => i.slot)), "Duplicate item slot");
export const TraitObservationSchema = strict({
  trait: EntityRefSchema,
  num_units: count.nullable(),
  tier_current: count.nullable(),
  style: count.nullable(),
});
export const BoardObservationSchema = strict({
  observation_id: id,
  level: count.nullable(),
  units: z.array(UnitOccurrenceSchema),
  traits: z.array(TraitObservationSchema),
}).refine(
  (v) => unique(v.units.map((u) => u.occurrence_index)),
  "Duplicate occurrence index",
);
export const BoardOutcomeSchema = strict({
  observation_id: id,
  placement: positive.max(8).nullable(),
});
export const UnitRequirementSchema = strict({
  unit: EntityRefSchema,
  min_copies: positive,
  itemized: z.boolean().nullable(),
});
export const TraitRequirementSchema = strict({
  trait: EntityRefSchema,
  min_tier_current: positive,
});
export const StructuralPatternSchema = strict({
  pattern_id: id,
  label: id,
  units: z.array(UnitRequirementSchema),
  traits: z.array(TraitRequirementSchema),
});
export const VariationDefinitionSchema = strict({
  variation_id: id,
  label: id,
  description: z.string(),
  patterns: z.array(StructuralPatternSchema),
  representative_observation_ids: z.array(id),
});
export const FamilyDefinitionSchema = strict({
  family_id: id,
  label: id,
  description: z.string(),
  defining_patterns: z.array(StructuralPatternSchema),
  representative_observation_ids: z.array(id),
  variations: z.array(VariationDefinitionSchema),
});
export const MatchScoreSchema = strict({
  name: id,
  value: finite,
  kind: z.enum(["distance", "similarity", "model_probability"]),
  higher_is_better: z.boolean(),
}).refine(
  (v) => v.kind !== "model_probability" || (v.value >= 0 && v.value <= 1),
  "Invalid probability",
);
export const FamilyCandidateSchema = strict({
  family_id: id,
  score: MatchScoreSchema,
  evidence: z.array(z.string()),
});
export const BoardAssignmentSchema = strict({
  observation_id: id,
  status: z.enum(["assigned", "ambiguous", "unclassified"]),
  family_id: id.nullable(),
  variation_id: id.nullable(),
  candidates: z.array(FamilyCandidateSchema),
  explanation: z.string(),
}).refine(
  (v) =>
    v.status === "assigned"
      ? v.family_id !== null
      : v.family_id === null && v.variation_id === null,
  "Invalid primary family",
);
export const PatternSupportSchema = strict({
  pattern: StructuralPatternSchema,
  matching_boards: count,
  eligible_boards: count,
}).refine(
  (v) => v.matching_boards <= v.eligible_boards,
  "Invalid support denominator",
);
export const OutcomeSummarySchema = strict({
  state: z.enum(["available", "empty", "suppressed", "unavailable"]),
  observed_boards: count,
  placement_counts: z.array(count).length(8).nullable(),
  avg_placement: finite.min(1).max(8).nullable(),
  top4_rate: rate.nullable(),
  win_rate: rate.nullable(),
}).refine((v) => {
  const metrics = [
    v.placement_counts,
    v.avg_placement,
    v.top4_rate,
    v.win_rate,
  ];
  if (v.state !== "available")
    return (
      metrics.every((x) => x === null) &&
      (v.state !== "empty" || v.observed_boards === 0)
    );
  if (metrics.some((x) => x === null) || !v.observed_boards) return false;
  const c = v.placement_counts,
    n = v.observed_boards;
  return (
    c.reduce((a, b) => a + b, 0) === n &&
    Math.abs(c.reduce((a, b, i) => a + b * (i + 1), 0) / n - v.avg_placement) <
      1e-9 &&
    Math.abs(c.slice(0, 4).reduce((a, b) => a + b, 0) / n - v.top4_rate) <
      1e-9 &&
    Math.abs(c[0] / n - v.win_rate) < 1e-9
  );
}, "Inconsistent outcome distribution");
export const FamilyProfileSchema = strict({
  family_id: id,
  assigned_boards: count,
  eligible_population_boards: count,
  play_share: rate.nullable(),
  joint_patterns: z.array(PatternSupportSchema),
  outcomes: OutcomeSummarySchema,
}).refine(
  (v) =>
    v.assigned_boards <= v.eligible_population_boards &&
    (v.eligible_population_boards
      ? v.play_share !== null &&
        Math.abs(
          v.play_share - v.assigned_boards / v.eligible_population_boards,
        ) < 1e-9
      : v.play_share === null),
  "Invalid population denominator",
);
export const CompositionContextSchema = strict({
  source_kind: z.enum(["fixture", "experiment"]),
  population_kind: z.enum(["discovery_sample", "full_population"]),
  patch: id,
  set_number: count,
  queue_id: count,
  snapshot_revision: id,
  taxonomy_revision: id,
  feature_revision: id,
  algorithm_id: id.nullable(),
  algorithm_version: id.nullable(),
  experiment_id: id.nullable(),
});
export const BoardExampleViewSchema = strict({
  board: BoardObservationSchema,
  outcome: BoardOutcomeSchema.nullable(),
  assignment: BoardAssignmentSchema.nullable(),
  is_representative: z.boolean(),
});
export const FamilyPatternPreviewSchema = strict({
  pattern: StructuralPatternSchema,
  omitted_requirements: count,
  alternative_patterns: count,
}).refine((v) => v.pattern.units.length + v.pattern.traits.length <= 6,
  "A family preview may contain at most six requirements");
export const FamilySummaryViewSchema = strict({
  family_id: id,
  label: id,
  description: z.string(),
  assigned_boards: count,
  eligible_population_boards: count,
  play_share: rate.nullable(),
  variation_count: count,
  preview: FamilyPatternPreviewSchema.nullable(),
}).refine(
  (v) =>
    v.assigned_boards <= v.eligible_population_boards &&
    (v.eligible_population_boards
      ? v.play_share !== null &&
        Math.abs(
          v.play_share - v.assigned_boards / v.eligible_population_boards,
        ) < 1e-9
      : v.play_share === null),
  "Invalid summary denominator",
);
export const CompositionWarningSchema = strict({
  code: id,
  message: z.string(),
});
export const CompositionListResponseSchema = strict({
  schema_version: z.literal("composition.v1"),
  context: CompositionContextSchema,
  families: z.array(FamilySummaryViewSchema),
  warnings: z.array(CompositionWarningSchema),
});
export const CompositionDetailResponseSchema = strict({
  schema_version: z.literal("composition.v1"),
  context: CompositionContextSchema,
  family: FamilyDefinitionSchema,
  profile: FamilyProfileSchema.nullable(),
  examples: z.array(BoardExampleViewSchema),
  warnings: z.array(CompositionWarningSchema),
});
/** @typedef {z.infer<typeof BoardExampleViewSchema>} BoardExampleView */
/** @typedef {z.infer<typeof CompositionDetailResponseSchema>} CompositionDetailResponse */
/** @typedef {z.infer<typeof CompositionListResponseSchema>} CompositionListResponse */

export const DiagnosticPanelSchema = strict({
  panel_id: id,
  title: id,
  kind: z.enum(["table", "series", "tree", "graph", "distribution", "text"]),
  description: z.string(),
  data: z.record(z.unknown()),
});
export const DiagnosticsSchema = strict({
  schema_version: z.literal("diagnostics.v1"),
  panels: z.array(DiagnosticPanelSchema),
  warnings: z.array(z.string()),
});
/** Run-level model view: families and settings, never fitted algorithm state. */
export const ModelSummarySchema = strict({
  schema_version: z.literal("adapter.v1"),
  algorithm_id: id,
  algorithm_version: id,
  feature_revision: z.literal("structure.v1"),
  effective_parameters: z.record(z.unknown()),
  families: z.array(FamilyDefinitionSchema),
});
/** Compact classification for browsing; evidence comes from the board request. */
export const AssignmentSummarySchema = strict({
  observation_id: id,
  status: z.enum(["assigned", "ambiguous", "unclassified"]),
  family_id: id.nullable(),
  variation_id: id.nullable(),
}).refine(
  (v) =>
    v.status === "assigned"
      ? v.family_id !== null
      : v.family_id === null && v.variation_id === null,
  "Invalid primary family",
);
export const ExperimentRequestSchema = strict({
  algorithm_id: id,
  algorithm_version: id.nullable(),
  parameters: z.record(z.unknown()),
  seed: count.max(2147483647),
  sample_size: positive,
  full_population: z.boolean(),
  source_kind: z.enum(["active", "fixture"]),
  snapshot_id: id.nullable(),
});
export const PopulationSummarySchema = strict({
  population_kind: z.enum(["discovery_sample", "full_population"]),
  assignments: z.array(AssignmentSummarySchema),
  profiles: z.array(FamilyProfileSchema),
  coverage: rate.nullable(),
  ambiguity: rate.nullable(),
});
export const ExperimentResultViewSchema = strict({
  model: ModelSummarySchema,
  diagnostics: DiagnosticsSchema,
  populations: z.array(PopulationSummarySchema),
});
export const ExperimentViewSchema = strict({
  experiment_id: id,
  snapshot_id: id,
  created_at: z.string(),
  status: z.enum([
    "queued",
    "running",
    "completed",
    "cancelled",
    "interrupted",
    "failed",
  ]),
  stage: z.string(),
  elapsed_seconds: finite.nonnegative(),
  request: ExperimentRequestSchema,
  context: CompositionContextSchema,
  eligible_boards: count,
  sample_boards: count,
  error: z.string().nullable(),
  result: ExperimentResultViewSchema.nullable(),
});
export const ExperimentHistorySchema = strict({
  experiments: z.array(ExperimentViewSchema),
});
export const AlgorithmViewSchema = strict({
  algorithm_id: id,
  algorithm_version: id,
  parameter_schema: z.record(z.unknown()),
});
export const AlgorithmListSchema = strict({
  algorithms: z.array(AlgorithmViewSchema),
});
export const ComparisonMetricsSchema = strict({
  family_count: count,
  eligible_boards: count,
  coverage: rate.nullable(),
  ambiguity: rate.nullable(),
  elapsed_seconds: finite.nonnegative(),
});
export const ComparisonResponseSchema = strict({
  left_id: id,
  right_id: id,
  identical_population: z.boolean(),
  left_metrics: ComparisonMetricsSchema,
  right_metrics: ComparisonMetricsSchema,
  configuration_differences: z.record(z.unknown()),
  assignment_overlap: rate.nullable(),
  adjusted_rand_index: finite.nullable(),
  message: z.string(),
});
/** @typedef {z.infer<typeof ExperimentViewSchema>} ExperimentView */

export const SourceSummarySchema = strict({
  source_kind: z.enum(["active", "fixture"]),
  ready: z.boolean(),
  patch: z.string().nullable(),
  set_number: count.nullable(),
  queue_id: count.nullable(),
  eligible_boards: count.nullable(),
  fact_revision: z.string().nullable(),
  warning: z.string().nullable(),
});
