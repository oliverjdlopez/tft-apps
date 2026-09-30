import { useConfirmation } from "@/components/shared/confirmation";
import { Input as UiInput } from "@/components/ui/input";
import { Button as UiButton } from "@/components/ui/button";
import { Badge as UiBadge } from "@/components/ui/badge";
import { Textarea as UiTextarea } from "@/components/ui/textarea";
import { useEffect, useState } from "react";
import {
  apiGet,
  apiPut,
  EmptyState,
  Icon,
  Pill,
  Spinner,
} from "../app.jsx";

// --------------------------------------------------------------------------
// Data explorer — Assistant specifications
// --------------------------------------------------------------------------
function SpecsTab() {
  const { confirm, confirmation } = useConfirmation();
  const [workspace, setWorkspace] = useState(null);
  const [activeDocument, setActiveDocument] = useState(null);
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    apiGet("/api/specs").then(setWorkspace).catch((err) => setError(err.message));
  }, []);

  async function openDocument(documentId, force = false) {
    if (!force && activeDocument && draft !== activeDocument.content && !await confirm("Discard your unsaved spec changes?")) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const document = await apiGet(`/api/specs/documents/${documentId}`);
      setActiveDocument(document);
      setDraft(document.content);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function saveDocument() {
    if (!activeDocument) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const saved = await apiPut(`/api/specs/documents/${activeDocument.id}`, {
        content: draft,
        revision: activeDocument.revision,
      });
      setActiveDocument(saved);
      setDraft(saved.content);
      setWorkspace(await apiGet("/api/specs"));
      setNotice(`Saved and validated ${saved.path}.`);

    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!workspace && !error) return <Spinner label="Loading assistant specs…" />;
  const normalizedQuery = query.trim().toLowerCase();
  const assistants = (workspace?.assistants || []).filter((assistant) =>
    !normalizedQuery || `${assistant.name} ${assistant.description} ${assistant.model || ""}`.toLowerCase().includes(normalizedQuery),
  );
  const dirty = Boolean(activeDocument && draft !== activeDocument.content);

  return (
    <div className="explorer-pane spec-pane">
      {confirmation}
      <div className="spec-intro">
        <div>
          <h3>Assistant specifications</h3>
          <p className="lead">Inspect and safely edit assistant prompts, task wrappers, models, tools, context policy, and handoffs.</p>
        </div>
        {workspace ? <Pill kind="cat">{workspace.assistants.length} assistants</Pill> : null}
      </div>
      <section className="spec-workspace">
        <div className="spec-workspace-head">
          <div>
            <div className="eyebrow">Edit & validate</div>
            <h3>Specs workspace</h3>
            <p className="muted small">Every save validates the complete assistant graph before reloading the runtime registry. Run evaluations and compare results in Promptfoo.</p>
          </div>
        </div>
        <div className="spec-workspace-grid">
          <aside className="spec-source-browser">
            <label className="search-box spec-source-search">
              <Icon name="search" size={14} />
              <UiInput value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter assistants" />
            </label>
            <div className="spec-source-list">
              {assistants.map((assistant) => (
                <div className="spec-source-group" key={assistant.name}>
                  <div className="spec-source-group-title">
                    <code>{assistant.name}</code>
                    <span>{assistant.model || "default model"}</span>
                  </div>
                  <p className="muted small">{assistant.description}</p>
                  <div className="spec-source-fragments">
                    {assistant.sources.map((source) => (
                      <UiButton aria-pressed={activeDocument?.id === source.document_id} variant={activeDocument?.id === source.document_id ? "secondary" : "outline"}
                        className={activeDocument?.id === source.document_id ? "active" : ""}
                        key={source.document_id}
                        onClick={() => openDocument(source.document_id)}
                      >
                        <span>{source.label}</span>
                        <code>{source.path.split("/").pop()}</code>
                      </UiButton>
                    ))}
                  </div>
                  {assistant.eval_suites.length ? <div className="chips">{assistant.eval_suites.map((suite) => <UiBadge variant="secondary" className="chip" key={suite}>{suite}</UiBadge>)}</div> : null}
                </div>
              ))}
              {!assistants.length ? <div className="muted small spec-source-empty">No matching assistants.</div> : null}
            </div>
          </aside>
          <div className="spec-editor-panel">
            {activeDocument ? <>
              <div className="spec-editor-head">
                <div>
                  <div className="spec-editor-title">
                    <strong>{activeDocument.assistant} / {activeDocument.label}</strong>
                    <Pill kind="cat">{activeDocument.language}</Pill>
                    {dirty ? <Pill kind="warn">unsaved</Pill> : null}
                  </div>
                  <code>{activeDocument.path}</code>
                </div>
                <UiButton variant="ghost" size="sm" className="ghost tiny" disabled={busy} onClick={() => openDocument(activeDocument.id, true)}><Icon name="refresh" size={12} /> Reload</UiButton>
              </div>
              {error ? <div className="error"><Icon name="alert" size={14} /> {error}</div> : null}
              {notice ? <div className="spec-editor-notice"><Icon name="check" size={14} /> {notice}</div> : null}
              <UiTextarea className="spec-source-editor" value={draft} onChange={(event) => { setDraft(event.target.value); setNotice(null); }} spellCheck="false" aria-label={`Edit ${activeDocument.label}`} />
              <div className="spec-editor-actions">
                <span className="muted small">Revision-checked; the full assistant graph must validate before the source is replaced.</span>
                <div>
                  <UiButton variant="default" className="run" disabled={busy || !dirty} onClick={saveDocument}>
                    {busy ? <><Spinner /> Working…</> : <>Save & validate</>}
                  </UiButton>
                </div>
              </div>
            </> : busy ? <Spinner label="Opening spec…" /> : <EmptyState icon="search" title="Choose a spec">Select an assistant source file to inspect and edit it here.</EmptyState>}
          </div>
        </div>
      </section>
      {!activeDocument && error ? <div className="error"><Icon name="alert" size={14} /> {error}</div> : null}
    </div>
  );
}

export default SpecsTab;
