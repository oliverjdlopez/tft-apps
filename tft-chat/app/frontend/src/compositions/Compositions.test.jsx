import React from "react";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import Compositions, { BoardCard, FamilyDetail } from "./Compositions.jsx";
import cases from "../../../../tests/compositions/fixtures/contracts.json";
const detail = cases.find((c) => c.name === "detail").value;
const list = cases.find((c) => c.name === "list").value;
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
/** Return API responses through the application's actual fetch boundary. */
function mockApi(malformed = false) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url) => ({
      ok: true,
      text: async () =>
        JSON.stringify(
          url === "/api/config"
            ? { composition_workbench: true }
            : url.includes("/source?")
              ? {
                  source_kind: "active",
                  ready: true,
                  patch: "fixture",
                  set_number: 17,
                  queue_id: 1100,
                  eligible_boards: 24,
                  fact_revision: "fixture.v1",
                  warning: null,
                }
              : url.endsWith("/algorithms")
                ? { algorithms: [] }
                : url.endsWith("/experiments")
                  ? { experiments: [] }
                  : url.endsWith("/fixtures")
                    ? malformed
                      ? { ...list, secret: "bad" }
                      : list
                    : detail,
        ),
    })),
  );
}
it("retains duplicate champions and holder-bound duplicate items", () => {
  render(<BoardCard example={detail.examples[0]} />);
  expect(screen.getAllByText("Jinx")).toHaveLength(2);
  expect(screen.getAllByText("Blade")).toHaveLength(2);
  expect(screen.getByText(/tier Unknown/)).toBeInTheDocument();
  expect(screen.getByText(/Placement Unknown/)).toBeInTheDocument();
});
it("renders the representative structure distinctly from representative observations", () => {
  render(<FamilyDetail detail={detail} />);
  expect(screen.getByText("Representative structure")).toBeInTheDocument();
  expect(screen.getByText(/Representative board ·/)).toBeInTheDocument();
});
it("surfaces malformed wire payloads visibly", async () => {
  mockApi(true);
  render(<Compositions />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Composition contract error",
  );
});
it("blocks disabled workspaces before requesting private data", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      text: async () => JSON.stringify({ composition_workbench: false }),
    })),
  );
  render(<Compositions />);
  expect(await screen.findByRole("alert")).toHaveTextContent("disabled");
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("loads fixture family details through validated responses", async () => {
  mockApi();
  render(<Compositions />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Display fixtures" }),
  );
  fireEvent.click(
    within(
      screen.getByRole("navigation", { name: "Fixture families" }),
    ).getByRole("button", { name: /Jinx investment/ }),
  );
  expect(await screen.findByText("Representative structure")).toBeInTheDocument();
});

it("shows all eight placement counts and keeps unavailable outcomes distinct from zero", () => {
  const { rerender } = render(<FamilyDetail detail={detail} />);
  expect(
    screen.getByRole("img", { name: /Placement 1: 1 boards/ }),
  ).toHaveAccessibleName(/Placement 6: 0 boards/);
  expect(screen.getByText(/9 known placements/)).toBeVisible();
  const unavailable = structuredClone(detail);
  unavailable.profile.outcomes = cases.find(
    (entry) => entry.name === "suppressed",
  ).value;
  rerender(<FamilyDetail detail={unavailable} />);
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(screen.getAllByText("Unavailable")).toHaveLength(3);
  expect(screen.getByText(/Outcomes: suppressed/)).toBeVisible();
});

it("renders portraits, holder-bound item icons, traits, and family previews from one batch", async () => {
  const { EntityAssetProvider } = await import("../assets/EntityImages.jsx");
  const { compositionImageRequests } = await import("./utils.js");
  const { FamilyPreview } = await import("./Compositions.jsx");
  vi.stubGlobal("fetch", vi.fn(async (_url, options) => {
    const body = JSON.parse(options.body);
    return { ok: true, text: async () => JSON.stringify({ results: body.entities.map((entity) => ({
      status: "resolved", api_name: entity.name_or_id,
      src: `/media/tft/latest/set-17/en_us/files/${encodeURIComponent(entity.name_or_id)}.png`,
      asset_patch: "latest", fallback: true,
    })) }) };
  }));
  const { container } = render(<EntityAssetProvider context={detail.context}
    entities={compositionImageRequests({ detail, families: list.families })}>
    <FamilyPreview family={list.families[0]} />
    <FamilyDetail detail={detail} />
  </EntityAssetProvider>);
  await waitFor(() => expect(container.querySelectorAll("img").length).toBeGreaterThan(5));
  expect(fetch).toHaveBeenCalledTimes(1);
  const units = container.querySelectorAll(".composition-unit");
  expect(units).toHaveLength(detail.examples[0].board.units.length);
  units.forEach((unit, index) => {
    const occurrence = detail.examples[0].board.units[index];
    expect(unit.querySelector("img")).toHaveAttribute("width", "48");
    expect(unit.querySelectorAll("li img")).toHaveLength(occurrence.items.length);
    occurrence.items.forEach((item) => expect(unit).toHaveTextContent(`slot ${item.slot + 1}`));
  });
  expect(container.querySelector(".composition-family-preview img")).not.toBeNull();
  expect(screen.getByText("Boards matching the representative structure").closest('[data-slot="collapsible"]').querySelector("img")).not.toBeNull();
});

it("keeps alternative structures and truncated units and traits explicit in family previews", async () => {
  const { FamilyPreview } = await import("./Compositions.jsx");
  const family = { ...list.families[0], preview: {
    ...list.families[0].preview, omitted_requirements: 2, alternative_patterns: 1,
  } };
  render(<FamilyPreview family={family} />);
  expect(screen.getByText(/2 more units and traits/)).toHaveTextContent("1 other representative structure");
  expect(screen.getByText("Jinx")).toBeVisible();
});
