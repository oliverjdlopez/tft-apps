import { Disclosure, DisclosureSummary } from "@/components/shared/disclosure";
import { Table as UiTable, TableHeader as UiTableHeader, TableRow as UiTableRow, TableHead as UiTableHead, TableBody as UiTableBody, TableCell as UiTableCell } from "@/components/ui/table";
import { Button as UiButton } from "@/components/ui/button";
/** Readable algorithm diagnostics over the frozen, data-only panel envelope. */
import React, { useState } from "react";

/** Format scalar or nested cells without rendering executable diagnostic content. */
function cell(value) {
  if (value == null) return "Unavailable";
  if (typeof value === "number")
    return Number.isInteger(value) ? String(value) : value.toFixed(4);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
/** Paginate diagnostic records, keeping large sample diagnostics responsive. */
function DataTable({ rows }) {
  const [page, setPage] = useState(0);
  const columns = [
    ...new Set(rows.slice(0, 50).flatMap((row) => Object.keys(row))),
  ].filter((k) => k !== "board");
  return (
    <>
      <UiTable className="fields">
        <UiTableHeader>
          <UiTableRow>
            {columns.map((k) => (
              <UiTableHead key={k}>{k.replaceAll("_", " ")}</UiTableHead>
            ))}
          </UiTableRow>
        </UiTableHeader>
        <UiTableBody>
          {rows.slice(page * 25, page * 25 + 25).map((row, i) => (
            <UiTableRow key={i}>
              {columns.map((k) => (
                <UiTableCell key={k}>{cell(row[k])}</UiTableCell>
              ))}
            </UiTableRow>
          ))}
        </UiTableBody>
      </UiTable>
      {rows.length > 25 && (
        <p className="composition-actions">
          <UiButton variant="ghost" size="sm" className="ghost tiny" disabled={!page} onClick={() => setPage(page - 1)}>
            Previous
          </UiButton>
          {page * 25 + 1}–{Math.min(rows.length, page * 25 + 25)} of{" "}
          {rows.length}
          <UiButton variant="ghost" size="sm"
            className="ghost tiny"
            disabled={(page + 1) * 25 >= rows.length}
            onClick={() => setPage(page + 1)}
          >
            Next
          </UiButton>
        </p>
      )}
    </>
  );
}
/** Display HDBSCAN noise counts alongside cluster persistence records. */
function Distribution({ data }) {
  if (data.noise_count !== undefined)
    return (
      <>
        <p>
          Native noise: {data.noise_count} / {data.population_count} (
          {data.noise_fraction == null
            ? "Unavailable"
            : `${(data.noise_fraction * 100).toFixed(1)}%`}
          )
        </p>
        <DataTable rows={data.rows || []} />
      </>
    );
  return (
    <DataTable
      rows={Object.entries(data).map(([metric, value]) => ({ metric, value }))}
    />
  );
}
/** Select specialized panels by declared identity, with safe generic extension support. */
function Panel({ panel }) {
  if (panel.kind === "distribution") return <Distribution data={panel.data} />;
  if (panel.data.rows || panel.data.links)
    return <DataTable rows={panel.data.rows || panel.data.links} />;
  return (
    <DataTable
      rows={Object.entries(panel.data).map(([metric, value]) => ({
        metric,
        value,
      }))}
    />
  );
}
/** Render independently owned algorithm diagnostics using common presentation controls. */
export default function Diagnostics({ diagnostics }) {
  return (
    <section>
      <h3>Algorithm diagnostics</h3>
      {diagnostics.warnings.map((w, i) => (
        <p key={i}>{w}</p>
      ))}
      {diagnostics.panels.map((panel) => (
        <Disclosure key={panel.panel_id}>
          <DisclosureSummary>
            {panel.title} · {panel.kind}
          </DisclosureSummary>
          <p>{panel.description}</p>
          <Panel panel={panel} />
          <Disclosure>
            <DisclosureSummary>Inspect diagnostic data</DisclosureSummary>
            <pre>{JSON.stringify(panel.data, null, 2)}</pre>
          </Disclosure>
        </Disclosure>
      ))}
    </section>
  );
}
