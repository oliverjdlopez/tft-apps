# Framewise Video Analysis and Annotation

Normal entry point: run `python3 scripts/setup.py` from the suite root, then
`npm start` or `npm run dev` from `../desktop/`. See [suite setup](../docs/desktop.md).
Standalone commands below remain available for testing and troubleshooting.


Local app for uploading a video—or downloading one from a Twitch or YouTube URL—drawing one fixed analysis region, and classifying the round shown in that crop at a configurable snapshot interval.

The **Annotate** workspace reuses each upload across five independent tasks:
YOLO unit bounding boxes, YOLO text bounding boxes, round-classification crops,
unit-ID crops, and full frames saved as named augment templates. Choose a
sampling interval, then save, skip, revisit, or replace frames from the
persistent queue. Model datasets and augment templates are written beneath
`data/datasets/` while queue metadata remains in `data/vod.sqlite3`.

Round labels and the unit-ID catalog live in
`config/annotation_tasks.json`. The 49 round labels are included; unit-ID starts
empty and becomes available after real labels are added and the backend is
restarted. Dataset roots can be moved with `VOD_DATASET_DIR`, and the task
configuration can be overridden with `VOD_ANNOTATION_TASK_CONFIG`.

Video processing decodes continuously but converts, crops, and classifies only every
30th frame. Selected crops are classified in batches of 64 by default (configurable
from 1–256 in the workspace), avoiding expensive RGB conversion and model inference
for skipped frames.

Sampling is based on the video presentation timeline (PTS), including variable-frame-rate videos. Each result stores both its scheduled time and the actual nearest frame timestamp; the UI seeks to the actual timestamp and warns when the nearest frame differs by more than 100 ms.

## Run the backend

Start the frontend and backend together from the repository root. Any arguments
are forwarded to the backend; the frontend always runs with `npm run dev`:

```bash
uv run vod-review-start --reload --port 8000
```

```bash
uv sync
uv run start --reload --port 8000
```

The backend uses ONNX Runtime OCR and stores accepted predictions in the same
compact label format as the annotated classes (for example, OCR text `5-1`
becomes `51`). A crop with no detected text or no accepted OCR result is stored
as `unknown`; there is no local classifier fallback.

To also save every sampled full frame as a PNG under `frames/<video UUID>/`, start the server with:

```bash
uv run start --reload --port 8000 --save-frames
```

To save only the selected bounding-box crops under `boxes/<video UUID>/`, use:

```bash
uv run start --reload --port 8000 --save-boxes
```

Both flags can be supplied together to save full frames and crops.

## Transcribe VOD audio

Transcription is opt-in. After downloading a video, choose **Transcribe selected
video** in the library panel, or select **Audio only, then transcribe** before
starting a URL download. Install the optional dependency with `uv sync --extra
transcription`. The default model is `large-v3` on CUDA with float16; configure
`VOD_WHISPER_MODEL`, `VOD_WHISPER_DEVICE`, and `VOD_WHISPER_COMPUTE_TYPE` to
choose another faster-whisper model/device/compute type. Raw recognized text and
detected language appear in the app; no LLM parsing or interpretation is applied.

Install the CUDA-enabled PyTorch build appropriate for the host when a CUDA GPU is available. The service automatically reports and uses a CPU fallback when CUDA cannot be initialized.

## Profile and benchmark the round pipeline

Performance events are always written to the backend log with the `VOD_TRACE`
marker. Persist the same events as structured JSON Lines with:

```bash
uv run start --trace-jsonl data/traces/round-pipeline.jsonl
```

Each inference-stage event carries the job ID, video ID, batch index, configured
batch capacity, and actual batch size. Job and batch resource snapshots include
process CPU time/utilization and RSS; CUDA hosts also report device memory,
PyTorch allocation/peak allocation, and GPU utilization when NVML is available.
The trace includes aggregate decode and crop conversion timings, model load and
first-batch timings, actual PyTorch device and ONNX Runtime providers, detector
transfer/extraction timings, OCR timings, and end-to-end job/database timings.

For synchronized stage timings, enable detailed profiling:

```bash
uv run start --trace-jsonl data/traces/round-pipeline.jsonl --detailed-profiling
```

Detailed mode splits detector and OCR work into CPU preprocessing, host-to-device
transfer, GPU forward, device-to-host transfer, and postprocessing fields. It uses
CUDA events and synchronized transfers, so it is intended for profiling runs and
adds measurement overhead. Normal tracing remains suitable for production use.

Run repeatable fixed-frame benchmarks against the production processing path with:

```bash
uv run python scripts/benchmark_round_pipeline.py path/to/video.mp4 \
  --box 0.75 0.02 0.20 0.10 \
  --batch-sizes 64 256 --frame-stride 30 --warmups 1 --runs 3 \
  --output data/traces/benchmark.jsonl \
  --trace-output data/traces/benchmark-events.jsonl
```

The runner uses the same video, crop, selected-frame stride, and warmed model for
each configuration. It records per-run predictions, stage totals, throughput,
environment and git metadata, then emits median and p95 end-to-end and per-stage
summaries. `predictions_consistent` detects output drift between measured runs.
The runner hashes every selected crop and raw prediction in order, both within a
batch-size configuration and across batch sizes; this digesting is benchmark-only.
Use `--no-detailed-profiling` to measure normal production overhead without CUDA
synchronization.

Run the backend tests from the repository root with `uv run pytest backend/tests`.

Evaluate PaddleOCR over every labeled image in
`data/datasets/round_classifier/train/` with:

```bash
uv run python scripts/evaluate_round_classifier.py
```

YOLO text detection automatically uses CUDA when PyTorch reports an available GPU.
PaddleOCR recognition runs through ONNX Runtime and uses its CUDA execution provider
when available, with CPU fallback. Install a CUDA-compatible `onnxruntime-gpu` build
in place of `onnxruntime` to enable that recognition path; only one ONNX Runtime
package should be installed in the environment.

The command runs YOLO text detection first, OCRs its highest-confidence box for
each image, and returns the valid round token when one is accepted. It writes aggregate accuracy and coverage,
unresolved counts, and per-image predictions to `round_classifier.json`. Every
image entry includes the selected YOLO/OCR candidate, raw OCR text, and both
confidence scores. Evaluation is OCR-only and uses a 0.50 OCR
confidence threshold by default; change it with `--minimum-confidence`.

## Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Uploads and analysis metadata are stored under `data/`.

`ffmpeg` should be available on `PATH` so yt-dlp can merge or remux downloaded videos and the analysis workspace can splice selected rounds into an MP4 export. Upload validation and metadata extraction use PyAV. Public Twitch and YouTube video URLs are supported, while private or subscriber-only videos require authentication that this local UI does not collect.


### Wisp classifier (development preview)

On macOS, Wisp OCR uses Apple Vision to read the entire saved analysis crop,
including multiple lines and text regions, without a separate YOLO detector.
It uses accurate English recognition with language correction disabled, retains
every region's best transcription without confidence filtering, and combines rows
top-to-bottom and left-to-right. Apple Vision chooses its compute devices; the UI
does not claim that every operation runs on the GPU. Install its macOS-only Python
bridge with `uv sync`, restart the backend, and rerun analysis to update saved text.
Other platforms retain direct whole-crop PaddleOCR (a line recognizer).
Round OCR still uses text
detection, preferring CUDA, then Apple MPS, then CPU. Recognition uses
ONNX Runtime: CUDA where available, Core ML on macOS (`MLProgram`, `CPUAndGPU`),
or CPU. Core ML may execute only part of the model; unsupported operations remain
on CPU. Accelerator initialization/inference failures retry recognition on CPU.
The workspace reports template matching, text detection, and recognition providers
separately. Restart the backend after changing device configuration. Detailed
PyTorch profiling synchronizes MPS operations; CUDA event measurements remain
CUDA-only. Raw recognized text is stored without changing Wisp detection decisions.

Open `/wisp_classifier` or choose **Wisp classifier** in the workspace switch.
Select a video, draw and save a bounding box, then choose **Process video**.
Every decoded frame is cropped to that region and given a binary template-match
label. Each positive frame appears in the existing results sidebar; consecutive
positive frames are retained individually. Clicking a timestamp pauses and seeks
to its presentation timestamp, with no round seek offset. Results are fetched
in pages of 25, with a bounded page-number selector for large videos.

Set `TEMPLATE_PATH` to the desired wisp template (currently `wisp_classifier/generic_wisp.png`) and calibrate `DETECTION_THRESHOLD` in `wisp_classifier/detector.py` before
using detections as real labels. The 0.85 threshold remains a placeholder. The loaded template determines the matching channels: grayscale
files use one channel, while RGB files use all three color channels. Color files
are converted from OpenCV's BGR order to RGB to match the decoded video crops.
RGBA templates use RGB and ignore alpha. Templates must have 8-bit pixels.
Matching prefers CUDA when an NVIDIA GPU is available, then Apple's MPS backend on
macOS, and otherwise falls back to the CPU. The job reports the selected device as
`cuda`, `mps`, or `cpu`. Template scoring runs in batches; video decoding and crop
preparation remain on the CPU. Matching computes the equivalent of `1 - TM_SQDIFF_NORMED` at the template's native
size when it fits. Smaller regions proportionally downscale the template to fit,
using bilinear interpolation on the selected device. The fitted template is reused across batches;
there is no aspect-ratio stretching or consecutive-frame deduplication. Crops are processed incrementally,
without keeping a whole video's frames in memory. Wisp boxes, jobs, and detections
are persisted separately from round analysis; interrupted jobs can be retried.


### Download FPS and analysis interval

The import form's **Saved video FPS** control defaults to **Native**. Selecting
10, 15, 24, 30, or 60 FPS transcodes the saved video with FFmpeg after transfer;
it does not reduce network transfer size. Quality selection still chooses source
resolution. Conversion can add time, and progress may remain near completion while
it runs. Both completed downloads and published partial checkpoints use the chosen
FPS, which is persisted for resume and server restarts. Native leaves cadence alone.

Both analysis workspaces accept **Interval (s)**: `0` analyzes every frame, `0.1`
selects about 10 frames per second, and `1` selects about one per second. Selection
uses presentation timestamps, choosing the first frame at or after each scheduled
time starting at zero, without duplicating frames or accumulating timing drift.
It works independently of saved FPS, including variable-FPS sources. Wisp jobs
still require CUDA. Round confirmation still uses a majority of three selected
observations; the interval controls sampling, not that vote count.

Changing the interval requires decoding fresh round crops. Legacy caches made
with frame-stride sampling must also be regenerated once before rerunning OCR.


### Shared sampled-frame preparation

Round and wisp preparation follows the requested analysis interval. For a ten-minute
video at a one-second interval, about 600 full frames are converted and cached, rather
than all 36,000 source frames at 60 FPS. The decoder may still traverse intermediate
frames because compressed video depends on neighboring frames, but those frames are
not cached or sent through inference.

Both analyzers share lossless sampled frame arrays and timestamps in `data/frame_cache/`.
An existing cache is reused for the same interval or an aligned coarser interval.
Denser or non-aligned sampling scans the source again to add missing frames, preserving
already-cached frames. Choosing interval 0 explicitly prepares and analyzes every
frame. Existing full-frame caches remain usable without conversion or rebuilding.

Preparation reports sampled-frame counts. The UI previews how many samples a run
will select. Frames are stored as memory-mapped NumPy arrays: native YUV420 when available,
with RGB fallback. This avoids expensive full-frame PNG encoding; RGB conversion
occurs only for the selected crop during inference. Existing PNG caches remain
readable. Raw arrays use more disk space than PNGs.

Sparse preparation avoids the large up-front full-video PNG workload;
it does not promise zero decoding for future intervals that have never been prepared.
Sampling occurs before loading cached images during inference. Video deletion removes
the shared cache, and timestamp selection remains independent of source FPS.

## Google Drive round clips

The round-classification workspace includes **Upload to GDrive** to upload a
separate clip for all or key rounds across the VOD, with a configurable start
offset and duration (60 seconds by default). See
[Google Drive setup, timing, and retry behavior](docs/google-drive.md).

## Shared shadcn interface

This frontend uses local shadcn/ui New York sources (CLI 4.21.0, neutral, Radix,
Lucide, TSX), Tailwind CSS 4, and a fixed neutral dark theme. `frontend/components.json`
records generation settings; `frontend/src/components/ui` owns primitives and
`frontend/src/components/shared` adapts existing dialogs, confirmations, and uploads.
`frontend/src/theme.css` is identical to ChatTFT's canonical theme at
`../tft-chat/app/frontend/src/theme.css`. The full contract and update procedure are
in [`../tft-chat/docs/development/shared-ui.md`](../tft-chat/docs/development/shared-ui.md).

Keep this build independent. Copy theme updates and port shared primitive changes
from ChatTFT, then validate both VOD Review and Wisps views in this application. Preserve
each branch's App, API, annotation, and upload features. Do not overwrite application
files from the other checkout. Keep video/canvas layout together; retain PTS seeking,
frame stepping, OCR, normalized boxes, and panel resizing. General controls use
36px height (32px compact); tables scroll internally and toolbars wrap.

After component updates, from `frontend` run `npm ci`, `npm test`, and
`npm run build`. Validate Analyze, Wisp classifier, and Annotate at 1440, 1024, and
390px, including focus return, file changes, processing states, and canvas alignment.
The committed lockfile and component sources are authoritative; the online shadcn
registry may change even when invoking the same CLI version.
## Share downloaded media with ChatTFT

Export the same absolute `TFT_MEDIA_DIR` in both backend environments to enable
one shared SQLite media catalog and local media directory. Both repositories
remain independently installed; review jobs, annotations, and ChatTFT's
application database remain separate. See [shared media setup](docs/shared-media.md)
for cache behavior, existing-file import, requirements, and storage lifecycle.
