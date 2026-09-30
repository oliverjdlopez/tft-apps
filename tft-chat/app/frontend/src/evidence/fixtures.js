/** Supply a deterministic resolved ranking for browser behavior tests. */
export function rankingPresentation(kind = "interactive_table", id = "view-1") {
  return {
    id,
    bundle: {
      version: 1,
      ref: "evidence-1",
      source: "rank_units",
      population: "All eligible boards",
      population_boards: 1000,
      minimum_reportable_boards: 10,
      warnings: [],
      datasets: [
        {
          kind: "ranking",
          ref: "rows",
          grain: "One aggregate per unit and star level",
          source_sort: ["games desc"],
          page: { offset: 0, count: 3, has_more: true },
          fields: [
            { key: "unit_name", label: "Unit", unit: "text", groupable: true },
            { key: "games", label: "Games", unit: "count", groupable: false },
            {
              key: "top4_rate",
              label: "Top 4",
              unit: "fraction",
              groupable: false,
            },
          ],
          rows: [
            {
              key: "r1",
              values: { unit_name: "Jinx", games: 125, top4_rate: 0.6251 },
            },
            {
              key: "r2",
              values: { unit_name: "Annie", games: 20, top4_rate: null },
            },
            {
              key: "r3",
              values: { unit_name: "Jinx", games: 15, top4_rate: 0.7 },
            },
          ],
        },
      ],
    },
    display: {
      evidence_ref: "evidence-1",
      dataset_ref: "rows",
      kind,
      title: "Unit outcomes",
      description: "Explore the retrieved ranking",
      columns: ["unit_name", "games", "top4_rate"],
      primary_metric: "top4_rate",
      sort_by: null,
      direction: "asc",
      group_by: null,
    },
  };
}
/** Supply explicit placement bins including an observed zero. */
export function distributionPresentation() {
  const result = rankingPresentation();
  result.bundle.datasets = [
    {
      kind: "distribution",
      ref: "target",
      label: "Target cohort",
      grain: "One placement category",
      boards: 28,
      unavailable: false,
      bins: Array.from({ length: 8 }, (_, i) => ({
        placement: i + 1,
        count: i,
      })),
    },
  ];
  result.display = {
    ...result.display,
    kind: "distribution",
    dataset_ref: "target",
    columns: [],
    primary_metric: null,
  };
  return result;
}
