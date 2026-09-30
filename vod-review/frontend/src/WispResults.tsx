import { Button as UiButton } from "@/components/ui/button";
import { useEffect, useState } from "react";
import { getWispDetections, WispPage } from "./api";

export default function WispResults({ videoId, jobId, onSeek }: { videoId: string; jobId?: string; onSeek: (time: number) => void }) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<WispPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    if (jobId) getWispDetections(videoId, jobId, page).then((result) => {
      if (!cancelled) setData(result);
    }).catch((reason: unknown) => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : "Could not load detections");
    });
    return () => { cancelled = true; };
  }, [videoId, jobId, page, retry]);
  const current = data?.page ?? page;
  const pages = data?.pages ?? 1;
  const numbers = Array.from(new Set([1, pages, current - 1, current, current + 1])).filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
  return <div className="results-section">
    <div className="results-heading"><div><p className="eyebrow">WISP DETECTIONS</p><h3>{data ? `${data.total.toLocaleString()} matching frames` : "Detected timestamps"}</h3></div></div>
    {!jobId ? <div className="results-empty">Draw and save a box, then process the video to detect wisps.</div> : error ? <div role="alert">{error} <UiButton variant="outline" onClick={() => setRetry((n) => n + 1)}>Retry</UiButton></div> : !data ? <div role="status">Loading timestamps…</div> : <>
      {data.total === 0 ? <div className="results-empty">No wisps detected.</div> : <div className="results-list">{data.results.map((hit) => <UiButton variant="outline" className="result-row h-auto whitespace-normal justify-start" key={hit.frame_index} onClick={() => onSeek(hit.timestamp_seconds)} aria-label={`Jump to wisp at ${hit.timestamp_seconds.toFixed(3)} seconds`}>
        <span className="result-class-badge">{Math.floor(hit.timestamp_seconds / 60)}:{(hit.timestamp_seconds % 60).toFixed(3).padStart(6, "0")}</span><span className="result-confidence">Frame {hit.frame_index + 1}</span><span className="result-jump">Jump</span>
      </UiButton>)}</div>}
      {data.total > 0 && <nav className="wisp-pagination" aria-label="Wisp timestamp pages">
        <UiButton variant="outline" aria-label="Previous page" disabled={current === 1} onClick={() => setPage(current - 1)}>«</UiButton>
        {numbers.map((n, i) => <span key={n}>{i > 0 && n - numbers[i - 1] > 1 && <span aria-hidden="true">…</span>}<UiButton variant={n === current ? "secondary" : "outline"} aria-label={`Page ${n}`} aria-current={n === current ? "page" : undefined} onClick={() => setPage(n)}>{n}</UiButton></span>)}
        <UiButton variant="outline" aria-label="Next page" disabled={current === pages} onClick={() => setPage(current + 1)}>»</UiButton>
        <span className="wisp-page-summary">Page {current} of {pages} · 25 per page</span>
      </nav>}
    </>}
  </div>;
}
