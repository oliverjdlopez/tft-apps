/** Persistent experiment controls and comparison on frozen input populations. */
import React, { useEffect, useRef, useState } from "react";
import { Copy, RefreshCw, Square } from "lucide-react";
import { useConfirmation } from "@/components/shared/confirmation";
import { Disclosure, DisclosureSummary } from "@/components/shared/disclosure";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { NativeSelect as UiNativeSelect } from "@/components/ui/native-select";
import { Button as UiButton } from "@/components/ui/button";
import {
  Table as UiTable,
  TableHeader as UiTableHeader,
  TableRow as UiTableRow,
  TableHead as UiTableHead,
  TableBody as UiTableBody,
  TableCell as UiTableCell,
} from "@/components/ui/table";
import { Icon, Spinner } from "../app.jsx";
import { compositionRequest } from "./api.js";
import {
  AlgorithmListSchema,
  ExperimentHistorySchema,
  ExperimentViewSchema,
  CompositionListResponseSchema,
  CompositionDetailResponseSchema,
  BoardExampleViewSchema,
  ComparisonResponseSchema,
  SourceSummarySchema,
} from "./models.js";
import { FamilyBrowser } from "./CompositionResults.jsx";
import { EntityAssetProvider } from "../assets/EntityImages.jsx";
import {
  algorithmLabel,
  compositionImageRequests,
  confirmSampleRun,
  percent,
  populationLabel,
  statusTone,
} from "./utils.js";
import Diagnostics from "./Diagnostics.jsx";
import ParameterLabel from "./ParameterLabel.jsx";
import RunRail from "./RunRail.jsx";
import ExperimentSetup from "./ExperimentSetup.jsx";
import BoardInspector from "./BoardInspector.jsx";

/** Start, cancel, reopen, duplicate, rerun, refresh, and compare saved experiments. */
export default function Experiments({ fixtures }) {
  const [page, setPage] = useState("setup");
  const [resultTab, setResultTab] = useState("families");
  const workspace = useRef(null);
  const previousPage = useRef(page);
  const boardsTrigger = useRef(null);
  const focusBoard = useRef(false);
  useEffect(() => {
    // Actions can hide their own trigger; move keyboard focus into the destination.
    if (previousPage.current !== page) {
      workspace.current?.querySelector(`[data-page="${page}"] h2`)?.focus();
      previousPage.current = page;
    }
  }, [page]);
  useEffect(() => {
    if (focusBoard.current && resultTab === "boards") {
      boardsTrigger.current?.focus();
      focusBoard.current = false;
    }
  }, [resultTab]);
  const { confirm, confirmation } = useConfirmation();
  const [algorithms, setAlgorithms] = useState([]),
    [history, setHistory] = useState([]),
    [run, setRun] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    algorithm_id: "hdbscan",
    algorithm_version: null,
    parameters: {},
    seed: 42,
    sample_size: 2000,
    full_population: false,
    source_kind: "active",
    snapshot_id: null,
  });
  const [population, setPopulation] = useState("discovery_sample"),
    [families, setFamilies] = useState(null),
    [detail, setDetail] = useState(null),
    [board, setBoard] = useState(null),
    [comparison, setComparison] = useState(null),
    [compareId, setCompareId] = useState("");
  const [sourceSummary, setSourceSummary] = useState(null);
  const [savedSource, setSavedSource] = useState(null);
  const sampleLimit = form.snapshot_id
    ? savedSource?.eligible_boards
    : sourceSummary?.eligible_boards;
  const sampleCount = form.snapshot_id
    ? savedSource?.sample_boards
    : Math.min(form.sample_size, sampleLimit ?? 0);
  // Polling the selected result can finish before a slower history request.
  // Prefer its newer status so the two visible views cannot disagree.
  const displayedHistory = history.map((entry) =>
    entry.experiment_id === run?.experiment_id ? run : entry,
  );
  const selectedPopulation = run?.result?.populations.find(
    (p) => p.population_kind === population,
  );
  const active = run && ["queued", "running"].includes(run.status);
  const otherCompleted = history.filter(
    (h) => h.status === "completed" && h.experiment_id !== run?.experiment_id,
  );
  /** Reload persistent summaries without changing the selected result. */
  async function refreshHistory() {
    const value = await compositionRequest(
      "/experiments",
      ExperimentHistorySchema,
    );
    setHistory(value.experiments);
    return value.experiments;
  }
  /** Surface request and contract errors while preventing duplicate submissions. */
  async function action(operation) {
    setError("");
    setBusy(true);
    try {
      await operation();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  /** Reopen a saved run and clear selections that belong to another result. */
  async function openRun(id) {
    const value = await compositionRequest(
      `/experiments/${id}`,
      ExperimentViewSchema,
    );
    setRun(value);
    setPopulation("discovery_sample");
    setPage("results");
    setResultTab(value.result ? "families" : "diagnostics");
    setCompareId("");
    setDetail(null);
    setBoard(null);
    setComparison(null);
  }
  /** Return to the open run with its selections intact, or load another saved run. */
  function selectRun(id) {
    if (id === run?.experiment_id) setPage("results");
    else action(() => openRun(id));
  }
  useEffect(() => {
    let alive = true;
    setSourceSummary(null);
    compositionRequest(
      `/source?source=${form.source_kind}`,
      SourceSummarySchema,
    )
      .then((value) => {
        if (alive) setSourceSummary(value);
      })
      .catch((e) => {
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [form.source_kind, form.snapshot_id]);
  useEffect(() => {
    // Source changes can make the previous selection larger than the new population.
    // Frozen snapshots retain their original request so existing reruns stay valid.
    if (!form.snapshot_id && sampleLimit > 0) {
      setForm((current) => ({
        ...current,
        sample_size: Math.min(current.sample_size, sampleLimit),
      }));
    }
  }, [sampleLimit, form.snapshot_id]);
  useEffect(() => {
    action(async () => {
      const a = await compositionRequest("/algorithms", AlgorithmListSchema);
      setAlgorithms(a.algorithms);
      await refreshHistory();
    });
  }, []);
  useEffect(() => {
    if (!active) return;
    let alive = true;
    const timer = setTimeout(
      () =>
        action(async () => {
          const updated = await compositionRequest(
            `/experiments/${run.experiment_id}`,
            ExperimentViewSchema,
          );
          if (alive) {
            setRun(updated);
            await refreshHistory();
          }
        }),
      1200,
    );
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [run]);
  useEffect(() => {
    let alive = true;
    setFamilies(null);
    setDetail(null);
    setBoard(null);
    setComparison(null);
    if (run?.status === "completed")
      compositionRequest(
        `/experiments/${run.experiment_id}/families?population=${population}`,
        CompositionListResponseSchema,
      )
        .then(async (value) => {
          if (!alive) return;
          if (value.families.length) {
            const first = await compositionRequest(
              `/experiments/${run.experiment_id}/families/${encodeURIComponent(value.families[0].family_id)}?population=${population}`,
              CompositionDetailResponseSchema,
            );
            if (alive) setDetail(first);
          }
          if (alive) setFamilies(value);
        })
        .catch((e) => {
          if (alive) setError(e.message);
        });
    return () => {
      alive = false;
    };
  }, [run?.experiment_id, run?.status, population]);
  useEffect(() => {
    if (run?.status === "completed") setResultTab("families");
    else if (run && !run.result) setResultTab("diagnostics");
  }, [run?.experiment_id, run?.status]);
  /** Freeze form settings and enqueue a new result through the validated boundary. */
  async function submit(event) {
    event.preventDefault();
    if (busy || !sampleCount || !(await confirmSampleRun(sampleCount, confirm, form.algorithm_id)))
      return;
    await action(async () => {
      const created = await compositionRequest(
        "/experiments",
        ExperimentViewSchema,
        form.snapshot_id ? form : { ...form, sample_size: sampleCount },
      );
      setRun(created);
      setPopulation("discovery_sample");
      setComparison(null);
      setPage("results");
      setResultTab(created.result ? "families" : "diagnostics");
      await refreshHistory();
    });
  }
  /** Open a family using the selected run and statistics population. */
  async function selectFamily(id) {
    await action(async () =>
      setDetail(
        await compositionRequest(
          `/experiments/${run.experiment_id}/families/${encodeURIComponent(id)}?population=${population}`,
          CompositionDetailResponseSchema,
        ),
      ),
    );
  }
  /** Load one observation of the selected population into the board inspector. */
  async function selectBoard(id) {
    await action(async () =>
      setBoard(
        await compositionRequest(
          `/experiments/${run.experiment_id}/boards/${encodeURIComponent(id)}?population=${population}`,
          BoardExampleViewSchema,
        ),
      ),
    );
  }
  /** Inspect an already validated example without issuing a duplicate board request. */
  function inspectExample(example) {
    setBoard(example);
    focusBoard.current = true;
    setResultTab("boards");
  }
  /** Stop a queued or running experiment and refresh its saved status. */
  function cancelRun() {
    action(async () => {
      setRun(
        await compositionRequest(
          `/experiments/${run.experiment_id}/cancel`,
          ExperimentViewSchema,
          {},
        ),
      );
      await refreshHistory();
    });
  }
  /** Re-enqueue the saved request on its frozen snapshot after any size confirmation. */
  async function rerun() {
    if (!(await confirmSampleRun(run.sample_boards, confirm, run.request.algorithm_id))) return;
    action(async () => {
      setRun(
        await compositionRequest(
          `/experiments/${run.experiment_id}/rerun`,
          ExperimentViewSchema,
          {},
        ),
      );
      setPopulation("discovery_sample");
      setResultTab("families");
      setComparison(null);
      await refreshHistory();
    });
  }
  /** Copy the saved request into the draft form, keeping its frozen sample counts. */
  function duplicate() {
    setSavedSource({
      eligible_boards: run.eligible_boards,
      sample_boards: run.sample_boards,
    });
    setForm({ ...run.request, algorithm_version: null });
    setPage("setup");
  }
  const kpis = run?.result && [
    ["Families", run.result.model.families.length.toLocaleString(), ""],
    ["Coverage", percent(selectedPopulation?.coverage), "boards assigned"],
    ["Ambiguous", percent(selectedPopulation?.ambiguity), "close contests"],
    ["Sample", run.sample_boards.toLocaleString(), `of ${run.eligible_boards.toLocaleString()} source`],
    ["Elapsed", `${run.elapsed_seconds.toFixed(1)}s`, run.request.full_population ? "incl. full classification" : ""],
  ];
  return (
    <section className="composition-workspace">
      {confirmation}
      <RunRail
        history={displayedHistory}
        selectedId={run?.experiment_id}
        page={page}
        busy={busy}
        onNew={() => setPage("setup")}
        onOpen={selectRun}
        onRefresh={() => action(refreshHistory)}
        showFixtures={!!fixtures}
        onFixtures={() => setPage("fixtures")}
      />
      <div className="composition-main" ref={workspace}>
        {error && (
          <p className="error composition-callout" role="alert">
            <Icon name="alert" size={14} /> {error}
          </p>
        )}
        <div data-page="setup" hidden={page !== "setup"}>
          <ExperimentSetup
            form={form}
            setForm={setForm}
            algorithms={algorithms}
            sourceSummary={sourceSummary}
            sampleLimit={sampleLimit}
            sampleCount={sampleCount}
            busy={busy}
            error={error}
            onSubmit={submit}
          />
        </div>
        {run && (
          <section data-page="results" hidden={page !== "results"}>
            <EntityAssetProvider key={`${run.experiment_id}:${population}`} context={run.context}
              entities={compositionImageRequests({ families: families?.families || [], detail, board })}>
            <header className="composition-run-header">
              <div className="composition-run-title">
                <div>
                  <div className="composition-actions">
                    <h2 tabIndex={-1}>{algorithmLabel(run.request.algorithm_id)}</h2>
                    <span className="composition-status composition-status-pill" data-tone={statusTone(run.status)}>{run.status}</span>
                  </div>
                  <p className="composition-muted composition-number">
                    Run <code>{run.experiment_id.slice(0, 8)}</code> · Patch {run.context.patch} · Set {run.context.set_number} ·
                    Queue {run.context.queue_id} · Seed {run.request.seed}
                    {!run.result && ` · Sample ${run.sample_boards.toLocaleString()} / ${run.eligible_boards.toLocaleString()} source boards`}
                  </p>
                </div>
                <div className="composition-actions">
                  {active && (
                    <UiButton variant="outline" disabled={busy} onClick={cancelRun}>
                      <Square aria-hidden="true" /> Cancel
                    </UiButton>
                  )}
                  <UiButton variant="outline" disabled={busy} onClick={rerun}>
                    <RefreshCw aria-hidden="true" /> Rerun saved inputs
                  </UiButton>
                  <UiButton variant="outline" onClick={duplicate}>
                    <Copy aria-hidden="true" /> Duplicate and edit
                  </UiButton>
                </div>
              </div>
              {active && (
                <div role="status" className="composition-card composition-progress">
                  <Spinner label={run.stage.replaceAll("_", " ")} />
                </div>
              )}
              {run.error && (
                <p className="error composition-callout" role="alert">
                  {run.error}
                </p>
              )}
              {kpis && (
                <dl className="composition-kpis composition-card" aria-label="Run metrics">
                  {kpis.map(([label, value, sub]) => (
                    <div key={label}>
                      <dt>{label}</dt>
                      <dd>
                        <strong>{value}</strong>
                        {sub && <span>{sub}</span>}
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
            </header>
            <Tabs
              value={resultTab}
              onValueChange={setResultTab}
              className="min-w-0"
            >
              <div className="composition-tabbar">
                <TabsList variant="line" aria-label="Run results" className="composition-tabs">
                  <TabsTrigger value="families" disabled={!run.result}>
                    Families
                    {families && <span className="composition-count" aria-hidden="true">{families.families.length}</span>}
                  </TabsTrigger>
                  <TabsTrigger
                    ref={boardsTrigger}
                    value="boards"
                    disabled={!run.result}
                  >
                    Boards
                  </TabsTrigger>
                  <TabsTrigger value="diagnostics">Diagnostics</TabsTrigger>
                  <TabsTrigger value="compare" disabled={!run.result}>
                    Compare
                  </TabsTrigger>
                </TabsList>
                {run.result && (
                  <div className="composition-population">
                    <ParameterLabel help="Choose whether family statistics and board inspection use the discovery sample or the full classified population.">
                      Statistics
                    </ParameterLabel>
                    <div role="group" aria-label="Statistics population" className="composition-segmented">
                      {run.result.populations.map((p) => (
                        <button
                          key={p.population_kind}
                          type="button"
                          aria-pressed={population === p.population_kind}
                          disabled={busy}
                          onClick={() => setPopulation(p.population_kind)}
                        >
                          {populationLabel(p.population_kind, run.request.algorithm_id)}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
              <TabsContent
                value="families"
                forceMount
                hidden={resultTab !== "families"}
              >
                {run.result && (
                  <FamilyBrowser
                    families={families?.families}
                    detail={detail}
                    label="Experiment families"
                    busy={busy}
                    onSelect={selectFamily}
                    onInspect={inspectExample}
                  />
                )}
              </TabsContent>
              <TabsContent
                value="boards"
                forceMount
                hidden={resultTab !== "boards"}
              >
                {run.result && (
                  <BoardInspector
                    key={`${run.experiment_id}:${population}`}
                    assignments={selectedPopulation?.assignments}
                    families={run.result.model.families}
                    board={board}
                    busy={busy}
                    onSelect={selectBoard}
                  />
                )}
              </TabsContent>
              <TabsContent
                value="compare"
                forceMount
                hidden={resultTab !== "compare"}
              >
                <section className="composition-card composition-section">
                  <div className="composition-card-head">
                    <h3>
                      <ParameterLabel help="Choose another completed experiment to compare with this run. Membership overlap requires identical structural populations and compatible patch, set, and queue contexts.">
                        Compare saved runs
                      </ParameterLabel>
                    </h3>
                  </div>
                  <div className="composition-actions">
                    <UiNativeSelect
                      aria-label="Comparison run"
                      value={compareId}
                      onChange={(e) => setCompareId(e.target.value)}
                    >
                      <option value="">Choose completed run</option>
                      {otherCompleted.map((h) => (
                        <option key={h.experiment_id} value={h.experiment_id}>
                          {algorithmLabel(h.request.algorithm_id)} · {h.experiment_id.slice(0, 8)}{" "}
                          · {h.elapsed_seconds.toFixed(1)}s
                        </option>
                      ))}
                    </UiNativeSelect>
                    <UiButton
                      variant="secondary"
                      disabled={busy || !compareId}
                      onClick={() =>
                        action(async () =>
                          setComparison(
                            await compositionRequest(
                              `/compare?left=${run.experiment_id}&right=${compareId}&population=${population}`,
                              ComparisonResponseSchema,
                            ),
                          ),
                        )
                      }
                    >
                      Compare
                    </UiButton>
                  </div>
                  {!otherCompleted.length && (
                    <p className="composition-muted">
                      No other completed runs are available to compare.
                    </p>
                  )}
                  {comparison && (
                    <section className="composition-comparison">
                      <p>{comparison.message}</p>
                      <dl className="composition-kpis composition-card">
                        <div>
                          <dt>Assignment overlap</dt>
                          <dd><strong>{percent(comparison.assignment_overlap)}</strong></dd>
                        </div>
                        <div>
                          <dt>Adjusted Rand</dt>
                          <dd><strong>{comparison.adjusted_rand_index ?? "Unavailable"}</strong></dd>
                        </div>
                      </dl>
                      <UiTable className="fields">
                        <UiTableHeader>
                          <UiTableRow>
                            <UiTableHead>Metric</UiTableHead>
                            <UiTableHead>Current run</UiTableHead>
                            <UiTableHead>Compared run</UiTableHead>
                          </UiTableRow>
                        </UiTableHeader>
                        <UiTableBody>
                          {[
                            "family_count",
                            "eligible_boards",
                            "coverage",
                            "ambiguity",
                            "elapsed_seconds",
                          ].map((key) => (
                            <UiTableRow key={key}>
                              <UiTableCell>
                                {key.replaceAll("_", " ")}
                              </UiTableCell>
                              <UiTableCell>
                                {comparison.left_metrics[key] ?? "Unavailable"}
                              </UiTableCell>
                              <UiTableCell>
                                {comparison.right_metrics[key] ?? "Unavailable"}
                              </UiTableCell>
                            </UiTableRow>
                          ))}
                        </UiTableBody>
                      </UiTable>
                      <h4>Configuration differences</h4>
                      <UiTable className="fields">
                        <UiTableHeader>
                          <UiTableRow>
                            <UiTableHead>Setting</UiTableHead>
                            <UiTableHead>Current run</UiTableHead>
                            <UiTableHead>Compared run</UiTableHead>
                          </UiTableRow>
                        </UiTableHeader>
                        <UiTableBody>
                          {Object.entries(
                            comparison.configuration_differences,
                          ).map(([key, value]) => (
                            <UiTableRow key={key}>
                              <UiTableCell>
                                {key.replaceAll("_", " ")}
                              </UiTableCell>
                              <UiTableCell>
                                {JSON.stringify(value.left)}
                              </UiTableCell>
                              <UiTableCell>
                                {JSON.stringify(value.right)}
                              </UiTableCell>
                            </UiTableRow>
                          ))}
                        </UiTableBody>
                      </UiTable>
                    </section>
                  )}
                </section>
              </TabsContent>
              <TabsContent
                value="diagnostics"
                forceMount
                hidden={resultTab !== "diagnostics"}
              >
                <section className="composition-card composition-section">
                  <p className="composition-muted composition-caption">
                    Snapshot {run.snapshot_id} · Feature revision{" "}
                    {run.context.feature_revision}
                  </p>
                  <Disclosure>
                    <DisclosureSummary>Saved configuration</DisclosureSummary>
                    <p>
                      Algorithm {run.request.algorithm_id} · Version{" "}
                      {run.request.algorithm_version ?? "Unknown"} · Seed{" "}
                      {run.request.seed} · Feature revision{" "}
                      {run.context.feature_revision}
                    </p>
                    <p>
                      Requested sample {run.request.sample_size} · Full
                      classification{" "}
                      {run.request.full_population ? "enabled" : "disabled"}
                    </p>
                    <UiTable className="fields">
                      <UiTableHeader>
                        <UiTableRow>
                          <UiTableHead>Effective parameter</UiTableHead>
                          <UiTableHead>Saved value</UiTableHead>
                        </UiTableRow>
                      </UiTableHeader>
                      <UiTableBody>
                        {Object.entries(run.request.parameters).map(
                          ([key, value]) => (
                            <UiTableRow key={key}>
                              <UiTableCell>{key.replaceAll("_", " ")}</UiTableCell>
                              <UiTableCell>{JSON.stringify(value)}</UiTableCell>
                            </UiTableRow>
                          ),
                        )}
                      </UiTableBody>
                    </UiTable>
                  </Disclosure>
                  {run.result && (
                    <Diagnostics diagnostics={run.result.diagnostics} />
                  )}
                </section>
              </TabsContent>
            </Tabs>
            {!run.result && !active && (
              <p className="composition-muted composition-no-results">
                This run has no results. Inspect its saved configuration or rerun
                its inputs.
              </p>
            )}
            </EntityAssetProvider>
          </section>
        )}
        {fixtures && (
          <div data-page="fixtures" hidden={page !== "fixtures"}>
            {fixtures}
          </div>
        )}
      </div>
    </section>
  );
}
