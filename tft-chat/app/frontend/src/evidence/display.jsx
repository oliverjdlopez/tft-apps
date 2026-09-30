import React, { useState } from "react";
import { formatValue, readPresentation, visibleRows } from "./utils.js";

/** Isolate a malformed display so the accompanying answer remains readable. */
class DisplayBoundary extends React.Component {
  state = { failed: false };
  /** Convert a render failure into a local unavailable state. */
  static getDerivedStateFromError() {
    return { failed: true };
  }
  /** Keep failure contained within the owning evidence card. */
  render() {
    return this.state.failed ? (
      <p role="status">Evidence view unavailable.</p>
    ) : (
      this.props.children
    );
  }
}

/** Render one isolated backend-resolved presentation. */
export function EvidenceDisplay({ presentation }) {
  return (
    <DisplayBoundary key={presentation.id}>
      <EvidenceCard presentation={presentation} />
    </DisplayBoundary>
  );
}

/** Connect source context to a table or distribution and its local controls. */
function EvidenceCard({ presentation }) {
  const { bundle, dataset, display } = readPresentation(presentation);
  return (
    <section className="evidence-card" aria-label={display.title}>
      <header>
        <span className="evidence-eyebrow">Retrieved evidence</span>
        <h3>{display.title}</h3>
        {display.description && <p>{display.description}</p>}
      </header>
      <p className="evidence-context">
        {bundle.population}
        {bundle.population_boards != null
          ? ` · ${formatValue(bundle.population_boards, "count")} population boards`
          : ""}
      </p>
      {dataset.kind === "ranking" ? (
        <EvidenceTable dataset={dataset} display={display} />
      ) : (
        <Distribution dataset={dataset} />
      )}
      <details className="evidence-source">
        <summary>Source and interpretation</summary>
        <p>
          Source: {bundle.source}. {dataset.grain}. Minimum reportable sample:{" "}
          {bundle.minimum_reportable_boards} boards.
        </p>
        {dataset.source_sort?.length > 0 && (
          <p>Retrieved ordering: {dataset.source_sort.join(", ")}.</p>
        )}
      </details>
      {bundle.warnings.length > 0 && (
        <ul className="evidence-warnings">
          {bundle.warnings.map((warning, i) => (
            <li key={i}>{warning.message}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Explore a loaded ranking slice without changing its evidence or population. */
function EvidenceTable({ dataset, display }) {
  const initial = {
    sortBy: display.sort_by || "",
    direction: display.direction,
    groupBy: display.group_by || "",
    search: "",
    rowLimit: String(Math.max(1, dataset.rows.length)),
  };
  const [state, setState] = useState(initial);
  const fields = display.columns.map((key) =>
    dataset.fields.find((field) => field.key === key),
  );
  const matchingRows = visibleRows(dataset, display.columns, state);
  const rowLimit = Math.min(
    dataset.rows.length,
    Math.max(1, Number.parseInt(state.rowLimit, 10) || dataset.rows.length),
  );
  const rows = matchingRows.slice(0, rowLimit);
  const groups = new Map();
  for (const row of rows) {
    const value = state.groupBy ? row.values[state.groupBy] : "";
    if (!groups.has(value)) groups.set(value, []);
    groups.get(value).push(row);
  }
  const partial = dataset.page.has_more || dataset.page.offset > 0;
  return (
    <>
      <p className="evidence-coverage">
        {partial ? "Partial result" : "Complete returned result"} ·{" "}
        {dataset.rows.length} loaded rows
        {dataset.page.offset
          ? ` · starting at result ${dataset.page.offset + 1}`
          : ""}
        .
        {display.kind === "interactive_table"
          ? " Sorting, search and the row limit apply to these rows."
          : ""}
      </p>
      {display.kind === "interactive_table" && (
        <details className="evidence-exploration">
          <summary>Explore table: sort, search and group</summary>
          <div className="evidence-controls">
            <label>
              Search loaded rows
              <input
                value={state.search}
                onChange={(event) =>
                  setState({ ...state, search: event.target.value })
                }
              />
            </label>
            <label>
              Sort by
              <select
                aria-label="Sort by"
                value={state.sortBy}
                onChange={(event) =>
                  setState({ ...state, sortBy: event.target.value })
                }
              >
                <option value="">Retrieved order</option>
                {fields.map((field) => (
                  <option key={field.key} value={field.key}>
                    {field.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Direction
              <select
                aria-label="Direction"
                value={state.direction}
                disabled={!state.sortBy}
                onChange={(event) =>
                  setState({ ...state, direction: event.target.value })
                }
              >
                <option value="asc">Ascending</option>
                <option value="desc">Descending</option>
              </select>
            </label>
            <label>
              Group by
              <select
                aria-label="Group by"
                value={state.groupBy}
                onChange={(event) =>
                  setState({ ...state, groupBy: event.target.value })
                }
              >
                <option value="">No grouping</option>
                {fields
                  .filter((field) => field.groupable)
                  .map((field) => (
                    <option key={field.key} value={field.key}>
                      {field.label}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Rows to show
              <input
                aria-label="Rows to show"
                type="number"
                min="1"
                max={Math.max(1, dataset.rows.length)}
                disabled={!dataset.rows.length}
                value={state.rowLimit}
                onChange={(event) =>
                  setState({ ...state, rowLimit: event.target.value })
                }
              />
            </label>
            <button type="button" onClick={() => setState(initial)}>
              Reset view
            </button>
          </div>
        </details>
      )}
      {display.kind === "interactive_table" && (
        <p aria-live="polite">
          {rows.length} of {matchingRows.length} matching rows shown ·{" "}
          {dataset.rows.length} loaded rows
          {state.groupBy
            ? "; groups are sections, not combined statistics"
            : ""}
          .
        </p>
      )}
      {!rows.length ? (
        <p role="status">
          {dataset.rows.length
            ? "No loaded rows match your search."
            : "No reportable results."}
        </p>
      ) : (
        <div
          className="evidence-table-scroll"
          tabIndex={0}
          role="region"
          aria-label={`${display.title} table`}
        >
          <table className="evidence-table">
            <thead>
              <tr>
                {fields.map((field) => (
                  <th
                    key={field.key}
                    scope="col"
                    className={`${field.unit === "text" ? "" : "evidence-number"} ${field.key === display.primary_metric ? "evidence-primary" : ""}`}
                    aria-sort={
                      state.sortBy === field.key
                        ? state.direction === "asc"
                          ? "ascending"
                          : "descending"
                        : undefined
                    }
                  >
                    {field.label}
                  </th>
                ))}
              </tr>
            </thead>
            {[...groups].map(([value, groupRows], i) => (
              <tbody key={i}>
                {state.groupBy && (
                  <tr>
                    <th colSpan={fields.length} scope="rowgroup">
                      {
                        fields.find((field) => field.key === state.groupBy)
                          ?.label
                      }
                      :{" "}
                      {formatValue(
                        value,
                        fields.find((field) => field.key === state.groupBy)
                          ?.unit,
                      )}{" "}
                      · {groupRows.length} rows
                    </th>
                  </tr>
                )}
                {groupRows.map((row) => (
                  <tr key={row.key}>
                    {fields.map((field) => (
                      <td
                        key={field.key}
                        className={`${field.unit === "text" ? "" : "evidence-number"} ${field.key === display.primary_metric ? "evidence-primary" : ""}`}
                      >
                        {formatValue(row.values[field.key], field.unit)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
        </div>
      )}
    </>
  );
}

/** Display explicit placement counts without inferring missing or suppressed bins. */
function Distribution({ dataset }) {
  if (dataset.unavailable)
    return (
      <p role="status">
        {dataset.label}: distribution unavailable or suppressed.
      </p>
    );
  const maximum = Math.max(1, ...dataset.bins.map((bin) => bin.count));
  return (
    <>
      <p>
        {dataset.label} · {formatValue(dataset.boards, "count")} boards
      </p>
      <div
        className="evidence-distribution"
        role="img"
        aria-label={`${dataset.label}: board counts by placement; exact values in the table below`}
      >
        <p className="evidence-axis">Boards</p>
        <div className="evidence-bars">
          {dataset.bins.map((bin) => (
            <div className="evidence-bin" key={bin.placement}>
              <div className="evidence-bar-space">
                <span
                  className="evidence-count"
                  title={formatValue(bin.count, "count")}
                >
                  {new Intl.NumberFormat("en-US", {
                    notation: "compact",
                    maximumFractionDigits: 1,
                  }).format(bin.count)}
                </span>
                <span
                  className="evidence-bar"
                  style={{ height: `${(160 * bin.count) / maximum}px` }}
                />
              </div>
              <span className="evidence-placement">{bin.placement}</span>
            </div>
          ))}
        </div>
        <p className="evidence-axis evidence-axis-bottom">Placement</p>
      </div>
      <details>
        <summary>Placement counts</summary>
        <table className="evidence-table">
          <thead>
            <tr>
              <th scope="col">Placement</th>
              <th scope="col">Boards</th>
            </tr>
          </thead>
          <tbody>
            {dataset.bins.map((bin) => (
              <tr key={bin.placement}>
                <th scope="row">{bin.placement}</th>
                <td>{formatValue(bin.count, "count")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </>
  );
}
