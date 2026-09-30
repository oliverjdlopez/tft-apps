/** React Flow canvas for one workspace's flowchart, emitting document changes for saving. */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  addEdge,
  Background,
  ConnectionMode,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  SelectionMode,
  useEdgesState,
  useNodesState,
  useConnection,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  BookmarkPlus, Circle, CircleDot, CornerDownRight, Diamond, GitFork, Grid3x3, Map as MapIcon, Spline, Square,
  StickyNote, Zap,
} from "lucide-react";
import { Button as UiButton } from "@/components/ui/button";
import { Input as UiInput } from "@/components/ui/input";
import { useLocalStorage } from "../app.jsx";
import { FlowchartContext } from "./context.js";
import { edgeTypes } from "./edges.jsx";
import { nodeTypes } from "./nodes.jsx";
import {
  ARROW_MARKER,
  CHIP_KINDS,
  connectionKind,
  edgeDecoration,
  fromFragment,
  isValidLink,
  newId,
  newNode,
  readDraggedEntity,
  readDraggedGroup,
  toEdges,
  toFlowchart,
  toFragment,
  toNodes,
} from "./utils.js";

const SNAP_GRID = [16, 16];

/** Toolbar entries for each node role, in the order a gameplan usually reads. */
const NODE_TOOLS = [
  { kind: "start", label: "Start", icon: Circle },
  { kind: "plan", label: "State", icon: Square },
  { kind: "action", label: "Action", icon: Zap },
  { kind: "decision", label: "Decision", icon: Diamond },
  { kind: "fork", label: "Fork / join", icon: GitFork },
  { kind: "end", label: "End", icon: CircleDot },
  { kind: "note", label: "Note", icon: StickyNote },
];

// A drop anywhere inside one of these nodes adds a chip instead of a new entity node.
const CHIP_TARGETS = [...CHIP_KINDS].map((kind) => `.react-flow__node-${kind}`).join(", ");

/** Minimap fill per node kind, matching each role's outline color token. */
const MINIMAP_COLORS = {
  plan: "var(--fc-state)",
  action: "var(--fc-action)",
  decision: "var(--fc-decision)",
  note: "var(--fc-note)",
};
const minimapColor = (node) => MINIMAP_COLORS[node.type] ?? "var(--fc-flow)";

// Left drag draws a selection box and right (or middle) drag pans, like most
// diagram editors; React Flow's default pans on left drag.
const PAN_BUTTONS = [1, 2];
const suppressContextMenu = (event) => event.preventDefault();

/**
 * Canvas with toolbar, drop handling, and change detection.
 *
 * The parent keys this component by workspace, so node and edge state is
 * initialized once from the document and then owned here.
 *
 * Args:
 *   flowchart: Saved flowchart document to initialize from.
 *   catalog: `Map` from `category:api_name` to catalog entries.
 *   readOnly: Disable editing for checked-in JSON workspaces. Saving a
 *     selection as a group still works, since it does not edit the workspace.
 *   onChange: Receives the serialized flowchart after each persisted-field edit.
 *   onSaveGroup: Async `(name, fragment)` callback that stores a selection in
 *     the library; a rejection's message is shown in the save form.
 *   insertRef: Ref the canvas fills with `{ insertGroup(fragment) }`, so the
 *     library tab can insert a group at the visible center.
 */
export default function FlowchartPanel(props) {
  return <ReactFlowProvider><Canvas {...props} /></ReactFlowProvider>;
}

function Canvas({ flowchart, catalog, readOnly, onChange, onSaveGroup, insertRef }) {
  const [nodes, setNodes, onNodesChange] = useNodesState(() => toNodes(flowchart.elements));
  const [edges, setEdges, onEdgesChange] = useEdgesState(() => toEdges(flowchart.connections));
  const [viewport, setViewport] = useState(flowchart.viewport);
  const [storedSettings, setSettings] = useLocalStorage("tft.flowchart.panel", {});
  // Merge over defaults so settings saved before a new option existed still work.
  const settings = { snap: true, minimap: true, edgeStyle: "step", ...storedSettings };
  const connecting = useConnection((connection) => connection.inProgress);
  const { screenToFlowPosition } = useReactFlow();
  const canvasRef = useRef(null);

  // Emit only when persisted fields change. The first serialization is the
  // baseline, so opening a workspace (or React Flow measuring nodes) never saves.
  const baseline = useRef(null);
  const serialized = useMemo(() => JSON.stringify(toFlowchart(nodes, edges, viewport)), [nodes, edges, viewport]);
  useEffect(() => {
    if (baseline.current === null) baseline.current = serialized;
    else if (serialized !== baseline.current) {
      baseline.current = serialized;
      onChange(JSON.parse(serialized));
    }
  }, [serialized, onChange]);

  const updateNodeData = useCallback((id, patch) => {
    setNodes((current) => current.map((node) => node.id === id ? { ...node, data: { ...node.data, ...patch } } : node));
  }, [setNodes]);
  const updateEdgeData = useCallback((id, patch) => {
    setEdges((current) => current.map((edge) => edge.id === id ? { ...edge, data: { ...edge.data, ...patch } } : edge));
  }, [setEdges]);
  const context = useMemo(
    () => ({ readOnly, catalog, edgeStyle: settings.edgeStyle, updateNodeData, updateEdgeData }),
    [readOnly, catalog, settings.edgeStyle, updateNodeData, updateEdgeData],
  );

  const onConnect = useCallback((connection) => {
    const kind = connectionKind(nodes, connection.source, connection.target);
    setEdges((current) => addEdge({
      ...connection, id: newId("link"), type: kind, ...edgeDecoration(kind),
      data: { condition: "", notes: "" },
    }, current));
  }, [nodes, setEdges]);
  const isValidConnection = useCallback((connection) => isValidLink(nodes, connection), [nodes]);

  /** The visible canvas center, so toolbar and library additions are never off-screen. */
  const visibleCenter = useCallback(() => {
    const bounds = canvasRef.current?.getBoundingClientRect();
    return screenToFlowPosition({
      x: (bounds?.left ?? 0) + (bounds?.width ?? 0) / 2,
      y: (bounds?.top ?? 0) + (bounds?.height ?? 0) / 2,
    });
  }, [screenToFlowPosition]);

  const addNode = (kind) => setNodes((current) => [...current, newNode(kind, visibleCenter())]);

  /**
   * Paste a saved group as fresh copies with its top-left corner at `origin`.
   *
   * The copies replace the current selection, so they can be dragged into
   * place straight away.
   */
  const insertGroup = useCallback((fragment, origin) => {
    if (readOnly) return;
    const inserted = fromFragment(fragment, origin ?? visibleCenter());
    setNodes((current) => [...current.map((node) => ({ ...node, selected: false })), ...inserted.nodes]);
    setEdges((current) => [...current.map((edge) => ({ ...edge, selected: false })), ...inserted.edges]);
  }, [readOnly, visibleCenter, setNodes, setEdges]);
  useEffect(() => {
    if (!insertRef) return undefined;
    insertRef.current = { insertGroup };
    return () => { insertRef.current = null; };
  }, [insertRef, insertGroup]);

  const selectedCount = nodes.filter((node) => node.selected).length;
  const saveGroup = (name) => onSaveGroup(name, toFragment(nodes, edges));

  /**
   * Handle palette drops. A saved group is pasted where it lands; an entity
   * on a state or action adds a chip, and on empty canvas creates an entity node.
   */
  const onDrop = (event) => {
    event.preventDefault();
    if (readOnly) return;
    const group = readDraggedGroup(event.dataTransfer);
    if (group) {
      insertGroup(group, screenToFlowPosition({ x: event.clientX, y: event.clientY }));
      return;
    }
    const entity = readDraggedEntity(event.dataTransfer);
    if (!entity) return;
    const targetId = event.target.closest?.(CHIP_TARGETS)?.getAttribute("data-id");
    if (targetId) {
      setNodes((current) => current.map((node) => node.id === targetId && node.data.entities.length < 40
        ? { ...node, data: { ...node.data, entities: [...node.data.entities, entity] } }
        : node));
      return;
    }
    setNodes((current) => [...current, {
      id: newId("entity"), type: "entity",
      position: screenToFlowPosition({ x: event.clientX, y: event.clientY }),
      data: { title: "", stage_hint: "", entities: [entity], text: "" },
    }]);
  };

  return (
    <FlowchartContext.Provider value={context}>
      <div className="flowchart-panel">
        <div className="flowchart-toolbar" role="toolbar" aria-label="Canvas tools">
          {NODE_TOOLS.map(({ kind, label, icon: Icon }) => (
            <UiButton key={kind} size="sm" variant="outline" disabled={readOnly} onClick={() => addNode(kind)}>
              <Icon aria-hidden="true" /> {label}
            </UiButton>
          ))}
          <SaveGroupForm selectedCount={selectedCount} onSave={saveGroup} />
          <span className="flowchart-toolbar-spacer" />
          <UiButton
            size="sm" variant="ghost" aria-pressed={settings.snap}
            onClick={() => setSettings({ ...settings, snap: !settings.snap })}
          >
            <Grid3x3 aria-hidden="true" /> Snap
          </UiButton>
          <UiButton
            size="sm" variant="ghost" aria-pressed={settings.minimap}
            onClick={() => setSettings({ ...settings, minimap: !settings.minimap })}
          >
            <MapIcon aria-hidden="true" /> Minimap
          </UiButton>
          <UiButton
            size="sm" variant="ghost" aria-label="Link style"
            title={settings.edgeStyle === "curve" ? "Curved links" : "Right-angle links"}
            onClick={() => setSettings({ ...settings, edgeStyle: settings.edgeStyle === "curve" ? "step" : "curve" })}
          >
            {settings.edgeStyle === "curve"
              ? <><Spline aria-hidden="true" /> Curved</>
              : <><CornerDownRight aria-hidden="true" /> Right-angle</>}
          </UiButton>
        </div>
        {/* One arrowhead shared by every transition, filled with the link color token. */}
        <svg className="flowchart-defs" aria-hidden="true">
          <defs>
            <marker
              id={ARROW_MARKER} viewBox="0 0 10 10" refX="9" refY="5"
              markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto-start-reverse"
            >
              <path className="flowchart-arrow" d="M 1 1.5 L 9 5 L 1 8.5 z" />
            </marker>
          </defs>
        </svg>
        <div
          ref={canvasRef}
          className="flowchart-canvas"
          data-testid="flowchart-canvas"
          data-connecting={connecting || undefined}
          onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = readOnly ? "none" : "copy"; }}
          onDrop={onDrop}
          onContextMenu={suppressContextMenu}
        >
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={readOnly ? undefined : onConnect}
            isValidConnection={isValidConnection}
            connectionMode={ConnectionMode.Loose}
            connectionLineType={settings.edgeStyle === "curve" ? "default" : "smoothstep"}
            onMoveEnd={(_, next) => setViewport(next)}
            defaultViewport={flowchart.viewport}
            nodesDraggable={!readOnly}
            nodesConnectable={!readOnly}
            deleteKeyCode={readOnly ? null : ["Backspace", "Delete"]}
            panOnDrag={PAN_BUTTONS}
            selectionOnDrag
            selectionMode={SelectionMode.Full}
            onPaneContextMenu={suppressContextMenu}
            snapToGrid={settings.snap}
            snapGrid={SNAP_GRID}
            minZoom={0.2}
            maxZoom={3}
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={SNAP_GRID[0]} />
            <Controls showInteractive={false} />
            {settings.minimap && <MiniMap pannable zoomable nodeColor={minimapColor} nodeStrokeWidth={2} />}
          </ReactFlow>
        </div>
      </div>
    </FlowchartContext.Provider>
  );
}

/**
 * Toolbar control that names the current selection and saves it to the library.
 *
 * It stays a single button until opened, then shows an inline name field;
 * Electron has no `window.prompt`, so naming happens in the toolbar.
 */
function SaveGroupForm({ selectedCount, onSave }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [status, setStatus] = useState({ busy: false, error: "" });
  const close = () => { setOpen(false); setName(""); setStatus({ busy: false, error: "" }); };
  const submit = async (event) => {
    event.preventDefault();
    if (!name.trim() || !selectedCount) return;
    setStatus({ busy: true, error: "" });
    try {
      await onSave(name.trim());
      close();
    } catch (error) {
      setStatus({ busy: false, error: error.message });
    }
  };
  if (!open) {
    return (
      <UiButton
        size="sm" variant="outline" disabled={!selectedCount} onClick={() => setOpen(true)}
        title={selectedCount ? `Save ${selectedCount} selected as a reusable group` : "Select elements to save them as a group"}
      >
        <BookmarkPlus aria-hidden="true" /> Save group
      </UiButton>
    );
  }
  return (
    <form className="flowchart-save-group" onSubmit={submit} aria-label="Save selection as group">
      <UiInput
        autoFocus aria-label="Group name" placeholder={`Name ${selectedCount} selected`} maxLength={120}
        value={name} onChange={(event) => setName(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Escape") close(); }}
      />
      <UiButton size="sm" type="submit" disabled={status.busy || !name.trim() || !selectedCount}>Save</UiButton>
      <UiButton size="sm" variant="ghost" type="button" onClick={close}>Cancel</UiButton>
      {status.error && <span className="flowchart-save-group-error" role="alert">{status.error}</span>}
    </form>
  );
}
