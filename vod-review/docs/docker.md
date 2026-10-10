# VOD container runtime

The suite keeps Electron on the host and packages VOD separately from ChatTFT.
See [suite desktop setup](../../docs/desktop.md) for launch commands and Compose
ownership. The image definition is `../../docker/Dockerfile.vod`, built with the
suite root as its context. Its adjacent Docker ignore file admits source and
lockfiles while excluding local configuration, credentials, media, databases,
model weights, dependency directories and results.

## Processes and frontend

The VOD image stores source under `/opt/tft-apps/vod-review` and its independent
Python environment under `/opt/venv`. It installs the committed Python lock with
the transcription extra, FFmpeg, IANA timezone data for replay schedules, and
the native image-processing libraries.
Production frontend dependencies are installed with `npm ci` in a Node 22 build
stage. The built frontend goes into `frontend/dist` with an empty `VITE_API_BASE`,
so API requests, playback and uploads use the page's origin.

The image command runs `docker/backend.py --service vod` through Python. One
Uvicorn process binds container port 8000 and handles normal termination signals.
Compose publishes the configured local backend and frontend ports to that same
service. Existing VOD API routes and lifespan run unchanged. The container
entrypoint appends static-file and HTML client-route handling; missing API routes
and missing assets remain 404, and paths outside the built frontend are rejected.
The desktop identity endpoint uses the same wrapper as the native launcher.

Development uses `docker/Dockerfile.frontend` with build argument
`FRONTEND_DIR=vod-review/frontend`. Vite listens on container port 5173;
`TFT_API_PROXY_TARGET=http://vod:8000` selects the API service and
`VITE_API_BASE=` keeps browser requests on the frontend origin. Source mounts
must preserve the image's `node_modules`; Vite's cache directories are writable
for the host uid/gid selected by Compose.

## Local state and model caches

Images contain no copied runtime data. Keep existing data and shared-media
directories on local disk and mount them at the same absolute paths used by the
stored VOD records. Set `VOD_DATA_DIR`, `VOD_FRAMES_DIR`, `VOD_BOXES_DIR`,
`VOD_OCR_CACHE_DIR` and `TFT_MEDIA_DIR` to those container-visible paths.
This preserves existing SQLite references to downloaded and uploaded files.

Mount the VOD `artifacts/` directory at
`/opt/tft-apps/vod-review/artifacts`. The retained YOLO detector uses
`artifacts/text-detection/train/weights/best.pt` relative to the application root.
Its existing download behavior runs only when a requested detector is absent;
image builds do not download any model.

Mount a writable cache home at `/home/app`. Hugging Face models use
`/home/app/.cache/huggingface`, Paddle models use `/home/app/.paddlex`, and
Ultralytics configuration uses `/home/app/.config/Ultralytics`. Existing model
caches can be mounted into these locations. Keep the OAuth token file in the
mounted VOD data directory; mount the existing external Google client file
separately and pass its container-visible path in `VOD_GDRIVE_CLIENT_FILE`.
Run as the host uid/gid so files created by containers remain host-editable.

## GPU libraries

The current lock includes PyTorch 2.13 and ONNX Runtime 1.28 with CUDA 13
libraries. Its CTranslate2 4.8.2 transcription dependency still loads CUDA 12
cuBLAS. The image therefore uses a CUDA 12.8 cuDNN runtime base alongside the
locked CUDA 13 wheel libraries, with their library directories available to the
loader. No Python dependency is replaced during the build.

The host supplies the GPU driver through container passthrough. CUDA 13 requires
a compatible driver from the R580 generation or newer; see NVIDIA's
[compatibility guidance](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html).
Both the detector and recognizer report their actual providers through existing
runtime diagnostics. A successful image build alone does not establish GPU
inference or transcription compatibility.

For CPU-only operation, omit GPU passthrough and select
`VOD_WHISPER_DEVICE=cpu` with `VOD_WHISPER_COMPUTE_TYPE=int8`. The detector and OCR
already support CPU fallback; transcription has an explicit device setting.
