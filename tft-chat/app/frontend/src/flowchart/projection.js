/** Personal view projections over canonical, fully persisted workspace documents. */
import { toNodes, toEdges, parentOrder, descendants, elementSize, absolutePosition, contentSize } from './utils.js';
import { isPositionLocked } from './document.js';

/** Project collapse and focus without altering any stored endpoint or manual placement. */
export function visibleGraph(document, collapsed, focus, selected, selectedEdges, measured = {}) {
  const byId = new Map(document.elements.map((e) => [e.id, e]));
  const representative = (id) => {
    let current = byId.get(id), result = id;
    while (current?.parent_id) { current = byId.get(current.parent_id); if (current && collapsed.has(current.id)) result = current.id; }
    return result;
  };
  const ordered = parentOrder(document.elements), visible = ordered.filter((e) => representative(e.id) === e.id);
  const nodes = toNodes(visible).map((node) => {
    const e = byId.get(node.id), compact = e.kind === 'group' && collapsed.has(e.id);
    const size = compact ? { width: 200, height: 76 } : e.size ?? contentSize(e);
    return { ...node, ...size, style: { width: size.width, height: size.height, opacity: focus && !focus.has(e.id) ? 0.2 : 1 },
      selected: selected.has(node.id), draggable: !isPositionLocked(document, e.id),
      zIndex: e.kind === 'group' ? -1 : 0,
      data: { ...node.data, collapsed: compact, count: descendants(document.elements, [e.id]).size - 1, positionLocked: isPositionLocked(document, e.id) } };
  });
  const connections = document.connections.flatMap((edge) => {
    const source = representative(edge.source), target = representative(edge.target);
    if (source === target) return [];
    const proxy = source !== edge.source || target !== edge.target;
    return [{ ...edge, source, target, proxy, original: edge }];
  });
  const edges = toEdges(connections).map((edge, i) => ({ ...edge, selected: selectedEdges.has(edge.id), reconnectable: !connections[i].proxy,
    style: { opacity: focus && !(focus.has(connections[i].original.source) && focus.has(connections[i].original.target)) ? 0.15 : 1 },
    data: { ...edge.data, proxy: connections[i].proxy, original: connections[i].original } }));
  return { nodes, edges };
}
/** Walk transition edges in either direction with cycle protection; include annotations and containers. */
export function focusObjects(document, seeds, mode) {
  if (!mode || mode === 'none' || !seeds.size) return null;
  const elementIds = new Set(document.elements.map((e) => e.id));
  const resolved = new Set([...seeds].filter((id) => elementIds.has(id)));
  for (const edge of document.connections) if (seeds.has(edge.id)) { resolved.add(edge.source); resolved.add(edge.target); }
  const ids = descendants(document.elements, resolved);
  if (mode !== 'selection') for (let changed = true; changed;) {
    changed = false;
    for (const edge of document.connections.filter((e) => e.kind === 'transition')) {
      if ((mode === 'downstream' || mode === 'both') && ids.has(edge.source) && !ids.has(edge.target)) { ids.add(edge.target); changed = true; }
      if ((mode === 'upstream' || mode === 'both') && ids.has(edge.target) && !ids.has(edge.source)) { ids.add(edge.source); changed = true; }
    }
  }
  for (const edge of document.connections.filter((e) => e.kind === 'annotation')) {
    if (ids.has(edge.source)) ids.add(edge.target);
    if (ids.has(edge.target)) ids.add(edge.source);
  }
  const map = new Map(document.elements.map((e) => [e.id, e]));
  for (const id of [...ids]) { let e = map.get(id); while (e?.parent_id) { ids.add(e.parent_id); e = map.get(e.parent_id); } }
  return ids;
}
/** Search complete text and resolved names across nodes and connections. */
export function searchDiagram(document, query, catalog = new Map()) {
  const term = query.trim().toLocaleLowerCase();
  if (!term) return [];
  return [...document.elements.map((e) => ({ id: e.id, kind: 'element', label: e.title || e.text || e.kind,
    text: [e.title, e.text, e.stage_hint, e.kind, ...e.entities.map((ref) => `${ref.api_name} ${catalog.get(`${ref.category}:${ref.api_name}`)?.name ?? ''}`)].join(' ') })),
  ...document.connections.map((e) => ({ id: e.id, kind: 'connection', label: e.condition || e.notes || 'Connection', text: `${e.condition} ${e.notes}` }))]
    .filter((result) => result.text.toLocaleLowerCase().includes(term));
}
/** Reveal all ancestors of search or focus targets in the personal collapse set. */
export function revealAncestors(document, ids, collapsed) {
  const next = new Set(collapsed), map = new Map(document.elements.map((e) => [e.id, e]));
  for (const id of ids) { let e = map.get(id); while (e?.parent_id) { next.delete(e.parent_id); e = map.get(e.parent_id); } }
  return next;
}
/** Validate and prune personal view references after deletion or workspace reload. */
export function pruneViews(document, views) {
  const ids = new Set([...document.elements, ...document.connections].map((e) => e.id)), groups = new Set(document.elements.filter((e) => e.kind === 'group').map((e) => e.id));
  return (Array.isArray(views) ? views : []).slice(0, 30).filter((v) => typeof v?.name === 'string' && ['none', 'selection', 'upstream', 'downstream', 'both'].includes(v.mode)
    && v.viewport && Number.isFinite(v.viewport.x) && Number.isFinite(v.viewport.y) && Number.isFinite(v.viewport.zoom) && v.viewport.zoom > 0 && v.viewport.zoom <= 10)
    .map((v) => ({ ...v, name: v.name.slice(0, 120), seeds: (Array.isArray(v.seeds) ? v.seeds : []).filter((id) => ids.has(id)), collapsed: (Array.isArray(v.collapsed) ? v.collapsed : []).filter((id) => groups.has(id)) }));
}
/** Convert visible React Flow node geometry to worker obstacle rectangles. */
export function routingGraph(document, graph) {
  const elements = graph.nodes.map((node) => ({ id: node.id, kind: node.type, parent_id: node.parentId ?? null,
    position: absolutePosition({ id: node.id, parent_id: node.parentId, position: node.position }, document.elements),
    size: { width: node.width, height: node.height }, collapsed: node.data.collapsed }));
  const connections = graph.edges.map((edge) => ({ ...edge.data.original, source: edge.source, target: edge.target,
    // Proxy paths are temporary. Stored manual points become usable again on expansion.
    waypoints: edge.data.proxy ? [] : edge.data.waypoints, source_handle: edge.sourceHandle, target_handle: edge.targetHandle }));
  return { elements, connections };
}
