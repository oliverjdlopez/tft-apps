/** Conversions between portable workspace documents, saved groups, and React Flow state. */
import { getBezierPath, getSmoothStepPath } from "@xyflow/react";
import { FlowchartFragmentSchema } from "./models.js";

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
    data: {
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
    data: { condition: connection.condition, notes: connection.notes },
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
    return ["unit", "item", "augment"].includes(value?.category) && typeof value.api_name === "string"
      ? { category: value.category, api_name: value.api_name }
      : null;
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
