import { AssistantName } from "./assistant-names.js";
import { MessageSquare, Sparkles, ListChecks, Database, Info, X, Copy, Send, ChevronRight, PanelRight, RefreshCw, Search, Zap, TriangleAlert, Check, Trash2, Menu, ArrowLeft, ArrowRight, Play } from "lucide-react";
import { SidebarProvider, Sidebar as SidebarPrimitive, SidebarHeader, SidebarContent, SidebarFooter, SidebarMenu, SidebarMenuItem, SidebarMenuButton, SidebarTrigger, useSidebar } from "@/components/ui/sidebar";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Collapsible as CollapsibleRoot, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible";
import { Badge } from "@/components/ui/badge";
import { Textarea as UiTextarea } from "@/components/ui/textarea";
import { Badge as UiBadge } from "@/components/ui/badge";
import { Button as UiButton } from "@/components/ui/button";
import { NativeSelect as UiNativeSelect } from "@/components/ui/native-select";
import { Input as UiInput } from "@/components/ui/input";
import { Table as UiTable, TableHeader as UiTableHeader, TableRow as UiTableRow, TableHead as UiTableHead, TableBody as UiTableBody, TableCell as UiTableCell } from "@/components/ui/table";
import { Card as UiCard } from "@/components/ui/card";
import { Alert as UiAlert } from "@/components/ui/alert";
import Compositions from "./compositions/Compositions.jsx";
import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import DOMPurify from "dompurify";
import { EvidenceDisplay } from "./evidence/display.jsx";
import { marked } from "marked";
import { openAiTraceUrl } from "./openai.js";
import {
  consumeStreamBuffer,
  formatChatPart,
  parseAssistant,
} from "./streaming.js";
import {
  ModelsTab,
  OverviewTab,
  RawTab,
  RolldownTab,
  ResponseTuningTab,
  SpecsTab,
  ToolsTab,
} from "./tabs/index.jsx";

// --------------------------------------------------------------------------
// API
// --------------------------------------------------------------------------
async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "content-type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail = data && typeof data === "object" ? data.detail : data;
    const message = Array.isArray(detail)
      ? detail.map((issue) => {
          const location = (issue.loc || []).filter((part) => part !== "body").join(" → ");
          return `${location ? `${location}: ` : ""}${issue.msg || "Invalid value"}`;
        }).join("; ")
      : typeof detail === "string"
        ? detail
        : data && typeof data === "object"
          ? JSON.stringify(data)
          : `Request failed with status ${res.status}`;
    // Callers such as the Flowchart save loop branch on 409 conflicts.
    throw Object.assign(new Error(message), { status: res.status });
  }
  return data;
}

const apiGet = (path) => api(path);
const apiPost = (path, body) =>
  api(path, { method: "POST", body: JSON.stringify(body) });
const apiPut = (path, body) =>
  api(path, { method: "PUT", body: JSON.stringify(body) });
const apiPatch = (path, body) =>
  api(path, { method: "PATCH", body: JSON.stringify(body) });
const apiDelete = (path, body) =>
  api(path, { method: "DELETE", body: JSON.stringify(body) });

function useLocalStorage(key, initial) {
  const [value, setValue] = useState(() => {
    try {
      const raw = window.localStorage.getItem(key);
      return raw === null ? initial : JSON.parse(raw);
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* ignore */
    }
  }, [key, value]);
  return [value, setValue];
}

// --------------------------------------------------------------------------
// Shared Lucide icon vocabulary; the TFT brand mark remains application-owned.
// --------------------------------------------------------------------------
const UI_ICONS = { chat: MessageSquare, sparkles: Sparkles, tasks: ListChecks, data: Database, info: Info, close: X, copy: Copy, send: Send, chevron: ChevronRight, panel: PanelRight, refresh: RefreshCw, search: Search, bolt: Zap, alert: TriangleAlert, check: Check, clear: Trash2, menu: Menu, "arrow-left": ArrowLeft, "arrow-right": ArrowRight, play: Play };

/** Render a consistent Lucide icon through the existing application icon API. */
function Icon({ name, size = 18, className }) {
  const Component = UI_ICONS[name];
  return Component ? <Component size={size} strokeWidth={1.75} className={"icon " + (className || "")} aria-hidden="true" /> : null;
}

function Logo({ size = 30 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" className="brand-mark">
      <defs>
        <linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#8b9dff" />
          <stop offset="1" stopColor="#e9c46a" />
        </linearGradient>
      </defs>
      <path
        d="M16 2.5 27.7 9.2v13.6L16 29.5 4.3 22.8V9.2z"
        fill="url(#lg)"
        opacity="0.16"
      />
      <path
        d="M16 2.5 27.7 9.2v13.6L16 29.5 4.3 22.8V9.2z"
        fill="none"
        stroke="url(#lg)"
        strokeWidth="1.6"
      />
      <path
        d="M11 20.5 16 9l5 11.5M12.7 16.8h6.6"
        fill="none"
        stroke="url(#lg)"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// --------------------------------------------------------------------------
// Primitives
// --------------------------------------------------------------------------
marked.setOptions({ gfm: true, breaks: true });

function renderMarkdown(value) {
  const text = value == null ? "" : String(value);
  if (!text) return "";
  return DOMPurify.sanitize(marked.parse(text));
}

function Markdown({ value, className }) {
  const html = useMemo(() => renderMarkdown(value), [value]);
  if (!html) return null;
  return (
    <div
      className={"markdown " + (className || "")}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

function AutoTextarea({ value, minRows = 3, maxHeight = 420, ...props }) {
  const ref = useRef(null);
  const resize = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, maxHeight) + "px";
  }, [maxHeight]);
  useEffect(resize, [value, resize]);
  return (
    <UiTextarea ref={ref} rows={minRows} value={value} onInput={resize} {...props} />
  );
}

function Json({ value }) {
  const text =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return <pre className="json">{text}</pre>;
}
const JsonBlock = Json;

function Pill({ children, kind }) {
  return <Badge variant="secondary" className={"pill " + (kind || "")}>{children}</Badge>;
}

function Chip({ children, title }) {
  return (
    <UiBadge variant="secondary" className="chip" title={title}>
      {children}
    </UiBadge>
  );
}

function IconButton({ icon, label, onClick, disabled, active, size = 16 }) {
  return (
    <UiButton variant={active ? "secondary" : "ghost"} size="icon-sm"
      type="button"
      className={"icon-btn " + (active ? "active" : "")}
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
    >
      <Icon name={icon} size={size} />
    </UiButton>
  );
}

function CopyButton({ text, label }) {
  const [done, setDone] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(
        typeof text === "string" ? text : JSON.stringify(text, null, 2),
      );
      setDone(true);
      setTimeout(() => setDone(false), 1200);
    } catch {
      setDone(false);
    }
  }
  return (
    <UiButton variant="ghost" size="sm" className="ghost tiny copy-btn" onClick={copy} type="button">
      <Icon name={done ? "check" : "copy"} size={13} />
      <span>{done ? "copied" : label || "copy"}</span>
    </UiButton>
  );
}

function Spinner({ label }) {
  return (
    <span className="spinner-wrap">
      <span className="spinner" />
      {label ? <span className="muted">{label}</span> : null}
    </span>
  );
}

/** Disclose supporting content without nesting interactive header actions. */
function Collapsible({ title, subtitle, defaultOpen = true, right, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <CollapsibleRoot open={open} onOpenChange={setOpen} className="rounded-lg border">
      <div className="flex items-center gap-2 p-2">
        <CollapsibleTrigger asChild>
          <UiButton variant="ghost" className="h-auto min-w-0 flex-1 justify-start whitespace-normal text-left">
            <Icon name="chevron" size={14} className={open ? "rotate-90" : ""} />
            <span className="font-medium">{title}</span>
            {subtitle != null && <span className="text-muted-foreground">{subtitle}</span>}
          </UiButton>
        </CollapsibleTrigger>
        {right}
      </div>
      <CollapsibleContent className="border-t p-4">{children}</CollapsibleContent>
    </CollapsibleRoot>
  );
}

function EmptyState({ icon, title, children }) {
  return (
    <div className="empty-state">
      {icon ? <Icon name={icon} size={26} /> : null}
      <strong>{title}</strong>
      {children ? <p className="muted">{children}</p> : null}
    </div>
  );
}

// ViewHeader's props and DOM structure are frozen for this round of
// parallel work: Compositions is newly adopting it while Workflows/
// Developer restyle it. Only its CSS (styles.css) may change; do not
// add/remove/rename props or alter the rendered markup shape here.
function ViewHeader({ icon, eyebrow, title, subtitle, actions }) {
  return (
    <header className="view-header">
      <div className="view-header-main">
        {icon ? (
          <span className="view-header-icon">
            <Icon name={icon} size={20} />
          </span>
        ) : null}
        <div>
          {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
          <h1>{title}</h1>
          {subtitle ? <p className="view-subtitle">{subtitle}</p> : null}
        </div>
      </div>
      {actions ? <div className="view-header-actions">{actions}</div> : null}
    </header>
  );
}

function formatCount(value) {
  return Number(value || 0).toLocaleString();
}

// --------------------------------------------------------------------------
// Schema-driven argument form (native tools / raw calls)
// --------------------------------------------------------------------------
function nonNullSchema(prop) {
  if (!prop || !Array.isArray(prop.anyOf)) return prop || {};
  return prop.anyOf.find((item) => item && item.type !== "null") || prop;
}

function schemaFields(schema) {
  if (!schema || !schema.properties) return [];
  const required = new Set(schema.required || []);
  return Object.entries(schema.properties).map(([name, prop]) => {
    const p = nonNullSchema(prop);
    const itemSchema = nonNullSchema(p.items || {});
    return {
      name,
      type: p.type || "string",
      enum: p.enum,
      itemEnum: itemSchema.enum,
      itemSchema,
      fields: p.type === "object" ? schemaFields(p) : [],
      description: prop.description || p.description || "",
      default: p.default,
      required: required.has(name),
    };
  });
}

function isEmptyObject(value) {
  return (
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).length === 0
  );
}

function coerce(field, raw) {
  if (raw === "" || raw == null) return undefined;
  if (field.type === "integer") return parseInt(raw, 10);
  if (field.type === "number") return parseFloat(raw);
  if (field.type === "boolean") return raw === true || raw === "true";
  if (field.type === "object") {
    if (typeof raw === "object" && !Array.isArray(raw)) {
      return isEmptyObject(raw) ? undefined : raw;
    }
    try {
      return JSON.parse(raw);
    } catch {
      return raw;
    }
  }
  if (field.type === "array") {
    if (Array.isArray(raw)) return raw.length ? raw : undefined;
    try {
      return JSON.parse(raw);
    } catch {
      const parts = String(raw)
        .split(",")
        .map((part) => part.trim())
        .filter(Boolean);
      return parts.length ? parts : undefined;
    }
  }
  return raw;
}

function buildValue(field, raw) {
  if (field.type === "object" && field.fields.length) {
    return buildArgs(field.fields, raw || {});
  }
  return coerce(field, raw);
}

function fieldPlaceholder(field) {
  if (field.default !== undefined) return `default: ${JSON.stringify(field.default)}`;
  if (field.type === "array" && field.itemEnum) return "comma-separated values";
  if (field.type === "array") return "JSON array";
  if (field.type === "object") return "JSON object";
  return field.type;
}

function ArgForm({ fields, values, setValues, nested = false }) {
  const formId = useId();
  if (!fields.length) return <div className="muted small">No arguments.</div>;
  return (
    <div className={"arg-form " + (nested ? "nested" : "")}>
      {fields.map((f) => (
        <div className={"form-row " + (f.type === "object" ? "object-row" : "")} key={f.name}>
          <label htmlFor={`${formId}-${f.name}`} title={f.description}>
            <code>{f.name}</code>
            {f.required ? <Pill kind="req">required</Pill> : null}
          </label>
          {f.type === "object" && f.fields.length ? (
            <div className="nested-object">
              <ArgForm
                fields={f.fields}
                values={values[f.name] || {}}
                nested
                setValues={(next) => setValues({ ...values, [f.name]: next })}
              />
            </div>
          ) : f.type === "boolean" ? (
            <UiNativeSelect id={`${formId}-${f.name}`}
              value={values[f.name] ?? ""}
              onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
            >
              <option value="">(unset)</option>
              <option value="true">true</option>
              <option value="false">false</option>
            </UiNativeSelect>
          ) : f.enum ? (
            <UiNativeSelect id={`${formId}-${f.name}`}
              value={values[f.name] ?? ""}
              onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
            >
              <option value="">(unset)</option>
              {f.enum.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </UiNativeSelect>
          ) : f.type === "array" || f.type === "object" ? (
            <UiTextarea id={`${formId}-${f.name}`}
              rows={f.type === "array" && f.itemEnum ? 2 : 4}
              placeholder={fieldPlaceholder(f)}
              value={values[f.name] ?? ""}
              onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
            />
          ) : (
            <UiInput id={`${formId}-${f.name}`}
              type={f.type === "integer" || f.type === "number" ? "number" : "text"}
              placeholder={fieldPlaceholder(f)}
              value={values[f.name] ?? ""}
              onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
            />
          )}
          {f.type === "array" && f.itemEnum ? (
            <span className="hint">
              Allowed values: <code>{f.itemEnum.join(", ")}</code>
            </span>
          ) : null}
          {f.description ? <span className="hint">{f.description}</span> : null}
        </div>
      ))}
    </div>
  );
}

function buildArgs(fields, values) {
  const args = {};
  for (const f of fields) {
    const c = buildValue(f, values[f.name]);
    if (c !== undefined && !isEmptyObject(c)) args[f.name] = c;
  }
  return args;
}

// --------------------------------------------------------------------------
// Tool activity
// --------------------------------------------------------------------------
function tryParseJson(value) {
  if (value == null) return null;
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value);
  } catch {
    // result_preview may be truncated with a trailing "..."; try stripping it.
    const trimmed = value.replace(/\s*\.\.\.\s*$/, "");
    try {
      return JSON.parse(trimmed);
    } catch {
      return null;
    }
  }
}

function formatNumber(value) {
  if (value == null || value === "") return "—";
  if (typeof value !== "number") return String(value);
  if (!Number.isFinite(value)) return String(value);
  if (Number.isInteger(value)) return value.toLocaleString();
  const abs = Math.abs(value);
  if (abs >= 100) return value.toFixed(1);
  if (abs >= 1) return value.toFixed(2);
  return value.toFixed(3);
}

function formatPercent(value) {
  if (value == null) return "—";
  if (typeof value !== "number" || !Number.isFinite(value)) return String(value);
  return (value * 100).toFixed(1) + "%";
}

const PERCENT_COLS = new Set(["top4_rate", "win_rate", "pick_rate_per_board"]);
const PLACEMENT_COLS = new Set([
  "avg_placement",
  "avg_placement_on_board",
]);

function prettifyKey(key) {
  return String(key).replace(/_/g, " ");
}

function shortenId(value) {
  if (typeof value !== "string") return value;
  // Strip noisy set prefixes / item prefixes for readability while staying truthful.
  return value
    .replace(/^TFT\d+_/, "")
    .replace(/^TFT_Item_/, "")
    .replace(/^Set\d+_/, "");
}

function formatCell(column, value) {
  if (value == null) return <span className="muted">—</span>;
  if (Array.isArray(value)) {
    return value.map((v) => shortenId(v)).join(", ");
  }
  if (PERCENT_COLS.has(column)) return formatPercent(value);
  if (PLACEMENT_COLS.has(column)) return formatNumber(value);
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "string") {
    const short = shortenId(value);
    return short === value ? (
      <span title={value}>{value}</span>
    ) : (
      <span title={value}>{short}</span>
    );
  }
  return JSON.stringify(value);
}

function MiniTable({ columns, rows, caption }) {
  if (!rows || !rows.length) return null;
  return (
    <div className="mini-table-wrap">
      {caption ? <div className="mini-table-caption">{caption}</div> : null}
      <UiTable className="mini-table">
        <UiTableHeader>
          <UiTableRow>
            {columns.map((c) => (
              <UiTableHead key={c}>{prettifyKey(c)}</UiTableHead>
            ))}
          </UiTableRow>
        </UiTableHeader>
        <UiTableBody>
          {rows.map((row, i) => (
            <UiTableRow key={i}>
              {columns.map((c) => (
                <UiTableCell
                  key={c}
                  className={
                    typeof row[c] === "number" ? "num" : ""
                  }
                >
                  {formatCell(c, row[c])}
                </UiTableCell>
              ))}
            </UiTableRow>
          ))}
        </UiTableBody>
      </UiTable>
    </div>
  );
}

function recordsToTable(records, caption) {
  if (!Array.isArray(records) || !records.length) return null;
  if (!records.every((r) => r && typeof r === "object" && !Array.isArray(r))) {
    return null;
  }
  const cols = [];
  const seen = new Set();
  for (const row of records) {
    for (const k of Object.keys(row)) {
      if (!seen.has(k)) {
        seen.add(k);
        cols.push(k);
      }
    }
  }
  return <MiniTable columns={cols} rows={records} caption={caption} />;
}

function ScalarGrid({ entries }) {
  if (!entries.length) return null;
  return (
    <div className="kv-grid">
      {entries.map(([k, v]) => (
        <div className="kv-row" key={k}>
          <div className="kv-key">{prettifyKey(k)}</div>
          <div className="kv-val">{formatCell(k, v)}</div>
        </div>
      ))}
    </div>
  );
}

function splitScalarsAndLists(obj) {
  const scalars = [];
  const records = [];
  const nested = [];
  for (const [k, v] of Object.entries(obj || {})) {
    if (v == null) continue;
    if (Array.isArray(v)) {
      if (v.length === 0) continue;
      if (v.every((x) => x && typeof x === "object" && !Array.isArray(x))) {
        records.push([k, v]);
      } else {
        scalars.push([k, v]);
      }
    } else if (typeof v === "object") {
      nested.push([k, v]);
    } else {
      scalars.push([k, v]);
    }
  }
  return { scalars, records, nested };
}

function StatsResultBody({ data }) {
  if (data == null) return null;
  // Lists at the top level: render each as its own table.
  if (Array.isArray(data)) {
    const table = recordsToTable(data);
    return table || <Json value={data} />;
  }
  if (typeof data !== "object") {
    return <ScalarGrid entries={[["value", data]]} />;
  }
  const { scalars, records, nested } = splitScalarsAndLists(data);
  return (
    <div className="pretty-body">
      {scalars.length ? <ScalarGrid entries={scalars} /> : null}
      {nested.map(([k, v]) => (
        <div key={k} className="pretty-section">
          <div className="pretty-section-label">{prettifyKey(k)}</div>
          {Array.isArray(v) ? (
            recordsToTable(v) || <Json value={v} />
          ) : (
            <ScalarGrid entries={Object.entries(v)} />
          )}
        </div>
      ))}
      {records.map(([k, v]) => (
        <div key={k} className="pretty-section">
          <div className="pretty-section-label">
            {prettifyKey(k)}
            <span className="muted small"> · {v.length}</span>
          </div>
          {recordsToTable(v)}
        </div>
      ))}
    </div>
  );
}

function QueryResultBody({ data }) {
  if (data == null) return null;
  if (
    data &&
    typeof data === "object" &&
    Array.isArray(data.columns) &&
    Array.isArray(data.rows)
  ) {
    const cols = data.columns;
    const objRows = data.rows.map((row) => {
      if (Array.isArray(row)) {
        const obj = {};
        cols.forEach((c, i) => {
          obj[c] = row[i];
        });
        return obj;
      }
      return row;
    });
    return (
      <div className="pretty-body">
        <div className="query-meta">
          <Pill>{data.row_count ?? objRows.length} rows</Pill>
          <Pill kind="opt">{cols.length} cols</Pill>
        </div>
        <MiniTable columns={cols} rows={objRows} />
      </div>
    );
  }
  // describe_query_schema returns a schema object; fall back to stats-style rendering.
  return <StatsResultBody data={data} />;
}

function ArgsSummary({ args }) {
  const entries = Object.entries(args || {}).filter(
    ([, v]) => v != null && !(Array.isArray(v) && v.length === 0),
  );
  if (!entries.length) {
    return <div className="muted small">no arguments</div>;
  }
  return (
    <div className="kv-grid">
      {entries.map(([k, v]) => {
        let display;
        if (Array.isArray(v)) {
          display = v.map((x) => shortenId(x)).join(", ");
        } else if (v && typeof v === "object") {
          const sub = Object.entries(v)
            .filter(([, sv]) => sv != null && sv !== "")
            .map(([sk, sv]) => `${sk}=${shortenId(sv)}`)
            .join(", ");
          display = sub || "{}";
        } else {
          display = shortenId(v);
        }
        return (
          <div className="kv-row" key={k}>
            <div className="kv-key">{prettifyKey(k)}</div>
            <div className="kv-val arg-val" title={String(display)}>
              {String(display)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ToolEvent({ event, groupKey }) {
  const [open, setOpen] = useState(false);
  const [rawArgs, setRawArgs] = useState(false);
  const [rawResult, setRawResult] = useState(false);
  // Prefer the full structured result emitted by the backend; fall back to
  // parsing the (possibly truncated) string preview for older events.
  const parsedResult = useMemo(
    () =>
      event.result !== undefined && event.result !== null
        ? event.result
        : tryParseJson(event.result_preview),
    [event.result, event.result_preview],
  );
  // Every tool result that decodes to structured data gets the rich renderer.
  const canPrettyResult =
    parsedResult != null &&
    (typeof parsedResult === "object" || Array.isArray(parsedResult));
  const hasResult = event.result != null || !!event.result_preview;
  const hasArgs =
    event.arguments && Object.keys(event.arguments).length > 0;
  const hasDetail = hasArgs || hasResult || event.error;

  const groupLabel = groupKey || event.type || "event";

  return (
    <div
      className={
        "tool-event " +
        (event.error ? "bad " : "") +
        (groupKey ? "group-" + groupKey : "")
      }
    >
      <div
        className={"tool-event-head " + (hasDetail ? "clickable" : "")}
        onClick={hasDetail ? () => setOpen((v) => !v) : undefined}
      >
        <Icon name={event.type === "handoff" ? "arrow-right" : "bolt"} size={14} />
        <code className="tool-event-name">{event.name || "tool"}</code>
        <span className="tool-event-type">{groupLabel}</span>
        {hasDetail ? (
          <Icon
            name="chevron"
            size={13}
            className={"chev " + (open ? "down" : "")}
          />
        ) : null}
      </div>
      {open ? (
        <div className="tool-event-body">
          {event.description ? (
            <p className="muted small">{event.description}</p>
          ) : null}
          {hasArgs ? (
            <div>
              <div className="tool-event-label">
                arguments
                <UiButton variant="ghost" size="sm"
                  type="button"
                  className="tiny-toggle"
                  onClick={() => setRawArgs((v) => !v)}
                >
                  {rawArgs ? "pretty" : "raw json"}
                </UiButton>
              </div>
              {rawArgs ? (
                <JsonBlock value={event.arguments} />
              ) : (
                <ArgsSummary args={event.arguments} />
              )}
            </div>
          ) : null}
          {hasResult ? (
            <div>
              <div className="tool-event-label">
                result
                {canPrettyResult ? (
                  <UiButton variant="ghost" size="sm"
                    type="button"
                    className="tiny-toggle"
                    onClick={() => setRawResult((v) => !v)}
                  >
                    {rawResult ? "pretty" : "raw json"}
                  </UiButton>
                ) : null}
              </div>
              {canPrettyResult && !rawResult ? (
                groupKey === "query" ? (
                  <QueryResultBody data={parsedResult} />
                ) : (
                  <StatsResultBody data={parsedResult} />
                )
              ) : (
                <JsonBlock
                  value={
                    event.result !== undefined && event.result !== null
                      ? event.result
                      : event.result_preview
                  }
                />
              )}
            </div>
          ) : null}
          {event.error ? (
            <div className="statusline bad">{event.error}</div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function ResourceEvent({ event }) {
  const [open, setOpen] = useState(false);
  const isContext = event.type === "context";
  const hasDetail = !!(event.description || event.path || event.content);
  return (
    <div className={"tool-event resource-event resource-" + event.type}>
      <div
        className={"tool-event-head " + (hasDetail ? "clickable" : "")}
        onClick={hasDetail ? () => setOpen((value) => !value) : undefined}
      >
        <Icon name={isContext ? "info" : "tasks"} size={14} />
        <code className="tool-event-name">{event.name}</code>
        <span className="tool-event-type">{event.type}</span>
        {hasDetail ? (
          <Icon
            name="chevron"
            size={13}
            className={"chev " + (open ? "down" : "")}
          />
        ) : null}
      </div>
      {open ? (
        <div className="tool-event-body">
          {event.description ? (
            <p className="muted small">{event.description}</p>
          ) : null}
          {event.path ? (
            <code className="resource-path">
              {event.path}{event.line ? ":" + event.line : ""}
            </code>
          ) : null}
          {event.content ? (
            <div className="resource-content">
              <Markdown value={event.content} />
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function TraceEvent({ event }) {
  return (
    <div className="activity-trace">
      <Icon name="info" size={14} />
      <div className="activity-trace-detail">
        <span className="activity-trace-name">{event.name || "OpenAI trace"}</span>
        <code title={event.trace_id}>{event.trace_id}</code>
      </div>
      <CopyButton text={event.trace_id} label="trace ID" />
      <a
        className="ghost tiny activity-trace-link"
        href={openAiTraceUrl(event.trace_id)}
        target="_blank"
        rel="noreferrer"
        title="Open in the OpenAI Traces dashboard"
      >
        OpenAI
      </a>
    </div>
  );
}

function ToolTrace({ events, toolGroupOf }) {
  if (!events || !events.length) return null;
  return (
    <div className="tool-trace">
      {events.map((e, i) => (
        <ToolEvent
          key={i}
          event={e}
          groupKey={toolGroupOf ? toolGroupOf[e.name] : undefined}
        />
      ))}
    </div>
  );
}

// --------------------------------------------------------------------------
// Chat
// --------------------------------------------------------------------------
const INITIAL_MESSAGE = {
  role: "assistant",
  content:
    "Ask about the meta. I read straight from the match data — comps, exact builds, placement deltas — and I call out thin samples instead of guessing.",
};

// Keep the starter prompt feature available for a future configured list.
const STARTER_PROMPTS = [];

function ChatMessage({ message, streaming }) {
  if (message.role === "user") {
    return (
      <div className="msg msg-user">
        <div className="msg-bubble">
          <p className="user-text">{message.content}</p>
        </div>
      </div>
    );
  }
  // Tool and handoff calls are surfaced in the side Activity panel, not inline.
  const { text, error } = parseAssistant(message.content || "");
  return (
    <div className="msg msg-assistant">
      <div className="msg-avatar">
        <Logo size={22} />
      </div>
      <div className="msg-body">
        {text ? (
          <Markdown value={text} />
        ) : streaming ? (
          <p className="muted typing">
            <span className="dots">
              <span />
              <span />
              <span />
            </span>{" "}
            thinking
          </p>
        ) : null}
        {(message.presentations || []).map((presentation) => <EvidenceDisplay key={presentation.id} presentation={presentation} />)}
        {message.presentationError ? <p role="status">{message.presentationError}</p> : null}
        {error ? (
          <div className="statusline bad">
            <Icon name="alert" size={13} /> {error}
          </div>
        ) : null}
        {text && !streaming ? (
          <div className="msg-actions">
            <CopyButton text={text} />
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ChatView({ config, reloadConfig, isActive }) {
  const [messages, setMessages] = useState([INITIAL_MESSAGE]);
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedModel, setSelectedModel] = useLocalStorage(
    "chatModel",
    "",
  );
  const [selectedAssistant, setSelectedAssistant] = useLocalStorage(
    "chatAssistant",
    "",
  );
  // Start with the answer visible when Activity would occupy an overlay.
  const [showInspector, setShowInspector] = useState(() => window.matchMedia ? window.matchMedia("(min-width: 1081px)").matches : true);
  const [inspectorWidth, setInspectorWidth] = useLocalStorage(
    "inspectorWidth",
    380,
  );
  const logRef = useRef(null);
  const activityRef = useRef(null);
  const reading = useRef({ messages: { top: 0, follow: true }, activity: { top: 0, follow: true } });
  const resizingRef = useRef(false);

  // Drag-to-resize the activity panel. Listeners are bound once; the drag
  // state lives in a ref so we don't re-bind on every pointer move.
  useEffect(() => {
    const onMove = (e) => {
      if (!resizingRef.current) return;
      const next = window.innerWidth - e.clientX;
      const max = Math.max(320, window.innerWidth - 420);
      setInspectorWidth(Math.min(Math.max(next, 280), max));
    };
    const onUp = () => {
      if (!resizingRef.current) return;
      resizingRef.current = false;
      document.body.classList.remove("resizing-x");
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  const startResize = (e) => {
    e.preventDefault();
    resizingRef.current = true;
    document.body.classList.add("resizing-x");
  };

  const onlyGreeting = messages.length <= 1;
  const assistantNames = config?.assistants?.length
    ? config.assistants
    : [config?.default_assistant || AssistantName.CHAT];
  const assistantName = assistantNames.includes(selectedAssistant)
    ? selectedAssistant
    : assistantNames.includes(config?.default_assistant)
      ? config.default_assistant
      : assistantNames[0];
  const model =
    config?.models?.find((candidate) => candidate.id === selectedModel) ||
    config?.models?.find((candidate) => candidate.id === config?.default_model) ||
    config?.models?.[0];
  const toolGroupOf = useMemo(() => {
    const map = {};
    (config?.tool_groups || []).forEach((group) => {
      (group.tools || []).forEach((tool) => {
        map[tool.name] = group.key;
      });
    });
    return map;
  }, [config?.tool_groups]);

  // Accumulate tool and handoff calls across the whole conversation into one
  // chronological feed for the side panel.
  const activity = useMemo(() => {
    const items = [];
    messages.forEach((m, turn) => {
      if (m.role !== "assistant") return;
      (m.events || []).forEach((event) =>
        ["trace", "context", "skill", "tool", "handoff"].includes(event.type)
          ? items.push({ kind: "event", event, turn })
          : null,
      );
    });
    return items;
  }, [messages]);

  function clearConversation() {
    if (busy) return;
    setMessages([INITIAL_MESSAGE]);
    reading.current = { messages: { top: 0, follow: true }, activity: { top: 0, follow: true } };
    setError("");
  }

  // Hidden panes defer scrolling; returning restores the user's reading position.
  useEffect(() => {
    if (!isActive) return;
    for (const [key, ref] of [["messages", logRef], ["activity", activityRef]]) {
      const node = ref.current;
      if (node) node.scrollTop = reading.current[key].follow ? node.scrollHeight : reading.current[key].top;
    }
  }, [messages, activity.length, isActive]);

  /** Record whether the reader wants new output to follow the bottom. */
  function rememberScroll(key, event) {
    if (!isActive) return;
    const node = event.currentTarget;
    reading.current[key] = { top: node.scrollTop, follow: node.scrollHeight - node.scrollTop - node.clientHeight < 48 };
  }

  async function send(text = input) {
    if (!text.trim() || busy) return;
    setBusy(true);
    reading.current.messages.follow = true;
    setError("");
    const nextMessages = [
      ...messages.filter((m) => m.role !== "system"),
      { role: "user", content: text.trim() },
    ];
    // Surface definitions and activity metadata are browser state, not chat
    // history. Keep the API contract text-only when a later turn is sent.
    const historyMessages = nextMessages
      .filter((m) => ["user", "assistant"].includes(m.role))
      .map(({ role, content }) => ({ role, content }));
    setMessages([...nextMessages, { role: "assistant", content: "", events: [] }]);
    setInput("");
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "X-Chat-Assistant": assistantName,
        },
        body: JSON.stringify({
          model: model?.id || selectedModel,
          messages: historyMessages,
        }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let pending = "";
      let displayablePartCount = 0;
      let textPart = "";
      const applyConsumed = (consumed) => {
        let formattedText = "";
        const activityEvents = [];
        const presentations = [];
        let presentationError = null;
        for (const segment of consumed.segments) {
          if (segment.type === "text") {
            textPart += segment.value;
            continue;
          }
          const event = segment.value;
          if (event.type === "text_part_complete") {
            if (textPart) {
              formattedText += formatChatPart(textPart, ++displayablePartCount);
              textPart = "";
            }
            continue;
          }
          if (event.type === "presentation") {
            if (event.presentation?.id) presentations.push(event.presentation);
            else presentationError = "Evidence view unavailable.";
            continue;
          }
          if (event.type === "presentation_error") {
            presentationError = "Evidence view unavailable.";
            continue;
          }
          activityEvents.push(event);
        }
        if (activityEvents.length || formattedText || presentations.length || presentationError) {
          setMessages((prev) => {
            const copy = [...prev];
            const last = { ...copy[copy.length - 1] };
            if (formattedText) last.content = (last.content || "") + formattedText;
            if (activityEvents.length) last.events = [...(last.events || []), ...activityEvents];
            if (presentations.length) {
              const existing = last.presentations || [];
              last.presentations = [...existing, ...presentations.filter((item) => !existing.some((old) => old.id === item.id))];
              last.presentationError = null;
            }
            if (presentationError) last.presentationError = presentationError;
            copy[copy.length - 1] = last;
            return copy;
          });
        }
      };
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        const consumed = consumeStreamBuffer(pending + decoder.decode(value, { stream: true }));
        pending = consumed.pending;
        applyConsumed(consumed);
      }
      applyConsumed(consumeStreamBuffer(pending + decoder.decode()));
      if (textPart) {
        applyConsumed({
          segments: [{ type: "event", value: { type: "text_part_complete" } }],
        });
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className={"chat-shell " + (showInspector ? "with-inspector" : "")}
      style={{
        "--inspector-w":
          Math.max(280, Math.min(inspectorWidth, 1000)) + "px",
      }}
    >
      <section className="chat-main">
        <header className="chat-bar">
          <div className="chat-bar-title">
            <h1>ChatTFT</h1>
            <span className="muted small">Meta analyst over your match data</span>
          </div>
          <div className="chat-bar-actions">
            <label className="assistant-select">
              <span>Assistant</span>
              <UiNativeSelect
                aria-label="Assistant"
                value={assistantName}
                onChange={(event) => setSelectedAssistant(event.target.value)}
                disabled={busy || !config?.assistants?.length}
              >
                {assistantNames.map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </UiNativeSelect>
            </label>
            <label
              className={
                "model-chip " + (model?.key_configured ? "ok" : "warn")
              }
              title={model?.key_configured ? "API key configured" : "API key missing"}
            >
              <span className="status-dot small" />
              <UiNativeSelect
                aria-label="Chat model"
                value={model?.id || ""}
                onChange={(event) => setSelectedModel(event.target.value)}
                disabled={busy || !config?.models?.length}
              >
                {(config?.models || []).map((candidate) => (
                  <option key={candidate.id} value={candidate.id}>
                    {candidate.label}
                  </option>
                ))}
              </UiNativeSelect>
            </label>
            <IconButton
              icon="clear"
              label="New conversation"
              onClick={clearConversation}
              disabled={busy || onlyGreeting}
            />
            <span className="panel-toggle">
              {!showInspector && activity.length ? (
                <span className="panel-badge">{activity.length}</span>
              ) : null}
              <IconButton
                icon="panel"
                label={showInspector ? "Hide activity" : "Show activity"}
                active={showInspector}
                onClick={() => setShowInspector((v) => !v)}
              />
            </span>
          </div>
        </header>

        <div
          className={"messages" + (onlyGreeting ? " messages-empty" : "")}
          ref={logRef}
          onScroll={(event) => rememberScroll("messages", event)}
        >
          <div className="messages-inner">
            {messages.map((m, i) => (
              <ChatMessage
                key={i}
                message={m}
                streaming={
                  busy && m.role === "assistant" && i === messages.length - 1
                }
              />
            ))}
            {onlyGreeting && STARTER_PROMPTS.length ? (
              <div className="starters">
                {STARTER_PROMPTS.map((s) => (
                  <UiButton variant="outline"
                    key={s.label}
                    className="starter h-auto whitespace-normal justify-start"
                    disabled={busy}
                    onClick={() => send(s.prompt)}
                  >
                    <span className="starter-label">{s.label}</span>
                    <span className="starter-prompt">{s.prompt}</span>
                  </UiButton>
                ))}
              </div>
            ) : null}
          </div>
        </div>

        <div className="composer-wrap">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
            className="composer"
          >
            <AutoTextarea
              value={input}
              minRows={1}
              maxHeight={200}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="Ask a TFT question…  (Enter to send · Shift+Enter for newline)"
            />
            <UiButton variant="default"
              className="send-btn"
              disabled={busy || !input.trim()}
              title="Send"
            >
              {busy ? <span className="spinner" /> : <Icon name="send" size={17} />}
            </UiButton>
          </form>
          {error ? (
            <p className="error">
              <Icon name="alert" size={14} /> {error}
            </p>
          ) : null}
        </div>
      </section>

      {showInspector ? (
        <aside className="inspector">
          <div
            className="inspector-resize"
            onMouseDown={startResize}
            title="Drag to resize"
            role="separator"
            aria-orientation="vertical"
          />
          <div className="inspector-head">
            <strong>Activity</strong>
            {activity.length ? (
              <span className="inspector-count">{activity.length}</span>
            ) : null}
            <IconButton
              icon="close"
              label="Close"
              onClick={() => setShowInspector(false)}
            />
          </div>
          <div className="inspector-body" ref={activityRef} onScroll={(event) => rememberScroll("activity", event)}>
            {activity.length ? (
              <div className="activity-feed">
                {activity.map((item, i) =>
                  item.event.type === "trace" ? (
                    <TraceEvent key={i} event={item.event} />
                  ) : ["context", "skill"].includes(item.event.type) ? (
                    <ResourceEvent key={i} event={item.event} />
                  ) : (
                    <ToolEvent
                      key={i}
                      event={item.event}
                      groupKey={toolGroupOf[item.event.name]}
                    />
                  ),
                )}
              </div>
            ) : (
              <div className="activity-empty">
                <Icon name="bolt" size={22} />
                <p className="muted small">
                  Selected context, skills, tool calls, and handoffs show up here
                  as the assistant works.
                </p>
              </div>
            )}
            <div className="inspector-ref">
              <Collapsible
                title="Tools available"
                subtitle={String((config?.tools || []).length)}
                defaultOpen={false}
              >
                <div className="chips">
                  {(config?.tools || []).map((t) => (
                    <Chip key={t.name}>{t.name}</Chip>
                  ))}
                </div>
              </Collapsible>
            </div>
          </div>
        </aside>
      ) : null}
    </div>
  );
}

// --------------------------------------------------------------------------
// Assistants & Tasks
// --------------------------------------------------------------------------
function ChipRow({ label, items }) {
  if (!items || !items.length) return null;
  return (
    <div className="chip-row">
      <span className="chip-row-label">{label}</span>
      {items.map((item) => (
        <Chip key={item}>{item}</Chip>
      ))}
    </div>
  );
}

function WorkflowResult({ result }) {
  const [raw, setRaw] = useState(false);
  if (!result) return null;
  const ok = result.ok;
  const text =
    ok && typeof result.result === "string"
      ? result.result
      : ok
        ? JSON.stringify(result.result, null, 2)
        : "";
  return (
    <Collapsible
      title="Result"
      subtitle={<Pill kind={ok ? "ok" : "bad"}>{ok ? "ok" : "error"}</Pill>}
      defaultOpen
      right={
        <>
          {text ? <CopyButton text={text} /> : null}
          <UiButton variant="ghost" size="sm" className="ghost tiny" onClick={() => setRaw((v) => !v)}>
            {raw ? "rendered" : "raw"}
          </UiButton>
        </>
      }
    >
      {raw ? (
        <Json value={result} />
      ) : ok ? (
        <div className="result-scroll">
          {typeof result.result === "string" ? (
            <Markdown value={result.result} />
          ) : (
            <Json value={result.result} />
          )}
        </div>
      ) : (
        <p className="error">{result.error || "Run failed."}</p>
      )}
    </Collapsible>
  );
}

function WorkflowCard({
  kind,
  workflow,
  placeholder,
  value,
  onChange,
  busy,
  onRun,
  result,
  elapsedMs,
}) {
  const w = workflow;
  const inputId = useId();
  return (
    <UiCard as="div" className="card workflow block gap-0 p-4 sm:p-6 shadow-xs">
      <div className="workflow-head">
        <h3>{w.name}</h3>
        <Pill kind="cat">{kind}</Pill>
      </div>
      {w.description ? (
        <p className="muted workflow-desc">{w.description}</p>
      ) : null}
      {(w.tools && w.tools.length) || (w.handoffs && w.handoffs.length) ? (
        <Collapsible
          title="Capabilities"
          subtitle={`${(w.tools || []).length} tools`}
          defaultOpen={false}
        >
          <div className="workflow-meta">
            <ChipRow label="tools" items={w.tools} />
            <ChipRow label="handoffs" items={w.handoffs} />
          </div>
        </Collapsible>
      ) : null}
      <label className="field-label" htmlFor={inputId}>Input</label>
      <AutoTextarea
        id={inputId}
        minRows={3}
        maxHeight={360}
        placeholder={placeholder}
        value={value}
        onChange={onChange}
      />
      <div className="workflow-actions">
        <UiButton variant="default" className="run" onClick={onRun} disabled={busy}>
          {busy ? (
            <Spinner />
          ) : (
            <>
              <Icon name="play" size={14} /> Run
            </>
          )}
        </UiButton>
        {elapsedMs != null && !busy ? (
          <span className="muted small">finished in {elapsedMs} ms</span>
        ) : null}
      </div>
      <WorkflowResult result={result} />
    </UiCard>
  );
}

function WorkflowPicker({ workflows, selected, onToggle, onSelectAll, onClear }) {
  return (
    <aside className="workflow-picker">
      <div className="picker-head">
        <span className="picker-label">Show</span>
        <span className="picker-count">
          {selected.length} / {workflows.length}
        </span>
      </div>
      <div className="picker-chips">
        {workflows.map((w) => {
          const active = selected.includes(w.name);
          return (
            <UiButton variant={active ? "secondary" : "outline"}
              key={w.name}
              type="button"
              className={"picker-chip " + (active ? "active" : "")}
              aria-pressed={active}
              onClick={() => onToggle(w.name)}
              title={w.description || w.name}
            >
              <span className="picker-box">
                {active ? <Icon name="check" size={12} /> : null}
              </span>
              <span className="picker-chip-name">{w.name}</span>
            </UiButton>
          );
        })}
      </div>
      <div className="picker-actions">
        <UiButton variant="ghost" size="sm"
          className="ghost tiny"
          onClick={onSelectAll}
          disabled={selected.length === workflows.length}
        >
          All
        </UiButton>
        <UiButton variant="ghost" size="sm"
          className="ghost tiny"
          onClick={onClear}
          disabled={selected.length === 0}
        >
          None
        </UiButton>
      </div>
    </aside>
  );
}

function WorkflowView({ kind, navigation }) {
  const [workflows, setWorkflows] = useState([]);
  const [selected, setSelected] = useState([]);
  const [inputs, setInputs] = useState({});
  const [results, setResults] = useState({});
  const [elapsed, setElapsed] = useState({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const isTask = kind === "task";
  const copy = {
    assistant: {
      icon: "sparkles",
      eyebrow: "Assistants",
      title: "Focused TFT assistants",
      description:
        "Each assistant turns a focused request into a reusable analysis pass.",
      empty: "No assistants are registered.",
      placeholder: "Provide input for this assistant…",
    },
    task: {
      icon: "tasks",
      eyebrow: "Tasks",
      title: "Repeatable TFT tasks",
      description:
        "Tasks keep operational workflows separate from assistant prompts.",
      empty: "No tasks are registered.",
      placeholder: "Provide input for this task…",
    },
  }[kind];

  useEffect(() => {
    setLoading(true);
    setError("");
    api("/api/assistants")
      .then((d) => {
        const list = d[isTask ? "tasks" : "assistants"] || [];
        setWorkflows(list);
        // Default to showing only the first, so the page isn't a wall of cards.
        setSelected(list.length ? [list[0].name] : []);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [isTask]);

  function toggleSelected(name) {
    setSelected((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  }

  async function run(workflow) {
    const name = workflow.name;
    setBusy(name);
    setError("");
    const started = performance.now();
    try {
      const path = isTask
        ? `/api/assistants/tasks/${encodeURIComponent(name)}/run`
        : `/api/assistants/${encodeURIComponent(name)}/run`;
      const result = await api(path, {
        method: "POST",
        body: JSON.stringify({ input: inputs[name] || "" }),
      });
      setResults((prev) => ({ ...prev, [name]: result }));
    } catch (e) {
      setError(e.message);
    } finally {
      setElapsed((prev) => ({
        ...prev,
        [name]: Math.round(performance.now() - started),
      }));
      setBusy("");
    }
  }

  return (
    <div className="view">
      <ViewHeader
        icon={copy.icon}
        eyebrow={copy.eyebrow}
        title={copy.title}
        subtitle={copy.description}
      />
      {navigation}
      <div role="tabpanel" id="workflow-panel" aria-labelledby={`workflow-${kind}`} tabIndex={0}>
      {error ? (
        <p className="error">
          <Icon name="alert" size={14} /> {error}
        </p>
      ) : null}
      {loading ? (
        <UiCard as="div" className="card muted block gap-0 p-4 sm:p-6 shadow-xs">
          <Spinner label={`Loading ${copy.eyebrow.toLowerCase()}…`} />
        </UiCard>
      ) : workflows.length ? (
        <div className="workflow-layout">
          <WorkflowPicker
            workflows={workflows}
            selected={selected}
            onToggle={toggleSelected}
            onSelectAll={() => setSelected(workflows.map((w) => w.name))}
            onClear={() => setSelected([])}
          />
          {selected.length ? (
            <div className="workflow-list">
              {workflows
                .filter((w) => selected.includes(w.name))
                .map((w) => (
                  <WorkflowCard
                    key={w.name}
                    kind={kind}
                    workflow={w}
                    placeholder={copy.placeholder}
                    value={inputs[w.name] || ""}
                    onChange={(e) =>
                      setInputs((p) => ({ ...p, [w.name]: e.target.value }))
                    }
                    busy={busy === w.name}
                    onRun={() => run(w)}
                    result={results[w.name]}
                    elapsedMs={elapsed[w.name]}
                  />
                ))}
            </div>
          ) : (
            <UiCard as="div" className="card block gap-0 p-4 sm:p-6 shadow-xs">
              <EmptyState icon={copy.icon} title="Nothing selected">
                Check {copy.eyebrow.toLowerCase()} in the side panel to display
                them.
              </EmptyState>
            </UiCard>
          )}
        </div>
      ) : (
        <UiCard as="div" className="card block gap-0 p-4 sm:p-6 shadow-xs">
          <EmptyState icon={copy.icon} title={copy.empty} />
        </UiCard>
      )}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
/** Group assistant and task execution in the main Workflows destination. */
function WorkflowsView({ kind, setKind }) {
  // Remount the runner so inputs cannot cross workflow categories.
  return (
    <WorkflowView key={kind} kind={kind} navigation={
      <Tabs value={kind} onValueChange={setKind}>
        <TabsList aria-label="Workflow categories">
          <TabsTrigger id="workflow-assistant" aria-controls="workflow-panel" value="assistant">Assistants</TabsTrigger>
          <TabsTrigger id="workflow-task" aria-controls="workflow-panel" value="task">Tasks</TabsTrigger>
        </TabsList>
      </Tabs>
    } />
  );
}

const DEVELOPER_TABS = [
  ["overview", "Status", OverviewTab],
  ["models", "Models", ModelsTab],
  ["tools", "Tools", ToolsTab],
  ["raw", "Raw API", RawTab],
  ["response-tuning", "Prompt tuning", ResponseTuningTab],
  ["specs", "Specs", SpecsTab],
];

/** Group application diagnostics and editors in the Developer page. */
function DeveloperView({ tab, setTab }) {
  const Active = (DEVELOPER_TABS.find((item) => item[0] === tab) || DEVELOPER_TABS[0])[2];
  return (
    <div className="view">
      <ViewHeader icon="data" eyebrow="Developer" title="Developer workspace"
        subtitle="Inspect application tools, test upstream calls, and edit assistant definitions." />
      <Tabs value={tab} onValueChange={setTab} className="mb-4 min-w-0">
        <TabsList aria-label="Developer sections" className="h-auto max-w-full flex-wrap justify-start">
          {DEVELOPER_TABS.map(([id, label]) => <TabsTrigger key={id} id={`developer-${id}`} aria-controls="developer-panel" value={id}>{label}</TabsTrigger>)}
        </TabsList>
      </Tabs>
      <UiCard as="div" role="tabpanel" id="developer-panel" aria-labelledby={`developer-${tab}`} tabIndex={0} className="card explorer-card developer-section block gap-0 p-4 sm:p-6 shadow-xs"><Active /></UiCard>
    </div>
  );
}

// --------------------------------------------------------------------------
// App shell
// --------------------------------------------------------------------------
const NAV = [
  { id: "chat", label: "Chat", icon: "chat" },
  { id: "workflows", label: "Workflows", icon: "tasks" },
  { id: "developer", label: "Developer", icon: "data" },
];

/** Navigate product destinations while preserving the app-owned saved state. */
function Sidebar({ tab, setTab }) {
  const { isMobile, setOpenMobile } = useSidebar();
  return (
    <SidebarPrimitive collapsible="icon">
      <SidebarHeader className="h-16 justify-center border-b px-4">
        <div className="flex items-center gap-3 overflow-hidden"><Logo size={28} /><span className="font-semibold group-data-[collapsible=icon]:hidden">ChatTFT</span></div>
      </SidebarHeader>
      <SidebarContent className="p-2">
        <nav aria-label="Primary navigation" className="nav-items">
          <SidebarMenu>
            {NAV.map((item) => (
              <SidebarMenuItem key={item.id}>
                <SidebarMenuButton isActive={tab === item.id} tooltip={item.label} aria-current={tab === item.id ? "page" : undefined}
                  onClick={() => { setTab(item.id); if (isMobile) setOpenMobile(false); }}>
                  <Icon name={item.icon} size={18} /><span>{item.label}</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        </nav>
      </SidebarContent>
      <SidebarFooter><SidebarTrigger /></SidebarFooter>
    </SidebarPrimitive>
  );
}

function App() {
  const [tab, setTab] = useLocalStorage("tft.tab", "chat");
  const [workflowKind, setWorkflowKind] = useLocalStorage("tft.workflowKind", "assistant");
  const [developerTab, setDeveloperTab] = useLocalStorage("tft.dataTab", "overview");
  useEffect(() => {
    // Preserve saved destinations from before the navigation consolidation.
    if (tab === "assistants" || tab === "tasks") {
      setWorkflowKind(tab === "tasks" ? "task" : "assistant");
      setTab("workflows");
    } else if (["data", "specs", "response-tuning"].includes(tab)) {
      if (tab !== "data") setDeveloperTab(tab);
      setTab("developer");
    } else if (!NAV.some((item) => item.id === tab)) {
      setTab("chat");
    }
    if (!["specs", "response-tuning"].includes(tab) &&
        !DEVELOPER_TABS.some((item) => item[0] === developerTab)) {
      setDeveloperTab("overview");
    }
  }, [tab, developerTab, setTab, setDeveloperTab, setWorkflowKind]);
  const [collapsed, setCollapsed] = useLocalStorage("tft.sidebarCollapsed", false);
  const [config, setConfig] = useState(null);

  const reloadConfig = useCallback(() => {
    api("/api/config")
      .then(setConfig)
      .catch(() => setConfig(null));
  }, []);
  useEffect(reloadConfig, [reloadConfig]);

  return (
    <SidebarProvider open={!collapsed} onOpenChange={(open) => setCollapsed(!open)} className="ui-app" style={{ "--sidebar-width": "232px", "--sidebar-width-icon": "64px" }}>
      <Sidebar
        tab={tab}
        setTab={setTab}
        collapsed={collapsed}
        setCollapsed={setCollapsed}
      />
      <main className="content ui-content">
        <div className="ui-mobile-header"><SidebarTrigger /><span>ChatTFT</span></div>
        {config?.database?.warning ? (
          <UiAlert className="app-warning" role="status">
            <Icon name="alert" size={17} />
            <div>
              <strong>Database unavailable</strong>
              <span>{config.database.warning}</span>
            </div>
          </UiAlert>
        ) : null}
        <div hidden={tab !== "chat"}>
          <ChatView config={config} reloadConfig={reloadConfig} isActive={tab === "chat"} />
        </div>
        {tab === "chat" ? null : tab === "workflows" ? (
          <WorkflowsView kind={workflowKind} setKind={setWorkflowKind} />
        ) : tab === "developer" ? (
          <DeveloperView tab={developerTab} setTab={setDeveloperTab} />
        ) : (
          <ChatView config={config} reloadConfig={reloadConfig} />
        )}
      </main>
    </SidebarProvider>
  );
}

export {
  api,
  apiGet,
  apiDelete,
  apiPatch,
  apiPost,
  apiPut,
  ArgForm,
  AutoTextarea,
  buildArgs,
  Collapsible,
  EmptyState,
  Icon,
  Json,
  Markdown,
  Pill,
  schemaFields,
  Spinner,
  useLocalStorage,
  ViewHeader,
};

// The Flowchart page pulls in React Flow; load it only for the /flowchart tab.
const Flowchart = React.lazy(() => import("./flowchart/Flowchart.jsx"));

/** Render a standalone desktop workspace page or the main ChatTFT application. */
function ApplicationRoot() {
  if (window.location.pathname.replace(/\/$/, "") === "/compositions") return <Compositions />;
  if (window.location.pathname.replace(/\/$/, "") === "/flowchart")
    return <React.Suspense fallback={<Spinner />}><Flowchart /></React.Suspense>;
  return window.location.pathname.replace(/\/$/, "") === "/rolldown"
    ? <RolldownTab />
    : <App />;
}

export default ApplicationRoot;
