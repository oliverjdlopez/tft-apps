import { Button as UiButton } from "@/components/ui/button";
import { Disclosure, DisclosureSummary } from "@/components/shared/disclosure";
import { Table as UiTable, TableHeader as UiTableHeader, TableRow as UiTableRow, TableHead as UiTableHead, TableBody as UiTableBody, TableCell as UiTableCell } from "@/components/ui/table";
import { Input as UiInput } from "@/components/ui/input";
import { useEffect, useState } from "react";
import { apiGet, Icon, Json, Pill, Spinner } from "../app.jsx";

// Data explorer — Models
// --------------------------------------------------------------------------
function FieldTable({ fields }) {
  return (
    <UiTable className="fields">
      <UiTableHeader>
        <UiTableRow>
          <UiTableHead>field</UiTableHead>
          <UiTableHead>type</UiTableHead>
          <UiTableHead>req</UiTableHead>
          <UiTableHead>default</UiTableHead>
          <UiTableHead>description</UiTableHead>
        </UiTableRow>
      </UiTableHeader>
      <UiTableBody>
        {fields.map((f) => (
          <UiTableRow key={f.attr || f.name}>
            <UiTableCell>
              <code>{f.name}</code>
            </UiTableCell>
            <UiTableCell>
              <code>{f.type}</code>
            </UiTableCell>
            <UiTableCell>{f.required ? "✓" : ""}</UiTableCell>
            <UiTableCell className="desc">
              {f.default === null || f.default === undefined
                ? ""
                : JSON.stringify(f.default)}
            </UiTableCell>
            <UiTableCell className="desc">{f.description || ""}</UiTableCell>
          </UiTableRow>
        ))}
      </UiTableBody>
    </UiTable>
  );
}

function ModelCard({ m }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="list-item">
      <UiButton variant="ghost" type="button" aria-expanded={open} className="head h-auto w-full justify-start whitespace-normal text-left" onClick={() => setOpen(!open)}>
        <Icon name="chevron" size={13} className={"chev " + (open ? "down" : "")} />
        <span className="name">{m.name}</span>
        <span className="desc">{(m.doc || "").split("\n")[0]}</span>
        {m.table ? <Pill kind="cat">table: {m.table}</Pill> : null}
        <span className="muted small">{m.fields.length} fields</span>
      </UiButton>
      {open ? (
        <div className="body">
          {m.doc ? <p className="muted prewrap">{m.doc}</p> : null}
          <FieldTable fields={m.fields} />
          {m.table_ddl ? (
            <div>
              <h4>
                Maps to database table <code>{m.table}</code>
              </h4>
              <pre className="ddl">{m.table_ddl}</pre>
            </div>
          ) : null}
          <Disclosure>
            <DisclosureSummary>JSON schema (tool contract)</DisclosureSummary>
            <Json value={m.json_schema} />
          </Disclosure>
        </div>
      ) : null}
    </div>
  );
}

function ModelsTab() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [q, setQ] = useState("");
  useEffect(() => {
    apiGet("/api/models").then(setData).catch((e) => setErr(e.message));
  }, []);
  if (err) return <div className="statusline bad">Failed to load: {err}</div>;
  if (!data) return <Spinner label="Loading…" />;
  const needle = q.trim().toLowerCase();
  return (
    <div className="explorer-pane">
      <p className="lead">
        Every shape that flows through the backend, straight from{" "}
        <code>src/        core/models.py</code>. Click a model for its fields, the
        table it maps to, and the JSON schema.
      </p>
      <div className="search-box">
        <Icon name="search" size={15} />
        <UiInput
          type="text"
          aria-label="Filter models by name"
          placeholder="Filter models by name…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>
      {data.groups.map((g) => {
        const models = g.models.filter(
          (m) => !needle || m.name.toLowerCase().includes(needle),
        );
        if (!models.length) return null;
        return (
          <div key={g.key}>
            <h3>
              {g.label} <span className="muted small">({models.length})</span>
            </h3>
            {g.blurb ? <div className="muted small mb">{g.blurb}</div> : null}
            {models.map((m) => (
              <ModelCard key={m.name} m={m} />
            ))}
          </div>
        );
      })}
    </div>
  );
}

// --------------------------------------------------------------------------
export default ModelsTab;
