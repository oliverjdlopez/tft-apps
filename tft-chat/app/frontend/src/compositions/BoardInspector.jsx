/** Boards tab: browse a population's assignments and inspect one observed board. */
import React, { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button as UiButton } from "@/components/ui/button";
import ParameterLabel from "./ParameterLabel.jsx";
import { BoardCard } from "./CompositionResults.jsx";

const pageSize = 25;
const statusNames = { assigned: "Assigned", ambiguous: "Ambiguous", unclassified: "Unclassified" };

/**
 * List observations by assignment status beside the selected board's evidence.
 *
 * Args:
 *   assignments: Assignments of the chosen statistics population.
 *   families: Family definitions, used to name assigned observations.
 *   board: The currently inspected example, or null.
 *   busy: Disables selection while a board request is in flight.
 *   onSelect: Loads one observation by ID.
 */
export default function BoardInspector({ assignments = [], families = [], board, busy, onSelect }) {
  const [status, setStatus] = useState("all");
  const [page, setPage] = useState(0);
  const labels = new Map(families.map((family) => [family.family_id, family.label]));
  const counts = assignments.reduce((total, a) => ({ ...total, [a.status]: (total[a.status] || 0) + 1 }), {});
  const visible = status === "all" ? assignments : assignments.filter((a) => a.status === status);
  // Filters can shrink the list below the current page, so clamp rather than reset on every render.
  const lastPage = Math.max(0, Math.ceil(visible.length / pageSize) - 1);
  const current = Math.min(page, lastPage);
  const selectedId = board?.board.observation_id;

  /** Change the status filter and return to the first page of its results. */
  function filter(next) {
    setStatus(next);
    setPage(0);
  }

  return (
    <div className="composition-layout">
      <section className="composition-card composition-list-panel" aria-label="Observations">
        <div className="composition-list-head">
          <h3>
            <ParameterLabel help="Select an observation from the chosen statistics population to inspect its board and assignment evidence.">
              Board inspector
            </ParameterLabel>
          </h3>
          <div role="group" aria-label="Assignment status" className="composition-chips">
            {[["all", "All", assignments.length], ...Object.keys(statusNames).map((key) => [key, statusNames[key], counts[key] || 0])]
              .map(([key, label, n]) => (
                <button key={key} type="button" className="composition-chip" aria-pressed={status === key} onClick={() => filter(key)}>
                  {label} <span>{n.toLocaleString()}</span>
                </button>
              ))}
          </div>
        </div>
        <nav aria-label="Observation list" className="composition-list">
          {visible.slice(current * pageSize, current * pageSize + pageSize).map((a) => (
            <button
              key={a.observation_id}
              type="button"
              className="composition-list-row composition-observation"
              aria-pressed={a.observation_id === selectedId}
              disabled={busy}
              onClick={() => onSelect(a.observation_id)}
            >
              <code>{a.observation_id}</code>
              <span data-status={a.status}>
                {a.status === "assigned" ? labels.get(a.family_id) ?? a.family_id : statusNames[a.status]}
              </span>
            </button>
          ))}
          {!visible.length && <p className="composition-muted composition-caption">No observations match this filter.</p>}
        </nav>
        {visible.length > pageSize && (
          <div className="composition-list-foot">
            <span>
              {current * pageSize + 1}–{Math.min(visible.length, current * pageSize + pageSize)} of {visible.length.toLocaleString()}
            </span>
            <span className="composition-actions">
              <UiButton variant="outline" size="icon-sm" aria-label="Previous observations" disabled={!current} onClick={() => setPage(current - 1)}>
                <ChevronLeft aria-hidden="true" />
              </UiButton>
              <UiButton variant="outline" size="icon-sm" aria-label="Next observations" disabled={current >= lastPage} onClick={() => setPage(current + 1)}>
                <ChevronRight aria-hidden="true" />
              </UiButton>
            </span>
          </div>
        )}
      </section>
      <div className="composition-detail-column">
        {board ? (
          <BoardCard example={board} />
        ) : (
          <div className="composition-card composition-empty">
            <p className="composition-muted">
              Choose an observation to inspect its roster and assignment evidence.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
