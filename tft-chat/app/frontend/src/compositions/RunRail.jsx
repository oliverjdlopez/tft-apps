/** Persistent workspace rail: new-experiment entry, saved run history, and fixtures. */
import React from "react";
import { FlaskConical, Plus, RefreshCw } from "lucide-react";
import { Button as UiButton } from "@/components/ui/button";
import { algorithmLabel, statusTone } from "./utils.js";

/**
 * Keep every saved run one click away so setup, history, and results never
 * replace each other as separate pages.
 *
 * Args:
 *   history: Saved runs, newest first, with the selected run's fresher status merged in.
 *   selectedId: Experiment currently open in the results view, if any.
 *   page: Visible workspace page, used to mark the active rail entry.
 *   busy: Disables opening other runs while a request is in flight.
 *   onNew, onOpen, onRefresh, onFixtures: Navigation callbacks owned by Experiments.
 *   showFixtures: Whether the illustrative fixture view is available.
 */
export default function RunRail({ history, selectedId, page, busy, onNew, onOpen, onRefresh, onFixtures, showFixtures }) {
  return (
    <aside className="composition-rail" aria-label="Compositions workspace">
      <div className="composition-rail-title">
        <h1>Compositions</h1>
        <p>Discover structures and compare reproducible experiments.</p>
      </div>
      <UiButton className="composition-rail-new" aria-pressed={page === "setup"} onClick={onNew}>
        <Plus aria-hidden="true" /> New experiment
      </UiButton>
      <div className="composition-rail-runs">
        <div className="composition-rail-heading">
          <h2>Runs</h2>
          <UiButton variant="ghost" size="icon-sm" aria-label="Refresh run history" disabled={busy} onClick={onRefresh}>
            <RefreshCw aria-hidden="true" />
          </UiButton>
        </div>
        <nav aria-label="Run history" className="composition-rail-list">
          {history.map((run) => {
            const current = run.experiment_id === selectedId;
            return (
              <button
                key={run.experiment_id}
                type="button"
                className="composition-rail-run"
                aria-current={current && page === "results" ? "page" : undefined}
                data-selected={current || undefined}
                // Returning to the open run must keep its selections, so only other runs are gated.
                disabled={busy && !current}
                onClick={() => onOpen(run.experiment_id)}
              >
                <span className="composition-rail-run-top">
                  <strong>{algorithmLabel(run.request.algorithm_id)}</strong>
                  <span className="composition-status" data-tone={statusTone(run.status)}>{run.status}</span>
                </span>
                <span className="composition-rail-run-meta">
                  <code>{run.experiment_id.slice(0, 8)}</code>
                  <span>{run.elapsed_seconds.toFixed(1)}s</span>
                </span>
                <span className="composition-rail-run-meta">
                  {run.context.patch} · {run.sample_boards.toLocaleString()} / {run.eligible_boards.toLocaleString()} boards
                </span>
              </button>
            );
          })}
          {!history.length && <p className="composition-muted composition-caption">No saved runs yet. Start an experiment to discover families.</p>}
        </nav>
      </div>
      {showFixtures && (
        <div className="composition-rail-footer">
          <UiButton variant="ghost" className="composition-rail-fixtures" aria-pressed={page === "fixtures"} onClick={onFixtures}>
            <FlaskConical aria-hidden="true" /> Display fixtures
          </UiButton>
        </div>
      )}
    </aside>
  );
}
