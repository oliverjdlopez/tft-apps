import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import Experiments from "./Experiments.jsx";
import { compositionRequest } from "./api.js";

vi.mock("./api.js", () => ({ compositionRequest: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.resetAllMocks();
});

/** Render controls against saved-run and source responses without launching work. */
async function setup({ population = 50000, savedSample = 20001, savedAlgorithm = "hdbscan", savedParameters = {} } = {}) {
  const saved = {
    experiment_id: "saved-run",
    snapshot_id: "saved-snapshot",
    status: "failed",
    stage: "failed",
    elapsed_seconds: 1,
    eligible_boards: 40000,
    sample_boards: savedSample,
    result: null,
    error: null,
    context: { patch: "test", set_number: 17, queue_id: 1100 },
    request: {
      algorithm_id: savedAlgorithm,
      algorithm_version: "1",
      parameters: savedParameters,
      seed: 42,
      sample_size: savedSample,
      full_population: false,
      source_kind: "active",
      snapshot_id: "saved-snapshot",
    },
  };
  compositionRequest.mockImplementation(async (path, schema, body) => {
    if (path === "/algorithms")
      return {
        algorithms: [{ algorithm_id: "hdbscan", parameter_schema: { properties: {
          min_cluster_size: { type: "integer", default: 5 },
          min_samples: { type: "integer", default: 3 },
          rejection_distance: { type: "number", default: 2 },
          ambiguity_margin: { type: "number", default: 0.05 },
        } } }],
      };
    if (path.startsWith("/source?"))
      return {
        source_kind: path.endsWith("fixture") ? "fixture" : "active",
        ready: true,
        eligible_boards: path.endsWith("fixture") ? 24 : population,
      };
    if (path === "/experiments" && body === undefined)
      return { experiments: [saved] };
    return saved;
  });
  render(<Experiments />);
  await screen.findByRole("button", { name: /saved-ru/ });
  fireEvent.click(screen.getByRole("button", { name: "New experiment" }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Start experiment" }),
    ).toBeEnabled(),
  );
  return { saved };
}

/** Open a saved run from the history rail; returning to the open run keeps its selections. */
function openSaved(name = /saved-ru/) {
  fireEvent.click(within(screen.getByRole("navigation", { name: "Run history" })).getAllByRole("button", { name })[0]);
}

/** Select an exact discovery size through the visible form. */
function selectSample(size) {
  fireEvent.change(screen.getByRole("spinbutton", { name: "Sample size" }), {
    target: { value: String(size) },
  });
}

/** Identify writes separately from read-only history and source requests. */
function submissions() {
  return compositionRequest.mock.calls.filter(
    ([, , body]) => body !== undefined,
  );
}

it("offers only HDBSCAN settings and submits standalone sampling parameters", async () => {
  await setup({ population: 12000 });
  expect(screen.getByRole("group", { name: "HDBSCAN" })).toBeVisible();
  expect(screen.queryByRole("radiogroup", { name: "Algorithm" })).not.toBeInTheDocument();
  expect(screen.queryByText(/consensus/i)).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("spinbutton", { name: "min_cluster_size" }), { target: { value: "8" } });
  fireEvent.click(screen.getByRole("button", { name: "Start experiment" }));
  await waitFor(() => expect(submissions()).toHaveLength(1));
  expect(submissions()[0][2]).toMatchObject({
    algorithm_id: "hdbscan", sample_size: 2000,
    parameters: { min_cluster_size: 8 },
  });
});

it("preserves standalone HDBSCAN parameters when duplicating and confirms large reruns", async () => {
  await setup({ savedParameters: { min_cluster_size: 9, min_samples: 4 } });
  openSaved();
  fireEvent.click(await screen.findByRole("button", { name: "Duplicate and edit" }));
  expect(screen.getByRole("spinbutton", { name: "Sample size" })).toBeDisabled();
  expect(screen.getByRole("spinbutton", { name: "min_cluster_size" })).toHaveValue(9);
  expect(screen.getByRole("spinbutton", { name: "min_samples" })).toHaveValue(4);
  openSaved(/saved-ru|complete/);
  fireEvent.click(screen.getByRole("button", { name: "Rerun saved inputs" }));
  expect(screen.getByRole("alertdialog")).toHaveTextContent("20,001 boards");
  expect(submissions()).toHaveLength(0);
});

it("caps the field at the current population and adjusts when the source changes", async () => {
  await setup({ population: 30000 });
  const input = screen.getByRole("spinbutton", { name: "Sample size" });
  expect(input).toHaveAttribute("max", "30000");
  selectSample(30001);
  expect(input.validity.rangeOverflow).toBe(true);
  fireEvent.change(screen.getByRole("combobox", { name: /^Source/ }), {
    target: { value: "fixture" },
  });
  await waitFor(() => expect(input).toHaveValue(24));
  expect(input).toHaveAttribute("max", "24");
});

it("starts exactly 20000 without confirmation, even with full classification", async () => {
  await setup();
  selectSample(20000);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Start experiment" }));
  await waitFor(() => expect(submissions()).toHaveLength(1));
  expect(submissions()[0][2]).toMatchObject({
    sample_size: 20000,
    full_population: true,
  });
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
});

it("requires confirmation above 20000 and cancelling sends no request", async () => {
  await setup();
  selectSample(20001);
  fireEvent.click(screen.getByRole("button", { name: "Start experiment" }));
  expect(screen.getByRole("alertdialog")).toHaveTextContent("20,001");
  expect(submissions()).toHaveLength(0);
  fireEvent.click(
    within(screen.getByRole("alertdialog")).getByRole("button", {
      name: "Cancel",
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Start experiment" }));
  fireEvent.click(
    within(screen.getByRole("alertdialog")).getByRole("button", {
      name: "Continue",
    }),
  );
  await waitFor(() => expect(submissions()).toHaveLength(1));
  expect(submissions()[0][2].sample_size).toBe(20001);
});

it("confirms reruns and duplicates using the frozen sample despite a smaller live source", async () => {
  await setup({ population: 24 });
  openSaved();
  const rerun = await screen.findByRole("button", {
    name: "Rerun saved inputs",
  });
  await waitFor(() => expect(rerun).toBeEnabled());
  fireEvent.click(rerun);
  expect(screen.getByRole("alertdialog")).toHaveTextContent("20,001");
  expect(submissions()).toHaveLength(0);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(submissions()).toHaveLength(0);
  fireEvent.click(rerun);
  fireEvent.click(
    within(screen.getByRole("alertdialog")).getByRole("button", {
      name: "Continue",
    }),
  );
  await waitFor(() => expect(submissions()).toHaveLength(1));
  expect(submissions()[0][0]).toBe("/experiments/saved-run/rerun");
  await waitFor(() => expect(rerun).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Duplicate and edit" }));
  const input = screen.getByRole("spinbutton", { name: "Sample size" });
  expect(input).toHaveValue(20001);
  expect(input).toHaveAttribute("max", "40000");
  expect(input).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Start experiment" }));
  expect(screen.getByRole("alertdialog")).toHaveTextContent("20,001");
  expect(submissions()).toHaveLength(1);
  fireEvent.click(
    within(screen.getByRole("alertdialog")).getByRole("button", {
      name: "Cancel",
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Start experiment" }));
  fireEvent.click(
    within(screen.getByRole("alertdialog")).getByRole("button", {
      name: "Continue",
    }),
  );
  await waitFor(() => expect(submissions()).toHaveLength(2));
  expect(submissions()[1][2]).toMatchObject({
    sample_size: 20001,
    snapshot_id: "saved-snapshot",
  });
});

it("reruns a saved 20000-board sample without confirmation", async () => {
  await setup({ savedSample: 20000 });
  openSaved();
  const rerun = await screen.findByRole("button", {
    name: "Rerun saved inputs",
  });
  await waitFor(() => expect(rerun).toBeEnabled());
  fireEvent.click(rerun);
  await waitFor(() => expect(submissions()).toHaveLength(1));
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
});

/** Mount two completed runs and two populations to exercise result navigation. */
async function completedWorkspace() {
  const cases = (
    await import("../../../../tests/compositions/fixtures/contracts.json")
  ).default;
  const detail = structuredClone(
    cases.find((entry) => entry.name === "detail").value,
  );
  const list = cases.find((entry) => entry.name === "list").value;
  const other = structuredClone(detail.examples[0]);
  other.board.observation_id = "example-001";
  other.assignment.observation_id = "example-001";
  detail.examples.push(other);
  const saved = {
    experiment_id: "complete-one",
    snapshot_id: "snapshot-one",
    status: "completed",
    stage: "completed",
    elapsed_seconds: 1,
    eligible_boards: 24,
    sample_boards: 24,
    error: null,
    context: detail.context,
    request: {
      algorithm_id: "hdbscan",
      algorithm_version: "1",
      parameters: {},
      seed: 42,
      sample_size: 24,
      full_population: true,
      source_kind: "fixture",
      snapshot_id: "snapshot-one",
    },
    result: {
      model: { families: [detail.family] },
      diagnostics: {
        warnings: [],
        panels: [
          {
            panel_id: "example",
            title: "Sample diagnostic",
            kind: "table",
            description: "Saved diagnostic records",
            data: { rows: [{ value: 2 }] },
          },
        ],
      },
      populations: ["discovery_sample", "full_population"].map(
        (population_kind) => ({
          population_kind,
          coverage: 0.5,
          ambiguity: 0,
          assignments: detail.examples.map((e) => e.assignment),
        }),
      ),
    },
  };
  compositionRequest.mockImplementation(async (path) => {
    if (path === "/algorithms")
      return {
        algorithms: [{ algorithm_id: "hdbscan", parameter_schema: {} }],
      };
    if (path.startsWith("/source?"))
      return { ready: true, eligible_boards: 24 };
    if (path === "/experiments")
      return {
        experiments: [saved, { ...saved, experiment_id: "complete-two" }],
      };
    if (path.includes("/families?")) return list;
    if (path.includes("/families/")) return detail;
    if (path.startsWith("/compare?"))
      return {
        message: "Comparable populations",
        assignment_overlap: 0.8,
        adjusted_rand_index: 0.7,
        left_metrics: { family_count: 1 },
        right_metrics: { family_count: 2 },
        configuration_differences: {},
      };
    return saved;
  });
  render(<Experiments />);
  await screen.findAllByRole("button", { name: /complete/ });
  openSaved(/complete/);
  await screen.findByRole("heading", { name: "Representative structure" });
  return { detail };
}

it("retains the selected example and diagnostic disclosures across result tabs", async () => {
  await completedWorkspace();
  fireEvent.click(screen.getByRole("button", { name: /example-001/ }));
  fireEvent.mouseDown(screen.getByRole("tab", { name: "Diagnostics" }), {
    button: 0,
    ctrlKey: false,
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Sample diagnostic · table" }),
  );
  expect(screen.getByText("Saved diagnostic records")).toBeVisible();
  fireEvent.mouseDown(screen.getByRole("tab", { name: "Families" }), {
    button: 0,
    ctrlKey: false,
  });
  expect(screen.getByRole("button", { name: /example-001/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  fireEvent.mouseDown(screen.getByRole("tab", { name: "Diagnostics" }), {
    button: 0,
    ctrlKey: false,
  });
  expect(screen.getByText("Saved diagnostic records")).toBeVisible();
});

it("opens an example in the dedicated inspector, transfers focus, and preserves draft inputs", async () => {
  await completedWorkspace();
  fireEvent.click(screen.getByRole("button", { name: "Inspect board →" }));
  expect(screen.getByRole("tab", { name: "Boards" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(screen.getByRole("tab", { name: "Boards" })).toHaveFocus();
  expect(screen.getByRole("button", { name: /example-000/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(
    screen.getByRole("heading", { name: "Assignment evidence" }),
  ).toBeVisible();
  expect(
    compositionRequest.mock.calls.some(([path]) => path.includes("/boards/")),
  ).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "New experiment" }));
  fireEvent.change(screen.getByRole("spinbutton", { name: "Seed" }), {
    target: { value: "123" },
  });
  openSaved(/saved-ru|complete/);
  expect(screen.getByRole("button", { name: /example-000/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  fireEvent.click(screen.getByRole("button", { name: "New experiment" }));
  expect(screen.getByRole("spinbutton", { name: "Seed" })).toHaveValue(123);
});

it("clears comparison and board evidence when the statistics population changes", async () => {
  await completedWorkspace();
  fireEvent.click(screen.getByRole("button", { name: "Inspect board →" }));
  fireEvent.mouseDown(screen.getByRole("tab", { name: "Compare" }), {
    button: 0,
    ctrlKey: false,
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Comparison run" }), {
    target: { value: "complete-two" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Compare", exact: true }));
  expect(await screen.findByText("Comparable populations")).toBeVisible();
  fireEvent.click(
    within(screen.getByRole("group", { name: "Statistics population" })).getByRole(
      "button",
      { name: "Full population" },
    ),
  );
  await waitFor(() =>
    expect(
      screen.queryByText("Comparable populations"),
    ).not.toBeInTheDocument(),
  );
  fireEvent.mouseDown(screen.getByRole("tab", { name: "Boards" }), {
    button: 0,
    ctrlKey: false,
  });
  expect(screen.getByRole("button", { name: /example-000/ })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  await waitFor(() =>
    expect(
      compositionRequest.mock.calls.some(([path]) =>
        path.endsWith("/families?population=full_population"),
      ),
    ).toBe(true),
  );
});
