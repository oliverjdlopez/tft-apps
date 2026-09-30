import { useConfirmation } from "@/components/shared/confirmation";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Progress } from "@/components/ui/progress";
import { Button as UiButton } from "@/components/ui/button";
import { NativeSelect as UiNativeSelect } from "@/components/ui/native-select";
import { Input as UiInput } from "@/components/ui/input";
import { Checkbox as UiCheckbox } from "@/components/ui/checkbox";
import { KeyboardEvent as ReactKeyboardEvent, PointerEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Check, Crosshair, Database, LoaderCircle, RotateCcw, Save, SkipForward, Trash2, TriangleAlert, X } from "lucide-react";
import {
  AnnotationItem,
  AnnotationProject,
  AnnotationTask,
  DatasetSplit,
  deleteAnnotationFrame,
  getAnnotationProject,
  listAnnotationTasks,
  putAnnotationFrame,
  putAnnotationProject,
  resetAnnotationProject,
  TaskKey,
  VideoRecord,
} from "./api";
import { useOptimizedPlayback } from "./useOptimizedPlayback";

type Point = { x: number; y: number };
type DraftItem = AnnotationItem & { clientId: string };

const TASK_ORDER: TaskKey[] = ["unit_segmentation", "text_detection", "round_classifier", "unit_id", "augment_classifier"];

function formatTime(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(whole / 60);
  return `${minutes}:${String(whole % 60).padStart(2, "0")}`;
}

function isTypingTarget(target: EventTarget | null): boolean {
  return target instanceof HTMLInputElement || target instanceof HTMLSelectElement || target instanceof HTMLTextAreaElement;
}

export default function AnnotationWorkspace({ video, onError }: { video: VideoRecord; onError: (message: string) => void }) {
  const { confirm, confirmation } = useConfirmation();
  const [tasks, setTasks] = useState<AnnotationTask[]>([]);
  const [taskKey, setTaskKey] = useState<TaskKey>("unit_segmentation");
  const [project, setProject] = useState<AnnotationProject | null>(null);
  const [split, setSplit] = useState<DatasetSplit>("train");
  const [interval, setInterval] = useState(5);
  const [queuePosition, setQueuePosition] = useState(0);
  const [draftItems, setDraftItems] = useState<DraftItem[]>([]);
  const [activeLabel, setActiveLabel] = useState("");
  const [templateLabel, setTemplateLabel] = useState("");
  const [selectedItem, setSelectedItem] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [keepBoxes, setKeepBoxes] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const playback = useOptimizedPlayback(video.id, videoRef);
  const stageRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drawingStart = useRef<Point | null>(null);
  const carriedItems = useRef<DraftItem[] | null>(null);
  const [preview, setPreview] = useState<AnnotationItem | null>(null);

  const activeTask = useMemo(() => tasks.find((task) => task.key === taskKey) ?? null, [tasks, taskKey]);
  const current = project?.queue[queuePosition] ?? null;

  const loadProject = useCallback(async (key: TaskKey) => {
    setLoading(true);
    try {
      const fresh = await getAnnotationProject(video.id, key);
      setProject(fresh);
      setSplit(fresh?.split ?? "train");
      setInterval(fresh?.sample_interval_seconds ?? 5);
      const firstPending = fresh?.queue.findIndex((item) => item.status === "pending") ?? -1;
      setQueuePosition(firstPending >= 0 ? firstPending : 0);
    } catch (reason: unknown) {
      onError(reason instanceof Error ? reason.message : "Could not load annotation project");
    } finally {
      setLoading(false);
    }
  }, [video.id, onError]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listAnnotationTasks()
      .then((definitions) => {
        if (cancelled) return;
        setTasks(definitions);
        const selected = definitions.find((task) => task.key === taskKey);
        setActiveLabel(selected?.labels[0]?.id ?? "");
        return loadProject(taskKey);
      })
      .catch((reason: unknown) => !cancelled && onError(reason instanceof Error ? reason.message : "Could not load annotation tasks"))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [video.id, loadProject]);

  useEffect(() => {
    const definition = tasks.find((task) => task.key === taskKey);
    setActiveLabel(definition?.labels[0]?.id ?? "");
    setTemplateLabel("");
    setDraftItems([]);
    setSelectedItem(null);
    setPreview(null);
    void loadProject(taskKey);
  }, [taskKey]); // loadProject is stable for a video; tasks only supplies the selected label.

  useEffect(() => {
    if (!current) {
      setDraftItems([]);
      return;
    }
    const carried = carriedItems.current;
    carriedItems.current = null;
    if (taskKey === "augment_classifier") {
      setDraftItems([]);
      if (current.items[0]?.label_id) setTemplateLabel(current.items[0].label_id);
    } else {
      setDraftItems(carried ?? current.items.map((item, index) => ({ ...item, clientId: `${current.sample_index}-${index}` })));
    }
    setSelectedItem(null);
    setPreview(null);
    const timestamp = current.actual_timestamp_seconds ?? current.requested_timestamp_seconds;
    if (videoRef.current) videoRef.current.currentTime = timestamp;
  }, [current?.sample_index, current?.status, current?.actual_timestamp_seconds]);

  const redraw = useCallback(() => {
    const canvas = canvasRef.current;
    const stage = stageRef.current;
    if (!canvas || !stage) return;
    const rect = stage.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(rect.width * ratio));
    canvas.height = Math.max(1, Math.floor(rect.height * ratio));
    canvas.style.width = `${rect.width}px`;
    canvas.style.height = `${rect.height}px`;
    const context = canvas.getContext("2d");
    if (!context) return;
    context.scale(ratio, ratio);
    context.clearRect(0, 0, rect.width, rect.height);
    const entries = [...draftItems, ...(preview ? [{ ...preview, clientId: "preview" }] : [])];
    entries.forEach((item, index) => {
      const x = item.x * rect.width;
      const y = item.y * rect.height;
      const width = item.width * rect.width;
      const height = item.height * rect.height;
      const selected = index === selectedItem;
      context.fillStyle = selected ? "rgba(255, 184, 107, .16)" : "rgba(89, 224, 184, .13)";
      context.fillRect(x, y, width, height);
      context.strokeStyle = selected ? "#ffb86b" : "#59e0b8";
      context.lineWidth = selected ? 3 : 2;
      context.strokeRect(x, y, width, height);
      const label = item.label_id || "UNIT";
      context.font = "600 11px ui-monospace, SFMono-Regular, Menlo, monospace";
      const labelWidth = Math.max(34, context.measureText(label).width + 12);
      context.fillStyle = selected ? "#ffb86b" : "#59e0b8";
      context.fillRect(x, Math.max(0, y - 19), labelWidth, 19);
      context.fillStyle = "#07101c";
      context.fillText(label, x + 6, Math.max(13, y - 6));
    });
  }, [draftItems, preview, selectedItem]);

  useEffect(() => {
    redraw();
    const observer = new ResizeObserver(redraw);
    if (stageRef.current) observer.observe(stageRef.current);
    return () => observer.disconnect();
  }, [redraw]);

  const pointerPoint = (event: PointerEvent<HTMLCanvasElement>): Point => {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    };
  };

  const pointerDown = (event: PointerEvent<HTMLCanvasElement>) => {
    if (!project || working || !current || activeTask?.kind === "template") return;
    event.currentTarget.setPointerCapture(event.pointerId);
    drawingStart.current = pointerPoint(event);
    setSelectedItem(null);
  };

  const pointerMove = (event: PointerEvent<HTMLCanvasElement>) => {
    if (!drawingStart.current) return;
    const point = pointerPoint(event);
    const start = drawingStart.current;
    setPreview({
      x: Math.min(start.x, point.x),
      y: Math.min(start.y, point.y),
      width: Math.abs(start.x - point.x),
      height: Math.abs(start.y - point.y),
      label_id: activeTask?.kind === "classification" ? activeLabel : "unit",
    });
  };

  const pointerUp = (event: PointerEvent<HTMLCanvasElement>) => {
    const start = drawingStart.current;
    drawingStart.current = null;
    if (!start) {
      setPreview(null);
      return;
    }
    const point = pointerPoint(event);
    const completed: AnnotationItem = {
      x: Math.min(start.x, point.x),
      y: Math.min(start.y, point.y),
      width: Math.abs(start.x - point.x),
      height: Math.abs(start.y - point.y),
      label_id: activeTask?.kind === "classification" ? activeLabel : "unit",
    };
    if (completed.width < 0.005 || completed.height < 0.005) {
      setPreview(null);
      return;
    }
    const item = { ...completed, clientId: crypto.randomUUID() };
    setDraftItems((currentItems) => taskKey === "round_classifier" ? [item] : [...currentItems, item]);
    setPreview(null);
  };

  const createProject = async () => {
    setWorking(true);
    try {
      const fresh = await putAnnotationProject(video.id, taskKey, split, interval);
      setProject(fresh);
      setQueuePosition(0);
    } catch (reason: unknown) {
      onError(reason instanceof Error ? reason.message : "Could not create annotation project");
    } finally {
      setWorking(false);
    }
  };

  const advance = useCallback((direction: number) => {
    if (!project) return;
    carriedItems.current = keepBoxes && activeTask?.kind !== "template" ? draftItems.map((item) => ({ ...item, clientId: crypto.randomUUID() })) : null;
    setQueuePosition((position) => Math.max(0, Math.min(project.queue.length - 1, position + direction)));
  }, [project, keepBoxes, draftItems, activeTask?.kind]);

  const applyFreshProject = (fresh: AnnotationProject, advanceAfter: boolean) => {
    carriedItems.current = keepBoxes && activeTask?.kind !== "template" ? draftItems.map((item) => ({ ...item, clientId: crypto.randomUUID() })) : [];
    setProject(fresh);
    setDraftItems([]);
    setSelectedItem(null);
    if (advanceAfter) {
      const nextPending = fresh.queue.findIndex((item, index) => index > queuePosition && item.status === "pending");
      setQueuePosition(nextPending >= 0 ? nextPending : Math.min(queuePosition + 1, fresh.queue.length - 1));
    }
  };

  const saveCurrent = useCallback(async () => {
    if (!project || !current || !activeTask) return;
    const normalizedTemplateLabel = templateLabel.trim();
    if (activeTask.kind === "template" && !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(normalizedTemplateLabel)) {
      onError("Enter a template label using letters, numbers, dots, underscores, or hyphens.");
      return;
    }
    if (activeTask.kind === "classification" && draftItems.length === 0) {
      onError(`Draw ${taskKey === "round_classifier" ? "one crop" : "at least one unit crop"} before saving.`);
      return;
    }
    if (taskKey === "round_classifier" && draftItems.length !== 1) {
      onError("Round classification requires exactly one crop.");
      return;
    }
    if (activeTask.kind === "classification" && draftItems.some((item) => !item.label_id)) {
      onError("Choose a label for every crop.");
      return;
    }
    setWorking(true);
    try {
      const geometry = draftItems.map(({ x, y, width, height }) => ({ x, y, width, height }));
      const payload = activeTask.kind === "detection"
        ? { kind: "detection" as const, status: "saved" as const, boxes: geometry }
        : activeTask.kind === "template"
          ? { kind: "template" as const, status: "saved" as const, label_id: normalizedTemplateLabel }
        : { kind: "classification" as const, status: "saved" as const, crops: draftItems.map(({ x, y, width, height, label_id }) => ({ x, y, width, height, label_id: label_id! })) };
      const fresh = await putAnnotationFrame(video.id, taskKey, current.sample_index, payload);
      applyFreshProject(fresh, true);
    } catch (reason: unknown) {
      onError(reason instanceof Error ? reason.message : "Could not save annotation");
    } finally {
      setWorking(false);
    }
  }, [project, current, activeTask, draftItems, taskKey, video.id, onError, queuePosition, templateLabel]);

  const skipCurrent = useCallback(async () => {
    if (!project || !current || !activeTask) return;
    setWorking(true);
    try {
      const payload = activeTask.kind === "detection"
        ? { kind: "detection" as const, status: "skipped" as const, boxes: [] }
        : activeTask.kind === "template"
          ? { kind: "template" as const, status: "skipped" as const }
        : { kind: "classification" as const, status: "skipped" as const, crops: [] };
      const fresh = await putAnnotationFrame(video.id, taskKey, current.sample_index, payload);
      applyFreshProject(fresh, true);
    } catch (reason: unknown) {
      onError(reason instanceof Error ? reason.message : "Could not skip frame");
    } finally {
      setWorking(false);
    }
  }, [project, current, activeTask, video.id, taskKey, onError, queuePosition]);

  const deleteCurrent = async () => {
    if (!project || !current || current.status === "pending") return;
    setWorking(true);
    try {
      const fresh = await deleteAnnotationFrame(video.id, taskKey, current.sample_index);
      setProject(fresh);
      setDraftItems([]);
    } catch (reason: unknown) {
      onError(reason instanceof Error ? reason.message : "Could not remove annotation");
    } finally {
      setWorking(false);
    }
  };

  const resetProject = async () => {
    if (!project || !await confirm(`Reset all ${activeTask?.display_name ?? taskKey} annotations for this video? Saved dataset files will be removed.`)) return;
    setWorking(true);
    try {
      await resetAnnotationProject(video.id, taskKey);
      setProject(null);
      setDraftItems([]);
      setQueuePosition(0);
    } catch (reason: unknown) {
      onError(reason instanceof Error ? reason.message : "Could not reset annotation project");
    } finally {
      setWorking(false);
    }
  };

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (document.querySelector('[role="alertdialog"]') || isTypingTarget(event.target) || !project || working) return;
      if (event.key === "ArrowLeft") { event.preventDefault(); advance(-1); }
      if (event.key === "ArrowRight") { event.preventDefault(); advance(1); }
      if (event.key === "Enter") { event.preventDefault(); void saveCurrent(); }
      if (event.key.toLowerCase() === "s") { event.preventDefault(); void skipCurrent(); }
      if (event.key === "Escape") { setPreview(null); setSelectedItem(null); drawingStart.current = null; }
      if ((event.key === "Delete" || event.key === "Backspace") && draftItems.length) {
        event.preventDefault();
        const target = selectedItem ?? draftItems.length - 1;
        setDraftItems((items) => items.filter((_, index) => index !== target));
        setSelectedItem(null);
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [project, working, advance, saveCurrent, skipCurrent, draftItems.length, selectedItem]);

  const setItemLabel = (index: number, labelId: string) => {
    setDraftItems((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, label_id: labelId } : item));
  };

  const handleLabelKey = (event: ReactKeyboardEvent<HTMLSelectElement>) => {
    if (event.key === "Enter") event.stopPropagation();
  };

  if (loading && tasks.length === 0) return <div className="annotation-loading"><LoaderCircle className="spin" size={20} /> Loading annotation tools</div>;

  return <div className="annotator">{confirmation}
    <div className="analyzer-heading annotation-heading">
      <div><p className="eyebrow">ANNOTATION WORKSPACE</p><h2>{video.original_name}</h2></div>
      {project && <div className="dataset-badge"><Database size={13} /> {activeTask?.kind === "template" ? "template library" : `${project.split} dataset`}</div>}
    </div>

    <Tabs value={taskKey} onValueChange={(value) => setTaskKey(value as typeof taskKey)}>
      <TabsList aria-label="Annotation task" className="h-auto max-w-full flex-wrap justify-start">
        {TASK_ORDER.map((key) => {
          const definition = tasks.find((task) => task.key === key);
          return <TabsTrigger key={key} id={`annotation-${key}`} aria-controls="annotation-panel" value={key} className="flex-col gap-0.5">
            <span>{definition?.display_name ?? key}</span>
            {!definition?.enabled && <small>Needs labels</small>}
          </TabsTrigger>;
        })}
      </TabsList>
    </Tabs>

    <div role="tabpanel" id="annotation-panel" aria-labelledby={`annotation-${taskKey}`} tabIndex={0}>
    {activeTask && !activeTask.enabled ? <div className="annotation-disabled">
      <TriangleAlert size={20} />
      <div><strong>{activeTask.display_name} is ready for its label catalog.</strong><span>Add labels to <code>config/annotation_tasks.json</code> and restart the backend. The full annotation flow will enable automatically.</span></div>
    </div> : !project ? <div className="annotation-setup">
      <div><p className="eyebrow">NEW DATASET PASS</p><h3>Set up {activeTask?.display_name.toLowerCase()}</h3><p>{activeTask?.kind === "template" ? "Choose how often to sample the video. Each selected frame can be saved directly as a named augment template." : "This video can be reused for every task. These settings apply only to this task and lock after the first save or skip."}</p></div>
      <div className="setup-controls">
        {activeTask?.kind !== "template" && <label><span>Dataset split</span><UiNativeSelect value={split} onChange={(event) => setSplit(event.target.value as DatasetSplit)}><option value="train">Training</option><option value="val">Validation</option></UiNativeSelect></label>}
        <label><span>Sample every</span><div><UiInput type="number" min="0.1" max="3600" step="0.1" value={interval} onChange={(event) => setInterval(Math.max(0.1, Math.min(3600, Number(event.target.value) || 0.1)))} /><small>seconds</small></div></label>
        <UiButton variant="default" className="primary-button" disabled={working} onClick={createProject}>{working ? <LoaderCircle className="spin" size={16} /> : <Crosshair size={16} />} Start annotating</UiButton>
      </div>
    </div> : project.queue.length === 0 ? <div className="annotation-disabled"><TriangleAlert size={20} /><div><strong>No frames fit this interval.</strong><span>Reset the project and choose an interval shorter than the video.</span></div><UiButton variant="outline" className="secondary-button" onClick={resetProject}>Reset project</UiButton></div> : <>
      <div className="annotation-progress">
        <div className="progress-summary"><span><Check size={13} /> {project.counts.saved} saved</span><span>{project.counts.skipped} skipped</span><span>{project.counts.pending} pending</span></div>
        <Progress aria-label="Annotation progress" value={((project.counts.saved + project.counts.skipped) / project.queue.length) * 100} />
        <UiButton variant="outline" className="reset-link" onClick={resetProject} disabled={working}><RotateCcw size={12} /> Reset project</UiButton>
      </div>

      <div className="video-stage-wrap annotation-stage-wrap">
        <div className="video-stage annotation-stage" ref={stageRef} style={{ aspectRatio: `${video.width} / ${video.height}` }}>
          <video ref={videoRef} playsInline preload="auto" onLoadedMetadata={(event) => { if (current) event.currentTarget.currentTime = current.actual_timestamp_seconds ?? current.requested_timestamp_seconds; }} />
          {playback.status === "preparing" && <div className="playback-status"><LoaderCircle className="spin" size={18} /><strong>Preparing fast playback…</strong><span>This one-time step makes frame seeking responsive.</span></div>}
          {playback.status === "failed" && <div className="playback-warning"><span>{playback.error ?? "Optimized playback is unavailable."}</span><UiButton variant="outline" type="button" onClick={() => void playback.retry()}>Retry</UiButton></div>}
          <canvas ref={canvasRef} className={`box-canvas ${activeTask?.kind === "template" ? "" : "is-editing"}`} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={() => { drawingStart.current = null; setPreview(null); }} aria-label={activeTask?.kind === "template" ? "Augment template frame" : "Draw annotation boxes on the current frame"} />
          {activeTask?.kind === "template" ? <div className="canvas-hint template-hint"><Save size={20} /><strong>Save this full frame as a template</strong><small>Enter an augment label below</small></div> : draftItems.length === 0 && !preview && <div className="canvas-hint"><span>+</span><strong>{taskKey === "text_detection" ? "Draw every visible text region" : activeTask?.kind === "detection" ? "Draw every visible unit" : taskKey === "round_classifier" ? "Draw the round display crop" : "Draw and label unit crops"}</strong><small>Click and drag · {keepBoxes ? "boxes carry to the next frame" : "boxes clear between frames"}</small></div>}
          <span className={`frame-state ${current?.status}`}>{current?.status}</span>
        </div>
      </div>

      <div className="queue-toolbar">
        <UiButton variant="ghost" size="icon-sm" className="icon-button" onClick={() => advance(-1)} disabled={queuePosition === 0 || working} aria-label="Previous frame"><ArrowLeft size={17} /></UiButton>
        <div className="queue-position"><strong>Frame {queuePosition + 1} of {project.queue.length}</strong><span>{formatTime(current!.actual_timestamp_seconds ?? current!.requested_timestamp_seconds)} · requested {formatTime(current!.requested_timestamp_seconds)}</span></div>
        <UiButton variant="ghost" size="icon-sm" className="icon-button" onClick={() => advance(1)} disabled={queuePosition === project.queue.length - 1 || working} aria-label="Next frame"><ArrowRight size={17} /></UiButton>
        <div className="queue-spacer" />
        {activeTask?.kind !== "template" && <label className="keep-boxes-toggle"><UiCheckbox  checked={keepBoxes} onCheckedChange={(checked) => setKeepBoxes(checked === true)} /><span>Keep boxes</span></label>}
        {activeTask?.kind === "template" && <label className="active-label-select template-label-input"><span>Augment label</span><UiInput value={templateLabel} placeholder="e.g. jeweled_lotus" onChange={(event) => setTemplateLabel(event.target.value)} /></label>}
        {activeTask?.kind === "classification" && <label className="active-label-select"><span>Next crop label</span><UiNativeSelect value={activeLabel} onKeyDown={handleLabelKey} onChange={(event) => { setActiveLabel(event.target.value); if (taskKey === "round_classifier" && draftItems.length) setItemLabel(0, event.target.value); }}>{activeTask.labels.map((label) => <option key={label.id} value={label.id}>{label.display_name}</option>)}</UiNativeSelect></label>}
        <UiButton variant="outline" className="secondary-button" onClick={skipCurrent} disabled={working}><SkipForward size={15} /> Skip <kbd>S</kbd></UiButton>
        <UiButton variant="default" className="primary-button" onClick={saveCurrent} disabled={working || (activeTask?.kind === "classification" && draftItems.length === 0) || (activeTask?.kind === "template" && !templateLabel.trim())}>{working ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />} {activeTask?.kind === "template" ? current?.status === "saved" ? "Update template & next" : "Save template & next" : current?.status === "saved" ? "Update & next" : activeTask?.kind === "detection" && draftItems.length === 0 ? "Save empty & next" : "Save & next"} <kbd>↵</kbd></UiButton>
      </div>

      <div className="annotation-items-panel">
        <div className="annotation-items-heading"><div><p className="eyebrow">CURRENT FRAME</p><h3>{activeTask?.kind === "template" ? current?.status === "saved" ? "Saved template" : "Template candidate" : `${draftItems.length} ${draftItems.length === 1 ? "annotation" : "annotations"}`}</h3></div>{current?.status !== "pending" && <UiButton variant="destructive" className="danger-link" onClick={deleteCurrent} disabled={working}><Trash2 size={13} /> Remove saved state</UiButton>}</div>
        {activeTask?.kind === "template" ? <div className="items-empty">{current?.status === "saved" ? `Saved as template “${current.items[0]?.label_id ?? templateLabel}”.` : "This frame has not been saved as a template."}</div> : draftItems.length === 0 ? <div className="items-empty">{activeTask?.kind === "detection" ? "No boxes. Saving creates a valid negative YOLO example." : "Draw a crop on the frame to create a classification example."}</div> : <div className="annotation-item-list">{draftItems.map((item, index) => <div key={item.clientId} className={`annotation-item ${selectedItem === index ? "selected" : ""}`} onClick={() => setSelectedItem(index)}>
          <UiButton type="button" variant="ghost" size="sm" aria-label={`Select annotation ${index + 1}`} aria-pressed={selectedItem === index} onClick={() => setSelectedItem(index)}><span className="item-number">{index + 1}</span></UiButton>
          {activeTask?.kind === "classification" ? <UiNativeSelect aria-label={`Annotation ${index + 1} label`} value={item.label_id ?? ""} onClick={(event) => event.stopPropagation()} onKeyDown={handleLabelKey} onChange={(event) => setItemLabel(index, event.target.value)}>{activeTask.labels.map((label) => <option key={label.id} value={label.id}>{label.display_name}</option>)}</UiNativeSelect> : <strong>Unit box</strong>}
          <span className="item-size">{Math.round(item.width * video.width)} × {Math.round(item.height * video.height)} px</span>
          <UiButton type="button" variant="ghost" size="icon-sm" className="item-remove" aria-label={`Remove annotation ${index + 1}`} onClick={(event) => { event.stopPropagation(); setDraftItems((items) => items.filter((_, itemIndex) => itemIndex !== index)); }}><X size={14} /></UiButton>
        </div>)}</div>}
      </div>
    </>}
    </div>
  </div>;
}
