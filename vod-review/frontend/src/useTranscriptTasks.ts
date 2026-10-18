import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, type TranscriptionTask } from "./api";

export type Segment = { id: string; start: number; end: number; text: string };
export type TranscriptSource = TranscriptionTask & { title?: string; segments: Segment[] | null };
export type Evidence = { start_segment_id: string; end_segment_id: string; start_seconds: number; end_seconds: number; excerpt: string };
export type MomentsOutput = { moments: { title: string; explanation: string; evidence: Evidence[] }[] };
export type TaskRun = { id: string; task_name: string; status: "queued" | "running" | "completed" | "failed"; output: string | MomentsOutput | null; error: string | null };
export type TaskState = { name: string; active_run: TaskRun | null; latest_run: TaskRun | null; successful_run: TaskRun | null };
export type TaskDefinition = { name: string; label: string; available: boolean; reason: string | null };
type Data = { identity: string; source: TranscriptSource | null; tasks: TaskState[]; definitions: TaskDefinition[]; error: string | null };

async function request<T>(path: string, signal?: AbortSignal, body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { signal, ...(body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}) });
  const payload = await response.json();
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "Could not load transcript tools");
  return payload;
}

/** Keep browser requests and task polling scoped to both video and transcript identity. */
export function useTranscriptTasks(transcriptionId?: string, videoId?: string) {
  const identity = `${videoId ?? "audio"}:${transcriptionId ?? "none"}`;
  const current = useRef(identity);
  current.current = identity;
  const [data, setData] = useState<Data>({ identity, source: null, tasks: [], definitions: [], error: null });
  const [starting, setStarting] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const reload = useRef<() => Promise<void>>(async () => {});
  const requests = useRef(new Set<AbortController>());

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    let busy = false;
    let refreshPending = false;
    setStarting({});
    setErrors({});
    setData({ identity, source: null, tasks: [], definitions: [], error: null });
    const refresh = async () => {
      if (controller.signal.aborted) return;
      if (busy) { refreshPending = true; return; }
      busy = true;
      window.clearTimeout(timer);
      try {
        const [catalogue, source, state] = await Promise.all([
          request<{ tasks: TaskDefinition[] }>("/api/transcript-tasks", controller.signal),
          transcriptionId ? request<TranscriptSource>(`/api/transcriptions/${transcriptionId}?include_segments=true`, controller.signal) : Promise.resolve(null),
          transcriptionId ? request<{ tasks: TaskState[] }>(`/api/transcriptions/${transcriptionId}/tasks`, controller.signal) : Promise.resolve({ tasks: [] }),
        ]);
        if (current.current !== identity || controller.signal.aborted) return;
        setData({ identity, source, tasks: state.tasks ?? [], definitions: catalogue.tasks ?? [], error: null });
        if (state.tasks?.some(task => task.active_run)) timer = window.setTimeout(refresh, 2000);
      } catch (reason) {
        if (!controller.signal.aborted && current.current === identity) {
          setData(previous => ({ ...previous, error: reason instanceof Error ? reason.message : "Could not refresh transcript tools" }));
          timer = window.setTimeout(refresh, 2000);
        }
      } finally {
        busy = false;
        if (refreshPending && !controller.signal.aborted) {
          refreshPending = false;
          window.clearTimeout(timer);
          timer = window.setTimeout(refresh, 0);
        }
      }
    };
    reload.current = refresh;
    void refresh();
    const focus = () => void refresh();
    window.addEventListener("focus", focus);
    return () => {
      controller.abort(); window.clearTimeout(timer); window.removeEventListener("focus", focus);
      for (const pending of requests.current) pending.abort();
      requests.current.clear();
    };
  }, [identity, transcriptionId]);

  const start = useCallback(async (name: string, rerun = false) => {
    if (!transcriptionId) return;
    const controller = new AbortController();
    requests.current.add(controller);
    setStarting(previous => ({ ...previous, [name]: true }));
    setErrors(previous => ({ ...previous, [name]: "" }));
    try {
      await request(`/api/transcriptions/${transcriptionId}/tasks/${name}`, controller.signal, { rerun });
      if (current.current === identity) await reload.current();
    } catch (reason) {
      if (!controller.signal.aborted && current.current === identity) setErrors(previous => ({ ...previous, [name]: reason instanceof Error ? reason.message : "Could not start task" }));
    } finally {
      requests.current.delete(controller);
      if (current.current === identity) setStarting(previous => ({ ...previous, [name]: false }));
    }
  }, [identity, transcriptionId]);
  return { ...(data.identity === identity ? data : { source: null, tasks: [], definitions: [], error: null }), start, starting, errors };
}
