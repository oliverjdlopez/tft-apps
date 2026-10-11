/** Canonical document canvas: commands/history own edits; React Flow renders personal projections. */
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Background, ConnectionMode, Controls, MiniMap, ReactFlow, ReactFlowProvider, SelectionMode, useConnection, useReactFlow } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { BookmarkPlus, Circle, CircleDot, Diamond, GitFork, Square, StickyNote, Zap } from 'lucide-react';
import { Button as UiButton } from '@/components/ui/button';
import { Input as UiInput } from '@/components/ui/input';
import { useLocalStorage } from '../app.jsx';
import { FlowchartContext } from './context.js';
import { edgeTypes } from './edges.jsx';
import { nodeTypes } from './nodes.jsx';
import TextField from './TextField.jsx';
import { FlowchartElementSchema, FlowchartConnectionSchema } from './models.js';
import { ARROW_MARKER, newId, absolutePosition, boundsFor, contentSize, elementSize, growGroups, dragGuides,
  isEditorTarget, readClipboard, readDraggedEntity, readDraggedGroup, isValidLink, descendants } from './utils.js';
import { createHistory, commit, undo, redo, groupSelection, ungroup, reparentSelection, deleteSelection,
  copySelection, pasteFragment, reconnect, insertAction, arrangeSelection, isPositionLocked, moveInternalRoutes } from './document.js';
import { visibleGraph, focusObjects, searchDiagram, revealAncestors, pruneViews, routingGraph } from './projection.js';
import { layoutGraph, applyLayout } from './layout.js';

const NODE_TOOLS = [
  { kind: 'start', label: 'Start', icon: Circle }, { kind: 'plan', label: 'State', icon: Square },
  { kind: 'action', label: 'Action', icon: Zap }, { kind: 'decision', label: 'Decision', icon: Diamond },
  { kind: 'fork', label: 'Fork / join', icon: GitFork }, { kind: 'end', label: 'End', icon: CircleDot },
  { kind: 'note', label: 'Note', icon: StickyNote },
];
const EMPTY_SET = new Set();
const CONTEXT_CLICK_MS = 350;
const CONTEXT_CLICK_DISTANCE = 5;

/** Scope React Flow to one open workspace; remounting creates a fresh document history. */
export default function FlowchartPanel(props) {
  return <ReactFlowProvider><Canvas {...props} /></ReactFlowProvider>;
}
/** Own document transactions, worker lifetimes, clipboard events, and personal view state. */
function Canvas({ flowchart, catalog, readOnly, onChange, onSaveGroup, insertRef, workspaceKey = 'workspace' }) {
  const [history, setHistory] = useState(() => createHistory(flowchart)), historyRef = useRef(history);
  const [gesture, setGesture] = useState(null), gestureRef = useRef(null), gesturing = useRef(false);
  const document = gesture ?? history.present, docRef = useRef(document); docRef.current = document;
  const [selected, setSelected] = useState(EMPTY_SET), [selectedEdges, setSelectedEdges] = useState(EMPTY_SET);
  const selectionRef = useRef(selected); selectionRef.current = selected;
  const [measured, setMeasured] = useState({}), measuredRef = useRef(measured); measuredRef.current = measured;
  const [guides, setGuides] = useState([]), [message, setMessage] = useState(''), [query, setQuery] = useState('');
  const [menu, setMenu] = useState(null), [targetGroup, setTargetGroup] = useState('');
  const [direction, setDirection] = useState('DOWN'), [layoutBusy, setLayoutBusy] = useState(false);
  const [routes, setRoutes] = useState({}), [routingBusy, setRoutingBusy] = useState(false), [progress, setProgress] = useState(null);
  const [storedSettings, setSettings] = useLocalStorage('tft.flowchart.panel', {});
  const settings = { snap: true, minimap: true, edgeStyle: 'step', ...storedSettings };
  const [personal, setPersonal] = useLocalStorage(`tft.flowchart.views:${workspaceKey}`, { collapsed: [], views: [] });
  const [focusMode, setFocusMode] = useState('none'), [focusSeeds, setFocusSeeds] = useState(EMPTY_SET), [viewName, setViewName] = useState('');
  const collapsed = useMemo(() => new Set(personal.collapsed ?? []), [personal.collapsed]);
  const namedViews = useMemo(() => pruneViews(document, personal.views), [document, personal.views]);
  const focus = useMemo(() => focusObjects(document, focusSeeds, focusMode), [document, focusSeeds, focusMode]);
  const graph = useMemo(() => visibleGraph(document, collapsed, focus, selected, selectedEdges, measured), [document, collapsed, focus, selected, selectedEdges, measured]);
  const nodes = graph.nodes.map((node) => ({ ...node, draggable: !readOnly && node.draggable,
    // A selected container moves its selected descendants once through parenting.
    ...(node.parentId && selected.has(node.parentId) ? { draggable: false } : {}) }));
  const edges = graph.edges.map((edge) => ({ ...edge, reconnectable: !readOnly && edge.reconnectable, data: { ...edge.data, route: routes[edge.id] } }));
  const { screenToFlowPosition, setCenter, getViewport, setViewport } = useReactFlow();
  const connecting = useConnection((connection) => connection.inProgress);
  const canvasRef = useRef(null), panelRef = useRef(null), pointer = useRef(null);
  const rightPress = useRef(null);
  const routingGeneration = useRef(0), layoutGeneration = useRef(0), layoutWorker = useRef(null);
  const results = useMemo(() => searchDiagram(document, query, catalog), [document, query, catalog]);
  const selectedElements = document.elements.filter((e) => selected.has(e.id));
  const siblings = selectedElements.length > 0 && new Set(selectedElements.map((e) => e.parent_id)).size === 1;
  const selectedGroup = selectedElements.length === 1 && selectedElements[0].kind === 'group' ? selectedElements[0] : null;
  const selectedConnection = document.connections.find((e) => selectedEdges.has(e.id));

  /** Clear viewer selection on an empty-canvas click without editing the document. */
  const clearSelection = () => { setSelected(EMPTY_SET); setSelectedEdges(EMPTY_SET); };
  /** Remember a right press without intercepting React Flow's pan gesture. */
  const startContextClick = (event) => {
    if (event.button !== 2 || event.target.closest('.flowchart-context-menu, .react-flow__controls, .react-flow__minimap')) return;
    rightPress.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY,
      time: performance.now(), target: event.target, moved: false };
  };
  /** Any excursion beyond the click tolerance makes this press a pan, even if it returns. */
  const trackContextClick = (event) => {
    const press = rightPress.current;
    if (press?.pointerId === event.pointerId && Math.hypot(event.clientX - press.x, event.clientY - press.y) > CONTEXT_CLICK_DISTANCE) press.moved = true;
  };
  /** Open common commands on release; holding or dragging retains right-button panning. */
  const finishContextClick = (event) => {
    const press = rightPress.current;
    if (event.button !== 2 || press?.pointerId !== event.pointerId) return;
    trackContextClick(event); rightPress.current = null;
    if (press.moved || performance.now() - press.time > CONTEXT_CLICK_MS) return;
    const nodeId = press.target.closest('.react-flow__node')?.getAttribute('data-id');
    const edgeId = press.target.closest('.react-flow__edge, .flowchart-edge-label')?.getAttribute('data-id');
    if (nodeId && !selected.has(nodeId)) { setSelected(new Set([nodeId])); setSelectedEdges(EMPTY_SET); }
    else if (edgeId && !selectedEdges.has(edgeId)) { setSelected(EMPTY_SET); setSelectedEdges(new Set([edgeId])); }
    const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
    pointer.current = position;
    setMenu({ x: event.clientX, y: event.clientY, position });
  };
  /** Return keyboard shortcuts to the canvas after choosing or dismissing a menu command. */
  const closeMenu = () => { setMenu(null); panelRef.current?.focus(); };

  /** Validate, commit, and autosave only real user mutations. Opening/measurement never saves. */
  const transact = useCallback((operation) => {
    if (readOnly) return false;
    try {
      const next = commit(historyRef.current, typeof operation === 'function' ? operation(historyRef.current.present) : operation);
      if (next === historyRef.current) return false;
      historyRef.current = next; setHistory(next); onChange(next.present); setMessage(''); return true;
    } catch (error) { setMessage(error.message); return false; }
  }, [readOnly, onChange]);
  const travel = (operation) => {
    if (readOnly || gesturing.current) return;
    const next = operation(historyRef.current);
    if (next !== historyRef.current) { historyRef.current = next; setHistory(next); onChange(next.present); }
  };
  const beginGesture = useCallback(() => { if (!readOnly) { gesturing.current = true; gestureRef.current = historyRef.current.present; } }, [readOnly]);
  const endGesture = useCallback(() => {
    if (!gesturing.current) return;
    const next = gestureRef.current; gesturing.current = false; gestureRef.current = null; setGesture(null); setGuides([]);
    if (next) transact(growGroups(next, measuredRef.current));
  }, [transact]);
  const updateNodeData = useCallback((id, patch) => transact((doc) => {
    const sizes = { ...measuredRef.current }; delete sizes[id];
    return growGroups({ ...doc, elements: doc.elements.map((e) => e.id === id ? { ...e, ...patch } : e) }, sizes);
  }), [transact]);
  const updateEdgeData = useCallback((id, patch) => transact((doc) => ({ ...doc,
    connections: doc.connections.map((e) => e.id === id ? { ...e, ...patch } : e) })), [transact]);
  const fitContent = useCallback((id) => transact((doc) => {
    if (isPositionLocked(doc, id)) return doc;
    return growGroups({ ...doc, elements: doc.elements.map((e) => e.id === id ? { ...e, size: null } : e) });
  }), [transact]);
  const toggleCollapse = useCallback((id) => setPersonal((current) => {
    const next = new Set(current.collapsed ?? []); if (next.has(id)) next.delete(id); else next.add(id);
    return { ...current, collapsed: [...next] };
  }), [setPersonal]);
  const groupMinimum = useCallback((id) => {
    const children = docRef.current.elements.filter((e) => e.parent_id === id), bounds = boundsFor(children, measuredRef.current);
    return { width: Math.max(160, bounds.x + bounds.width + 24), height: Math.max(96, bounds.y + bounds.height + 24) };
  }, []);
  const context = { readOnly, catalog, edgeStyle: settings.edgeStyle, updateNodeData, updateEdgeData, beginGesture, endGesture,
    fitContent, toggleCollapse, groupMinimum, screenToFlowPosition, routingBusy };

  /** React Flow selection and measurement are viewer state; gesture geometry is a temporary draft. */
  const onNodesChange = (changes) => {
    const picks = changes.filter((c) => c.type === 'select');
    if (picks.length) setSelected((current) => { const next = new Set(current); for (const c of picks) c.selected ? next.add(c.id) : next.delete(c.id); return next; });
    const measurements = changes.filter((c) => c.type === 'dimensions' && !c.resizing && !c.setAttributes);
    if (measurements.length) setMeasured((current) => {
      const next = { ...current }; let changed = false;
      for (const c of measurements) if (c.dimensions && (current[c.id]?.width !== c.dimensions.width || current[c.id]?.height !== c.dimensions.height)) { next[c.id] = c.dimensions; changed = true; }
      return changed ? next : current;
    });
    if (readOnly) return;
    const geometry = changes.filter((c) => c.type === 'position' && c.position || c.type === 'dimensions' && gesturing.current && c.dimensions);
    if (!geometry.length) return;
    const before = gestureRef.current ?? historyRef.current.present;
    let next = before;
    next = { ...next, elements: next.elements.map((element) => {
      if (isPositionLocked(next, element.id)) return element;
      let updated = element;
      for (const c of geometry.filter((c) => c.id === element.id)) {
        if (c.type === 'dimensions') updated = { ...updated, size: c.dimensions };
        if (c.type === 'position') {
          let position = c.position;
          const peers = next.elements.filter((e) => e.parent_id === element.parent_id && !selectionRef.current.has(e.id) && e.id !== element.id);
          if (gesturing.current && selectionRef.current.size <= 1) {
            const guide = dragGuides(element, position, peers, measuredRef.current); position = guide.position;
            const parent = next.elements.find((e) => e.id === element.parent_id), origin = parent ? absolutePosition(parent, next.elements) : { x: 0, y: 0 };
            setGuides(guide.guides.map((g) => ({ ...g, line: g.line + origin[g.axis] })));
          }
          updated = { ...updated, position };
        }
      }
      return updated;
    }) };
    next = moveInternalRoutes(before, next);
    if (gesturing.current) { gestureRef.current = next; setGesture(next); }
    else transact(growGroups(next, measuredRef.current));
  };
  const onEdgesChange = (changes) => {
    const picks = changes.filter((c) => c.type === 'select');
    if (picks.length) setSelectedEdges((current) => { const next = new Set(current); for (const c of picks) c.selected ? next.add(c.id) : next.delete(c.id); return next; });
  };
  const visibleCenter = useCallback(() => {
    const bounds = canvasRef.current?.getBoundingClientRect();
    return screenToFlowPosition({ x: (bounds?.left ?? 0) + (bounds?.width ?? 0) / 2, y: (bounds?.top ?? 0) + (bounds?.height ?? 0) / 2 });
  }, [screenToFlowPosition]);
  const addNode = (kind, at = visibleCenter(), entities = []) => {
    const element = FlowchartElementSchema.parse({ id: newId(kind), kind, position: at, entities,
      title: kind === 'plan' ? 'New state' : '', size: kind === 'fork' ? { width: 160, height: 10 } : null });
    if (transact((doc) => ({ ...doc, elements: [...doc.elements, element] }))) { setSelected(new Set([element.id])); setSelectedEdges(EMPTY_SET); }
  };
  const onConnect = (connection) => {
    if (!isValidLink(nodes, connection)) return;
    const kind = nodes.some((n) => [connection.source, connection.target].includes(n.id) && n.type === 'note') ? 'annotation' : 'transition';
    const edge = FlowchartConnectionSchema.parse({ id: newId('link'), source: connection.source, target: connection.target, kind,
      source_handle: connection.sourceHandle, target_handle: connection.targetHandle });
    transact((doc) => ({ ...doc, connections: [...doc.connections, edge] }));
  };
  const onReconnect = (edge, endpoints) => {
    if (edge.data.proxy || !isValidLink(nodes, endpoints)) return;
    const kind = nodes.some((n) => [endpoints.source, endpoints.target].includes(n.id) && n.type === 'note') ? 'annotation' : 'transition';
    transact((doc) => reconnect(doc, edge.id, { source: endpoints.source, target: endpoints.target, kind,
      source_handle: endpoints.sourceHandle, target_handle: endpoints.targetHandle }));
  };
  const insertGroup = useCallback((fragment, origin) => {
    try {
      const pasted = pasteFragment(historyRef.current.present, fragment, origin ?? visibleCenter());
      if (transact(pasted.document)) { setSelected(pasted.rootIds); setSelectedEdges(EMPTY_SET); }
    } catch (error) { setMessage(error.message); }
  }, [transact, visibleCenter]);
  useEffect(() => { if (insertRef) insertRef.current = { insertGroup }; return () => { if (insertRef) insertRef.current = null; }; }, [insertRef, insertGroup]);
  const remove = (withContents = false) => transact((doc) => deleteSelection(doc, selected, selectedEdges, withContents));
  const duplicate = () => { const fragment = copySelection(document, selected); if (fragment) insertGroup(fragment, pointer.current ?? visibleCenter()); };
  const makeGroup = () => {
    let groupId;
    if (transact((doc) => { const next = groupSelection(doc, selected); groupId = next.elements.at(-1).id; return next; })) setSelected(new Set([groupId]));
  };
  const resetRoutes = () => transact((doc) => ({ ...doc, connections: doc.connections.map((e) => selectedEdges.has(e.id) || selected.has(e.source) || selected.has(e.target)
    ? { ...e, waypoints: [], label_offset: null } : e) }));
  const onDrop = (event) => {
    event.preventDefault(); if (readOnly) return;
    const at = screenToFlowPosition({ x: Number.isFinite(event.clientX) ? event.clientX : 0, y: Number.isFinite(event.clientY) ? event.clientY : 0 }), fragment = readDraggedGroup(event.dataTransfer);
    if (fragment) { insertGroup(fragment, at); return; }
    const entity = readDraggedEntity(event.dataTransfer); if (!entity) return;
    const target = event.target.closest?.('.react-flow__node-plan, .react-flow__node-action')?.getAttribute('data-id');
    if (target) { const node = document.elements.find((e) => e.id === target); if (node.entities.length < 40) updateNodeData(target, { entities: [...node.entities, entity] }); }
    else addNode('entity', at, [entity]);
  };
  const clipboard = (event, cutting = false) => {
    if (isEditorTarget(event.target)) return;
    const fragment = copySelection(document, selected); if (!fragment || !event.clipboardData) return;
    const payload = JSON.stringify({ type: 'tft.flowchart.fragment', version: 2, fragment });
    event.clipboardData.setData('application/x-tft-flowchart-fragment', payload);
    event.clipboardData.setData('text/plain', payload); event.preventDefault();
    if (cutting && !readOnly) transact((doc) => deleteSelection(doc, descendants(doc.elements, selected), EMPTY_SET, true));
  };
  const paste = (event) => {
    if (readOnly || isEditorTarget(event.target)) return;
    const fragment = readClipboard(event.clipboardData?.getData('application/x-tft-flowchart-fragment') || event.clipboardData?.getData('text/plain'));
    if (!fragment) return;
    event.preventDefault(); insertGroup(fragment, pointer.current ?? visibleCenter());
  };
  const keyboard = (event) => {
    if (isEditorTarget(event.target)) return;
    const key = event.key.toLowerCase(), mod = event.ctrlKey || event.metaKey;
    if (mod && key === 'a') { event.preventDefault(); setSelected(new Set(graph.nodes.map((n) => n.id))); setSelectedEdges(new Set(graph.edges.map((e) => e.id))); }
    if (mod && key === 'z') { event.preventDefault(); travel(event.shiftKey ? redo : undo); }
    if (event.ctrlKey && key === 'y') { event.preventDefault(); travel(redo); }
    if (mod && key === 'd') { event.preventDefault(); duplicate(); }
    if (['delete', 'backspace'].includes(key)) { event.preventDefault(); remove(); }
    if (key === 'escape') { closeMenu(); setFocusMode('none'); }
  };

  // Routing owns a snapshot and a generation. Terminating superseded workers
  // bounds resource usage during continuous editing; the token rejects late events.
  const routeSnapshot = JSON.stringify(routingGraph(document, graph));
  useEffect(() => {
    const generation = ++routingGeneration.current; setRoutes({});
    if (gesturing.current || !graph.edges.length || typeof Worker === 'undefined') { setRoutingBusy(false); return; }
    setRoutingBusy(true); setProgress({ completed: 0, total: graph.edges.length });
    let worker;
    const timer = setTimeout(() => {
      worker = new Worker(new URL('./routing.worker.js', import.meta.url), { type: 'module' });
      worker.onmessage = ({ data }) => {
        if (data.generation !== routingGeneration.current) return;
        if (data.progress) setProgress(data.progress);
        if (data.routes) { setRoutes(data.routes); setRoutingBusy(false); worker.terminate(); }
        if (data.error) { setMessage(`Routing: ${data.error}`); setRoutingBusy(false); worker.terminate(); }
      };
      worker.onerror = () => { if (generation === routingGeneration.current) { setMessage('Routing unavailable; provisional paths shown.'); setRoutingBusy(false); } worker.terminate(); };
      worker.postMessage({ generation, graph: JSON.parse(routeSnapshot) });
    }, 120);
    return () => { clearTimeout(timer); worker?.terminate(); };
  }, [routeSnapshot, gesture !== null]);
  useEffect(() => {
    layoutGeneration.current++; layoutWorker.current?.terminate(); layoutWorker.current = null; setLayoutBusy(false);
    const ids = new Set(document.elements.map((e) => e.id));
    setSelected((current) => new Set([...current].filter((id) => ids.has(id))));
    const edgeIds = new Set(document.connections.map((e) => e.id));
    setSelectedEdges((current) => new Set([...current].filter((id) => edgeIds.has(id))));
    const nextViews = pruneViews(document, personal.views);
    const nextCollapsed = (personal.collapsed ?? []).filter((id) => document.elements.some((e) => e.id === id && e.kind === 'group'));
    if (JSON.stringify(nextViews) !== JSON.stringify(personal.views ?? []) || JSON.stringify(nextCollapsed) !== JSON.stringify(personal.collapsed ?? []))
      setPersonal({ ...personal, views: nextViews, collapsed: nextCollapsed });
  }, [history.present]);
  useEffect(() => () => layoutWorker.current?.terminate(), []);
  const layout = (selection) => {
    if (readOnly || typeof Worker === 'undefined') { setMessage('Layout requires browser workers.'); return; }
    try {
      const built = layoutGraph(document, selection, direction, measured), snapshot = historyRef.current.present;
      layoutWorker.current?.terminate(); const generation = ++layoutGeneration.current;
      const worker = new Worker(new URL('./layout.worker.js', import.meta.url), { type: 'module' }); layoutWorker.current = worker; setLayoutBusy(true);
      worker.onmessage = ({ data }) => {
        if (data.id !== layoutGeneration.current || historyRef.current.present !== snapshot) return;
        setLayoutBusy(false); worker.terminate(); layoutWorker.current = null;
        if (data.error) setMessage(`Layout: ${data.error.message ?? data.error}`);
        else transact(applyLayout(snapshot, selection, data.data, measuredRef.current));
      };
      worker.onerror = (event) => { setLayoutBusy(false); setMessage(`Layout worker failed: ${event.message}`); worker.terminate(); };
      worker.postMessage({ id: -1, cmd: 'register', algorithms: ['layered'] });
      worker.postMessage({ id: generation, cmd: 'layout', graph: built.graph });
    } catch (error) { setMessage(error.message); }
  };
  const reveal = (result) => {
    const ids = result.kind === 'connection' ? (() => { const e = document.connections.find((e) => e.id === result.id); return [e.source, e.target]; })() : [result.id];
    setPersonal({ ...personal, collapsed: [...revealAncestors(document, ids, collapsed)] });
    setSelected(new Set(result.kind === 'element' ? ids : [])); setSelectedEdges(new Set(result.kind === 'connection' ? [result.id] : [])); setFocusMode('none');
    if (!canvasRef.current?.getBoundingClientRect().width || !canvasRef.current?.getBoundingClientRect().height) return;
    const positions = ids.map((id) => { const e = document.elements.find((e) => e.id === id), p = absolutePosition(e, document.elements), s = elementSize(e, measured); return { x: p.x + s.width / 2, y: p.y + s.height / 2 }; });
    setCenter(positions.reduce((sum, p) => sum + p.x, 0) / positions.length, positions.reduce((sum, p) => sum + p.y, 0) / positions.length, { zoom: Number.isFinite(getViewport().zoom) ? Math.max(0.6, getViewport().zoom) : 1, duration: 200 });
  };
  const saveView = (event) => {
    event.preventDefault(); if (!viewName.trim()) return;
    const view = { name: viewName.trim(), mode: focusMode, seeds: [...focusSeeds], collapsed: [...collapsed], viewport: getViewport() };
    setPersonal({ ...personal, views: [...namedViews.filter((v) => v.name !== view.name), view].slice(-30) }); setViewName('');
  };
  const activateView = (view) => { if (!view) return; setPersonal({ ...personal, collapsed: view.collapsed }); setFocusMode(view.mode); setFocusSeeds(new Set(view.seeds)); setViewport(view.viewport); };
  const renderSelectionCommands = () => <>
    <UiButton size="sm" variant="outline" disabled={readOnly || !siblings || selected.size < 2} onClick={makeGroup}>Group</UiButton>
    <UiButton size="sm" variant="outline" disabled={readOnly || !selectedGroup} onClick={() => transact((doc) => ungroup(doc, selectedGroup.id))}>Ungroup</UiButton>
    <select aria-label="Target group" value={targetGroup} onChange={(e) => setTargetGroup(e.target.value)} disabled={readOnly}>
      <option value="">Choose group</option>{document.elements.filter((e) => e.kind === 'group' && !descendants(document.elements, selected).has(e.id)).map((e) => <option key={e.id} value={e.id}>{e.title || 'Group'}</option>)}
    </select>
    <UiButton size="sm" variant="outline" disabled={readOnly || !siblings || !targetGroup} onClick={() => transact((doc) => reparentSelection(doc, selected, targetGroup))}>Add to group</UiButton>
    <UiButton size="sm" variant="outline" disabled={readOnly || !siblings || !selectedElements[0]?.parent_id} onClick={() => {
      const parent = document.elements.find((e) => e.id === selectedElements[0].parent_id);
      transact((doc) => reparentSelection(doc, selected, parent?.parent_id ?? null));
    }}>Remove from group</UiButton>
    <UiButton size="sm" variant="outline" disabled={readOnly || !selected.size} onClick={() => {
      const lock = !selectedElements.every((e) => e.locked);
      transact((doc) => ({ ...doc, elements: doc.elements.map((e) => selected.has(e.id) ? { ...e, locked: lock } : e) }));
    }}>{selectedElements.length && selectedElements.every((e) => e.locked) ? 'Unlock position' : 'Lock position'}</UiButton>
    <UiButton size="sm" variant="outline" disabled={readOnly || !selected.size} onClick={duplicate}>Duplicate</UiButton>
    <UiButton size="sm" variant="outline" disabled={readOnly || !selected.size && !selectedEdges.size} onClick={() => remove()}>Delete selection</UiButton>
    <UiButton size="sm" variant="outline" disabled={readOnly || !selectedGroup} onClick={() => remove(true)}>Delete group and contents</UiButton>
    <UiButton size="sm" variant="outline" disabled={readOnly || selectedEdges.size !== 1 || selectedConnection?.kind !== 'transition' || edges.find((e) => e.id === selectedConnection?.id)?.data.proxy}
      onClick={() => transact((doc) => insertAction(doc, selectedConnection.id))}>Insert action</UiButton>
    <UiButton size="sm" variant="outline" disabled={readOnly || !selected.size && !selectedEdges.size} onClick={resetRoutes}>Reset route/label placement</UiButton>
  </>;
  return <FlowchartContext.Provider value={context}><div ref={panelRef} className="flowchart-panel" tabIndex={0}
    onKeyDown={keyboard} onCopy={clipboard} onCut={(event) => clipboard(event, true)} onPaste={paste}>
    <div className="flowchart-toolbar" role="toolbar" aria-label="Canvas tools">
      {NODE_TOOLS.map(({ kind, label, icon: Icon }) => <UiButton key={kind} size="sm" variant="outline" disabled={readOnly} onClick={() => addNode(kind)}><Icon aria-hidden="true" />{label}</UiButton>)}
      <SaveGroupForm selectedCount={selected.size} onSave={(name) => onSaveGroup(name, copySelection(document, selected))} />
      <UiButton size="sm" variant="outline" disabled={readOnly || !history.past.length} onClick={() => travel(undo)}>Undo</UiButton>
      <UiButton size="sm" variant="outline" disabled={readOnly || !history.future.length} onClick={() => travel(redo)}>Redo</UiButton>
      <UiButton size="sm" variant="ghost" aria-pressed={settings.snap} onClick={() => setSettings({ ...settings, snap: !settings.snap })}>Snap</UiButton>
      <UiButton size="sm" variant="ghost" aria-pressed={settings.minimap} onClick={() => setSettings({ ...settings, minimap: !settings.minimap })}>Minimap</UiButton>
      <UiButton size="sm" variant="ghost" aria-label="Link style" onClick={() => setSettings({ ...settings, edgeStyle: settings.edgeStyle === 'curve' ? 'step' : 'curve' })}>{settings.edgeStyle === 'curve' ? 'Curved' : 'Right-angle'}</UiButton>
    </div>
    <div className="flowchart-toolbar" role="toolbar" aria-label="Layout and selection">
      <select aria-label="Layout direction" value={direction} onChange={(e) => setDirection(e.target.value)}><option value="DOWN">Top to bottom</option><option value="RIGHT">Left to right</option></select>
      <UiButton size="sm" variant="outline" disabled={readOnly || layoutBusy} onClick={() => layout(null)}>Layout diagram</UiButton>
      <UiButton size="sm" variant="outline" disabled={readOnly || layoutBusy || !siblings} onClick={() => layout(new Set(selected))}>Layout selection</UiButton>
      <select aria-label="Align or distribute" value="" disabled={readOnly || !siblings || selected.size < 2} onChange={(e) => transact((doc) => arrangeSelection(doc, selected, e.target.value, measured))}>
        <option value="">Align / distribute</option>{['left', 'center', 'right', 'top', 'middle', 'bottom', 'distribute-x', 'distribute-y'].map((value) => <option key={value} value={value}>{value.replace('distribute-x', 'Distribute horizontally').replace('distribute-y', 'Distribute vertically')}</option>)}
      </select>{renderSelectionCommands()}
    </div>
    <div className="flowchart-toolbar flowchart-view-tools" aria-label="Personal view controls">
      <UiInput aria-label="Search diagram" placeholder="Search diagram" value={query} onChange={(e) => setQuery(e.target.value)} />
      <select aria-label="Focus mode" value={focusMode} onChange={(e) => { setFocusMode(e.target.value); setFocusSeeds(new Set([...selected, ...selectedEdges])); }}>
        <option value="none">No focus</option>{['selection', 'upstream', 'downstream', 'both'].map((mode) => <option key={mode} value={mode}>{mode[0].toUpperCase() + mode.slice(1)}</option>)}
      </select><UiButton size="sm" variant="ghost" onClick={() => { setFocusMode('none'); setFocusSeeds(EMPTY_SET); }}>Reset focus</UiButton>
      <form onSubmit={saveView}><UiInput aria-label="Focus view name" placeholder="Name view" value={viewName} maxLength={120} onChange={(e) => setViewName(e.target.value)} /><UiButton size="sm" variant="outline" type="submit" disabled={!viewName.trim()}>Save view</UiButton></form>
      <select aria-label="Named focus views" value="" onChange={(e) => activateView(namedViews.find((v) => v.name === e.target.value))}>
        <option value="">Open view</option>{namedViews.map((view) => <option key={view.name}>{view.name}</option>)}
      </select>
      <UiButton size="sm" variant="ghost" disabled={!namedViews.length} onClick={() => setPersonal({ ...personal, views: [] })}>Clear saved views</UiButton>
    </div>
    {query.trim() && <div className="flowchart-search-results" aria-label="Diagram results">{results.length ? results.slice(0, 100).map((result) => <button key={`${result.kind}:${result.id}`} type="button" onClick={() => reveal(result)}>{result.kind}: {result.label}</button>) : <span>No matches</span>}</div>}
    {(layoutBusy || routingBusy) && <div className="flowchart-progress" aria-live="polite">{layoutBusy ? 'Arranging diagram…' : `Routing ${progress?.completed ?? 0}/${progress?.total ?? graph.edges.length}…`}</div>}
    {message && <div className="flowchart-banner" role="alert">{message}<button type="button" onClick={() => setMessage('')}>Dismiss</button></div>}
    {Object.values(routes).some((route) => route.warning) && <div className="flowchart-routing-warning">Some routes or labels overlap geometry. Move overlapping objects or reset manual placement.</div>}
    <div className="flowchart-work-area">
      <div ref={canvasRef} className="flowchart-canvas" data-testid="flowchart-canvas" data-connecting={connecting || undefined}
        onPointerDownCapture={startContextClick} onPointerMoveCapture={trackContextClick} onPointerUpCapture={finishContextClick}
        onPointerCancel={() => { rightPress.current = null; }} onPointerLeave={() => { rightPress.current = null; }}
        onPointerMove={(event) => { pointer.current = screenToFlowPosition({ x: event.clientX, y: event.clientY }); }}
        onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = readOnly ? 'none' : 'copy'; }} onDrop={onDrop}
        onContextMenu={(event) => event.preventDefault()}>
        <svg className="flowchart-defs" aria-hidden="true"><defs><marker id={ARROW_MARKER} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path className="flowchart-arrow" d="M 1 1.5 L 9 5 L 1 8.5 z" /></marker></defs></svg>
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
          onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={readOnly ? undefined : onConnect} onReconnect={readOnly ? undefined : onReconnect}
          isValidConnection={(link) => isValidLink(nodes, link)} connectionMode={ConnectionMode.Loose}
          connectionLineType={settings.edgeStyle === 'curve' ? 'default' : 'smoothstep'}
          defaultViewport={personal.viewport ?? flowchart.viewport} onMoveEnd={(_, viewport) => {
            if (Number.isFinite(viewport.x) && Number.isFinite(viewport.y) && Number.isFinite(viewport.zoom)) setPersonal((current) => ({ ...current, viewport }));
          }}
          onNodeDragStart={beginGesture} onNodeDragStop={endGesture} nodesConnectable={!readOnly} deleteKeyCode={null}
          onPaneClick={() => { clearSelection(); closeMenu(); }}
          onNodeClick={() => panelRef.current?.focus()} onEdgeClick={() => panelRef.current?.focus()}
          panOnDrag={[1, 2]} multiSelectionKeyCode={["Shift", "Meta", "Control"]} selectionOnDrag selectionMode={SelectionMode.Full} snapToGrid={settings.snap} snapGrid={[16, 16]}
          minZoom={0.05} maxZoom={3} proOptions={{ hideAttribution: true }}>
          <Background gap={16} /><Controls showInteractive={false} />{settings.minimap && <MiniMap pannable zoomable />}
          {guides.length > 0 && <svg className="flowchart-guides"><g transform={`translate(${getViewport().x},${getViewport().y}) scale(${getViewport().zoom})`}>{guides.map((g) => <line key={g.axis} x1={g.axis === 'x' ? g.line : -1e5} x2={g.axis === 'x' ? g.line : 1e5} y1={g.axis === 'y' ? g.line : -1e5} y2={g.axis === 'y' ? g.line : 1e5} />)}</g></svg>}
        </ReactFlow>
        {menu && <CanvasContextMenu menu={menu} onClose={closeMenu}>
          <UiButton size="sm" variant="outline" disabled={readOnly || !history.past.length} onClick={() => travel(undo)}>Undo</UiButton>
          <UiButton size="sm" variant="outline" disabled={readOnly || !history.future.length} onClick={() => travel(redo)}>Redo</UiButton>
          {NODE_TOOLS.map(({ kind, label }) => <UiButton key={kind} size="sm" variant="outline" disabled={readOnly} onClick={() => addNode(kind, menu.position)}>Add {label.toLowerCase()}</UiButton>)}
          {selectedGroup && <UiButton size="sm" variant="outline" onClick={() => toggleCollapse(selectedGroup.id)}>{collapsed.has(selectedGroup.id) ? 'Expand group' : 'Collapse group'}</UiButton>}
          {renderSelectionCommands()}<UiButton size="sm" variant="ghost" onClick={closeMenu}>Close menu</UiButton>
        </CanvasContextMenu>}
      </div>
      <details className="flowchart-properties" open={Boolean(selected.size || selectedEdges.size)}><summary>Properties</summary>
        {selectedElements.map((element) => <article key={element.id}><strong>{element.kind}</strong>
          <TextField label="Title in properties" value={element.title} placeholder="Title" maxLength={120} multiline onCommit={(title) => updateNodeData(element.id, { title })} />
          <TextField label="Stage in properties" value={element.stage_hint ?? ''} placeholder="Stage" maxLength={40} onCommit={(stage_hint) => updateNodeData(element.id, { stage_hint: stage_hint || null })} />
          <TextField label="Text in properties" value={element.text} placeholder="Notes" maxLength={4000} multiline onCommit={(text) => updateNodeData(element.id, { text })} />
          <ul>{element.entities.map((ref, i) => <li key={i}>{catalog.get(`${ref.category}:${ref.api_name}`)?.name ?? ref.api_name}</li>)}</ul>
          <UiButton size="sm" variant="outline" disabled={readOnly || isPositionLocked(document, element.id) || element.kind === 'group'} onClick={() => fitContent(element.id)}>Fit to content</UiButton>
          {element.kind === 'group' && <><label>Group tint<input type="color" aria-label="Group tint" disabled={readOnly} value={element.tint ?? '#dbeafe'} onChange={(e) => updateNodeData(element.id, { tint: e.target.value })} /></label>
            <UiButton size="sm" variant="outline" onClick={() => toggleCollapse(element.id)}>{collapsed.has(element.id) ? 'Expand group' : 'Collapse group'}</UiButton></>}
        </article>)}
        {document.connections.filter((e) => selectedEdges.has(e.id)).map((edge) => <article key={edge.id}><strong>{edge.kind}</strong>
          <p>{document.elements.find((e) => e.id === edge.source)?.title || edge.source} → {document.elements.find((e) => e.id === edge.target)?.title || edge.target}</p>
          {edges.find((e) => e.id === edge.id)?.data.proxy && <p>Expand endpoint groups to reconnect this connection.</p>}
          <TextField label="Guard in properties" value={edge.condition} placeholder="Guard" maxLength={200} multiline onCommit={(condition) => updateEdgeData(edge.id, { condition })} />
          <TextField label="Connection notes in properties" value={edge.notes} placeholder="Connection notes" maxLength={2000} multiline onCommit={(notes) => updateEdgeData(edge.id, { notes })} />
        </article>)}
        {!selected.size && !selectedEdges.size && <p>Select an object to inspect complete text and connections. Copy/cut/paste use the browser clipboard. Ctrl/Cmd+D duplicates.</p>}
      </details>
    </div>
  </div></FlowchartContext.Provider>;
}
/** Keep the popup beside the click and inside the viewport, and focus its commands. */
function CanvasContextMenu({ menu, onClose, children }) {
  const ref = useRef(null);
  const [position, setPosition] = useState({ left: menu.x + 2, top: menu.y + 2 });
  useLayoutEffect(() => {
    const bounds = ref.current.getBoundingClientRect();
    setPosition({ left: Math.max(8, Math.min(menu.x + 2, window.innerWidth - bounds.width - 8)),
      top: Math.max(8, Math.min(menu.y + 2, window.innerHeight - bounds.height - 8)) });
    ref.current.querySelector('button:not(:disabled)')?.focus();
  }, [menu]);
  useEffect(() => {
    /** Dismiss from any application region, including the workspace rail outside the canvas panel. */
    const outsidePress = (event) => { if (!ref.current?.contains(event.target)) onClose(); };
    globalThis.document.addEventListener('pointerdown', outsidePress, true);
    return () => globalThis.document.removeEventListener('pointerdown', outsidePress, true);
  }, [onClose]);
  return <div ref={ref} className="flowchart-context-menu" role="group" aria-label="Selection menu" style={position}
    onKeyDown={(event) => { if (event.key === 'Escape') { event.stopPropagation(); onClose(); } }}
    onClick={(event) => { if (event.target.closest('button:not(:disabled)')) onClose(); }}>
    {children}
  </div>;
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
