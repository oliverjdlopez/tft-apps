/** Canonical document commands. Visible graph changes never become persisted deletions. */
import { FlowchartSchema, ClipboardSchema } from './models.js';
import { absolutePosition, descendants, boundsFor, elementSize, newId, parentOrder, growGroups } from './utils.js';

/** Initialize the 100-transaction history for one open workspace. */
export function createHistory(document) {
  return { past: [], present: FlowchartSchema.parse(document), future: [] };
}
/** Validate and commit one command, discarding no-op edits and redo branches. */
export function commit(history, document) {
  const next = FlowchartSchema.parse(document);
  if (JSON.stringify(next) === JSON.stringify(history.present)) return history;
  return { past: [...history.past, history.present].slice(-100), present: next, future: [] };
}
/** Restore the preceding document; the caller submits it through ordinary autosave. */
export function undo(history) {
  if (!history.past.length) return history;
  return { past: history.past.slice(0, -1), present: history.past.at(-1), future: [history.present, ...history.future] };
}
/** Reapply one undone command. */
export function redo(history) {
  if (!history.future.length) return history;
  return { past: [...history.past, history.present].slice(-100), present: history.future[0], future: history.future.slice(1) };
}
/** Lock movement and resizing for a locked object or a container with locked descendants. */
export function isPositionLocked(document, id) {
  const ids = descendants(document.elements, [id]);
  return document.elements.some((element) => ids.has(element.id) && element.locked);
}
/** Group two or more siblings, retaining their absolute positions and connections. */
export function groupSelection(document, selected, title = 'New group') {
  const picked = document.elements.filter((e) => selected.has(e.id));
  if (picked.length < 2 || new Set(picked.map((e) => e.parent_id)).size !== 1) throw new Error('Group at least two siblings.');
  const bounds = boundsFor(picked), parent_id = picked[0].parent_id;
  const id = newId('group'), position = { x: bounds.x - 24, y: bounds.y - 48 };
  const group = { id, kind: 'group', parent_id, position, size: { width: bounds.width + 48, height: bounds.height + 72 },
    title, stage_hint: null, entities: [], text: '', locked: false, tint: '#dbeafe' };
  return growGroups({ ...document, elements: [...document.elements.map((e) => selected.has(e.id)
    ? { ...e, parent_id: id, position: { x: e.position.x - position.x, y: e.position.y - position.y } } : e), group] });
}
/** Explicitly reparent siblings to a container, preserving absolute geometry. */
export function reparentSelection(document, selected, parentId) {
  const parent = document.elements.find((e) => e.id === parentId);
  if (parentId && parent?.kind !== 'group') throw new Error('Choose a group.');
  const picked = document.elements.filter((e) => selected.has(e.id));
  if (new Set(picked.map((e) => e.parent_id)).size > 1) throw new Error('Choose siblings.');
  if (descendants(document.elements, selected).has(parentId)) throw new Error('A group cannot contain itself.');
  const origin = parent ? absolutePosition(parent, document.elements) : { x: 0, y: 0 };
  return growGroups({ ...document, elements: document.elements.map((e) => {
    if (!selected.has(e.id)) return e;
    const at = absolutePosition(e, document.elements);
    return { ...e, parent_id: parentId, position: { x: at.x - origin.x, y: at.y - origin.y } };
  }) });
}
/** Remove a container only; immediate children inherit its parent and retain positions. */
export function ungroup(document, groupId) {
  const group = document.elements.find((e) => e.id === groupId);
  if (group?.kind !== 'group') return document;
  return { ...document, elements: document.elements.filter((e) => e.id !== groupId).map((e) => e.parent_id === groupId
    ? { ...e, parent_id: group.parent_id, position: { x: e.position.x + group.position.x, y: e.position.y + group.position.y } } : e) };
}
/** Ordinary deletion ungroups containers; the explicit recursive command removes contents. */
export function deleteSelection(document, selected, edgeIds = new Set(), withContents = false) {
  let next = document;
  const removed = withContents ? descendants(document.elements, selected) : new Set(selected);
  if (!withContents) for (const id of selected) next = ungroup(next, id);
  return { ...next, elements: next.elements.filter((e) => !removed.has(e.id)),
    connections: next.connections.filter((e) => !removed.has(e.source) && !removed.has(e.target) && !edgeIds.has(e.id)) };
}
/** Copy group descendants and internal edges, detaching children of unselected parents. */
export function copySelection(document, selected) {
  const ids = descendants(document.elements, selected);
  if (!ids.size) return null;
  const picked = document.elements.filter((e) => ids.has(e.id));
  const roots = picked.filter((e) => !ids.has(e.parent_id));
  const left = Math.min(...roots.map((e) => absolutePosition(e, document.elements).x));
  const top = Math.min(...roots.map((e) => absolutePosition(e, document.elements).y));
  return { elements: parentOrder(picked).map((e) => {
    if (ids.has(e.parent_id)) return e;
    const at = absolutePosition(e, document.elements);
    return { ...e, parent_id: null, position: { x: at.x - left, y: at.y - top } };
  }), connections: document.connections.filter((e) => ids.has(e.source) && ids.has(e.target)).map((e) => ({
    ...e, waypoints: e.waypoints.map((p) => ({ x: p.x - left, y: p.y - top })),
  })) };
}
/** Paste a validated fragment with independent ids, translating only root positions. */
export function pasteFragment(document, fragment, origin) {
  const valid = ClipboardSchema.parse({ type: 'tft.flowchart.fragment', version: 2, fragment }).fragment;
  const ids = new Map(valid.elements.map((e) => [e.id, newId(e.kind)]));
  const elements = valid.elements.map((e) => ({ ...e, id: ids.get(e.id), parent_id: ids.get(e.parent_id) ?? null,
    position: e.parent_id ? e.position : { x: origin.x + e.position.x, y: origin.y + e.position.y } }));
  const connections = valid.connections.map((e) => ({ ...e, id: newId('link'), source: ids.get(e.source), target: ids.get(e.target),
    waypoints: e.waypoints.map((p) => ({ x: p.x + origin.x, y: p.y + origin.y })) }));
  return { document: { ...document, elements: [...document.elements, ...elements], connections: [...document.connections, ...connections] }, ids: new Set(elements.map((e) => e.id)), rootIds: new Set(elements.filter((e) => !e.parent_id).map((e) => e.id)) };
}
/** Reconnect an existing link without replacing identity, guard, notes or label placement. */
export function reconnect(document, id, endpoints) {
  return FlowchartSchema.parse({ ...document, connections: document.connections.map((e) => e.id === id ? { ...e, ...endpoints } : e) });
}
/** Insert one action on a transition; the original metadata stays on the incoming link. */
export function insertAction(document, id) {
  const edge = document.connections.find((e) => e.id === id);
  if (edge?.kind !== 'transition') throw new Error('Select a transition.');
  const a = document.elements.find((e) => e.id === edge.source), b = document.elements.find((e) => e.id === edge.target);
  const from = absolutePosition(a, document.elements), to = absolutePosition(b, document.elements);
  const parent_id = a.parent_id === b.parent_id ? a.parent_id : null;
  const parent = document.elements.find((e) => e.id === parent_id);
  const origin = parent ? absolutePosition(parent, document.elements) : { x: 0, y: 0 };
  const node = { id: newId('action'), kind: 'action', parent_id, locked: false, tint: null,
    position: { x: (from.x + to.x) / 2 - origin.x, y: (from.y + to.y) / 2 - origin.y },
    size: null, title: 'New action', text: '', stage_hint: null, entities: [] };
  return growGroups({ ...document, elements: [...document.elements, node], connections: [...document.connections.map((e) => e.id === id
    ? { ...e, target: node.id, waypoints: [], target_handle: 'top' } : e),
    { id: newId('link'), source: node.id, target: b.id, kind: 'transition', condition: '', notes: '',
      source_handle: 'bottom', target_handle: edge.target_handle, waypoints: [], label_offset: null }] });
}
/** Align or distribute selected siblings. Locked objects and their containing groups stay fixed. */
export function arrangeSelection(document, selected, command, measured = {}) {
  const picked = document.elements.filter((e) => selected.has(e.id));
  if (picked.length < 2 || new Set(picked.map((e) => e.parent_id)).size !== 1) throw new Error('Arrange selected siblings.');
  const bounds = boundsFor(picked, measured), positions = new Map();
  if (command.startsWith('distribute')) {
    if (picked.length < 3) return document;
    const axis = command.endsWith('x') ? 'x' : 'y', dimension = axis === 'x' ? 'width' : 'height';
    const ordered = [...picked].sort((a, b) => a.position[axis] - b.position[axis]);
    const total = ordered.reduce((sum, e) => sum + elementSize(e, measured)[dimension], 0);
    const gap = (bounds[dimension] - total) / (ordered.length - 1);
    let at = bounds[axis];
    for (const e of ordered) { positions.set(e.id, { ...e.position, [axis]: at }); at += elementSize(e, measured)[dimension] + gap; }
  } else for (const e of picked) {
    const s = elementSize(e, measured), position = { ...e.position };
    if (command === 'left') position.x = bounds.x;
    if (command === 'center') position.x = bounds.x + (bounds.width - s.width) / 2;
    if (command === 'right') position.x = bounds.x + bounds.width - s.width;
    if (command === 'top') position.y = bounds.y;
    if (command === 'middle') position.y = bounds.y + (bounds.height - s.height) / 2;
    if (command === 'bottom') position.y = bounds.y + bounds.height - s.height;
    positions.set(e.id, position);
  }
  const moved = new Set();
  const elements = document.elements.map((e) => {
    if (!positions.has(e.id) || isPositionLocked(document, e.id)) return e;
    moved.add(e.id); return { ...e, position: positions.get(e.id) };
  });
  const affected = descendants(elements, moved);
  return growGroups({ ...document, elements, connections: document.connections.map((e) => affected.has(e.source) || affected.has(e.target) ? { ...e, waypoints: [] } : e) }, measured);
}

/** Translate authored bends when both endpoints move by the same group/selection delta. */
export function moveInternalRoutes(before, after) {
  const positions = (elements) => {
    const map = new Map();
    for (const e of parentOrder(elements)) {
      const parent = map.get(e.parent_id) ?? { x: 0, y: 0 };
      map.set(e.id, { x: e.position.x + parent.x, y: e.position.y + parent.y });
    }
    return map;
  };
  const old = positions(before.elements), next = positions(after.elements);
  const delta = (id) => ({ x: next.get(id).x - old.get(id).x, y: next.get(id).y - old.get(id).y });
  return { ...after, connections: after.connections.map((edge) => {
    const a = delta(edge.source), b = delta(edge.target);
    if (a.x !== b.x || a.y !== b.y || !edge.waypoints.length || !a.x && !a.y) return edge;
    return { ...edge, waypoints: edge.waypoints.map((p) => ({ x: p.x + a.x, y: p.y + a.y })) };
  }) };
}
