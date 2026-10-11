import { Card as UiCard } from "@/components/ui/card";
import { useEffect, useState } from "react";
import { apiGet, Spinner } from "../app.jsx";

/** Show data coverage and workspace entry points in Developer's Status section. */
function OverviewTab() {
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    apiGet("/api/overview").then(setOverview).catch((e) => setError(e.message));
  }, []);
  return (
    <div className="explorer-pane">
      <h3>Data status</h3>
      {error ? <div className="statusline bad">Failed to load data coverage: {error}</div> :
        !overview ? <Spinner label="Loading data coverage…" /> : (
          <div className="metric-grid">
            <UiCard as="div" className="card metric block gap-0 p-6 shadow-xs">
              <div className="metric-label">Scoped boards</div>
              <div className="metric-value">{overview.db.scoped_boards.toLocaleString()}</div>
              <div className="muted small">{overview.db.raw_boards.toLocaleString()} raw boards stored</div>
            </UiCard>
          </div>
        )}
      <h3>Connected workspaces</h3>
      <p>Open the <a href="/rolldown" target="_blank" rel="noreferrer">Rolldown</a> simulator in its own page, or use the desktop Rolldown tab.</p>
      <p>Browse tables and run SQL in the desktop Database tab, or open{" "}
        <a href="http://localhost:8979" target="_blank" rel="noreferrer">CloudBeaver</a>.
        Manage evaluation datasets, prompt candidates, and experiments in the desktop
        Langfuse tab, or open{" "}
        <a href="http://localhost:15510/project/tft-apps-evals" target="_blank" rel="noreferrer">Langfuse</a>.
      </p>
      <p className="muted small">Both services must be started separately. Production assistant definitions remain in Specs.</p>
    </div>
  );
}

export default OverviewTab;
