/** Custom React Flow edges: guarded transitions with attached notes, and dashed note annotations. */
import React, { useState } from "react";
import { BaseEdge, EdgeLabelRenderer, useInternalNode } from "@xyflow/react";
import { StickyNote } from "lucide-react";
import { useFlowchart } from "./context.js";
import { edgePath } from "./utils.js";

/** Wider invisible hit area so thin links are easy to click. */
const INTERACTION_WIDTH = 16;

/**
 * A "move on when..." link whose guard is drawn as a `[guard]` pill on the line.
 *
 * Empty guards stay hidden until the link is selected, so unlabeled links do
 * not clutter the canvas. Links leaving a decision are its branches, so an
 * empty guard there is always shown and flagged until the player names it.
 * Situational notes open from the pill's note button in a callout hanging
 * under it, keeping them attached to this transition. The label is portalled by `EdgeLabelRenderer`
 * into an HTML layer, so it needs explicit pointer events and `nodrag nopan`
 * to stay editable over the canvas.
 */
export function TransitionEdge({ id, source, target, data, selected, markerEnd, ...geometry }) {
  const { readOnly, edgeStyle, updateEdgeData } = useFlowchart();
  const [path, labelX, labelY] = edgePath(geometry, edgeStyle);
  const condition = data?.condition ?? "";
  const notes = data?.notes ?? "";
  // Notes start collapsed so callouts never cover nodes; a gold note icon on
  // the pill shows that a transition has notes.
  const [notesOpen, setNotesOpen] = useState(false);
  const sourceNode = useInternalNode(source);
  const targetNode = useInternalNode(target);
  const branch = sourceNode?.type === "decision";
  const missingGuard = branch && !condition.trim();
  // A box selection also selects the links inside it; only a link picked on
  // its own (its ends not both selected) opens its empty guard for editing.
  const editing = !readOnly && selected && !(sourceNode?.selected && targetNode?.selected);
  const showGuard = Boolean(condition) || editing || (missingGuard && !readOnly);
  const showToggle = editing || Boolean(notes);
  const showNotes = notesOpen && (editing || Boolean(notes));
  return <>
    <BaseEdge
      id={id} path={path} markerEnd={markerEnd}
      interactionWidth={INTERACTION_WIDTH} className="flowchart-transition"
    />
    {(showGuard || showToggle) && (
      <EdgeLabelRenderer>
        {/* Anchored by the pill's center; the notes callout hangs below it. */}
        <div
          className="nodrag nopan flowchart-edge-label"
          style={{ transform: `translate(-50%, -12px) translate(${labelX}px, ${labelY}px)` }}
        >
          <div
            className="flowchart-edge-pill"
            data-selected={selected || undefined}
            data-missing-guard={missingGuard || undefined}
          >
            {showGuard && <>
              <span aria-hidden="true">[</span>
              {readOnly
                ? <span>{condition}</span>
                : <input
                    aria-label="Transition guard"
                    placeholder={branch ? "branch when…" : "when…"}
                    value={condition}
                    maxLength={200}
                    onChange={(event) => updateEdgeData(id, { condition: event.target.value })}
                  />}
              <span aria-hidden="true">]</span>
            </>}
            {showToggle && (
              <button
                type="button"
                className="flowchart-edge-notes-toggle"
                aria-label="Notes"
                aria-expanded={notesOpen}
                data-has-notes={notes ? true : undefined}
                onClick={() => setNotesOpen(!notesOpen)}
              >
                <StickyNote aria-hidden="true" />
              </button>
            )}
          </div>
          {showNotes && (readOnly
            ? <p className="flowchart-edge-notes">{notes}</p>
            : <textarea
                className="nowheel flowchart-edge-notes"
                aria-label="Transition notes"
                placeholder="Situational detail for this transition"
                value={notes}
                maxLength={2000}
                rows={2}
                onChange={(event) => updateEdgeData(id, { notes: event.target.value })}
              />)}
        </div>
      </EdgeLabelRenderer>
    )}
  </>;
}

/** A dashed link attaching a situational note to the element it explains. */
export function AnnotationEdge({ id, ...geometry }) {
  const { edgeStyle } = useFlowchart();
  const [path] = edgePath(geometry, edgeStyle);
  return <BaseEdge id={id} path={path} interactionWidth={INTERACTION_WIDTH} className="flowchart-annotation" />;
}

export const edgeTypes = { transition: TransitionEdge, annotation: AnnotationEdge };
