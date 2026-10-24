import { API_BASE, type SampleResult } from "./api";

export type ViewingEntry = {
  id: string; name: string; source: string; duration: number; source_id: string | null;
  start: number; local_available: boolean; video_id: string | null; content_url: string | null;
  has_transcript: boolean; has_transitions: boolean;
};
export type ViewingDetail = ViewingEntry & {
  transcript: { transcript: string; language: string | null; segments: { start: number; end: number; text: string }[] | null } | null;
  transcript_error: string | null; transitions: SampleResult[]; manifest_url: string | null;
};

/** Read existing artifacts through a GET-only interface. */
async function read<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}/api/viewing-library${path}`, { signal });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : "Could not load the library. Try refreshing.");
  }
  return response.json();
}
export const listViewingMedia = (signal: AbortSignal) => read<ViewingEntry[]>("", signal);
export const getViewingMedia = (id: string, signal: AbortSignal) => read<ViewingDetail>(`/${encodeURIComponent(id)}`, signal);
