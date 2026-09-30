import { Input as UiInput } from "@/components/ui/input";
import { Button as UiButton } from "@/components/ui/button";
import { useEffect, useRef, useState } from "react";

import { getWispFrame, WispFrame } from "./api";

export default function WispFrameReview({ videoId, jobId, time, onSeek, paused = true }: { videoId: string; jobId: string; time: number; onSeek: (time: number) => void; paused?: boolean }) {
  const [step, setStep] = useState("1");
  const [frame, setFrame] = useState<WispFrame | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const requestId = useRef(0);
  const count = Number(step);
  const valid = Number.isSafeInteger(count) && count > 0;

  async function load(offset: number, seek = false) {
    const id = ++requestId.current;
    setBusy(true);
    setFrame(null);
    setError("");
    try {
      const data = await getWispFrame(videoId, jobId, time, offset);
      if (id !== requestId.current) return;
      setFrame(data);
      if (seek) onSeek(data.timestamp);
    } catch (reason) {
      if (id === requestId.current) setError(reason instanceof Error ? reason.message : "Could not load frame confidence");
    } finally {
      if (id === requestId.current) setBusy(false);
    }
  }

  useEffect(() => {
    if (!paused) {
      requestId.current++;
      setFrame(null);
      setBusy(false);
      setError("");
      return;
    }
    void load(0);
    return () => { requestId.current++; };
  }, [time, videoId, jobId, paused]);

  if (!paused) return <p className="wisp-placeholder-note">Pause the video to review frame confidence and OCR text.</p>;

  return <div className="workspace-actions" aria-label="Frame review">
    <label className="batch-size-control">Frames to skip <UiInput aria-label="Frames to skip" type="number" min="1" step="1" value={step} onChange={(event) => setStep(event.target.value)} /></label>
    <UiButton variant="outline" className="secondary-button" aria-label="Skip frames backward" disabled={!valid || busy || !frame || frame.sample_index === 0} onClick={() => void load(-count, true)}>←</UiButton>
    <UiButton variant="outline" className="secondary-button" aria-label="Skip frames forward" disabled={!valid || busy || !frame || frame.sample_index === frame.total - 1} onClick={() => void load(count, true)}>→</UiButton>
    <span aria-live="polite">{busy ? "Loading confidence…" : frame ? `Analyzed frame ${frame.sample_index + 1} of ${frame.total} · ${frame.timestamp.toFixed(3)}s · Confidence: ${(frame.confidence * 100).toFixed(2)}%` : error}</span>
    <small>Steps count analyzed frames. Confidence belongs to the nearest analyzed timestamp shown above.</small>
    {!busy && frame && <div aria-label="Frame OCR text" style={{ width: "100%", whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>OCR text: {frame.ocr_text == null ? "Not recorded — rerun analysis to capture text." : frame.ocr_text === "" ? "No text recognized." : `“${frame.ocr_text}”`}</div>}
  </div>;
}
