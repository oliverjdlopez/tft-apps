/** Standalone patch gameplan workspace: workspace rail, entity palette, and flowchart canvas. */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Database, Download, FileJson, Import, Plus, RefreshCw, Trash2, Upload } from "lucide-react";
import { Button as UiButton } from "@/components/ui/button";
import { Input as UiInput } from "@/components/ui/input";
import { api, EmptyState } from "../app.jsx";
import {
  createGroup,
  createWorkspace,
  deleteGroup,
  deleteWorkspace,
  exportWorkspace,
  getWorkspace,
  importWorkspace,
  listGroups,
  listWorkspaces,
  loadCatalog,
  renameGroup,
  renameWorkspace,
  saveWorkspace,
} from "./api.js";
import EntitySidebar from "./EntitySidebar.jsx";
import FlowchartPanel from "./FlowchartPanel.jsx";
import { PatchWorkspaceSchema } from "./models.js";
import { catalogIndex, downloadWorkspace } from "./utils.js";
import "./flowchart.css";

const SAVE_DELAY_MS = 800;
const SAVE_LABELS = {
  idle: "",
  pending: "Unsaved changes",
  saving: "Saving…",
  saved: "Saved",
  error: "Save failed",
  conflict: "Conflict",
};

/**
 * Root of the `/flowchart` page loaded by the desktop Flowchart tab.
 *
 * Database workspaces autosave through a debounced, revision-checked loop.
 * Checked-in JSON workspaces open read-only and can be imported to the
 * database, which stays the single place edits happen.
 */
export default function Flowchart() {
  const [source, setSource] = useState(null);
  const [list, setList] = useState([]);
  const [record, setRecord] = useState(null);
  const [canvasKey, setCanvasKey] = useState(0);
  const [catalog, setCatalog] = useState(null);
  const [catalogError, setCatalogError] = useState("");
  const [saveState, setSaveState] = useState("idle");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [draftName, setDraftName] = useState("");
  const [form, setForm] = useState({ name: "", patch: "", set_number: "" });
  const [groups, setGroups] = useState(null);
  const [groupsError, setGroupsError] = useState("");
  // Filled by the canvas so the library tab can insert at the visible center.
  const insertRef = useRef(null);
  const fileInput = useRef(null);

  // The save loop runs outside React state so debounced timers always see the
  // newest revision and pending draft without re-creating callbacks.
  const current = useRef(null);
  const draft = useRef(null);
  const timer = useRef(null);
  const inflight = useRef(null);
  const conflicted = useRef(false);
  // A workspace to open once a source switch has reloaded the list.
  const preferred = useRef(null);

  /** Send the pending draft, rescheduling if more edits arrived while saving. */
  const flush = useCallback(() => {
    clearTimeout(timer.current);
    if (inflight.current) return inflight.current;
    if (!draft.current || !current.current || conflicted.current) return Promise.resolve();
    const target = current.current;
    const flowchart = draft.current;
    draft.current = null;
    setSaveState("saving");
    inflight.current = (async () => {
      let succeeded = false;
      try {
        const saved = await saveWorkspace(target.id, target.revision, { ...target.workspace, gameplan: { flowchart } });
        if (current.current?.id === saved.id) current.current = saved;
        setList((items) => items.map((item) => item.id === saved.id
          ? { ...item, revision: saved.revision, updated_at: saved.updated_at }
          : item));
        succeeded = true;
        setSaveState(draft.current ? "pending" : "saved");
      } catch (e) {
        if (e.status === 409) {
          conflicted.current = true;
          setSaveState("conflict");
        } else {
          // Keep the unsent edit so the next change (or reload prompt) retries it.
          draft.current ??= flowchart;
          setSaveState("error");
          setError(e.message);
        }
      } finally {
        inflight.current = null;
        if (succeeded && draft.current) timer.current = setTimeout(flush, SAVE_DELAY_MS);
      }
    })();
    return inflight.current;
  }, []);

  /** Finish any in-flight or pending save before switching, renaming, or exporting. */
  const settle = useCallback(async () => {
    if (inflight.current) await inflight.current;
    if (draft.current && !conflicted.current) await flush();
  }, [flush]);

  const onCanvasChange = useCallback((flowchart) => {
    if (!current.current || current.current.source !== "database") return;
    draft.current = flowchart;
    if (!conflicted.current) setSaveState("pending");
    clearTimeout(timer.current);
    timer.current = setTimeout(flush, SAVE_DELAY_MS);
  }, [flush]);

  useEffect(() => {
    const beforeUnload = () => { flush(); };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [flush]);

  const refresh = useCallback(async (nextSource) => {
    const value = await listWorkspaces(nextSource);
    setList(value.workspaces);
    return value.workspaces;
  }, []);

  /** Load a workspace document, discarding any unsaved conflicting draft. */
  const open = useCallback(async (id, nextSource) => {
    const loaded = await getWorkspace(id, nextSource);
    clearTimeout(timer.current);
    draft.current = null;
    conflicted.current = false;
    current.current = loaded;
    setRecord(loaded);
    setDraftName(loaded.workspace.name);
    setSaveState("idle");
    setCanvasKey((key) => key + 1);
  }, []);

  /** Run a user action, surfacing failures in the page banner. */
  const run = useCallback(async (action) => {
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      setError(e.message);
    }
  }, []);

  // Start from the configured `[chat] flowchart_source`.
  useEffect(() => {
    run(async () => {
      const config = await api("/api/config");
      setSource(config.flowchart_source === "json" ? "json" : "database");
    });
  }, [run]);

  useEffect(() => {
    if (!source) return;
    run(async () => {
      const items = await refresh(source);
      const id = items.some((item) => item.id === preferred.current) ? preferred.current : items[0]?.id;
      preferred.current = null;
      if (id) await open(id, source);
      else {
        current.current = null;
        setRecord(null);
      }
    });
  }, [source, refresh, open, run]);

  const patch = record?.workspace.patch ?? null;
  const setNumber = record?.workspace.set_number ?? null;
  useEffect(() => {
    let alive = true;
    setCatalogError("");
    loadCatalog(patch, setNumber)
      .then((value) => { if (alive) setCatalog(value); })
      .catch((e) => { if (alive) setCatalogError(e.message); });
    return () => { alive = false; };
  }, [patch, setNumber]);
  const index = useMemo(() => catalogIndex(catalog), [catalog]);

  // The saved-group library is shared by every workspace, so it loads once.
  useEffect(() => {
    let alive = true;
    listGroups()
      .then((value) => { if (alive) setGroups(value); })
      .catch((e) => { if (alive) setGroupsError(e.message); });
    return () => { alive = false; };
  }, []);

  /** Store a canvas selection in the library; errors reach the toolbar form. */
  const saveGroup = useCallback(async (name, fragment) => {
    const saved = await createGroup({ name, set_number: setNumber, fragment });
    setGroups((current) => [saved, ...(current ?? [])]);
    setNotice(`Saved group "${saved.name}". Find it in the Groups tab.`);
  }, [setNumber]);

  const library = {
    groups,
    error: groupsError,
    setNumber,
    canInsert: Boolean(record) && record.source === "database",
    onInsert: (group) => insertRef.current?.insertGroup(group.fragment),
    onRename: async (group, name) => {
      try {
        const renamed = await renameGroup(group.id, name);
        setGroups((current) => current.map((item) => item.id === renamed.id ? renamed : item));
        return true;
      } catch (e) {
        setError(e.message);
        return false;
      }
    },
    onDelete: (group) => run(async () => {
      if (!window.confirm(`Delete saved group "${group.name}"? Copies already on canvases are kept.`)) return;
      await deleteGroup(group.id);
      setGroups((current) => current.filter((item) => item.id !== group.id));
    }),
  };

  const switchSource = (next) => run(async () => {
    if (next === source) return;
    await settle();
    setSource(next);
  });

  const select = (id) => run(async () => {
    await settle();
    await open(id, source);
  });

  const create = (event) => {
    event.preventDefault();
    run(async () => {
      await settle();
      const created = await createWorkspace({
        name: form.name.trim(),
        patch: form.patch.trim() || null,
        set_number: form.set_number ? Number(form.set_number) : null,
      });
      setForm({ name: "", patch: "", set_number: "" });
      await showInDatabase(created.id);
    });
  };

  const rename = () => run(async () => {
    const name = draftName.trim();
    if (!record || !name || name === current.current.workspace.name) return;
    await settle();
    const renamed = await renameWorkspace(record.id, current.current.revision, name);
    current.current = renamed;
    setRecord(renamed);
    await refresh("database");
  });

  const remove = () => run(async () => {
    if (!record || !window.confirm(`Delete workspace "${record.workspace.name}"? This cannot be undone.`)) return;
    clearTimeout(timer.current);
    draft.current = null;
    if (inflight.current) await inflight.current;
    await deleteWorkspace(record.id);
    current.current = null;
    setRecord(null);
    const items = await refresh("database");
    if (items.length) await open(items[0].id, "database");
  });

  const exportJson = () => run(async () => {
    await settle();
    const exported = await exportWorkspace(record.id, source);
    downloadWorkspace(exported.workspace);
    setNotice(`Exported to ${exported.path}`);
  });

  /** Open a database workspace, switching sources first when needed. */
  const showInDatabase = async (id) => {
    if (source !== "database") {
      preferred.current = id;
      setSource("database");
      return;
    }
    await refresh("database");
    await open(id, "database");
  };

  /** Copy a document into the editable database source and open it there. */
  const importDocument = async (workspace) => {
    await settle();
    const imported = await importWorkspace(workspace);
    await showInDatabase(imported.id);
    setNotice(`Imported "${imported.workspace.name}" to the database.`);
  };

  const importFile = (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    run(async () => {
      const parsed = PatchWorkspaceSchema.safeParse(JSON.parse(await file.text()));
      if (!parsed.success) throw new Error(`${file.name} is not a flowchart.v1 workspace.`);
      await importDocument(parsed.data);
    });
  };

  const readOnly = record?.source !== "database";

  return (
    <div className="flowchart-view">
      <aside className="flowchart-rail" aria-label="Flowchart workspaces">
        <div className="flowchart-rail-title">
          <h1>Flowchart</h1>
          <p>Map states, actions, and decisions for a patch.</p>
        </div>
        <div className="flowchart-source" role="group" aria-label="Workspace source">
          <UiButton size="sm" variant={source === "database" ? "default" : "outline"} aria-pressed={source === "database"}
            onClick={() => switchSource("database")}>
            <Database aria-hidden="true" /> Database
          </UiButton>
          <UiButton size="sm" variant={source === "json" ? "default" : "outline"} aria-pressed={source === "json"}
            onClick={() => switchSource("json")}>
            <FileJson aria-hidden="true" /> Checked-in JSON
          </UiButton>
        </div>
        <form className="flowchart-create" onSubmit={create} aria-label="Create workspace">
          <UiInput aria-label="Workspace name" placeholder="New workspace name" maxLength={120} value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })} />
          <div className="flowchart-create-row">
            <UiInput aria-label="Patch" placeholder="Patch" maxLength={40} value={form.patch}
              onChange={(event) => setForm({ ...form, patch: event.target.value })} />
            <UiInput aria-label="Set" placeholder="Set" type="number" min={1} max={99} value={form.set_number}
              onChange={(event) => setForm({ ...form, set_number: event.target.value })} />
          </div>
          <UiButton type="submit" size="sm" disabled={!form.name.trim()}>
            <Plus aria-hidden="true" /> Create
          </UiButton>
        </form>
        <div className="flowchart-rail-heading">
          <h2>{source === "json" ? "gameplans/" : "Workspaces"}</h2>
          <UiButton variant="ghost" size="icon-sm" aria-label="Refresh workspaces" disabled={!source}
            onClick={() => run(() => refresh(source))}>
            <RefreshCw aria-hidden="true" />
          </UiButton>
        </div>
        <nav className="flowchart-rail-list" aria-label="Workspace list">
          {list.map((item) => (
            <button key={item.id} type="button" className="flowchart-rail-item"
              aria-current={item.id === record?.id ? "page" : undefined} onClick={() => select(item.id)}>
              <strong>{item.name}</strong>
              <span>{[item.patch && `Patch ${item.patch}`, item.set_number && `Set ${item.set_number}`].filter(Boolean).join(" · ") || "Any patch"}</span>
            </button>
          ))}
          {source && !list.length && <p className="flowchart-muted">
            {source === "json" ? "No checked-in workspaces in gameplans/." : "No workspaces yet. Create one above."}
          </p>}
        </nav>
        <div className="flowchart-rail-footer">
          <input ref={fileInput} type="file" accept="application/json,.json" hidden onChange={importFile}
            data-testid="flowchart-import-file" />
          <UiButton variant="ghost" size="sm" onClick={() => fileInput.current?.click()}>
            <Upload aria-hidden="true" /> Import JSON file
          </UiButton>
        </div>
      </aside>

      <EntitySidebar catalog={catalog} error={catalogError} library={library} />

      <main className="flowchart-main">
        {record ? <>
          <header className="flowchart-header">
            <UiInput className="flowchart-name" aria-label="Workspace title" value={draftName} maxLength={120}
              readOnly={readOnly} onChange={(event) => setDraftName(event.target.value)} onBlur={rename}
              onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }} />
            {readOnly && <span className="flowchart-badge">Read-only JSON</span>}
            <span className="flowchart-save" role="status" data-state={saveState}>{SAVE_LABELS[saveState]}</span>
            <span className="flowchart-toolbar-spacer" />
            {readOnly
              ? <>
                  <UiButton size="sm" onClick={() => run(() => importDocument(record.workspace))}>
                    <Import aria-hidden="true" /> Import to database
                  </UiButton>
                  <UiButton size="sm" variant="outline" onClick={() => downloadWorkspace(record.workspace)}>
                    <Download aria-hidden="true" /> Download
                  </UiButton>
                </>
              : <>
                  <UiButton size="sm" variant="outline" onClick={exportJson}>
                    <FileJson aria-hidden="true" /> Export JSON
                  </UiButton>
                  <UiButton size="sm" variant="ghost" aria-label="Delete workspace" onClick={remove}>
                    <Trash2 aria-hidden="true" />
                  </UiButton>
                </>}
          </header>
          {saveState === "conflict" && (
            <div className="flowchart-banner" role="alert">
              This workspace changed somewhere else after it was opened, so your latest edits were not saved.
              <UiButton size="sm" variant="outline" onClick={() => run(() => open(record.id, source))}>Reload</UiButton>
            </div>
          )}
          {error && <div className="flowchart-banner" role="alert">{error}</div>}
          {notice && <div className="flowchart-banner" data-tone="info" role="status">{notice}</div>}
          <FlowchartPanel
            key={canvasKey}
            flowchart={record.workspace.gameplan.flowchart}
            catalog={index}
            readOnly={readOnly}
            onChange={onCanvasChange}
            onSaveGroup={saveGroup}
            insertRef={insertRef}
          />
        </> : <>
          {error && <div className="flowchart-banner" role="alert">{error}</div>}
          {notice && <div className="flowchart-banner" data-tone="info" role="status">{notice}</div>}
          <EmptyState icon="data" title="No workspace open">
            Create a workspace or pick one from the list to start planning.
          </EmptyState>
        </>}
      </main>
    </div>
  );
}
