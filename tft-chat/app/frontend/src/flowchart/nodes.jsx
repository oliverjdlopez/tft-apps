/**
 * Custom React Flow nodes for the player's decision graph.
 *
 * Each kind borrows a UML activity-diagram shape so its role reads at a glance:
 * cards for strategic states, rounded rectangles for actions, diamonds for
 * decisions, bars for forks and joins, dots for start and end, and folded
 * notes. Every outline is drawn by `Outline` from the same stroke, radius, and
 * role-color tokens in `flowchart.css`, so the shapes stay visually consistent.
 */
import React, { useEffect, useRef, useState } from "react";
import { Handle, NodeResizer, Position } from "@xyflow/react";
import { X } from "lucide-react";
import TextField from './TextField.jsx';
import EntityTile from "./EntityTile.jsx";
import { useFlowchart } from "./context.js";
import { DEFAULT_SIZES } from "./utils.js";

/** Chips shown before a node collapses the rest behind a "+N" chip. */
const VISIBLE_CHIPS = 12;
/** Depth of a note's folded corner, in pixels. */
const NOTE_FOLD = 14;

/**
 * Four connection points, one per side, shown on hover or selection.
 *
 * All are `source` handles; the canvas runs in loose connection mode, so any
 * side can also end a link. Ids name the side and are saved with each link.
 */
function SideHandles() {
  return <>
    <Handle type="source" id="top" position={Position.Top} />
    <Handle type="source" id="right" position={Position.Right} />
    <Handle type="source" id="bottom" position={Position.Bottom} />
    <Handle type="source" id="left" position={Position.Left} />
  </>;
}

/**
 * Draw a node's outline as SVG sized to the node's measured box.
 *
 * React Flow passes measured `width`/`height` to node components; before the
 * first measurement the kind's default size stands in. The selection halo is a
 * second, wider path in the ring color underneath, so every shape (including
 * the diamond and folded note) gets a halo that follows its real edge.
 *
 * Args:
 *   shape: `rect`, `rhombus`, or `note`.
 *   kind: Node kind, used for the fallback size and role color class.
 *   width: Measured node width, if known.
 *   height: Measured node height, if known.
 *   selected: Whether to draw the selection halo.
 */
function Outline({ shape, kind, width, height, selected }) {
  const w = width || DEFAULT_SIZES[kind].width;
  const h = height || DEFAULT_SIZES[kind].height;
  const d = outlinePath(shape, w, h);
  return (
    <svg className="flowchart-outline" data-kind={kind} width={w} height={h} aria-hidden="true">
      {selected && <path className="flowchart-outline-halo" d={d} />}
      <path className="flowchart-outline-body" d={d} />
      {shape === "note" && (
        <path className="flowchart-outline-fold" d={`M ${w - NOTE_FOLD} 1 V ${NOTE_FOLD} H ${w - 1}`} />
      )}
    </svg>
  );
}

/** SVG path for one outline shape, inset by half the stroke so it is never clipped. */
function outlinePath(shape, w, h) {
  const i = 1;
  if (shape === "rhombus") return `M ${w / 2} ${i} L ${w - i} ${h / 2} L ${w / 2} ${h - i} L ${i} ${h / 2} Z`;
  if (shape === "note") {
    return `M ${i} ${i} H ${w - NOTE_FOLD} L ${w - i} ${NOTE_FOLD} V ${h - i} H ${i} Z`;
  }
  const r = Math.min(10, w / 2, h / 2);
  return `M ${i + r} ${i} H ${w - i - r} Q ${w - i} ${i} ${w - i} ${i + r} V ${h - i - r}`
    + ` Q ${w - i} ${h - i} ${w - i - r} ${h - i} H ${i + r} Q ${i} ${h - i} ${i} ${h - i - r}`
    + ` V ${i + r} Q ${i} ${i} ${i + r} ${i} Z`;
}

/** Small caption naming a node's role, so the diagram's semantics stay visible. */
function Role({ children }) {
  return <span className="flowchart-role">{children}</span>;
}

/**
 * Title and stage-badge row shared by states and actions.
 *
 * Inputs carry `nodrag` so typing and text selection never drag the node.
 */
function TitleRow({ id, data, label, placeholder }) {
  const { readOnly, updateNodeData } = useFlowchart();
  return (
    <div className="flowchart-title-row">
      <TextField className="flowchart-title" label={label} placeholder={placeholder} value={data.title}
        maxLength={120} onCommit={(title) => updateNodeData(id, { title })} />
      <TextField className="flowchart-stage" label="Stage hint" placeholder="Stage" value={data.stage_hint}
        maxLength={40} onCommit={(stage_hint) => updateNodeData(id, { stage_hint: stage_hint || null })} />
    </div>
  );
}

/**
 * Entity chips on a state or action, each removable on hover.
 *
 * Long lists collapse behind a "+N" chip that expands the node in place; the
 * saved list is never truncated.
 */
function EntityChips({ id, data, empty }) {
  const { readOnly, catalog, updateNodeData } = useFlowchart();
  const [expanded, setExpanded] = useState(false);
  const removeEntity = (index) =>
    updateNodeData(id, { entities: data.entities.filter((_, position) => position !== index) });
  const hidden = expanded ? 0 : Math.max(0, data.entities.length - VISIBLE_CHIPS);
  const shown = hidden ? data.entities.slice(0, VISIBLE_CHIPS) : data.entities;
  if (!data.entities.length) return empty ? <span className="flowchart-chips-empty">{empty}</span> : null;
  return (
    <div className="flowchart-chips">
      {shown.map((entity, index) => {
        const entry = catalog.get(`${entity.category}:${entity.api_name}`);
        return (
          <span className="flowchart-chip" key={`${entity.category}:${entity.api_name}:${index}`}>
            <EntityTile entity={entity} entry={entry} size={32} />
            {!readOnly && (
              <button
                type="button"
                className="nodrag flowchart-chip-remove"
                aria-label={`Remove ${entry?.name ?? entity.api_name}`}
                onClick={() => removeEntity(index)}
              >
                <X aria-hidden="true" />
              </button>
            )}
          </span>
        );
      })}
      {hidden > 0 && (
        <button type="button" className="nodrag flowchart-chip-more" onClick={() => setExpanded(true)}>
          +{hidden}
        </button>
      )}
    </div>
  );
}

/** A strategic state or line (opener, composition, pivot): a titled group of entity chips. */
export function PlanNode({ id, data, selected, width, height }) {
  const { readOnly } = useFlowchart();
  return (
    <div className="flowchart-shape flowchart-card flowchart-state">
      <Outline shape="rect" kind="plan" width={width} height={height} selected={selected} />
      {!readOnly && !data.positionLocked && <ResizeControl id={id} isVisible={selected} minWidth={176} minHeight={80} lineClassName="flowchart-resize-line" handleClassName="flowchart-resize-handle" />}
      <SideHandles />
      <OverflowNotice id={id} data={data} />
      <div className="flowchart-card-header">
        <Role>State</Role>
        <TitleRow id={id} data={data} label="State title" placeholder="Opener, comp, or line" />
      </div>
      <div className="flowchart-card-body">
        <EntityChips id={id} data={data} empty={readOnly ? "" : "Drop units, items, or augments"} />
      </div>
    </div>
  );
}

/** Something the player does, such as slamming items or rolling at a stage. */
export function ActionNode({ id, data, selected, width, height }) {
  const { readOnly } = useFlowchart();
  return (
    <div className="flowchart-shape flowchart-card flowchart-action">
      <Outline shape="rect" kind="action" width={width} height={height} selected={selected} />
      {!readOnly && !data.positionLocked && <ResizeControl id={id} isVisible={selected} minWidth={160} minHeight={56} lineClassName="flowchart-resize-line" handleClassName="flowchart-resize-handle" />}
      <SideHandles />
      <OverflowNotice id={id} data={data} />
      <Role>Action</Role>
      <TitleRow id={id} data={data} label="Action" placeholder="Slam items, roll, level…" />
      <EntityChips id={id} data={data} />
    </div>
  );
}

/**
 * A question whose outgoing transitions carry the guards that pick a branch.
 *
 * The question sits in the rhombus's inscribed rectangle (half its width and
 * height), so text never crosses the diamond's edges. Several incoming
 * transitions make the same shape a merge.
 */
export function DecisionNode({ id, data, selected, width, height }) {
  const { readOnly, updateNodeData } = useFlowchart();
  return (
    <div className="flowchart-shape flowchart-decision">
      <Outline shape="rhombus" kind="decision" width={width} height={height} selected={selected} />
      {!readOnly && !data.positionLocked && <ResizeControl id={id} isVisible={selected} minWidth={96} minHeight={64} lineClassName="flowchart-resize-line" handleClassName="flowchart-resize-handle" />}
      <SideHandles />
      <OverflowNotice id={id} data={data} />
      <TextField label="Decision question" placeholder="Hit 3-star?" value={data.title} multiline
        maxLength={120} onCommit={(title) => updateNodeData(id, { title })} />
    </div>
  );
}

/**
 * A bar that splits one path into parallel ones (fork) or brings them back together (join).
 *
 * Orientation follows the saved size: wider than tall is a horizontal bar for
 * top-to-bottom flow. The resizer only changes the bar's length.
 */
export function ForkNode({ id, data, selected, width, height }) {
  const { readOnly } = useFlowchart();
  const w = width || DEFAULT_SIZES.fork.width;
  const h = height || DEFAULT_SIZES.fork.height;
  const horizontal = w >= h;
  return (
    <div className="flowchart-shape flowchart-fork" data-selected={selected || undefined} aria-label="Fork or join" role="group">
      {!readOnly && !data.positionLocked && (
        <ResizeControl id={id}
          isVisible={selected}
          lineClassName="flowchart-resize-line"
          handleClassName="flowchart-resize-handle"
          minWidth={horizontal ? 48 : h}
          maxWidth={horizontal ? 1600 : w}
          minHeight={horizontal ? h : 48}
          maxHeight={horizontal ? h : 1600}
        />
      )}
      <SideHandles />
    </div>
  );
}

/** Where the gameplan begins; the canvas refuses links into it. */
export function StartNode({ selected }) {
  return (
    <div className="flowchart-shape flowchart-terminal flowchart-start" data-selected={selected || undefined} aria-label="Start" role="group">
      <SideHandles />
    </div>
  );
}

/** Where a line finishes; the canvas refuses links out of it. */
export function EndNode({ selected }) {
  return (
    <div className="flowchart-shape flowchart-terminal flowchart-end" data-selected={selected || undefined} aria-label="End" role="group">
      <SideHandles />
    </div>
  );
}

/** A single dropped entity that can be linked on its own. */
export function EntityNode({ data, selected, width, height }) {
  const { catalog } = useFlowchart();
  const entity = data.entities[0];
  const entry = catalog.get(`${entity.category}:${entity.api_name}`);
  return (
    <div className="flowchart-shape flowchart-entity">
      <Outline shape="rect" kind="entity" width={width} height={height} selected={selected} />
      <SideHandles />
      <EntityTile entity={entity} entry={entry} size={48} />
      <span className="flowchart-entity-name">{entry?.name ?? entity.api_name}</span>
    </div>
  );
}

/** A free-text situational annotation, linked to elements with dashed edges. */
export function NoteNode({ id, data, selected, width, height }) {
  const { readOnly, updateNodeData } = useFlowchart();
  return (
    <div className="flowchart-shape flowchart-note">
      <Outline shape="note" kind="note" width={width} height={height} selected={selected} />
      {!readOnly && !data.positionLocked && <ResizeControl id={id} isVisible={selected} minWidth={160} minHeight={64} lineClassName="flowchart-resize-line" handleClassName="flowchart-resize-handle" />}
      <SideHandles />
      <OverflowNotice id={id} data={data} />
      <TextField label="Note" placeholder="Situational detail…" value={data.text} multiline
        maxLength={4000} onCommit={(text) => updateNodeData(id, { text })} />
    </div>
  );
}

export const nodeTypes = {
  plan: PlanNode,
  action: ActionNode,
  decision: DecisionNode,
  fork: ForkNode,
  start: StartNode,
  end: EndNode,
  entity: EntityNode,
  note: NoteNode,
  group: GroupNode,
};

/** Bridge resizer gestures to canonical history so a whole resize is one transaction. */
function ResizeControl({ id, ...props }) {
  const { beginGesture, endGesture } = useFlowchart();
  return <NodeResizer {...props} onResizeStart={() => beginGesture()} onResizeEnd={() => endGesture()} />;
}
/** Flag explicit sizes whose content overflows and expose a direct fit command. */
function OverflowNotice({ id, data }) {
  const { readOnly, fitContent } = useFlowchart();
  const marker = useRef(null), [overflow, setOverflow] = useState(false);
  useEffect(() => {
    const shape = marker.current?.parentElement;
    if (!shape || !data.explicitSize) { setOverflow(false); return; }
    const measure = () => setOverflow(shape.scrollHeight > shape.clientHeight + 2 || [...shape.querySelectorAll('.flowchart-text')].some((el) => el.scrollHeight > el.clientHeight + 2));
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure); observer.observe(shape);
    return () => observer.disconnect();
  }, [data.explicitSize, data.title, data.text, data.entities]);
  return <span ref={marker} className="flowchart-overflow-marker">{overflow && <button type="button" className="nodrag flowchart-overflow"
    disabled={readOnly || data.positionLocked} onClick={() => fitContent(id)} title="Complete text is available in Properties">Overflow · Fit to content</button>}</span>;
}
/** A nested visual container with a personal collapse state and descendant count. */
export function GroupNode({ id, data, selected, width, height }) {
  const { readOnly, updateNodeData, toggleCollapse, groupMinimum } = useFlowchart();
  const minimum = groupMinimum(id);
  return <div className="flowchart-shape flowchart-group" data-selected={selected || undefined}
    data-collapsed={data.collapsed || undefined} style={{ backgroundColor: data.tint ?? '#dbeafe' }}>
    {!readOnly && !data.collapsed && !data.positionLocked && <ResizeControl id={id} isVisible={selected}
      minWidth={minimum.width} minHeight={minimum.height} lineClassName="flowchart-resize-line" handleClassName="flowchart-resize-handle" />}
    <SideHandles />
    <div className="flowchart-group-heading"><TextField label="Container name" value={data.title} placeholder="Group"
      maxLength={120} onCommit={(title) => updateNodeData(id, { title })} />
      <button type="button" className="nodrag nopan" aria-label={data.collapsed ? 'Expand group' : 'Collapse group'}
        onClick={() => toggleCollapse(id)}>{data.collapsed ? '+' : '−'}</button></div>
    {data.collapsed && <span>{data.count} descendants</span>}
  </div>;
}
