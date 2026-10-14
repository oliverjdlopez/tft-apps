import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import RolldownTab from "./RolldownTab.jsx";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("prepares runs and automatically analyzes a purchased champion", async () => {
  const parameters = { level: 8, budget: 30, budget_type: "gold", pool_pressure: 0.2, simulations: 2000 };
  const run = { id: "run-1", label: "Example", parameters, prepared_samples: 2000 };
  const fetch = vi.fn(async (path) => new Response(JSON.stringify(
    path.endsWith("/units") ? { units: [{ name: "Example", cost: 4, bag_size: 10 }] }
      : path.endsWith("/analyze") ? { runs: [{ ...run, result: {
        probability_hit: 0.25, simulations: 2000, max_shops: 1,
        hit_all_by_shop: [0, 0.25], spend_by_shop: [0, 6], targets: [], trials: [],
      } }] }
        : { run_set_id: "prepared", runs: [run], sweeps: [{ dimension: "budget", values: [30] }] }
  ), { status: 200, headers: { "content-type": "application/json" } }));
  vi.stubGlobal("fetch", fetch);
  render(<RolldownTab />);
  await waitFor(() => expect(document.querySelector('datalist option[value="Example"]')).toBeInTheDocument());
  fireEvent.change(screen.getByDisplayValue("20, 30, 40, 50"), { target: { value: "20, 30, 40, 50, " } });
  fireEvent.click(screen.getByRole("button", { name: "Run simulation" }));
  fireEvent.change(await screen.findByPlaceholderText("Champion"), { target: { value: "Example" } });
  await waitFor(() => expect(screen.getAllByText("25.0%").length).toBeGreaterThan(0));
  const analysis = fetch.mock.calls.find(([path]) => path.endsWith("/analyze"));
  const preparation = fetch.mock.calls.find(([path]) => path.endsWith("/runs"));
  expect(JSON.parse(preparation[1].body).sweep.values).toEqual([20, 30, 40, 50]);
  expect(JSON.parse(analysis[1].body).target.groups[0].conditions).toEqual([{ unit: "Example", copies_at_least: 3 }]);
});
