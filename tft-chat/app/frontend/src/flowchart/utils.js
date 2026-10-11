/** Conversions between portable workspace documents, saved groups, and React Flow state. */
import { getBezierPath, getSmoothStepPath } from "@xyflow/react";
import { ClipboardSchema, EntityRefSchema, FlowchartFragmentSchema } from "./models.js";

/** Handle ids that name a side of a multi-handle node; other handles serialize as `null`. */
const HANDLE_SIDES = new Set(["top", "right", "bottom", "left"]);

/** Node kinds that accept dropped entity chips. */
export const CHIP_KINDS = new Set(["plan", "action"]);

/** Id of the shared arrowhead `<marker>` that `FlowchartPanel` renders once per canvas. */
export const ARROW_MARKER = "flowchart-arrow";

/**
 * Size each node kind starts at, on the 16px snap grid.
 *
 * Nodes whose size follows their content (states, actions, entities, notes)
 * only use this as the outline fallback before React Flow measures them.
 */
export const DEFAULT_SIZES = {
  group: { width: 320, height: 240 },
  plan: { width: 224, height: 112 },
  action: { width: 192, height: 64 },
  decision: { width: 128, height: 96 },
  fork: { width: 160, height: 10 },
  start: { width: 24, height: 24 },
  end: { width: 28, height: 28 },
  entity: { width: 96, height: 96 },
  note: { width: 192, height: 96 },
};

/**
 * Sizes applied to nodes saved without one.
 *
 * Decisions and fork bars have no content to size them. Notes get only a
 * width, so their text wraps and the note grows downward with it.
 */
const FIXED_SIZE_DEFAULTS = {
  decision: DEFAULT_SIZES.decision,
  fork: DEFAULT_SIZES.fork,
  note: { width: DEFAULT_SIZES.note.width },
};

/** MIME type carrying one `EntityRef` from the sidebar to the canvas. */
export const ENTITY_MIME = "application/x-tft-entity";

/** MIME type carrying a saved group's fragment from the library tab to the canvas. */
export const GROUP_MIME = "application/x-tft-flowchart-group";

/**
 * Create an element or connection id matching the backend's id pattern.
 *
 * Time plus randomness is unique enough for one player's canvas and avoids
 * depending on `crypto.randomUUID`, which older embedded browsers lack.
 */
export function newId(prefix) {
  return `${prefix}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

/** Index catalog entries by `category:api_name` for chip and tile rendering. */
export function catalogIndex(catalog) {
  const index = new Map();
  if (!catalog) return index;
  for (const [category, entries] of [["unit", catalog.units], ["item", catalog.items], ["augment", catalog.augments]])
    for (const entry of entries) index.set(`${category}:${entry.api_name}`, entry);
  return index;
}

/** Map saved elements to React Flow nodes; a saved size pins the node's dimensions. */
export function toNodes(elements) {
  return elements.map((element) => ({
    id: element.id,
    type: element.kind,
    position: element.position,
    ...(element.size ?? FIXED_SIZE_DEFAULTS[element.kind] ?? {}),
    parentId: element.parent_id ?? undefined,
    data: {
      parent_id: element.parent_id ?? null, locked: element.locked ?? false, tint: element.tint ?? null,
      explicitSize: element.size,
      title: element.title,
      stage_hint: element.stage_hint ?? "",
      entities: element.entities,
      text: element.text,
    },
  }));
}

/** Map saved connections to React Flow edges rendered by the custom edge types. */
export function toEdges(connections) {
  return connections.map((connection) => ({
    id: connection.id,
    source: connection.source,
    target: connection.target,
    // Links saved before every node had four sides (or saved with a null
    // side) left from the right and entered on the left, so keep them there.
    sourceHandle: connection.source_handle ?? "right",
    targetHandle: connection.target_handle ?? "left",
    type: connection.kind,
    ...edgeDecoration(connection.kind),
    data: { condition: connection.condition, notes: connection.notes, waypoints: connection.waypoints ?? [], label_offset: connection.label_offset ?? null },
  }));
}

/** Arrowheads show a transition's direction; annotations stay undirected. */
export function edgeDecoration(kind) {
  // React Flow wraps a string marker in `url('#…')` itself, so pass the bare id.
  return kind === "transition" ? { markerEnd: ARROW_MARKER } : {};
}

/**
 * Build an edge's SVG path and label point in the viewer's chosen style.
 *
 * Right-angle "step" routing is the default because it reads like an activity
 * diagram; "curve" keeps React Flow's bezier routing.
 */
export function edgePath(geometry, style) {
  const { sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition } = geometry;
  const points = { sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition };
  return style === "curve"
    ? getBezierPath(points)
    : getSmoothStepPath({ ...points, borderRadius: 8, offset: 16 });
}

/**
 * Serialize canvas state back to the portable flowchart document.
 *
 * Only persisted fields are read, so selection, dragging, and measurement
 * updates from React Flow never look like edits to the save loop.
 */
export function toFlowchart(nodes, edges, viewport) {
  return {
    elements: nodes.map((node) => ({
      id: node.id,
      kind: node.type,
      position: { x: finite(node.position.x), y: finite(node.position.y) },
      size: node.width && node.height
        ? { width: Math.round(node.width), height: Math.round(node.height) }
        : null,
      parent_id: node.parentId ?? node.data.parent_id ?? null, locked: node.data.locked ?? false, tint: node.data.tint ?? null,
      title: node.data.title ?? "",
      stage_hint: node.data.stage_hint ? node.data.stage_hint : null,
      entities: node.data.entities ?? [],
      text: node.data.text ?? "",
    })),
    connections: edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      kind: edge.type === "annotation" ? "annotation" : "transition",
      condition: edge.data?.condition ?? "",
      notes: edge.data?.notes ?? "",
      source_handle: HANDLE_SIDES.has(edge.sourceHandle) ? edge.sourceHandle : null,
      target_handle: HANDLE_SIDES.has(edge.targetHandle) ? edge.targetHandle : null,
      waypoints: edge.data?.waypoints ?? [], label_offset: edge.data?.label_offset ?? null,
    })),
    viewport: { x: viewport.x, y: viewport.y, zoom: viewport.zoom },
  };
}

/** Round a canvas coordinate, replacing NaN from an unmeasured canvas with the origin. */
function finite(value) {
  return Number.isFinite(value) ? Math.round(value) : 0;
}

/** Choose the connection kind: any link touching a note is an annotation. */
export function connectionKind(nodes, source, target) {
  const kinds = new Set(nodes.filter((node) => node.id === source || node.id === target).map((node) => node.type));
  return kinds.has("note") ? "annotation" : "transition";
}

/**
 * Refuse links the backend would reject, so the canvas never builds an unsavable graph.
 *
 * Mirrors `Flowchart.validate_graph`: no self-links, and a transition (any link
 * not touching a note) cannot enter a start or leave an end.
 */
export function isValidLink(nodes, { source, target }) {
  if (!source || !target || source === target) return false;
  const kind = (id) => nodes.find((node) => node.id === id)?.type;
  if (!kind(source) || !kind(target) || kind(source) === "group" || kind(target) === "group") return false;
  if (connectionKind(nodes, source, target) === "annotation") return true;
  return kind(target) !== "start" && kind(source) !== "end";
}

/** Initial title, size, and data for a node added from the toolbar. */
export function newNode(kind, position) {
  const node = {
    id: newId(kind), type: kind, position,
    data: { title: kind === "plan" ? "New state" : "", stage_hint: "", entities: [], text: "" },
  };
  // The fork starts as a horizontal bar for top-to-bottom flow.
  return FIXED_SIZE_DEFAULTS[kind] ? { ...node, ...FIXED_SIZE_DEFAULTS[kind] } : node;
}

/** Read a dragged `EntityRef`, ignoring drops that did not come from the sidebar. */
export function readDraggedEntity(dataTransfer) {
  try {
    const value = JSON.parse(dataTransfer.getData(ENTITY_MIME));
    const parsed = EntityRefSchema.safeParse(value);
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

/**
 * Cut the selected nodes, and the links between them, into a saved-group fragment.
 *
 * Links with only one selected end are dropped, since a group must stand on
 * its own. Positions are shifted so the group's top-left corner is the origin,
 * letting insertion place it anywhere.
 *
 * Returns:
 *   `{ elements, connections }`, or null when no node is selected.
 */
export function toFragment(nodes, edges) {
  const picked = nodes.filter((node) => node.selected);
  if (!picked.length) return null;
  const ids = new Set(picked.map((node) => node.id));
  const inside = edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));
  const { elements, connections } = toFlowchart(picked, inside, { x: 0, y: 0, zoom: 1 });
  const left = Math.min(...elements.map((element) => element.position.x));
  const top = Math.min(...elements.map((element) => element.position.y));
  return {
    elements: elements.map((element) => ({
      ...element, position: { x: element.position.x - left, y: element.position.y - top },
    })),
    connections,
  };
}

/**
 * Turn a saved group into new, selected canvas nodes and edges placed at `origin`.
 *
 * Every element and link gets a fresh id, so the same group can be inserted
 * many times and the copies never collide with each other or the canvas.
 */
export function fromFragment(fragment, origin) {
  const ids = new Map(fragment.elements.map((element) => [element.id, newId(element.kind)]));
  const nodes = toNodes(fragment.elements.map((element) => ({
    ...element,
    id: ids.get(element.id),
    position: { x: finite(origin.x + element.position.x), y: finite(origin.y + element.position.y) },
  }))).map((node) => ({ ...node, selected: true }));
  const edges = toEdges(fragment.connections.map((connection) => ({
    ...connection, id: newId("link"), source: ids.get(connection.source), target: ids.get(connection.target),
  })));
  return { nodes, edges };
}

/** Read a dragged saved group, ignoring payloads that are not a valid fragment. */
export function readDraggedGroup(dataTransfer) {
  try {
    const result = FlowchartFragmentSchema.safeParse(JSON.parse(dataTransfer.getData(GROUP_MIME)));
    return result.success && result.data.elements.length ? result.data : null;
  } catch {
    return null;
  }
}

/** Derive the same `<slug>.json` filename the server export writes. */
export function slugify(name) {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80).replace(/-+$/, "");
  return slug || "workspace";
}

/** Offer a workspace document to the browser as a JSON download. */
export function downloadWorkspace(workspace) {
  const blob = new Blob([JSON.stringify(workspace, null, 2) + "\n"], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${slugify(workspace.name)}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

// ============================================================================
// Canonical document and grouping commands
//
// Positions stay relative to parents in storage. Geometry algorithms use world
// coordinates, so all conversions pass through these shared helpers.
// ============================================================================

/** Accumulate parent offsets without depending on element array order. */
export function absolutePosition(element, elements) {
  const map = new Map(elements.map((e) => [e.id, e]));
  const position = { ...element.position }, seen = new Set([element.id]);
  let parent = map.get(element.parent_id);
  while (parent && !seen.has(parent.id)) {
    seen.add(parent.id); position.x += parent.position.x; position.y += parent.position.y; parent = map.get(parent.parent_id);
  }
  return position;
}
/** Include all nested descendants of the given seeds in bounded passes. */
export function descendants(elements, seeds) {
  const ids = new Set(seeds);
  for (let changed = true; changed;) {
    changed = false;
    for (const e of elements) if (ids.has(e.parent_id) && !ids.has(e.id)) { ids.add(e.id); changed = true; }
  }
  return ids;
}
/** Parents precede children as required by React Flow and compound layout. */
export function parentOrder(elements) {
  const result = [], pending = new Map(elements.map((e) => [e.id, e]));
  while (pending.size) {
    const ready = [...pending.values()].filter((e) => !pending.has(e.parent_id));
    if (!ready.length) throw new Error('Cyclic containment');
    for (const e of ready) { result.push(e); pending.delete(e.id); }
  }
  return result;
}
/** Content-aware size estimate used until DOM measurements become available. */
export function contentSize(element) {
  const base = DEFAULT_SIZES[element.kind] ?? { width: 320, height: 240 };
  if (['start', 'end', 'fork', 'group'].includes(element.kind)) return base;
  const text = element.kind === 'note' ? element.text : element.title;
  const width = base.width;
  const usable = element.kind === 'decision' ? width / 2 - 12 : width - 24;
  const lines = text.split('\n').reduce((sum, line) => sum + Math.max(1, Math.ceil(line.length * 7 / usable)), 0);
  const height = Math.max(base.height, lines * 20 * (element.kind === 'decision' ? 2 : 1) + 40 + Math.ceil(element.entities.length / 5) * 38);
  return { width, height: Math.min(4000, height) };
}
/** Prefer explicit geometry, otherwise current measurements, then readable defaults. */
export function elementSize(element, measured = {}) {
  return element.size ?? measured[element.id] ?? contentSize(element);
}
/** Bounding box in the supplied elements' common parent coordinates. */
export function boundsFor(elements, measured = {}) {
  if (!elements.length) return { x: 0, y: 0, width: 0, height: 0 };
  const x = Math.min(...elements.map((e) => e.position.x)), y = Math.min(...elements.map((e) => e.position.y));
  return { x, y, width: Math.max(...elements.map((e) => e.position.x + elementSize(e, measured).width)) - x,
    height: Math.max(...elements.map((e) => e.position.y + elementSize(e, measured).height)) - y };
}
/** Expand containers when explicit edits would otherwise clip their children. */
export function growGroups(document, measured = {}) {
  const elements = document.elements.map((e) => ({ ...e, position: { ...e.position } }));
  for (const group of parentOrder(elements).reverse().filter((e) => e.kind === 'group')) {
    const children = elements.filter((e) => e.parent_id === group.id);
    if (!children.length) continue;
    const bounds = boundsFor(children, measured);
    const dx = Math.min(0, bounds.x - 24), dy = Math.min(0, bounds.y - 48);
    // Expand toward the top/left while counter-translating children. Their world
    // positions, including locked descendants, must remain unchanged.
    group.position.x += dx; group.position.y += dy;
    for (const child of children) { child.position.x -= dx; child.position.y -= dy; }
    const size = elementSize(group, measured);
    group.size = { width: Math.max(size.width, bounds.x + bounds.width - dx + 24), height: Math.max(size.height, bounds.y + bounds.height - dy + 24) };
  }
  return { ...document, elements };
}
/** Detect an editable DOM target so canvas shortcuts preserve normal text editing. */
export function isEditorTarget(target) {
  return Boolean(target?.closest?.('input, textarea, [contenteditable="true"], select'));
}
/** Read the versioned clipboard envelope with payload and graph bounds enforced. */
export function readClipboard(text) {
  if (!text || text.length > 2_000_000) return null;
  try { const result = ClipboardSchema.safeParse(JSON.parse(text)); return result.success ? result.data.fragment : null; }
  catch { return null; }
}
/** Snap a sibling's moving box to nearby edges or centers and return guide lines. */
export function dragGuides(element, position, siblings, measured = {}, threshold = 6) {
  const size = elementSize(element, measured), next = { ...position }, guides = [];
  for (const [axis, dimension] of [['x', 'width'], ['y', 'height']]) {
    let best = threshold + 1, match;
    for (const other of siblings) {
      const otherSize = elementSize(other, measured);
      for (const fraction of [0, 0.5, 1]) for (const peerFraction of [0, 0.5, 1]) {
        const line = other.position[axis] + otherSize[dimension] * peerFraction;
        const offset = line - (position[axis] + size[dimension] * fraction);
        if (Math.abs(offset) < best) { best = Math.abs(offset); match = { axis, line, offset }; }
      }
    }
    if (match) { next[axis] += match.offset; guides.push(match); }
  }
  return { position: next, guides };
}

// ============================================================================
// Routing worker and custom edges
//
// These geometry helpers are pure so worker and geometry tests share the same
// obstacle and segment definitions without importing browser-only components.
// ============================================================================

/** Return whether an axis-aligned segment passes through a rectangle's interior. */
export function segmentBlocked(a, b, rect) {
  if (a.x === b.x) return a.x > rect.x && a.x < rect.x + rect.width && Math.max(a.y, b.y) > rect.y && Math.min(a.y, b.y) < rect.y + rect.height;
  if (a.y === b.y) return a.y > rect.y && a.y < rect.y + rect.height && Math.max(a.x, b.x) > rect.x && Math.min(a.x, b.x) < rect.x + rect.width;
  return true;
}
/** Rectangle intersection for label placement. Touching bounds are allowed. */
export function rectanglesOverlap(a, b) {
  return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
}
/** Remove repeated and collinear points from an orthogonal route. */
export function simplifyRoute(points) {
  const result = [];
  for (const point of points) {
    const b = result.at(-1), a = result.at(-2);
    if (b && b.x === point.x && b.y === point.y) continue;
    if (a && ((a.x === b.x && b.x === point.x && (b.y - a.y) * (point.y - b.y) >= 0) || (a.y === b.y && b.y === point.y && (b.x - a.x) * (point.x - b.x) >= 0))) result.pop();
    result.push(point);
  }
  return result;
}
/** Path serialization keeps manual routes orthogonal even after endpoint movement. */
export function orthogonalPoints(points) {
  const result = [];
  for (const point of points) {
    const prior = result.at(-1);
    if (prior && prior.x !== point.x && prior.y !== point.y) result.push({ x: point.x, y: prior.y });
    result.push(point);
  }
  return simplifyRoute(result);
}
/** Convert orthogonal points to a SVG path, with the midpoint as label fallback. */
export function routePath(points) {
  const line = orthogonalPoints(points);
  const middle = line[Math.floor(line.length / 2)] ?? { x: 0, y: 0 };
  return [line.map((p, i) => `${i ? 'L' : 'M'} ${p.x} ${p.y}`).join(' '), middle.x, middle.y];
}
/** Route length/turn heuristic for the visibility graph's A* search. */
export function manhattan(a, b) { return Math.abs(a.x - b.x) + Math.abs(a.y - b.y); }
/** Penalize sharing lanes and crossing already routed links to improve separation. */
export function segmentPenalty(a, b, previous) {
  let cost = 0;
  for (const [c, d] of previous) {
    const horizontal = a.y === b.y, otherHorizontal = c.y === d.y;
    if (horizontal === otherHorizontal) {
      const sameLane = horizontal ? a.y === c.y : a.x === c.x;
      const overlap = horizontal ? Math.min(Math.max(a.x, b.x), Math.max(c.x, d.x)) - Math.max(Math.min(a.x, b.x), Math.min(c.x, d.x))
        : Math.min(Math.max(a.y, b.y), Math.max(c.y, d.y)) - Math.max(Math.min(a.y, b.y), Math.min(c.y, d.y));
      if (sameLane && overlap > 0) cost += overlap * 0.8 + 40;
    } else {
      const h = horizontal ? [a, b] : [c, d], v = horizontal ? [c, d] : [a, b];
      if (v[0].x > Math.min(h[0].x, h[1].x) && v[0].x < Math.max(h[0].x, h[1].x) && h[0].y > Math.min(v[0].y, v[1].y) && h[0].y < Math.max(v[0].y, v[1].y)) cost += 100;
    }
  }
  return cost;
}
/** Binary min-heap operations avoid quadratic A* queue scans on large diagrams. */
export function heapPush(heap, item) {
  heap.push(item); let i = heap.length - 1;
  while (i > 0) { const parent = (i - 1) >> 1; if (heap[parent].score <= item.score) break; heap[i] = heap[parent]; i = parent; }
  heap[i] = item;
}
/** Pop the cheapest visibility state from the shared A* min-heap. */
export function heapPop(heap) {
  const first = heap[0], last = heap.pop();
  if (heap.length) {
    let i = 0;
    while (i * 2 + 1 < heap.length) {
      let child = i * 2 + 1;
      if (child + 1 < heap.length && heap[child + 1].score < heap[child].score) child++;
      if (heap[child].score >= last.score) break;
      heap[i] = heap[child]; i = child;
    }
    heap[i] = last;
  }
  return first;
}
