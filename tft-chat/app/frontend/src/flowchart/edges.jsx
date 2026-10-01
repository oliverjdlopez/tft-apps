/** Routed transitions with readable labels and explicit manual placement gestures. */
import React, { useState } from 'react';
import { BaseEdge, EdgeLabelRenderer, useInternalNode } from '@xyflow/react';
import { StickyNote } from 'lucide-react';
import { useFlowchart } from './context.js';
import { edgePath, routePath, orthogonalPoints } from './utils.js';
import TextField from './TextField.jsx';

/** Render worker routes, provisional curves, orthogonal bend handles and draggable guard text. */
export function TransitionEdge({ id, source, data, selected, markerEnd, ...geometry }) {
  const { readOnly, edgeStyle, updateEdgeData, screenToFlowPosition, routingBusy } = useFlowchart();
  const [notesOpen, setNotesOpen] = useState(false), [preview, setPreview] = useState(null), [labelPreview, setLabelPreview] = useState(null);
  const sourceNode = useInternalNode(source), branch = data?.original?.kind !== 'annotation' && sourceNode?.type === 'decision';
  const condition = data?.condition ?? '', notes = data?.notes ?? '';
  const route = data?.route, manual = Boolean(data?.waypoints?.length), proxy = data?.proxy;
  const points = preview ?? route?.points ?? orthogonalPoints([{ x: geometry.sourceX, y: geometry.sourceY }, ...(proxy ? [] : data?.waypoints ?? []), { x: geometry.targetX, y: geometry.targetY }]);
  const routed = !routingBusy && route;
  const [path, fallbackX, fallbackY] = (manual || preview || (edgeStyle !== 'curve' && routed)) ? routePath(points) : edgePath(geometry, edgeStyle);
  const label = routed?.label ?? { x: fallbackX, y: fallbackY }, offset = labelPreview ?? data?.label_offset ?? { x: 0, y: 0 };
  const showLabel = Boolean(condition || notes || selected || branch);
  /** A pointer gesture changes local preview; only its completed placement enters history. */
  const dragLabel = (event) => {
    if (readOnly || proxy || event.button !== 0) return;
    event.preventDefault(); event.stopPropagation();
    const start = screenToFlowPosition({ x: event.clientX, y: event.clientY }), initial = { ...offset };
    let next = initial;
    const move = (e) => { const at = screenToFlowPosition({ x: e.clientX, y: e.clientY }); next = { x: initial.x + at.x - start.x, y: initial.y + at.y - start.y }; setLabelPreview(next); };
    const finish = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', finish); window.removeEventListener('pointercancel', cancel); setLabelPreview(null); updateEdgeData(id, { label_offset: next }); };
    const cancel = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', finish); window.removeEventListener('pointercancel', cancel); setLabelPreview(null); };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', finish, { once: true }); window.addEventListener('pointercancel', cancel, { once: true });
  };
  const dragSegment = (event, index) => {
    if (readOnly || proxy || event.button !== 0) return;
    event.preventDefault(); event.stopPropagation();
    const a = points[index], b = points[index + 1], horizontal = a.y === b.y;
    const start = screenToFlowPosition({ x: event.clientX, y: event.clientY });
    let next = points;
    const move = (e) => {
      const at = screenToFlowPosition({ x: e.clientX, y: e.clientY });
      // Endpoint-adjacent legs gain two bends so the attachment never moves.
      next = points.flatMap((p, i) => {
        const shifted = { ...p, [horizontal ? 'y' : 'x']: a[horizontal ? 'y' : 'x'] + at[horizontal ? 'y' : 'x'] - start[horizontal ? 'y' : 'x'] };
        if (i === index) return i === 0 ? [p, shifted] : [shifted];
        if (i === index + 1) return i === points.length - 1 ? [shifted, p] : [shifted];
        return [p];
      });
      setPreview(next);
    };
    const finish = () => { cancel(); updateEdgeData(id, { waypoints: orthogonalPoints(next).slice(1, -1).slice(0, 64) }); };
    const cancel = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', finish); window.removeEventListener('pointercancel', cancel); setPreview(null); };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', finish, { once: true }); window.addEventListener('pointercancel', cancel, { once: true });
  };
  return <>
    <BaseEdge id={id} path={path} markerEnd={markerEnd} interactionWidth={16} className={data?.original?.kind === 'annotation' ? 'flowchart-annotation' : 'flowchart-transition'} />
    {selected && !readOnly && !proxy && points.slice(1).map((p, i) => <line key={i} className="flowchart-segment-handle nodrag nopan"
      x1={points[i].x} y1={points[i].y} x2={p.x} y2={p.y} stroke="transparent" strokeWidth={12}
      onPointerDown={(event) => dragSegment(event, i)}><title>Drag orthogonal segment</title></line>)}
    {selected && !readOnly && !proxy && <EdgeLabelRenderer>{points.slice(1).map((p, i) => <button key={i}
      type="button" className="flowchart-bend-grip nodrag nopan" aria-label={`Drag orthogonal segment ${i + 1}`}
      style={{ transform: `translate(-50%, -50%) translate(${(points[i].x + p.x) / 2}px, ${(points[i].y + p.y) / 2 + 32}px)` }}
      onPointerDown={(event) => dragSegment(event, i)}>↔</button>)}</EdgeLabelRenderer>}
    {showLabel && <EdgeLabelRenderer><div className="nodrag nopan flowchart-edge-label" data-id={id}
      style={{ transform: `translate(-50%, -50%) translate(${label.x + offset.x}px, ${label.y + offset.y}px)` }}>
      <div className="flowchart-edge-pill" data-selected={selected || undefined} data-missing-guard={branch && !condition.trim() || undefined}>
        {!readOnly && !proxy && <button type="button" className="flowchart-label-grip" aria-label="Drag guard label" onPointerDown={dragLabel}>⠿</button>}
        {(condition || selected || branch) && <TextField label="Transition guard" prefix="[" suffix="]" value={condition}
          placeholder={branch ? 'branch when…' : 'when…'} maxLength={200} multiline onCommit={(condition) => updateEdgeData(id, { condition })} />}
        {(notes || selected) && <button type="button" className="flowchart-edge-notes-toggle" aria-label="Notes" aria-expanded={notesOpen}
          data-has-notes={Boolean(notes) || undefined} onClick={() => setNotesOpen(!notesOpen)}><StickyNote aria-hidden="true" /></button>}
      </div>
      {notesOpen && <div className="flowchart-edge-notes"><TextField label="Transition notes" value={notes} placeholder="Situational detail"
        maxLength={2000} multiline onCommit={(notes) => updateEdgeData(id, { notes })} /></div>}
    </div></EdgeLabelRenderer>}
  </>;
}
/** Dashed annotations use the same obstacle routing while staying undirected. */
export function AnnotationEdge(props) {
  return <TransitionEdge {...props} markerEnd={undefined} />;
}
export const edgeTypes = { transition: TransitionEdge, annotation: AnnotationEdge };
