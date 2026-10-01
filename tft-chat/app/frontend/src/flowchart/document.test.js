import { describe, expect, it } from 'vitest';
import ELK from 'elkjs/lib/elk.bundled.js';
import { FlowchartSchema, FlowchartFragmentSchema, PatchWorkspaceSchema } from './models.js';
import { createHistory, commit, undo, redo, groupSelection, ungroup, reparentSelection, deleteSelection, copySelection, pasteFragment, reconnect, insertAction, arrangeSelection, isPositionLocked, moveInternalRoutes } from './document.js';
import { visibleGraph, focusObjects, searchDiagram, revealAncestors, pruneViews } from './projection.js';
import { absolutePosition, boundsFor, readClipboard, dragGuides, segmentBlocked, rectanglesOverlap } from './utils.js';
import { routeDiagram } from './routing.js';
import { layoutGraph, applyLayout } from './layout.js';

/** Fixture with a cycle, an annotation, and an independent branch. */
function fixture() {
  return FlowchartSchema.parse({ elements: [
    { id: 'a', kind: 'action', title: 'Roll', position: { x: 100, y: 100 } },
    { id: 'b', kind: 'decision', title: 'Hit?', position: { x: 100, y: 300 } },
    { id: 'c', kind: 'plan', title: 'Pivot', position: { x: 500, y: 300 }, entities: [{ category: 'unit', api_name: 'Ashe' }] },
    { id: 'n', kind: 'note', text: 'Contested', position: { x: 450, y: 100 } },
    { id: 'z', kind: 'action', position: { x: 1000, y: 1000 } },
  ], connections: [
    { id: 'ab', source: 'a', target: 'b', condition: 'long guard', notes: 'keep me', waypoints: [{ x: 200, y: 200 }], label_offset: { x: 3, y: 4 } },
    { id: 'ba', source: 'b', target: 'a' }, { id: 'bc', source: 'b', target: 'c' }, { id: 'na', source: 'n', target: 'a', kind: 'annotation' },
  ] });
}
const picked = (...ids) => new Set(ids);

it('normalizes legacy files and validates finite bounded geometry, parents, and link semantics', () => {
  expect(PatchWorkspaceSchema.parse({ schema_version: 'flowchart.v1', name: 'old', gameplan: { flowchart: fixture() } }).schema_version).toBe('flowchart.v2');
  for (const position of [{ x: NaN, y: 0 }, { x: Infinity, y: 0 }, { x: 1e7, y: 0 }]) expect(() => FlowchartSchema.parse({ elements: [{ id: 'a', kind: 'action', position }] })).toThrow();
  expect(() => FlowchartSchema.parse({ elements: [{ id: 'g', kind: 'group', parent_id: 'g', position: { x: 0, y: 0 } }] })).toThrow();
  expect(() => FlowchartFragmentSchema.parse({ elements: [{ id: 'a', kind: 'action', parent_id: 'missing', position: { x: 0, y: 0 } }] })).toThrow();
  expect(() => reconnect(fixture(), 'ab', { source: 'missing' })).toThrow();
});
it('history commits a whole command, caps at 100, discards redo after a new edit, and ignores no-ops', () => {
  let history = createHistory(fixture());
  expect(commit(history, history.present)).toBe(history);
  for (let i = 0; i < 105; i++) history = commit(history, { ...history.present, viewport: { x: i + 1, y: 0, zoom: 1 } });
  expect(history.past).toHaveLength(100);
  const reverted = undo(history); expect(reverted.present.viewport.x).toBe(104); expect(redo(reverted).present).toEqual(history.present);
  expect(commit(reverted, fixture()).future).toHaveLength(0);
});
it('groups and reparents nested children without changing their world positions; ordinary deletion ungroups', () => {
  const original = fixture(), grouped = groupSelection(original, picked('a', 'b'));
  const group = grouped.elements.at(-1);
  for (const id of ['a', 'b']) expect(absolutePosition(grouped.elements.find((e) => e.id === id), grouped.elements)).toEqual(original.elements.find((e) => e.id === id).position);
  const nested = groupSelection(grouped, picked(group.id, 'c'));
  const outer = nested.elements.at(-1);
  expect(FlowchartSchema.parse(nested)).toEqual(nested);
  expect(ungroup(grouped, group.id).elements).toEqual(original.elements);
  expect(deleteSelection(grouped, picked(group.id)).connections).toEqual(original.connections);
  expect(deleteSelection(nested, picked(outer.id), picked(), true).elements.map((e) => e.id)).toEqual(['n', 'z']);
  expect(() => reparentSelection(nested, picked(outer.id), group.id)).toThrow();
  const removed = reparentSelection(nested, picked('a'), null);
  expect(absolutePosition(removed.elements.find((e) => e.id === 'a'), removed.elements)).toEqual(original.elements[0].position);
  expect(() => groupSelection(grouped, picked('a', 'c'))).toThrow();
});
it('copies nested group contents with fresh ids and translates manual points, detaching selected children', () => {
  const grouped = groupSelection(fixture(), picked('a', 'b')), group = grouped.elements.at(-1);
  const fragment = copySelection(grouped, picked(group.id));
  expect(fragment.elements).toHaveLength(3); expect(fragment.connections).toHaveLength(2);
  const pasted = pasteFragment(grouped, fragment, { x: 800, y: 600 });
  expect(pasted.ids.size).toBe(3); expect([...pasted.ids].every((id) => !grouped.elements.some((e) => e.id === id))).toBe(true);
  const childCopy = copySelection(grouped, picked('a', 'b')); expect(childCopy.elements.every((e) => e.parent_id === null)).toBe(true);
  expect(readClipboard(JSON.stringify({ type: 'tft.flowchart.fragment', version: 2, fragment }))).toEqual(fragment);
  expect(readClipboard(JSON.stringify(fragment))).toBeNull();
  expect(readClipboard(JSON.stringify({ type: 'tft.flowchart.fragment', version: 2, fragment: { ...fragment, connections: [{ id: 'bad', source: 'missing', target: 'a' }] } }))).toBeNull();
});
it('collapse preserves canonical connections and every separate proxy; expansion restores manual metadata', () => {
  const grouped = groupSelection(fixture(), picked('a', 'b')), group = grouped.elements.at(-1);
  const before = JSON.stringify(grouped), collapsed = visibleGraph(grouped, picked(group.id), null, picked(), picked());
  expect(collapsed.nodes.map((n) => n.id)).not.toContain('a');
  expect(collapsed.edges.map((e) => e.id)).toEqual(['bc', 'na']);
  expect(collapsed.edges.every((e) => !e.reconnectable)).toBe(true);
  expect(collapsed.edges.find((e) => e.id === 'bc').source).toBe(group.id);
  expect(JSON.stringify(grouped)).toBe(before);
  expect(visibleGraph(grouped, picked(), null, picked(), picked()).edges.find((e) => e.id === 'ab').data.waypoints).toEqual(fixture().connections[0].waypoints);
});
it('focus traverses cycles, annotations and ancestors; search resolves entity names and reveals nested parents', () => {
  const grouped = groupSelection(fixture(), picked('a', 'b')), group = grouped.elements.at(-1);
  expect(focusObjects(grouped, picked('a'), 'downstream')).toEqual(picked('a', 'b', 'c', 'n', group.id));
  expect(focusObjects(grouped, picked('c'), 'upstream').has('a')).toBe(true);
  expect(focusObjects(grouped, picked('a'), 'both').has('z')).toBe(false);
  expect(focusObjects(grouped, picked('bc'), 'selection').has('c')).toBe(true);
  expect(searchDiagram(grouped, 'ice archer', new Map([['unit:Ashe', { name: 'Ice Archer' }]]))[0].id).toBe('c');
  expect(searchDiagram(grouped, 'long guard')[0].id).toBe('ab');
  expect(revealAncestors(grouped, ['a'], picked(group.id))).toEqual(picked());
  expect(pruneViews(grouped, [{ name: 'v', mode: 'selection', seeds: ['a', 'gone'], collapsed: [group.id, 'gone'], viewport: { x: 0, y: 0, zoom: 1 } }])[0].seeds).toEqual(['a']);
});
it('reconnect preserves identity and metadata; action insertion keeps the incoming guard and notes', () => {
  const doc = fixture(), edge = doc.connections[0];
  expect(reconnect(doc, 'ab', { target: 'c' }).connections[0]).toEqual({ ...edge, target: 'c' });
  const inserted = insertAction(doc, 'ab'), incoming = inserted.connections.find((e) => e.id === 'ab'), outgoing = inserted.connections.at(-1);
  expect(incoming).toMatchObject({ id: edge.id, condition: edge.condition, notes: edge.notes, source: 'a' });
  expect(outgoing).toMatchObject({ source: incoming.target, target: 'b', condition: '', notes: '' });
});
it('alignment respects locks and guides; mixed-parent arrangement is rejected', () => {
  const doc = fixture(); doc.elements[0].locked = true;
  const arranged = arrangeSelection(doc, picked('a', 'c'), 'right');
  expect(arranged.elements[0].position).toEqual(doc.elements[0].position);
  const grouped = groupSelection(doc, picked('a', 'b')); expect(isPositionLocked(grouped, grouped.elements.at(-1).id)).toBe(true);
  expect(() => arrangeSelection(grouped, picked('a', 'c'), 'left')).toThrow();
  const guide = dragGuides(doc.elements[1], { x: 103, y: 500 }, [doc.elements[0]]);
  expect(guide.position.x).toBe(100); expect(guide.guides).toHaveLength(1);
});
it('ELK handles measured nested graphs and selection layout preserves unselected positions and prior center', async () => {
  const doc = fixture(), selected = picked('a', 'b'), measured = { a: { width: 290, height: 100 } };
  const built = layoutGraph(doc, selected, 'RIGHT', measured);
  expect(built.graph.children[0].width).toBe(290);
  const result = await new ELK().layout(built.graph), arranged = applyLayout(doc, selected, result, measured);
  expect(arranged.elements.find((e) => e.id === 'c')).toEqual(doc.elements.find((e) => e.id === 'c'));
  const oldBounds = boundsFor(doc.elements.filter((e) => selected.has(e.id)), measured), nextBounds = boundsFor(arranged.elements.filter((e) => selected.has(e.id)), measured);
  expect(nextBounds.x + nextBounds.width / 2).toBeCloseTo(oldBounds.x + oldBounds.width / 2);
  expect(nextBounds.y + nextBounds.height / 2).toBeCloseTo(oldBounds.y + oldBounds.height / 2);
  expect(arranged.connections.find((e) => e.id === 'ab').waypoints).toEqual([]);
  const grouped = groupSelection(doc, selected), groupId = grouped.elements.at(-1).id;
  expect(() => layoutGraph(grouped, picked('a', 'c'), 'DOWN')).toThrow();
  const nested = groupSelection(grouped, picked(groupId, 'c'));
  const compoundResult = await new ELK().layout(layoutGraph(nested, null, 'DOWN').graph);
  expect(FlowchartSchema.parse(applyLayout(nested, null, compoundResult))).toBeTruthy();
  nested.elements.find((e) => e.id === 'a').locked = true;
  const lockedResult = applyLayout(nested, null, compoundResult);
  for (const e of nested.elements.filter((e) => descendantsOfLocked(nested, e.id))) expect(lockedResult.elements.find((n) => n.id === e.id)).toEqual(e);
});
/** Identify the locked subtree in this fixture for independent layout invariants. */
function descendantsOfLocked(doc, id) { return id !== 'n' && id !== 'z'; }

it('routes around obstacles, separates parallel attachments, preserves manual bends and places labels clearly', () => {
  const elements = [
    { id: 'a', kind: 'action', position: { x: 0, y: 0 }, size: { width: 100, height: 80 } },
    { id: 'block', kind: 'action', position: { x: 160, y: -30 }, size: { width: 100, height: 150 } },
    { id: 'b', kind: 'action', position: { x: 350, y: 0 }, size: { width: 100, height: 80 } },
  ];
  const connections = [0, 1].map((i) => ({ id: `e${i}`, source: 'a', target: 'b', source_handle: 'right', target_handle: 'left', condition: `guard ${i}`, waypoints: [], label_offset: null }));
  const routes = routeDiagram({ elements, connections });
  expect(routes.e0.points[0].y).not.toBe(routes.e1.points[0].y);
  const obstacle = { x: 160, y: -30, width: 100, height: 150 };
  for (const route of Object.values(routes)) {
    expect(route.warning).toBe(false);
    expect(route.points.slice(1).some((p, i) => segmentBlocked(route.points[i], p, obstacle))).toBe(false);
    expect(rectanglesOverlap({ x: route.label.x - 40, y: route.label.y - 14, width: 80, height: 28 }, obstacle)).toBe(false);
  }
  const manual = { ...connections[0], waypoints: [{ x: 280, y: 180 }] };
  const route = routeDiagram({ elements, connections: [manual] }).e0;
  expect(route.points.some((p) => p.y === 180)).toBe(true);
  expect(elements[0].position).toEqual({ x: 0, y: 0 });
});
it('retains usable warning paths when nodes overlap', () => {
  const elements = ['a', 'b'].map((id) => ({ id, kind: 'action', position: { x: 0, y: 0 }, size: { width: 100, height: 80 } }));
  const route = routeDiagram({ elements, connections: [{ id: 'e', source: 'a', target: 'b', condition: 'guard', waypoints: [] }] }).e;
  expect(route.points.length).toBeGreaterThan(1); expect(route.warning).toBe(true);
});

it('moving a container translates only its internal manual route geometry', () => {
  const grouped = groupSelection(fixture(), picked('a', 'b')), group = grouped.elements.at(-1);
  const after = { ...grouped, elements: grouped.elements.map((e) => e.id === group.id ? { ...e, position: { x: e.position.x + 50, y: e.position.y + 70 } } : e) };
  const moved = moveInternalRoutes(grouped, after);
  expect(moved.connections[0].waypoints).toEqual([{ x: 250, y: 270 }]);
  expect(moved.connections[0].label_offset).toEqual(grouped.connections[0].label_offset);
  expect(moved.connections.find((e) => e.id === 'bc')).toEqual(grouped.connections.find((e) => e.id === 'bc'));
});

it('content-sized projection grows after a long edit and fit ignores stale resized measurements', () => {
  const doc = fixture();
  doc.elements[0].title = 'A very long action title '.repeat(5);
  const projected = visibleGraph(doc, picked(), null, picked(), picked(), { a: { width: 192, height: 56 } });
  expect(projected.nodes.find((n) => n.id === 'a').height).toBeGreaterThan(56);
  doc.elements[0].size = { width: 192, height: 56 };
  expect(visibleGraph(doc, picked(), null, picked(), picked()).nodes.find((n) => n.id === 'a').height).toBe(56);
});
