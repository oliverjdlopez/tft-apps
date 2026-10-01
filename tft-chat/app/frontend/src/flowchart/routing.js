/** Obstacle-aware orthogonal routing on a shared sparse visibility graph. */
import { heapPush, heapPop, manhattan, segmentPenalty, simplifyRoute, orthogonalPoints, segmentBlocked, rectanglesOverlap } from './utils.js';

/** Build the visibility graph once per job, including endpoint and waypoint escape rays. */
export function visibilityGraph(rectangles, anchors) {
  const points = new Map();
  const add = (p) => { const key = `${p.x},${p.y}`; if (!points.has(key)) points.set(key, { ...p, key, links: [] }); return points.get(key); };
  for (const r of rectangles) for (const x of [r.x, r.x + r.width]) for (const y of [r.y, r.y + r.height]) add({ x, y });
  for (const p of anchors) add(p);
  const all = [...points.values()];
  if (!all.length) return points;
  const outer = { left: Math.min(...all.map((p) => p.x)) - 40, right: Math.max(...all.map((p) => p.x)) + 40,
    top: Math.min(...all.map((p) => p.y)) - 40, bottom: Math.max(...all.map((p) => p.y)) + 40 };
  // Project corners and anchors onto the first blocking side. Each ray joins a
  // rectangle boundary, whose corners provide the next turn, avoiding a dense
  // Cartesian grid for 400-node diagrams.
  for (const p of all) {
    let left = outer.left, right = outer.right, top = outer.top, bottom = outer.bottom;
    for (const r of rectangles) {
      if (p.y > r.y && p.y < r.y + r.height) {
        if (r.x + r.width <= p.x) left = Math.max(left, r.x + r.width);
        if (r.x >= p.x) right = Math.min(right, r.x);
      }
      if (p.x > r.x && p.x < r.x + r.width) {
        if (r.y + r.height <= p.y) top = Math.max(top, r.y + r.height);
        if (r.y >= p.y) bottom = Math.min(bottom, r.y);
      }
    }
    add({ x: left, y: p.y }); add({ x: right, y: p.y }); add({ x: p.x, y: top }); add({ x: p.x, y: bottom });
  }
  const rows = new Map(), columns = new Map();
  for (const p of points.values()) { if (!rows.has(p.y)) rows.set(p.y, []); rows.get(p.y).push(p);
    if (!columns.has(p.x)) columns.set(p.x, []); columns.get(p.x).push(p); }
  for (const [map, axis] of [[rows, 'x'], [columns, 'y']]) for (const line of map.values()) {
    line.sort((a, b) => a[axis] - b[axis]);
    for (let i = 1; i < line.length; i++) {
      const a = line[i - 1], b = line[i];
      if (!rectangles.some((r) => segmentBlocked(a, b, r))) { a.links.push(b.key); b.links.push(a.key); }
    }
  }
  return points;
}
/** Find a route with turn, shared-segment and crossing costs, bounded for degraded geometry. */
export function routeBetween(graph, start, end, previous = []) {
  const startKey = `${start.x},${start.y}`, endKey = `${end.x},${end.y}`;
  const heap = [], best = new Map(), parents = new Map();
  heapPush(heap, { key: startKey, direction: '', cost: 0, score: manhattan(start, end) });
  best.set(`${startKey}|`, 0);
  let visited = 0;
  while (heap.length && visited++ < 100_000) {
    const current = heapPop(heap), stateKey = `${current.key}|${current.direction}`;
    if (best.get(stateKey) !== current.cost) continue;
    if (current.key === endKey) {
      const result = [];
      for (let key = stateKey; key; key = parents.get(key)) result.push(graph.get(key.split('|')[0]));
      return simplifyRoute(result.reverse().map(({ x, y }) => ({ x, y })));
    }
    const point = graph.get(current.key);
    if (!point) continue;
    for (const key of point.links) {
      const next = graph.get(key), direction = next.x === point.x ? 'v' : 'h';
      const cost = current.cost + manhattan(point, next) + (current.direction && current.direction !== direction ? 24 : 0) + segmentPenalty(point, next, previous);
      const nextState = `${key}|${direction}`;
      if (cost >= (best.get(nextState) ?? Infinity)) continue;
      best.set(nextState, cost); parents.set(nextState, stateKey);
      heapPush(heap, { key, direction, cost, score: cost + manhattan(next, end) });
    }
  }
  return null;
}
/** Distribute endpoint attachments over each shared side, including fork/join bars. */
export function attachmentPoints(elements, connections) {
  const map = new Map(elements.map((e) => [e.id, e])), buckets = new Map(), result = new Map();
  for (const edge of connections) for (const end of ['source', 'target']) {
    const side = edge[`${end}_handle`] ?? (end === 'source' ? 'right' : 'left'), key = `${edge[end]}:${side}`;
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push({ edge, end, side });
  }
  for (const entries of buckets.values()) {
    entries.sort((a, b) => a.edge.id.localeCompare(b.edge.id) || a.end.localeCompare(b.end));
    entries.forEach(({ edge, end, side }, i) => {
      const node = map.get(edge[end]); if (!node) return;
      const { x, y } = node.position, { width, height } = node.size, fraction = (i + 1) / (entries.length + 1);
      const point = { x: side === 'left' ? x : side === 'right' ? x + width : x + width * fraction,
        y: side === 'top' ? y : side === 'bottom' ? y + height : y + height * fraction };
      const stub = { x: point.x + (side === 'left' ? -20 : side === 'right' ? 20 : 0), y: point.y + (side === 'top' ? -20 : side === 'bottom' ? 20 : 0) };
      result.set(`${edge.id}:${end}`, { point, stub });
    });
  }
  return result;
}
/** Place a wrapped guard at clear segment midpoints, avoiding previously placed labels. */
export function placeLabel(points, edge, rectangles, labels) {
  const width = Math.min(220, Math.max(60, edge.condition.length * 7 + 24)), height = Math.max(28, Math.ceil(edge.condition.length * 7 / 196) * 20 + 8);
  const segments = points.slice(1).map((p, i) => ({ a: points[i], b: p })).sort((a, b) => manhattan(b.a, b.b) - manhattan(a.a, a.b));
  for (const { a, b } of segments) for (const offset of [0, 24, -24, 48, -48, 80, -80]) {
    const p = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 + offset };
    const box = { x: p.x - width / 2, y: p.y - height / 2, width, height };
    if (![...rectangles, ...labels].some((r) => rectanglesOverlap(r, box))) { labels.push(box); return { ...p, warning: false }; }
  }
  const p = points[Math.floor(points.length / 2)] ?? { x: 0, y: 0 };
  return { ...p, warning: true };
}
/** Route a snapshot without changing node positions; report progress for large jobs. */
export function routeDiagram({ elements, connections }, progress = () => {}) {
  const attachments = attachmentPoints(elements, connections);
  const rectangles = elements.filter((e) => e.kind !== 'group' || e.collapsed).map((e) => ({ id: e.id,
    x: e.position.x - 12, y: e.position.y - 12, width: e.size.width + 24, height: e.size.height + 24 }));
  const anchors = [...attachments.values()].map((a) => a.stub).concat(connections.flatMap((e) => e.waypoints));
  const graph = visibilityGraph(rectangles, anchors), routes = {}, previous = [], labels = [];
  for (let index = 0; index < connections.length; index++) {
    const edge = connections[index], a = attachments.get(`${edge.id}:source`), b = attachments.get(`${edge.id}:target`);
    if (!a || !b) continue;
    const stops = [a.stub, ...edge.waypoints, b.stub], points = [a.point];
    const sourceNode = elements.find((e) => e.id === edge.source), targetNode = elements.find((e) => e.id === edge.target);
    let warning = rectanglesOverlap({ ...sourceNode.position, ...sourceNode.size }, { ...targetNode.position, ...targetNode.size });
    for (let i = 1; i < stops.length; i++) {
      const leg = routeBetween(graph, stops[i - 1], stops[i], previous);
      if (!leg) warning = true;
      points.push(...(leg ?? orthogonalPoints([stops[i - 1], stops[i]])));
    }
    points.push(b.point);
    const path = simplifyRoute(points), label = placeLabel(path, edge, rectangles, labels);
    // A short escape leg may cross an overlapping neighbour even if A* succeeds.
    warning ||= path.slice(1).some((p, i) => rectangles.some((r) => r.id !== edge.source && r.id !== edge.target && segmentBlocked(path[i], p, r)));
    routes[edge.id] = { points: path, label, warning: warning || (Boolean(edge.condition) && label.warning) };
    for (let i = 1; i < path.length; i++) previous.push([path[i - 1], path[i]]);
    if (index % 20 === 0 || index === connections.length - 1) progress({ completed: index + 1, total: connections.length });
  }
  return routes;
}
