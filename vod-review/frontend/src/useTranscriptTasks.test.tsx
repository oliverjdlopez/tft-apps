import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useTranscriptTasks } from "./useTranscriptTasks";
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

it("polls only active work, stops after completion, and refreshes on focus", async () => {
  let active = true;
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async input => {
    const url = String(input);
    const payload = url.endsWith('/api/transcript-tasks') ? { tasks: [] } : url.endsWith('/tasks') ? { tasks: [{ name: 'find_key_moments', active_run: active ? { status: 'running' } : null, latest_run: null, successful_run: null }] } : { task_id: 'speech', transcript: 'Source', segments: [] };
    return { ok: true, json: async () => payload } as Response;
  });
  const { result } = renderHook(() => useTranscriptTasks('speech', 'video'));
  await waitFor(() => expect(result.current.tasks[0]?.active_run).toBeTruthy());
  vi.useFakeTimers();
  // Refresh once under fake timers so the next active poll uses the controlled clock.
  await act(async () => { window.dispatchEvent(new Event('focus')); });
  const beforePoll = fetch.mock.calls.length;
  active = false;
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(fetch.mock.calls.length).toBeGreaterThan(beforePoll);
  expect(result.current.tasks[0]?.active_run).toBeNull();
  const calls = fetch.mock.calls.length;
  await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
  expect(fetch).toHaveBeenCalledTimes(calls);
  await act(async () => { window.dispatchEvent(new Event('focus')); });
  expect(fetch.mock.calls.length).toBeGreaterThan(calls);
});
