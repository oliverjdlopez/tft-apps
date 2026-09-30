/** Validate the resolved event before rendering backend-owned evidence. */
export function readPresentation(presentation) {
  const { bundle, display } = presentation || {};
  if (
    bundle?.version !== 1 ||
    display?.evidence_ref !== bundle.ref ||
    !Array.isArray(bundle.datasets)
  )
    throw new Error("Invalid evidence");
  const dataset = bundle.datasets.find(
    (item) => item.ref === display.dataset_ref,
  );
  if (!dataset || !Array.isArray(bundle.warnings))
    throw new Error("Missing dataset");
  if (display.kind === "distribution") {
    if (dataset.kind !== "distribution" || !Array.isArray(dataset.bins))
      throw new Error("Invalid distribution");
    if (
      !dataset.unavailable &&
      (dataset.bins.length !== 8 ||
        dataset.bins.some(
          (bin, i) =>
            bin.placement !== i + 1 ||
            !Number.isInteger(bin.count) ||
            bin.count < 0,
        ) ||
        dataset.bins.reduce((sum, bin) => sum + bin.count, 0) !==
          dataset.boards)
    )
      throw new Error("Invalid bins");
  } else {
    if (
      !["static_table", "interactive_table"].includes(display.kind) ||
      dataset.kind !== "ranking" ||
      !Array.isArray(dataset.rows) ||
      !Array.isArray(dataset.fields) ||
      !dataset.page
    )
      throw new Error("Invalid table");
    if (
      !Array.isArray(display.columns) ||
      !display.columns.length ||
      new Set(display.columns).size !== display.columns.length ||
      display.columns.some(
        (key) => !dataset.fields.some((field) => field.key === key),
      )
    )
      throw new Error("Invalid columns");
    if (
      new Set(dataset.rows.map((row) => row.key)).size !==
        dataset.rows.length ||
      dataset.rows.some((row) => !row.values)
    )
      throw new Error("Invalid rows");
  }
  return { bundle, display, dataset };
}

/** Format explicit backend units while keeping missing values distinct. */
export function formatValue(value, unit) {
  if (value == null) return "Unavailable";
  if (unit === "text") return String(value);
  if (typeof value !== "number" || !Number.isFinite(value))
    return "Unavailable";
  return new Intl.NumberFormat(
    "en-US",
    unit === "fraction"
      ? { style: "percent", maximumFractionDigits: 1 }
      : { maximumFractionDigits: unit === "count" ? 0 : 2 },
  ).format(value);
}

/** Select and sort a copy of the loaded slice without aggregating its rows. */
export function visibleRows(dataset, columns, state) {
  const search = state.search.trim().toLocaleLowerCase();
  const rows = dataset.rows.filter(
    (row) =>
      !search ||
      columns.some((key) =>
        String(row.values[key] ?? "")
          .toLocaleLowerCase()
          .includes(search),
      ),
  );
  if (state.sortBy)
    rows.sort((a, b) => {
      const left = a.values[state.sortBy];
      const right = b.values[state.sortBy];
      if (left == null) return right == null ? 0 : 1;
      if (right == null) return -1;
      const compared =
        typeof left === "number" && typeof right === "number"
          ? left - right
          : String(left).localeCompare(String(right));
      return state.direction === "desc" ? -compared : compared;
    });
  return rows;
}
