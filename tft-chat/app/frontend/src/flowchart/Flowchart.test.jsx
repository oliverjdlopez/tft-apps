import React from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Flowchart from "./Flowchart.jsx";
import EntitySidebar from "./EntitySidebar.jsx";
import {
  ENTITY_MIME, edgePath, fromFragment, GROUP_MIME, isValidLink, newNode, toEdges, toFlowchart, toFragment, toNodes,
} from "./utils.js";

const catalog = {
  patch: null,
  set_number: 17,
  units: [
    { api_name: "TFT17_Ashe", name: "Ashe", cost: 1, src: null },
    { api_name: "TFT17_Jinx", name: "Jinx", cost: 4, src: "/media/tft/latest/set-17/en_us/files/jinx.png" },
  ],
  items: [{ api_name: "TFT_Item_InfinityEdge", name: "Infinity Edge", type: "craftable", src: null }],
  augments: [{ api_name: "TFT17_Augment_Heroic", name: "Heroic Grab Bag", src: null }],
};

/** Build a portable document with one plan node, as the backend would return it. */
function workspace(name, elements = []) {
  return {
    schema_version: "flowchart.v1", name, patch: null, set_number: 17,
    gameplan: { flowchart: { elements, connections: [], viewport: { x: 0, y: 0, zoom: 1 } } },
  };
}

const plan = {
  id: "opener", kind: "plan", position: { x: 0, y: 0 }, size: null, title: "Opener",
  stage_hint: "2-1", entities: [], text: "",
};

let backend;
let requests;

/** Serve an in-memory flowchart backend through the application's fetch boundary. */
function mockApi({ source = "database", conflict = false } = {}) {
  backend = {
    database: new Map([["db-1", { id: "db-1", revision: 1, source: "database", workspace: workspace("Reroll", [plan]) }]]),
    json: new Map([["checked-in", { id: "checked-in", revision: 1, source: "json", workspace: workspace("Checked in", [plan]) }]]),
    groups: [],
  };
  requests = [];
  const reply = (status, body) => ({ ok: status < 400, status, text: async () => (body === undefined ? "" : JSON.stringify(body)) });
  const record = (value) => ({ created_at: null, updated_at: null, ...value });
  vi.stubGlobal("fetch", vi.fn(async (url, options = {}) => {
    const method = options.method ?? "GET";
    const body = options.body ? JSON.parse(options.body) : undefined;
    requests.push({ url, method, body });
    const { pathname, searchParams } = new URL(url, "http://local");
    const store = backend[searchParams.get("source") ?? "database"];
    if (pathname === "/api/config") return reply(200, { flowchart_source: source });
    if (pathname === "/api/assets/catalog") return reply(200, catalog);
    if (pathname === "/api/flowchart/groups") {
      if (method === "GET") return reply(200, { groups: backend.groups });
      const group = record({ id: `g-${backend.groups.length + 1}`, name: body.name, set_number: body.set_number, fragment: body.fragment });
      backend.groups.unshift(group);
      return reply(201, group);
    }
    if (pathname === "/api/flowchart/workspaces/import") {
      const id = `db-${backend.database.size + 1}`;
      backend.database.set(id, { id, revision: 1, source: "database", workspace: body.workspace });
      return reply(201, record(backend.database.get(id)));
    }
    if (pathname === "/api/flowchart/workspaces") {
      if (method === "POST") {
        const id = `db-${backend.database.size + 1}`;
        backend.database.set(id, { id, revision: 1, source: "database", workspace: { ...workspace(body.name), set_number: body.set_number } });
        return reply(201, record(backend.database.get(id)));
      }
      return reply(200, {
        source: searchParams.get("source"),
        workspaces: [...store.values()].map((w) => ({
          id: w.id, name: w.workspace.name, patch: null, set_number: 17, revision: w.revision, updated_at: null, source: w.source,
        })),
      });
    }
    const id = decodeURIComponent(pathname.split("/").pop());
    if (method === "PUT") {
      if (conflict) return reply(409, { detail: "This workspace changed after it was opened." });
      const saved = { ...store.get(id), revision: body.revision + 1, workspace: body.workspace };
      store.set(id, saved);
      return reply(200, record(saved));
    }
    return reply(200, record(store.get(id)));
  }));
}

/** Simulate dropping one sidebar entity with the palette's drag payload. */
function drop(target, entity) {
  const payload = JSON.stringify(entity);
  fireEvent.drop(target, {
    clientX: 10, clientY: 10,
    dataTransfer: { getData: (type) => (type === ENTITY_MIME ? payload : ""), dropEffect: "copy" },
  });
}

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("opens the first workspace and creates a new one from the rail", async () => {
  mockApi();
  render(<Flowchart />);
  expect(await screen.findByDisplayValue("Opener")).toBeInTheDocument();
  expect(screen.getByLabelText("Workspace title")).toHaveValue("Reroll");

  fireEvent.change(screen.getByLabelText("Workspace name"), { target: { value: "Fast 8" } });
  fireEvent.change(screen.getByLabelText("Set"), { target: { value: "17" } });
  fireEvent.click(screen.getByRole("button", { name: "Create" }));

  await waitFor(() => expect(screen.getByLabelText("Workspace title")).toHaveValue("Fast 8"));
  const created = requests.find((r) => r.method === "POST" && r.url.startsWith("/api/flowchart/workspaces?"));
  expect(created.body).toEqual({ name: "Fast 8", patch: null, set_number: 17 });
  expect(within(screen.getByRole("navigation", { name: "Workspace list" })).getByText("Fast 8")).toBeInTheDocument();
});

it("switches palette tabs and filters entities by search", () => {
  render(<EntitySidebar catalog={catalog} error="" />);
  expect(screen.getByText("1-cost")).toBeInTheDocument();
  expect(screen.getByRole("listitem", { name: "Jinx" })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Jinx" })).toHaveAttribute("src", catalog.units[1].src);

  fireEvent.change(screen.getByLabelText("Search entities"), { target: { value: "ash" } });
  expect(screen.queryByRole("listitem", { name: "Jinx" })).not.toBeInTheDocument();
  expect(screen.getByRole("listitem", { name: "Ashe" })).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Search entities"), { target: { value: "" } });
  fireEvent.mouseDown(screen.getByRole("tab", { name: "Augments" }), { button: 0, ctrlKey: false });
  expect(screen.getByRole("listitem", { name: "Heroic Grab Bag" })).toBeInTheDocument();
  fireEvent.mouseDown(screen.getByRole("tab", { name: "Items" }), { button: 0, ctrlKey: false });
  expect(screen.getByText("Craftable")).toBeInTheDocument();
});

it("drops entities onto plans and empty canvas, then autosaves with the revision", async () => {
  mockApi();
  const { container } = render(<Flowchart />);
  await screen.findByDisplayValue("Opener");

  drop(container.querySelector(".react-flow__node-plan .flowchart-state"), { category: "unit", api_name: "TFT17_Ashe" });
  // jsdom never measures nodes, so React Flow keeps them out of the accessibility tree.
  await waitFor(() => expect(container.querySelector('[aria-label="Remove Ashe"]')).not.toBeNull());

  drop(screen.getByTestId("flowchart-canvas"), { category: "augment", api_name: "TFT17_Augment_Heroic" });
  expect(await screen.findByText("Heroic Grab Bag", { selector: ".flowchart-entity-name" })).toBeInTheDocument();

  await waitFor(() => expect(requests.some((r) => r.method === "PUT")).toBe(true), { timeout: 3000 });
  const save = requests.filter((r) => r.method === "PUT").at(-1);
  expect(save.body.revision).toBe(1);
  const elements = save.body.workspace.gameplan.flowchart.elements;
  expect(elements.find((e) => e.id === "opener").entities).toEqual([{ category: "unit", api_name: "TFT17_Ashe" }]);
  expect(elements.find((e) => e.kind === "entity").entities).toEqual([{ category: "augment", api_name: "TFT17_Augment_Heroic" }]);
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Saved"));
});

it("shows a reload banner when a save conflicts", async () => {
  mockApi({ conflict: true });
  render(<Flowchart />);
  fireEvent.change(await screen.findByDisplayValue("Opener"), { target: { value: "Opener v2" } });
  expect(await screen.findByText(/changed somewhere else/, {}, { timeout: 3000 })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
});

it("opens checked-in JSON read-only and imports it to the database", async () => {
  mockApi({ source: "json" });
  const { container } = render(<Flowchart />);
  expect(await screen.findByText("Read-only JSON")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /State/ })).toBeDisabled();
  expect(screen.getByDisplayValue("Opener")).toHaveAttribute("readonly");

  drop(container.querySelector(".react-flow__node-plan .flowchart-state"), { category: "unit", api_name: "TFT17_Ashe" });
  expect(container.querySelector(".flowchart-chip")).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: /Import to database/ }));
  await waitFor(() => expect(screen.getByRole("button", { name: /Database/ })).toHaveAttribute("aria-pressed", "true"));
  await waitFor(() => expect(screen.getByLabelText("Workspace title")).toHaveValue("Checked in"));
  expect(screen.queryByText("Read-only JSON")).not.toBeInTheDocument();
  expect(requests.find((r) => r.url === "/api/flowchart/workspaces/import").body.workspace.name).toBe("Checked in");
});

it("adds activity roles from the toolbar and drops chips onto actions", async () => {
  mockApi();
  const { container } = render(<Flowchart />);
  await screen.findByDisplayValue("Opener");

  for (const name of ["Start", "Action", "Decision", "Fork / join", "End"])
    fireEvent.click(screen.getByRole("button", { name }));
  fireEvent.change(container.querySelector('[aria-label="Decision question"]'), { target: { value: "Hit 3-star?" } });
  drop(container.querySelector(".react-flow__node-action .flowchart-action"), { category: "item", api_name: "TFT_Item_InfinityEdge" });

  await waitFor(() => {
    const save = requests.filter((r) => r.method === "PUT").at(-1);
    const elements = save?.body.workspace.gameplan.flowchart.elements ?? [];
    expect(elements.map((e) => e.kind)).toEqual(["plan", "start", "action", "decision", "fork", "end"]);
    expect(elements.find((e) => e.kind === "decision").title).toBe("Hit 3-star?");
    expect(elements.find((e) => e.kind === "action").entities).toEqual([{ category: "item", api_name: "TFT_Item_InfinityEdge" }]);
    // Forks start as horizontal bars for top-to-bottom flow.
    expect(elements.find((e) => e.kind === "fork").size).toEqual({ width: 160, height: 10 });
  }, { timeout: 3000 });
});

it("keeps link sides, guards, and notes through a canvas round trip", () => {
  const elements = [
    { id: "q", kind: "decision", position: { x: 0, y: 0 }, size: { width: 128, height: 96 }, title: "Hit?", stage_hint: null, entities: [], text: "" },
    { id: "s", kind: "plan", position: { x: 200, y: 0 }, size: null, title: "Reroll", stage_hint: null, entities: [], text: "" },
    { id: "a", kind: "action", position: { x: 200, y: 200 }, size: null, title: "Econ", stage_hint: null, entities: [], text: "" },
  ];
  const connections = [
    { id: "t", source: "q", target: "s", kind: "transition", condition: "yes", notes: "Slam items", source_handle: "bottom", target_handle: "top" },
    // Any node kind can now use any side.
    { id: "u", source: "s", target: "a", kind: "transition", condition: "", notes: "", source_handle: "bottom", target_handle: "top" },
  ];
  const edges = toEdges(connections);
  expect(edges[0]).toMatchObject({ sourceHandle: "bottom", targetHandle: "top", type: "transition" });
  const round = toFlowchart(toNodes(elements), edges, { x: 0, y: 0, zoom: 1 });
  expect(round.connections).toEqual(connections);
});

it("routes links saved without sides from right to left, as they were drawn before", () => {
  const [edge] = toEdges([{
    id: "t", source: "a", target: "b", kind: "transition", condition: "", notes: "", source_handle: null, target_handle: null,
  }]);
  expect(edge).toMatchObject({ sourceHandle: "right", targetHandle: "left" });
});

it("sizes shape-driven nodes by default and leaves content-sized nodes free", () => {
  const at = { x: 0, y: 0 };
  const [decision, plan] = toNodes([
    { id: "q", kind: "decision", position: at, size: null, title: "", stage_hint: null, entities: [], text: "" },
    { id: "s", kind: "plan", position: at, size: null, title: "", stage_hint: null, entities: [], text: "" },
  ]);
  expect(decision).toMatchObject({ width: 128, height: 96 });
  expect(plan.width).toBeUndefined();
  expect(newNode("fork", at)).toMatchObject({ width: 160, height: 10 });
  expect(newNode("action", at).width).toBeUndefined();
});

it("draws right-angle links by default and curves on request", () => {
  const geometry = { sourceX: 0, sourceY: 0, sourcePosition: "bottom", targetX: 120, targetY: 160, targetPosition: "top" };
  const [step] = edgePath(geometry, "step");
  const [curve] = edgePath(geometry, "curve");
  expect(step).not.toMatch(/C/);
  expect(curve).toMatch(/C/);
});

it("refuses links into a start, out of an end, and self-links", () => {
  const nodes = [
    { id: "go", type: "start" }, { id: "done", type: "end" }, { id: "a", type: "action" }, { id: "n", type: "note" },
  ];
  expect(isValidLink(nodes, { source: "go", target: "a" })).toBe(true);
  expect(isValidLink(nodes, { source: "a", target: "go" })).toBe(false);
  expect(isValidLink(nodes, { source: "done", target: "a" })).toBe(false);
  expect(isValidLink(nodes, { source: "a", target: "a" })).toBe(false);
  // Notes annotate anything, including start and end.
  expect(isValidLink(nodes, { source: "n", target: "go" })).toBe(true);
});

it("saves a selection as a group and inserts copies from the Groups tab", async () => {
  mockApi();
  const { container } = render(<Flowchart />);
  await screen.findByDisplayValue("Opener");
  expect(screen.getByRole("button", { name: /Save group/ })).toBeDisabled();

  fireEvent.click(container.querySelector('.react-flow__node[data-id="opener"]'));
  fireEvent.click(await screen.findByRole("button", { name: /Save group/ }));
  fireEvent.change(screen.getByLabelText("Group name"), { target: { value: "Reroll opener" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() => expect(requests.some((r) => r.method === "POST" && r.url === "/api/flowchart/groups")).toBe(true));
  const saved = requests.find((r) => r.method === "POST" && r.url === "/api/flowchart/groups").body;
  expect(saved).toMatchObject({ name: "Reroll opener", set_number: 17 });
  expect(saved.fragment.elements).toHaveLength(1);
  expect(saved.fragment.elements[0]).toMatchObject({ kind: "plan", title: "Opener", position: { x: 0, y: 0 } });

  fireEvent.mouseDown(screen.getByRole("tab", { name: "Groups" }), { button: 0, ctrlKey: false });
  const card = await screen.findByRole("listitem", { name: "Reroll opener" });
  expect(within(card).getByText("1 state")).toBeInTheDocument();
  fireEvent.click(within(card).getByRole("button", { name: /Insert/ }));

  await waitFor(() => {
    const save = requests.filter((r) => r.method === "PUT").at(-1);
    const elements = save?.body.workspace.gameplan.flowchart.elements ?? [];
    expect(elements).toHaveLength(2);
    expect(elements[1]).toMatchObject({ kind: "plan", title: "Opener" });
    expect(elements[1].id).not.toBe("opener");
  }, { timeout: 3000 });
});

it("pastes a group dragged from the library where it is dropped", async () => {
  mockApi();
  render(<Flowchart />);
  await screen.findByDisplayValue("Opener");
  const fragment = {
    elements: [{ id: "a", kind: "action", position: { x: 0, y: 0 }, size: null, title: "Slam items", stage_hint: null, entities: [], text: "" }],
    connections: [],
  };
  const payload = JSON.stringify(fragment);
  fireEvent.drop(screen.getByTestId("flowchart-canvas"), {
    clientX: 10, clientY: 10,
    dataTransfer: { getData: (type) => (type === GROUP_MIME ? payload : ""), dropEffect: "copy" },
  });
  expect(await screen.findByDisplayValue("Slam items")).toBeInTheDocument();
});

it("cuts a selection into an origin-based fragment and pastes fresh copies", () => {
  const nodes = toNodes([
    { id: "a", kind: "action", position: { x: 100, y: 200 }, size: null, title: "Roll", stage_hint: null, entities: [], text: "" },
    { id: "q", kind: "decision", position: { x: 100, y: 360 }, size: null, title: "Hit?", stage_hint: null, entities: [], text: "" },
    { id: "x", kind: "plan", position: { x: 900, y: 0 }, size: null, title: "Other", stage_hint: null, entities: [], text: "" },
  ]).map((node) => ({ ...node, selected: node.id !== "x" }));
  const edges = toEdges([
    { id: "in", source: "a", target: "q", kind: "transition", condition: "3-1", notes: "", source_handle: "bottom", target_handle: "top" },
    { id: "out", source: "q", target: "x", kind: "transition", condition: "", notes: "", source_handle: null, target_handle: null },
  ]);
  const fragment = toFragment(nodes, edges);
  expect(fragment.elements.map((e) => [e.id, e.position])).toEqual([["a", { x: 0, y: 0 }], ["q", { x: 0, y: 160 }]]);
  // The link leaving the selection is dropped.
  expect(fragment.connections.map((c) => c.id)).toEqual(["in"]);
  expect(toFragment(nodes.map((node) => ({ ...node, selected: false })), edges)).toBeNull();

  const pasted = fromFragment(fragment, { x: 40, y: 40 });
  expect(pasted.nodes.map((n) => n.position)).toEqual([{ x: 40, y: 40 }, { x: 40, y: 200 }]);
  expect(pasted.nodes.every((n) => n.selected && !["a", "q"].includes(n.id))).toBe(true);
  expect(pasted.edges[0]).toMatchObject({ source: pasted.nodes[0].id, target: pasted.nodes[1].id, sourceHandle: "bottom" });
  expect(pasted.edges[0].data.condition).toBe("3-1");
});
