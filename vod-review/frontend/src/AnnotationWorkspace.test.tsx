import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AnnotationWorkspace from "./AnnotationWorkspace";
import type { AnnotationProject, AnnotationTask, VideoRecord } from "./api";

const tasks: AnnotationTask[] = [
  { key: "unit_segmentation", display_name: "Unit detection", kind: "detection", enabled: true, labels: [{ id: "unit", display_name: "Unit" }] },
  { key: "text_detection", display_name: "Text detection", kind: "detection", enabled: true, labels: [{ id: "text", display_name: "Text" }] },
  { key: "round_classifier", display_name: "Round classification", kind: "classification", enabled: true, labels: [{ id: "11", display_name: "11" }] },
  { key: "unit_id", display_name: "Unit identification", kind: "classification", enabled: false, labels: [] },
  { key: "augment_classifier", display_name: "Augment templates", kind: "template", enabled: true, labels: [] },
];

const video: VideoRecord = {
  id: "video-id",
  original_name: "sample.mp4",
  mime_type: "video/mp4",
  duration: 20,
  width: 100,
  height: 80,
  created_at: "now",
  box: null,
  current_job: null,
  active_job: null,
  latest_job: null,
};

function response(payload: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => payload } as Response;
}

afterEach(() => vi.restoreAllMocks());

describe("AnnotationWorkspace", () => {
  it("shows setup for enabled tasks and configuration guidance for an empty unit catalog", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/api/annotation-tasks")) return response(tasks);
      return response(null);
    });
    render(<AnnotationWorkspace video={video} onError={vi.fn()} />);
    expect(await screen.findByText(/Set up unit detection/i)).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByRole("tab", { name: /Unit identification/i }), { button: 0, ctrlKey: false });
    expect(await screen.findByText(/ready for its label catalog/i)).toBeInTheDocument();
    expect(screen.getByText(/config\/annotation_tasks.json/i)).toBeInTheDocument();
  });

  it("persists a negative detection frame and advances the queue", async () => {
    const initial: AnnotationProject = {
      id: "project-id", video_id: video.id, task: "unit_segmentation", kind: "detection", split: "train",
      sample_interval_seconds: 5, locked: false, created_at: "now", updated_at: "now",
      counts: { saved: 0, skipped: 0, pending: 2 },
      queue: [
        { sample_index: 1, requested_timestamp_seconds: 5, actual_timestamp_seconds: null, status: "pending", items: [] },
        { sample_index: 2, requested_timestamp_seconds: 10, actual_timestamp_seconds: null, status: "pending", items: [] },
      ],
    };
    const saved: AnnotationProject = {
      ...initial, locked: true, counts: { saved: 1, skipped: 0, pending: 1 },
      queue: [
        { ...initial.queue[0], actual_timestamp_seconds: 5.02, status: "saved" },
        initial.queue[1],
      ],
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, options) => {
      const path = String(input);
      if (path.endsWith("/api/annotation-tasks")) return response(tasks);
      if (options?.method === "PUT" && path.endsWith("/frames/1")) return response(saved);
      return response(initial);
    });
    render(<AnnotationWorkspace video={video} onError={vi.fn()} />);
    const save = await screen.findByRole("button", { name: /Save empty & next/i });
    fireEvent.click(save);
    await waitFor(() => expect(screen.getByText("Frame 2 of 2")).toBeInTheDocument());
    const put = fetchMock.mock.calls.find(([input, options]) => String(input).endsWith("/frames/1") && options?.method === "PUT");
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ kind: "detection", status: "saved", boxes: [] });
  });

  it("clears boxes between frames by default and carries them when enabled", async () => {
    const project: AnnotationProject = {
      id: "project-id", video_id: video.id, task: "unit_segmentation", kind: "detection", split: "train",
      sample_interval_seconds: 5, locked: false, created_at: "now", updated_at: "now",
      counts: { saved: 0, skipped: 0, pending: 2 },
      queue: [
        { sample_index: 1, requested_timestamp_seconds: 5, actual_timestamp_seconds: null, status: "pending", items: [{ x: 0.1, y: 0.2, width: 0.3, height: 0.4, label_id: "unit" }] },
        { sample_index: 2, requested_timestamp_seconds: 10, actual_timestamp_seconds: null, status: "pending", items: [] },
      ],
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => String(input).endsWith("/api/annotation-tasks") ? response(tasks) : response(structuredClone(project)));
    const view = within(render(<AnnotationWorkspace video={video} onError={vi.fn()} />).container);

    const toggle = await view.findByRole("checkbox", { name: /Keep boxes/i });
    expect(toggle).not.toBeChecked();
    fireEvent.click(view.getByRole("button", { name: /Next frame/i }));
    fireEvent.click(view.getByRole("button", { name: /Previous frame/i }));
    expect(view.getByRole("heading", { name: "1 annotation" })).toBeInTheDocument();
    fireEvent.click(view.getByRole("button", { name: /Next frame/i }));
    expect(view.getByRole("heading", { name: "0 annotations" })).toBeInTheDocument();
    fireEvent.click(view.getByRole("button", { name: /Previous frame/i }));
    fireEvent.click(toggle);
    fireEvent.click(view.getByRole("button", { name: /Next frame/i }));
    expect(view.getByRole("heading", { name: "1 annotation" })).toBeInTheDocument();
  });

  it("saves the current frame as a named augment template", async () => {
    const initial: AnnotationProject = {
      id: "augment-project", video_id: video.id, task: "augment_classifier", kind: "template", split: "train",
      sample_interval_seconds: 5, locked: false, created_at: "now", updated_at: "now",
      counts: { saved: 0, skipped: 0, pending: 2 },
      queue: [
        { sample_index: 1, requested_timestamp_seconds: 5, actual_timestamp_seconds: null, status: "pending", items: [] },
        { sample_index: 2, requested_timestamp_seconds: 10, actual_timestamp_seconds: null, status: "pending", items: [] },
      ],
    };
    const saved: AnnotationProject = {
      ...initial, locked: true, counts: { saved: 1, skipped: 0, pending: 1 },
      queue: [
        { ...initial.queue[0], actual_timestamp_seconds: 5.02, status: "saved", items: [{ label_id: "jeweled_lotus", x: 0, y: 0, width: 1, height: 1 }] },
        initial.queue[1],
      ],
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, options) => {
      const path = String(input);
      if (path.endsWith("/api/annotation-tasks")) return response(tasks);
      if (options?.method === "PUT" && path.endsWith("/augment_classifier/frames/1")) return response(saved);
      if (path.endsWith("/augment_classifier")) return response(initial);
      return response(null);
    });
    const view = within(render(<AnnotationWorkspace video={video} onError={vi.fn()} />).container);
    fireEvent.mouseDown(await view.findByRole("tab", { name: /Augment templates/i }), { button: 0, ctrlKey: false });
    const label = await view.findByRole("textbox", { name: /Augment label/i });
    fireEvent.change(label, { target: { value: "jeweled_lotus" } });
    fireEvent.click(view.getByRole("button", { name: /Save template & next/i }));

    await waitFor(() => expect(view.getByText("Frame 2 of 2")).toBeInTheDocument());
    const put = fetchMock.mock.calls.find(([input, options]) => String(input).endsWith("/augment_classifier/frames/1") && options?.method === "PUT");
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ kind: "template", status: "saved", label_id: "jeweled_lotus" });
  });
});
