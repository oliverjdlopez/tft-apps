import { Disclosure, DisclosureSummary } from "@/components/shared/disclosure";
import { Button as UiButton } from "@/components/ui/button";
import { useEffect, useState } from "react";
import { apiGet, apiPost, ArgForm, buildArgs, Icon, Json, schemaFields, Spinner } from "../app.jsx";

// Data explorer — Tools
// --------------------------------------------------------------------------
function ToolResult({ res }) {
  if (!res) return null;
  if (!res.ok)
    return (
      <div>
        <div className="statusline bad">error · {res.elapsed_ms} ms</div>
        <Json value={res.error} />
      </div>
    );
  return (
    <div>
      <div className="statusline ok">
        <Icon name="check" size={13} /> ok · {res.elapsed_ms} ms
      </div>
      <div className="explain">
        A native tool call returns JSON-compatible <b>structured output</b> that
        OpenAI can pass back into the conversation.
      </div>
      <h4>structured output</h4>
      <Json value={res.structured} />
    </div>
  );
}

function ToolCard({ tool }) {
  const [open, setOpen] = useState(false);
  const fields = schemaFields(tool.invocation_schema || tool.input_schema);
  const [values, setValues] = useState({});
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setRes(null);
    try {
      const r = await apiPost("/api/tools/call", {
        name: tool.name,
        arguments: buildArgs(fields, values),
      });
      setRes(r);
    } catch (e) {
      setRes({ ok: false, error: e.message, elapsed_ms: 0 });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="list-item">
      <UiButton variant="ghost" type="button" aria-expanded={open} className="head h-auto w-full justify-start whitespace-normal text-left" onClick={() => setOpen(!open)}>
        <Icon name="chevron" size={13} className={"chev " + (open ? "down" : "")} />
        <span className="name">{tool.name}</span>
        <span className="desc">{(tool.description || "").split("\n")[0]}</span>
      </UiButton>
      {open ? (
        <div className="body">
          <p className="muted prewrap">{tool.description}</p>
          <h4>arguments</h4>
          <ArgForm fields={fields} values={values} setValues={setValues} />
          <div className="run-row">
            <UiButton variant="default" className="run" disabled={busy} onClick={run}>
              {busy ? <Spinner /> : <><Icon name="play" size={14} /> call tool</>}
            </UiButton>
          </div>
          <ToolResult res={res} />
          <Disclosure>
            <DisclosureSummary>input / output schema</DisclosureSummary>
            <h4>input schema</h4>
            <Json value={tool.input_schema} />
            <h4>output schema</h4>
            <Json value={tool.output_schema} />
          </Disclosure>
        </div>
      ) : null}
    </div>
  );
}

function ToolsTab() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    apiGet("/api/tools").then(setData).catch((e) => setErr(e.message));
  }, []);
  if (err) return <div className="statusline bad">Failed to load: {err}</div>;
  if (!data) return <Spinner label="Loading…" />;
  return (
    <div className="explorer-pane">
      <p className="lead">
        Invoked through the native Python tool registry — exactly what OpenAI can
        call. Query, stats, and SQL tools are read-only and scoped to the
        current match projection.
      </p>
      {data.groups.map((g) => (
        <div key={g.key}>
          <h3>
            {g.label} <span className="muted small">({g.tools.length})</span>
          </h3>
          {g.description ? <p className="muted small">{g.description}</p> : null}
          {g.tools.map((t) => (
            <ToolCard key={t.name} tool={t} />
          ))}
        </div>
      ))}
    </div>
  );
}

// --------------------------------------------------------------------------
export default ToolsTab;
