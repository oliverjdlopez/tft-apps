/** Explicit ELK compound layout commands using node sizes and side-constrained ports. */
import { descendants, boundsFor, elementSize, growGroups } from './utils.js';
import { isPositionLocked } from './document.js';

/** Build the selected sibling subtree as a compound ELK graph with fixed-side ports. */
export function layoutGraph(document, selected, direction, measured = {}) {
  const roots = selected?.size ? document.elements.filter((e) => selected.has(e.id)) : document.elements.filter((e) => !e.parent_id);
  if (selected?.size && new Set(roots.map((e) => e.parent_id)).size > 1) throw new Error('Layout selection requires siblings.');
  const included = descendants(document.elements, roots.map((e) => e.id));
  const elements = document.elements.filter((e) => included.has(e.id));
  const sides = { top: 'NORTH', right: 'EAST', bottom: 'SOUTH', left: 'WEST' };
  const nodes = new Map(elements.map((e) => [e.id, { id: e.id, ...elementSize(e, measured),
    layoutOptions: { 'elk.portConstraints': 'FIXED_SIDE', 'elk.padding': '[top=48,left=24,bottom=24,right=24]' },
    ports: [],
    ...(e.kind === 'group' ? { children: [] } : {}) }]));
  const graph = { id: 'root', layoutOptions: { 'elk.algorithm': 'layered', 'elk.direction': direction,
    'elk.hierarchyHandling': 'INCLUDE_CHILDREN', 'elk.edgeRouting': 'ORTHOGONAL',
    'elk.spacing.nodeNode': '48', 'elk.layered.spacing.nodeNodeBetweenLayers': '80' }, children: [], edges: [] };
  for (const e of elements) (included.has(e.parent_id) ? nodes.get(e.parent_id).children : graph.children).push(nodes.get(e.id));
  // A unique port per connection avoids ELK's hyperedge merger building a
  // deeply recursive component on large cyclic graphs that share side ports.
  graph.edges = document.connections.filter((e) => included.has(e.source) && included.has(e.target)).map((e) => {
    const sourcePort = `${e.id}:source`, targetPort = `${e.id}:target`;
    nodes.get(e.source).ports.push({ id: sourcePort, width: 1, height: 1,
      layoutOptions: { 'elk.port.side': sides[e.source_handle ?? (direction === 'DOWN' ? 'bottom' : 'right')] } });
    nodes.get(e.target).ports.push({ id: targetPort, width: 1, height: 1,
      layoutOptions: { 'elk.port.side': sides[e.target_handle ?? (direction === 'DOWN' ? 'top' : 'left')] } });
    return { id: e.id, sources: [sourcePort], targets: [targetPort] };
  });
  return { graph, roots, included };
}
/** Apply a completed layout, centering selection and preserving all locked world geometry. */
export function applyLayout(document, selected, result, measured = {}) {
  const { roots, included } = layoutGraph(document, selected, 'DOWN', measured);
  const locations = new Map();
  const visit = (children) => { for (const child of children ?? []) { locations.set(child.id, child); visit(child.children); } };
  visit(result.children);
  const oldBounds = boundsFor(roots, measured), newBounds = boundsFor(roots.map((e) => ({ ...e, position: locations.get(e.id) ?? e.position, size: locations.get(e.id) ?? elementSize(e, measured) })));
  const shift = selected?.size ? { x: oldBounds.x + oldBounds.width / 2 - newBounds.x - newBounds.width / 2,
    y: oldBounds.y + oldBounds.height / 2 - newBounds.y - newBounds.height / 2 } : { x: 0, y: 0 };
  // A locked descendant freezes its ancestor subtree for this layout. Otherwise
  // relative child movement would violate the lock when an ancestor moves.
  const frozen = new Set();
  for (const root of roots) if (isPositionLocked(document, root.id)) for (const id of descendants(document.elements, [root.id])) frozen.add(id);
  const rootIds = new Set(roots.map((e) => e.id)), moved = new Set();
  const elements = document.elements.map((e) => {
    const at = locations.get(e.id);
    if (!at || frozen.has(e.id)) return e;
    moved.add(e.id);
    return { ...e, position: { x: at.x + (rootIds.has(e.id) ? shift.x : 0), y: at.y + (rootIds.has(e.id) ? shift.y : 0) },
      size: e.kind === 'group' ? { width: at.width, height: at.height } : e.size };
  });
  return growGroups({ ...document, elements, connections: document.connections.map((e) => (moved.has(e.source) || moved.has(e.target))
    ? { ...e, waypoints: [] } : e) }, measured);
}
