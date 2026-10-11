import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SpecsTab from "./SpecsTab.jsx";

const { apiGet, apiPost } = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
vi.mock("../app.jsx", () => ({ apiGet, apiPost, Spinner: ({label}) => <span>{label}</span>, EmptyState: ({title}) => <p>{title}</p> }));
vi.mock("@/components/shared/confirmation", () => ({ useConfirmation: () => ({ confirm: async () => true, confirmation: null }) }));

const config = {resolved_model: "mock-model", skill_names: [], handoff_names: [], tool_group_keys: []};
let active;
const saved = (files = {"system.md": "Draft instructions"}) => ({...active, draft: {id: "draft-revision-123", files, validation: {valid: true}}, diff: {"system.md": "-Active instructions\n+Draft instructions"}});

beforeEach(() => {
  localStorage.clear();
  active = {name: "chat", active: {hash: "a".repeat(64), files: {"system.md": "Active instructions"}, instructions: "Active instructions", configuration: config},
    source_hash: "s".repeat(64), source_changed: false, draft: null, validation: {valid: true, errors: []}, configuration: config, runs: [], history: {revisions: [], events: []}, diff: {}};
  apiGet.mockReset(); apiPost.mockReset();
  apiGet.mockImplementation(async path => path === "/api/specs" ? {assistants: [{name: "chat", description: "Chat"}]} : active);
});

async function open() { render(<SpecsTab />); fireEvent.click(await screen.findByRole("button", {name: "chat"})); return screen.findByLabelText("Edit system.md"); }

describe("Assistant Specs workspace", () => {
  it("saves a draft without using the retired document write and requires saving before Try", async () => {
    const editor = await open();
    fireEvent.change(editor, {target: {value: "Draft instructions"}});
    expect(screen.getByRole("button", {name: "Try"})).toBeDisabled();
    apiPost.mockResolvedValue(saved());
    fireEvent.click(screen.getByRole("button", {name: "Save draft"}));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/api/specs/assistants/chat/draft", expect.objectContaining({files: {"system.md": "Draft instructions"}, expected_draft: null})));
    await waitFor(() => expect(screen.getByRole("button", {name: "Try"})).toBeEnabled());
    expect(screen.getByText("Active instructions", {selector: "pre"})).toBeInTheDocument();
  });

  it("reviews the full diff before Apply and closes the draft", async () => {
    active = saved();
    await open();
    apiPost.mockResolvedValue({...active, draft: null});
    fireEvent.click(screen.getByRole("button", {name: "Apply"}));
    expect(screen.getByText(/-Active instructions/)).toBeInTheDocument();
    expect(apiPost).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", {name: "Apply reviewed draft"}));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/api/specs/assistants/chat/apply", expect.objectContaining({expected_draft: "draft-revision-123"})));
  });

  it("keeps edits after a conflict and supports adding optional task files", async () => {
    const editor = await open();
    fireEvent.change(editor, {target: {value: "Keep my edits"}});
    apiPost.mockRejectedValue(new Error("Repository files changed; draft preserved"));
    fireEvent.click(screen.getByRole("button", {name: "Save draft"}));
    await screen.findByText("Repository files changed; draft preserved");
    expect(editor).toHaveValue("Keep my edits");
    fireEvent.click(screen.getByRole("button", {name: "Add task.md"}));
    fireEvent.change(screen.getByLabelText("Edit task.md"), {target: {value: "Task wrapper"}});
    expect(screen.getByRole("button", {name: "Remove task.md"})).toBeEnabled();
  });

  it("starts a trial and retains its saved revision receipt", async () => {
    active = saved();
    await open();
    apiPost.mockResolvedValue({id: "trial-id", assistant: "chat", revision: active.draft.id, kind: "trial", state: "completed", value: {question: "Question", result: {output: "Mock answer", token_usage: {total: 12}}}});
    fireEvent.click(screen.getByRole("button", {name: "Try"}));
    fireEvent.change(screen.getByLabelText("Trial question"), {target: {value: "Question"}});
    fireEvent.click(screen.getByRole("button", {name: "Start trial"}));
    expect(await screen.findByText("Mock answer")).toBeInTheDocument();
    expect(apiPost).toHaveBeenCalledWith("/api/specs/assistants/chat/trials", expect.objectContaining({question: "Question", expected_draft: active.draft.id}));
  });

  it("explains unavailable experiments while leaving Apply available", async () => {
    active = saved();
    apiGet.mockImplementation(async path => {
      if (path.endsWith("/datasets")) throw new Error("Langfuse is unavailable");
      return path === "/api/specs" ? {assistants: [{name: "chat"}]} : active;
    });
    await open(); fireEvent.click(screen.getByRole("button", {name: "Run experiment"}));
    await screen.findByText("Langfuse is unavailable");
    expect(screen.getByRole("button", {name: "Apply"})).toBeEnabled();
  });

  it("submits dataset selections once and displays experiment result links", async () => {
    active = saved();
    apiGet.mockImplementation(async path => {
      if (path.endsWith("/datasets")) return {datasets: [{name: "end-to-end", assistant: "chat", cases: []}]};
      return path === "/api/specs" ? {assistants: [{name: "chat"}]} : active;
    });
    apiPost.mockResolvedValue({id: "experiment-id", revision: active.draft.id, kind: "experiment", state: "completed", value: {job: {result: {experiments: [{name: "Draft", passed: true, url: "http://localhost:15510/experiments/run"}]}}}});
    await open(); fireEvent.click(screen.getByRole("button", {name: "Run experiment"}));
    await screen.findByRole("option", {name: "end-to-end (chat)"});
    fireEvent.click(screen.getByRole("button", {name: "Submit comparison"}));
    expect(await screen.findByRole("link", {name: "Open in Langfuse"})).toHaveAttribute("href", "http://localhost:15510/experiments/run");
    expect(apiPost).toHaveBeenCalledWith("/api/specs/assistants/chat/experiments", expect.objectContaining({dataset: "end-to-end", cases: [], repetitions: 1, submission_id: expect.any(String)}));
  });

  it("imports a concrete prompt version as a draft and restores saved revisions", async () => {
    active.history.revisions = [{id: "old-revision", files: {"system.md": "Historical"}, validation: {valid: true}, created: 1}];
    apiGet.mockImplementation(async path => path.endsWith("/prompts") ? {prompts: [{name: "chattft/assistants/chat", versions: [1, 2]}]} : path === "/api/specs" ? {assistants: [{name: "chat"}]} : active);
    apiPost.mockResolvedValue(saved());
    await open(); fireEvent.click(screen.getByRole("button", {name: "Import from Langfuse"}));
    await screen.findByRole("option", {name: "chattft/assistants/chat"});
    fireEvent.click(screen.getByRole("button", {name: "Import as draft"}));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/api/specs/assistants/chat/import", expect.objectContaining({version: 2})));
    await waitFor(() => expect(screen.getByRole("button", {name: "Restore revision"})).toBeEnabled());
    fireEvent.click(screen.getByRole("button", {name: "Restore revision"}));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/api/specs/assistants/chat/restore", expect.objectContaining({revision: "old-revision"})));
  });
});
