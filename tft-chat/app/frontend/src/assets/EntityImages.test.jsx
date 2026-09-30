/** Exercise batching, cache reuse, image failures, and patch-switch race handling. */
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { apiPost } from "../app.jsx";
import { EntityAssetProvider, EntityLabel } from "./EntityImages.jsx";
import { createAssetLoader } from "./utils.js";

vi.mock("../app.jsx", () => ({ apiPost: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

/** Build a valid same-origin result for each requested entity. */
function response(body, assetPatch = body.patch) {
  return { results: body.entities.map((entity) => ({
    status: "resolved", api_name: entity.name_or_id,
    src: `/media/tft/${assetPatch}/set-17/en_us/files/${encodeURIComponent(entity.name_or_id)}.png`,
    asset_patch: assetPatch, fallback: assetPatch !== body.patch,
  })) };
}
/** Supply the same semantic request the composition view would collect. */
function request(name) {
  return { kind: "unit", name_or_id: name, role: "portrait" };
}
/** Render a single readable entity under a view-scoped catalog context. */
function View({ patch = "17.1", name = "Ashe" }) {
  return <EntityAssetProvider context={{ patch, set_number: 17 }} entities={[request(name)]}>
    <EntityLabel kind="unit" entity={{ key: name, name }} />
  </EntityAssetProvider>;
}

it("deduplicates requests, chunks at 256, and caches in-flight and completed results", async () => {
  apiPost.mockImplementation(async (_url, body) => response(body));
  const load = createAssetLoader("17.1", 17);
  const entities = Array.from({ length: 600 }, (_, i) => request(`Unit${i}`));
  const [first, second] = await Promise.all([load([...entities, entities[0]]), load(entities)]);
  expect(apiPost).toHaveBeenCalledTimes(3);
  expect(apiPost.mock.calls.map(([, body]) => body.entities.length)).toEqual([256, 256, 88]);
  expect(first.size).toBe(600);
  expect(second).toEqual(first);
  await load([entities[0]]);
  expect(apiPost).toHaveBeenCalledTimes(3);
});

it("keeps labels accessible, reports fallback, and replaces a broken image", async () => {
  apiPost.mockImplementation(async (_url, body) => response(body, "latest"));
  const { container } = render(<View />);
  await waitFor(() => expect(container.querySelector("img")).not.toBeNull());
  expect(screen.getByText("Ashe")).toBeVisible();
  expect(container.querySelector("img")).toHaveAttribute("alt", "");
  expect(container.querySelector("img")).toHaveAttribute("loading", "lazy");
  expect(screen.getByRole("status")).toHaveTextContent("same-set patch latest");
  fireEvent.error(container.querySelector("img"));
  expect(container.querySelector("img")).toBeNull();
  expect(screen.getByRole("status")).toHaveTextContent("1 entity image is unavailable");
  expect(screen.getByText("Ashe")).toBeVisible();
});

it("does not apply a late response from the previous patch or entity selection", async () => {
  let finishOld;
  apiPost.mockImplementationOnce((_url, body) => new Promise((resolve) => {
    finishOld = () => resolve(response(body));
  })).mockImplementation(async (_url, body) => response(body));
  const { container, rerender } = render(<View />);
  await waitFor(() => expect(finishOld).toBeDefined());
  rerender(<View patch="17.2" name="Jinx" />);
  await waitFor(() => expect(container.querySelector("img")?.getAttribute("src")).toContain("17.2"));
  finishOld();
  await waitFor(() => expect(container.querySelector("img")?.getAttribute("src")).toContain("Jinx.png"));
  expect(screen.queryByText("Ashe")).toBeNull();
  expect(container.querySelector("img").src).not.toContain("17.1");
});

it("treats transport and malformed responses as unavailable without hiding content", async () => {
  apiPost.mockRejectedValueOnce(new Error("offline"));
  const { rerender } = render(<View />);
  expect(await screen.findByRole("status")).toHaveTextContent("unavailable");
  expect(screen.getByText("Ashe")).toBeVisible();
  apiPost.mockResolvedValueOnce({ results: [] });
  rerender(<View name="Jinx" />);
  await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(2));
  expect(await screen.findByRole("status")).toHaveTextContent("unavailable");
  expect(screen.getByText("Jinx")).toBeVisible();
});
