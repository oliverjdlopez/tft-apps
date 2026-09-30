import { fireEvent, render, screen, waitFor, within, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./app.jsx";

vi.mock("./tabs/index.jsx", () => ({
  ModelsTab: () => <div>Model inspector</div>,
  OverviewTab: () => <div>Data status</div>,
  RawTab: () => <div>Upstream API probes</div>,
  RolldownTab: () => <div>Rolldown analysis</div>,
  ResponseTuningTab: () => <div>Response continuation tuner</div>,
  SpecsTab: () => <div>Production specs editor</div>,
  ToolsTab: () => <div>Tool invocation</div>,
}));

afterEach(cleanup);

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState({}, "", "/");
  global.fetch = vi.fn(async () => ({
    ok: true,
    text: async () => JSON.stringify({ assistants: [], tasks: [] }),
  }));
});

describe("consolidated application navigation", () => {
  it("renders Rolldown independently without changing the saved ChatTFT destination", () => {
    window.history.replaceState({}, "", "/rolldown");
    localStorage.setItem("tft.tab", JSON.stringify("developer"));
    render(<App />);
    expect(screen.getByText("Rolldown analysis")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Developer" })).not.toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem("tft.tab"))).toBe("developer");
  });

  it("exposes three main destinations and both workflow categories", async () => {
    localStorage.setItem("tft.tab", JSON.stringify("workflows"));
    const { container } = render(<App />);
    const primary = within(container.querySelector(".nav-items"));
    expect(primary.getAllByRole("button").map((button) => button.textContent)).toEqual([
      "Chat", "Workflows", "Developer",
    ]);
    expect(await screen.findByText("No assistants are registered.")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Tasks", exact: true }), { button: 0, ctrlKey: false });
    expect(await screen.findByText("No tasks are registered.")).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem("tft.workflowKind"))).toBe("task");
    fireEvent.click(primary.getByRole("button", { name: "Developer" }));
    const sections = within(screen.getByRole("tablist", { name: "Developer sections" }));
    expect(sections.queryByRole("button", { name: "Database" })).not.toBeInTheDocument();
    fireEvent.mouseDown(sections.getByRole("tab", { name: "Specs" }), { button: 0, ctrlKey: false });
    expect(screen.getByText("Production specs editor")).toBeInTheDocument();
    fireEvent.mouseDown(sections.getByRole("tab", { name: "Prompt tuning" }), { button: 0, ctrlKey: false });
    expect(screen.getByText("Response continuation tuner")).toBeInTheDocument();
  });

  it.each([
    ["tasks", "overview", "workflows", "No tasks are registered."],
    ["assistants", "overview", "workflows", "No assistants are registered."],
    ["specs", "overview", "developer", "Production specs editor"],
    ["specs", "database", "developer", "Production specs editor"],
    ["response-tuning", "overview", "developer", "Response continuation tuner"],
    ["data", "tools", "developer", "Tool invocation"],
    ["data", "database", "developer", "Data status"],
  ])("migrates saved %s / %s navigation", async (oldTab, oldSection, newTab, content) => {
    localStorage.setItem("tft.tab", JSON.stringify(oldTab));
    localStorage.setItem("tft.dataTab", JSON.stringify(oldSection));
    render(<App />);
    expect(await screen.findByText(content)).toBeInTheDocument();
    await waitFor(() => expect(JSON.parse(localStorage.getItem("tft.tab"))).toBe(newTab));
    expect(global.fetch.mock.calls.some(([path]) => path.startsWith("/api/db"))).toBe(false);
  });
});

it("preserves sidebar collapse and supports keyboard section navigation", async () => {
  localStorage.setItem("tft.tab", JSON.stringify("developer"));
  const { container } = render(<App />);
  fireEvent.click(container.querySelector('[data-slot="sidebar-footer"] button'));
  expect(JSON.parse(localStorage.getItem("tft.sidebarCollapsed"))).toBe(true);
  const status = screen.getByRole("tab", { name: "Status" });
  status.focus();
  fireEvent.keyDown(status, { key: "ArrowRight" });
  await waitFor(() => expect(screen.getByRole("tab", { name: "Models" })).toHaveFocus());
  expect(screen.getByText("Model inspector")).toBeInTheDocument();
});

it("resets workflow inputs when switching categories and returning", async () => {
  localStorage.setItem("tft.tab", JSON.stringify("workflows"));
  global.fetch = vi.fn(async (url) => ({ ok: true, text: async () => JSON.stringify(
    url === "/api/config"
      ? { default_assistant: "Analyst", assistants: ["Analyst"] }
      : { assistants: [{ name: "Analyst" }], tasks: [{ name: "Review" }] },
  ) }));
  render(<App />);
  fireEvent.change(await screen.findByLabelText("Input"), { target: { value: "Unsaved assistant request" } });
  fireEvent.mouseDown(screen.getByRole("tab", { name: "Tasks", exact: true }), { button: 0, ctrlKey: false });
  expect(await screen.findByLabelText("Input")).toHaveValue("");
  fireEvent.mouseDown(screen.getByRole("tab", { name: "Assistants", exact: true }), { button: 0, ctrlKey: false });
  expect(await screen.findByLabelText("Input")).toHaveValue("");
});
