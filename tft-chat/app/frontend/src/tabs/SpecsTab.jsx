import { useConfirmation } from "@/components/shared/confirmation";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useEffect, useRef, useState } from "react";
import { apiGet, apiPost, EmptyState, Spinner } from "../app.jsx";

const filesEqual = (a, b) => JSON.stringify(Object.entries(a || {}).sort()) === JSON.stringify(Object.entries(b || {}).sort());
const terminal = new Set(["completed", "failed", "interrupted"]);
const executed = run => run.kind === "trial"
  ? ["running", "completed", "failed"].includes(run.state)
  : ["running", "awaiting_scores", "completed"].includes(run.state) || (run.state === "failed" && Boolean(run.value.job?.result));

/** Edit saved assistant revisions and inspect their captured test results. */
export default function SpecsTab() {
  const { confirm, confirmation } = useConfirmation();
  const [workspace, setWorkspace] = useState(null);
  const [state, setState] = useState(null);
  const [files, setFiles] = useState({});
  const [file, setFile] = useState("system.md");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [dialog, setDialog] = useState(null);
  const [question, setQuestion] = useState("");
  const [datasets, setDatasets] = useState([]);
  const [dataset, setDataset] = useState("");
  const [cases, setCases] = useState([]);
  const [repetitions, setRepetitions] = useState(1);
  const [prompts, setPrompts] = useState([]);
  const [prompt, setPrompt] = useState("");
  const [version, setVersion] = useState("");
  const [runs, setRuns] = useState([]);
  const [availability, setAvailability] = useState("");
  const [selectedRevision, setSelectedRevision] = useState(null);
  const selected = useRef(null);

  useEffect(() => { apiGet("/api/specs").then(setWorkspace).catch(err => setError(err.message)); }, []);
  const dirty = Boolean(state && !filesEqual(files, state.draft?.files || state.active.files));
  const expected = () => ({ expected_draft: state.draft?.id || null, expected_active: state.active.hash, expected_source: state.source_hash });
  const accept = next => {
    setState(next); setFiles(next.draft?.files || next.active.files); setRuns(next.runs || []);
    setSelectedRevision(null); setFile(current => (next.draft?.files || next.active.files)[current] !== undefined ? current : "system.md");
  };

  // Poll receipt endpoints, never reload editor contents while the user types.
  useEffect(() => {
    if (!state || !runs.some(run => !terminal.has(run.state) && run.state !== "preparing")) return;
    const name = state.name;
    let stopped = false;
    const timer = setInterval(async () => {
      try {
        const updated = await Promise.all(runs.map(run => terminal.has(run.state) ? run : apiGet(`/api/specs/runs/${run.id}`)));
        if (!stopped && selected.current === name) setRuns(updated);
      } catch (err) { if (!stopped) setAvailability(err.message); }
    }, 2000);
    return () => { stopped = true; clearInterval(timer); };
  }, [state?.name, runs]);

  async function operation(action) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); } catch (err) { setError(err.message); } finally { setBusy(false); }
  }

  async function openAssistant(name) {
    if (dirty && !await confirm("Discard unsaved edits? Saved revisions remain in history.")) return;
    await operation(async () => {
      const next = await apiGet(`/api/specs/assistants/${name}`);
      selected.current = name; accept(next); setDialog(null); setAvailability("");
    });
  }

  async function mutation(action, extra = {}) {
    await operation(async () => {
      accept(await apiPost(`/api/specs/assistants/${state.name}/${action}`, { ...expected(), ...extra }));
      setNotice(action === "draft" ? "Draft saved. Active definitions are unchanged." : `${action === "apply" ? "Applied" : action === "restore" ? "Restored as a new draft" : "Draft discarded"}.`);
      setWorkspace(await apiGet("/api/specs"));
    });
  }

  async function openExperiments() {
    setDialog("experiment");
    await operation(async () => {
      try {
        const response = await apiGet(`/api/specs/assistants/${state.name}/datasets`);
        setDatasets(response.datasets); setDataset(response.datasets[0]?.name || ""); setCases([]); setRepetitions(1);
        setAvailability(response.datasets.length ? "" : "No registered live dataset reaches this assistant.");
      } catch (err) { setDatasets([]); setAvailability(err.message); }
    });
  }

  async function submitExperiment(forceNew = false) {
    await operation(async () => {
      const selection = { dataset, cases, repetitions: Number(repetitions) };
      const key = `specs-submission:${state.name}:${state.draft.id}:${JSON.stringify(selection)}`;
      let submissionId = forceNew ? null : localStorage.getItem(key);
      if (!submissionId) { submissionId = crypto.randomUUID(); localStorage.setItem(key, submissionId); }
      const receipt = await apiPost(`/api/specs/assistants/${state.name}/experiments`, { ...expected(), ...selection, submission_id: submissionId });
      setRuns(current => [receipt, ...current.filter(run => run.id !== receipt.id)]);
      setNotice(receipt.state === "preparing" ? "Submission reply uncertain. Retry uses the same identifier." : `Experiment ${receipt.state}.`);
      if (receipt.state !== "preparing") setDialog(null);
    });
  }

  async function openImport() {
    setDialog("import");
    await operation(async () => {
      const response = await apiGet(`/api/specs/assistants/${state.name}/prompts`);
      setPrompts(response.prompts); setPrompt(response.prompts[0]?.name || ""); setVersion(String(response.prompts[0]?.versions?.at(-1) || ""));
    });
  }

  const filtered = (workspace?.assistants || []).filter(item => `${item.name} ${item.description}`.toLowerCase().includes(query.toLowerCase()));
  const canTest = state?.draft && !dirty && state.validation.valid;
  const selectedDataset = datasets.find(row => row.name === dataset);
  const configuration = state?.configuration || state?.active.configuration;

  if (!workspace && !error) return <Spinner label="Loading assistant workspace…" />;
  return <div className="explorer-pane spec-pane">
    {confirmation}
    <div className="spec-intro"><div><h3>Assistant specifications</h3><p className="lead">Edit → save draft → try → compare → apply. Langfuse owns scored experiments and detailed comparisons.</p></div></div>
    {error && <div role="alert" className="error">{error}</div>}
    {notice && <div role="status" className="spec-editor-notice">{notice}</div>}
    <section className="spec-workspace"><div className="spec-workspace-grid">
      <aside className="spec-source-browser">
        <Input aria-label="Filter assistants" value={query} onChange={e => setQuery(e.target.value)} placeholder="Filter assistants" />
        <div className="spec-source-list">{filtered.map(item => <div className="spec-source-group" key={item.name}>
          <Button variant={state?.name === item.name ? "secondary" : "outline"} disabled={busy} onClick={() => openAssistant(item.name)}>{item.name}</Button>
          <p className="muted small">{item.description}</p>
        </div>)}</div>
      </aside>
      <div className="spec-editor-panel">{state ? <>
        <div className="spec-editor-head"><strong>{state.name}</strong><span>{dirty ? "Unsaved edits" : state.draft ? `Draft ${state.draft.id.slice(0, 8)}` : "Active definitions"}</span></div>
        {state.source_changed && <div className="spec-editor-notice">Repository files have changed outside the loaded runtime.
          <Button disabled={busy || dirty} onClick={() => operation(async () => {
            await apiPost("/api/specs/refresh", { expected_active: state.active.hash, expected_source: state.source_hash });
            accept(await apiGet(`/api/specs/assistants/${state.name}`)); setWorkspace(await apiGet("/api/specs"));
          })}>Refresh active definitions</Button></div>}
        <details><summary>Active instructions and configuration</summary><pre className="spec-readonly">{state.active.instructions}</pre><pre>{JSON.stringify(state.active.configuration, null, 2)}</pre></details>
        <p className="muted small">Model: {configuration?.resolved_model}; reasoning: {configuration?.reasoning || "default"}; tools: {configuration?.include_all_tools ? "all" : [...(configuration?.tool_group_keys || []), ...(configuration?.tool_names || [])].join(", ") || "none"}; handoffs: {configuration?.handoff_names?.join(", ") || "none"}; repository context: {configuration?.repository_context ? "enabled" : "disabled"}; skills: {configuration?.skill_names?.join(", ") ?? "all"}.</p>
        <div role="tablist" aria-label="Editable files">{["system.md", "agent.json", "task.md"].map(name => files[name] !== undefined ? <Button key={name} role="tab" aria-selected={file === name} onClick={() => setFile(name)}>{name}</Button> : <Button key={name} disabled={busy} onClick={() => { setFiles({ ...files, [name]: name === "agent.json" ? "{}\n" : "" }); setFile(name); }}>Add {name}</Button>)}</div>
        {file !== "system.md" && <Button disabled={busy} variant="ghost" onClick={() => { const next = { ...files }; delete next[file]; setFiles(next); setFile("system.md"); }}>Remove {file}</Button>}
        <Textarea className="spec-source-editor min-h-[26rem] font-mono" value={files[file] || ""} disabled={busy} spellCheck="false" aria-label={`Edit ${file}`} onChange={e => setFiles({ ...files, [file]: e.target.value })} />
        {!state.validation.valid && <div role="alert" className="error">Saved draft needs correction: {state.validation.errors.join("; ")}</div>}
        <div className="spec-editor-actions"><div className="spec-action-buttons">
          <Button disabled={busy || (!dirty && Boolean(state.draft))} onClick={() => mutation("draft", { files })}>Save draft</Button>
          <Button disabled={busy || !canTest} onClick={() => setDialog("trial")}>Try</Button>
          <Button disabled={busy || !canTest} onClick={openExperiments}>Run experiment</Button>
          <Button disabled={busy || !canTest} onClick={() => setDialog("apply")}>Apply</Button>
          <Button disabled={busy || dirty || !state.draft} onClick={async () => { if (await confirm("Discard the editable draft? Its revisions and results remain saved.")) await mutation("discard"); }}>Discard draft</Button>
          <Button disabled={busy || dirty} onClick={openImport}>Import from Langfuse</Button>
        </div></div>
        {dirty && <p className="muted small">Save all edits before testing or applying.</p>}
        <section aria-label="Saved results"><h4>Trials and experiments</h4>
          {!runs.length && <p className="muted small">This revision has no saved tests. Experiments are optional for Apply.</p>}
          {state.draft && !runs.some(run => run.revision === state.draft.id && executed(run)) && runs.length > 0 && <p>This draft revision has not been tested.</p>}
          {runs.map(run => <details key={run.id}><summary>{run.kind} · {run.state} · revision {run.revision.slice(0, 8)}{run.revision !== state.draft?.id ? " · earlier revision" : ""}</summary>
            {run.value.lineage?.active_registry_hash && run.value.lineage.active_registry_hash !== state.active.hash && <p>The active comparison definitions have since changed.</p>}
            <p>{run.value.question}</p><p>{run.value.error || run.value.receipt?.error || run.value.result?.error || run.value.job?.error}</p>
            {run.value.result && <><pre className="spec-readonly">{typeof run.value.result.output === "string" ? run.value.result.output : JSON.stringify(run.value.result.output, null, 2)}</pre><p>Usage: {run.value.result.token_usage?.total || 0} tokens</p></>}
            {(run.value.job?.result?.experiments || []).map((experiment, index) => <p key={index}>{experiment.name}: {experiment.passed ? "passed" : "failed"}{experiment.url && <> · <a href={experiment.url} target="_blank" rel="noreferrer">Open in Langfuse</a></>}</p>)}
            <details><summary>Captured definitions and run receipt</summary><pre className="spec-readonly">{JSON.stringify(run.value, null, 2)}</pre></details>
            {run.kind === "experiment" && terminal.has(run.state) && <Button disabled={busy || !canTest} onClick={async () => { await openExperiments(); }}>New comparison</Button>}
            {run.kind === "trial" && terminal.has(run.state) && <Button disabled={busy || dirty} onClick={() => { setQuestion(run.value.question); setDialog("trial"); }}>Retry question</Button>}
            <Button disabled={busy} onClick={() => operation(async () => { const updated = await apiGet(`/api/specs/runs/${run.id}`); setRuns(current => current.map(item => item.id === run.id ? updated : item)); })}>Refresh result</Button>
          </details>)}
        </section>
        <details><summary>Revision and apply history</summary>
          {(state.history?.revisions || []).map(revision => <p key={revision.id}><code>{revision.id.slice(0, 8)}</code> · {revision.validation.valid ? "valid" : "invalid"} · {new Date(revision.created * 1000).toLocaleString()} <Button disabled={busy} onClick={() => setSelectedRevision(revision)}>Inspect</Button> <Button disabled={busy || dirty} onClick={() => mutation("restore", { revision: revision.id })}>Restore revision</Button></p>)}
          {selectedRevision && <pre className="spec-readonly">{JSON.stringify(selectedRevision, null, 2)}</pre>}
          {(state.history?.events || []).map(event => <p key={event.id}>{event.action} · {event.revision?.slice(0, 8)}</p>)}
        </details>
      </> : <EmptyState icon="search" title="Choose an assistant">Select an assistant to edit a local draft.</EmptyState>}</div>
    </div></section>
    {dialog && <section className="spec-dialog" role="dialog" aria-label={dialog === "trial" ? "Try saved draft" : dialog === "apply" ? "Review and apply" : dialog === "import" ? "Import from Langfuse" : "Run experiment"}>
      <Button disabled={busy} variant="ghost" onClick={() => setDialog(null)}>Close</Button>
      {dialog === "trial" && <><h4>Try saved draft</h4><Textarea aria-label="Trial question" value={question} onChange={e => setQuestion(e.target.value)} /><p>Saved revision {state.draft?.id.slice(0, 8)} · 10 turns · 180 seconds</p><Button disabled={busy || !question.trim() || !canTest} onClick={() => operation(async () => {
        const receipt = await apiPost(`/api/specs/assistants/${state.name}/trials`, { ...expected(), question }); setRuns(current => [receipt, ...current]); setDialog(null); setNotice("Trial started. Results are retained when you leave this page.");
      })}>Start trial</Button></>}
      {dialog === "apply" && <><h4>Review all file changes</h4>{Object.entries(state.diff).map(([name, difference]) => <div key={name}><strong>{name}</strong><pre className="spec-readonly">{difference || "Optional file added or removed"}</pre></div>)}<p>Apply installs this validated revision for new invocations. Test outcomes do not block Apply.</p><Button disabled={busy || !canTest} onClick={async () => { await mutation("apply"); setDialog(null); }}>Apply reviewed draft</Button></>}
      {dialog === "experiment" && <><h4>Compare Active and Draft in Langfuse</h4>{availability && <p role="status">{availability}</p>}
        <label>Dataset <select aria-label="Experiment dataset" value={dataset} onChange={e => { setDataset(e.target.value); setCases([]); }}>{datasets.map(row => <option key={row.name} value={row.name}>{row.name} ({row.assistant})</option>)}</select></label>
        <label>Repetitions <Input aria-label="Repetitions" type="number" min="1" max="20" value={repetitions} onChange={e => setRepetitions(e.target.value)} /></label>
        <p>All active cases are selected by default. Concurrency: up to 4.</p>
        <details><summary>Optional case selection</summary>{selectedDataset?.cases.map(row => <label key={row.id} className="spec-case"><input type="checkbox" checked={cases.includes(row.id)} onChange={e => setCases(current => e.target.checked ? [...current, row.id] : current.filter(id => id !== row.id))} />{row.id}</label>)}</details>
        <Button disabled={busy || !dataset || !canTest || Number(repetitions) < 1 || Number(repetitions) > 20} onClick={() => submitExperiment()}>Submit comparison</Button>
        {runs.some(run => run.kind === "experiment" && terminal.has(run.state)) && <Button disabled={busy || !dataset || !canTest} onClick={() => submitExperiment(true)}>Submit a new comparison</Button>}
      </>}
      {dialog === "import" && <><h4>Import from Langfuse</h4><label>Prompt <select aria-label="Owned prompt" value={prompt} onChange={e => { setPrompt(e.target.value); setVersion(String(prompts.find(row => row.name === e.target.value)?.versions.at(-1) || "")); }}>{prompts.map(row => <option key={row.name}>{row.name}</option>)}</select></label>
        <label>Version <select aria-label="Prompt version" value={version} onChange={e => setVersion(e.target.value)}>{prompts.find(row => row.name === prompt)?.versions.map(value => <option key={value}>{value}</option>)}</select></label><p>Import saves a draft with provenance. It never applies automatically.</p>
        <Button disabled={busy || !prompt || !version || dirty} onClick={async () => { await mutation("import", { prompt, version: Number(version) }); setDialog(null); }}>Import as draft</Button>
      </>}
    </section>}
  </div>;
}
