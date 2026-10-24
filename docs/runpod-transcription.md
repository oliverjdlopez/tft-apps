# VOD Review transcription on Runpod

VOD Review uploads audio to a Runpod network volume and submits a small
`audio_path` reference to our Serverless worker. **Whisper weights are not in
our image and are not downloaded by the worker.** The endpoint selects the
Hugging Face model; Runpod stages it on the host before worker startup.

This follows [Runpod's cached-model guide](https://docs.runpod.io/serverless/development/huggingface-models#cached-model).
Model download time occurs before the worker starts and is not billed as worker
compute. Loading cached weights into GPU memory still occurs during startup.
The worker fails explicitly if the staged snapshot is missing or incomplete.

Upload confirmation, task retries, local database persistence, and shared
transcript publication retain the existing VOD Review workflow. Local Whisper
remains the default until the Runpod backend is configured.

## Configuration

From `vod-review/`, install `uv sync --extra runpod`. Set these in
`vod-review/.env`:

```dotenv
VOD_TRANSCRIPTION_BACKEND=runpod
VOD_RUNPOD_ENDPOINT_ID=your-deployed-endpoint-id
RUNPOD_API_KEY=your-runpod-api-key
RUNPOD_TRANSCRIPTION_VOLUME_ID=your-existing-network-volume-id
RUNPOD_TRANSCRIPTION_VOLUME_REGION=EU-RO-1
RUNPOD_TRANSCRIPTION_VOLUME_ACCESS_KEY=your-runpod-s3-access-key
RUNPOD_TRANSCRIPTION_VOLUME_SECRET_KEY=your-runpod-s3-secret
```

The ordinary Runpod API key authorizes job submission. The separate Runpod S3
access key and secret authorize uploads and deletion. The adapter supplies
these explicitly to `https://s3api-<region>.runpod.io`; AWS profiles and ambient
AWS credentials are not used. Boto3 is the protocol client; no AWS account or
AWS bucket is needed.

Use the volume's **ID**, not its display name, and its actual datacenter. The
endpoint must attach that volume and have GPU capacity in its datacenter.
Choose a region supporting [Runpod's S3 API](https://docs.runpod.io/storage/s3-api).

## Model cache and image

The endpoint's cached-model reference is **`Systran/faster-whisper-large-v3`**.
This is the CTranslate2 conversion required by faster-whisper; the original
`openai/whisper-large-v3` Transformers repository is not interchangeable.

The endpoint template sets `MODEL_NAME` to that repository. The handler resolves
its snapshot beneath:

```text
/runpod-volume/huggingface-cache/hub/models--Systran--faster-whisper-large-v3/snapshots/<revision>/
```

It follows `refs/main` when present and otherwise requires one unambiguous
snapshot. It checks for model.bin, config.json, and tokenizer.json,
then loads the local directory with CUDA, float16,
and `local_files_only=True`. `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`
prevent implicit Hugging Face downloads. The model loads once per worker and
is reused across jobs. Runpod permits one cached model per endpoint.
`preprocessor_config.json` is optional: official medium snapshots omit it, and
faster-whisper uses built-in feature-extractor defaults without downloading it.

Audio uploads occupy `/runpod-volume/vod-transcription/`; the host model cache
is a separate directory. The deployment request configures both a model cache
reference and the existing network volume. Actual coexistence and model loading
must be verified by the live acceptance test, not inferred from local tests.

`deploy/runpod-whisper/Dockerfile` pins a CUDA/cuDNN runtime base by digest and
installs pinned Runpod, faster-whisper, and CTranslate2 dependencies. It copies
only our handler and path/cache helpers. There is no build-time model-download
step, bundled model, or runtime download fallback. The restricted build context
excludes application dotenv, credentials, media, and runtime state.

Build and publish from `vod-review/`, substituting a registry you can push to:

```bash
RUNPOD_WHISPER_IMAGE=ghcr.io/your-account/vod-review-whisper:cached-v1
docker build --platform linux/amd64 -t "$RUNPOD_WHISPER_IMAGE" deploy/runpod-whisper
docker push "$RUNPOD_WHISPER_IMAGE"
```

Registry login is separate from Runpod authentication. A private image also
requires registry credentials configured in Runpod. Prefer an immutable image
digest for deployment after publishing.

## Deploy

```bash
uv run --extra runpod python scripts/runpod_whisper.py deploy \
  --image "$RUNPOD_WHISPER_IMAGE" \
  --model-repo Systran/faster-whisper-large-v3
# For a private image, also pass --registry-auth-id <runpod-registry-auth-id>.
```

This creates an RTX 4090 endpoint with zero minimum workers, one maximum worker,
a five-second idle timeout, and a six-hour execution timeout. It attaches the
existing audio volume and configures the host-cached Hugging Face repository
using the `modelReferences` endpoint field. Volume attachments use objects such as
`networkVolumeIds: [{"networkVolumeId": "<volume-id>"}]` in the GraphQL input.
This capability uses the same
GraphQL EndpointInput mutation as Runpod's app SDK; template creation uses REST.
The Model field can also be inspected in the Runpod console.

The script saves the endpoint ID, model alias, and backend choice directly to
`vod-review/.env`; restart the application to load them. Deployment IDs and the
selected repository are retained in ignored `data/runpod-whisper-deployment.json`.
The script refuses to create duplicates when an endpoint is already configured.
Update that endpoint when publishing a new image or selecting another model.
Changing models does not require rebuilding the image. Update both the endpoint's
`modelReferences` and `MODEL_NAME` environment variable to the same repository
(for example, `Systran/faster-whisper-medium`), then set the app-local
`VOD_WHISPER_MODEL=medium` for subsequent jobs. A configuration update can create
a new release using the same image digest. Submit a new test with the matching
model alias; an older queued job retains its original requested model.
A scaled-to-zero endpoint has no GPU compute charge. The audio network volume
remains separately billable while it exists.

## Input and completion contract

The adapter uploads to `vod-transcription/<unique-id>` and submits a queued
job containing its relative `audio_path`. The default model alias is `large-v3`,
with beam size 5 and VAD enabled. The handler rejects model changes that do not
match the single repository configured on the endpoint. It does not download
URL inputs or accept embedded audio bytes.

The worker reads the mounted file directly. Absolute paths, traversal, missing
files, and symlink escapes are rejected. The worker does not delete mounted
media. The local adapter deletes only its uploaded file after completion or
failure. Cleanup errors preserve successful recognition and are logged. A killed
backend can leave files behind; remove stale uploads only when no job uses them.

`VOD_WHISPER_MODEL` is the requested model alias, which must match the configured
repository. The local device/compute-type overrides apply only to local Whisper;
the remote worker uses CUDA/float16. Text, language, and original-media segment
timings normalize into the existing application result.

The stable Runpod SDK submits the job and polls with a 21,900-second polling
limit. A polling timeout attempts remote cancellation before removing its
upload. Stopping the application does not guarantee cancellation of work already
submitted. Remote failures do not silently fall back to local recognition.
Progress stays at its previous value while remote recognition runs, reaches
99% when output returns, then reaches 100% after local persistence.

## Validation

Extract a ten-minute audio-only slice without modifying the original:

```bash
mkdir -p data/runpod-transcription-test
ffmpeg -n -i test_audio.mp4 -t 600 -map 0:a:0 -vn -c:a copy \
  data/runpod-transcription-test/first-10-minutes.m4a
uv run --extra runpod python scripts/runpod_whisper.py test \
  data/runpod-transcription-test/first-10-minutes.m4a
```

The paid acceptance test uses the real upload/client/worker path, checks result
shape and timestamp ordering, and saves text, timestamped JSON, and timing under
a new ignored directory in `data/runpod-transcription-test/`. Artifacts are
independent of the application database. Inspect the transcript to assess TFT
terminology; structural checks do not establish recognition accuracy.

The container can be checked offline with no GPU and no model acquisition:

```bash
docker run --rm --network none --entrypoint python3 \
  --mount "type=bind,source=$PWD/deploy/runpod-whisper/verify_handler.py,target=/tmp/verify_handler.py,readonly" \
  "$RUNPOD_WHISPER_IMAGE" /tmp/verify_handler.py
```

This verifies dependencies, absence of baked Whisper weights, failure on a
missing cache, local-only initialization using simulated cache files, model
reuse, and mounted input resolution. Inference is stubbed; it does not verify
real cached weights or CUDA execution.

```bash
.venv/bin/python -m pytest -q backend/tests/test_remote_transcription.py \
  backend/tests/test_runpod_worker_image.py backend/tests/test_runpod_deployment.py \
  backend/tests/test_shared_transcripts.py
```

Set `VOD_TRANSCRIPTION_BACKEND=local` and install the `transcription` extra to use
local Whisper again.
