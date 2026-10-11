# VOD Review scope

VOD Review now opens directly into review and round classification. Its desktop
tab owns one frontend/backend pair. ChatTFT, Compositions, Rolldown, Flowchart,
Media, and the suite support services remain independent.

## Removed source and functionality

| Directory or files | Retired functionality | Why review does not require it |
| --- | --- | --- |
| `vod-review/wisp_classifier/`, `backend/wisps.py` | Wisp template matching, Apple Vision OCR, Wisp jobs and frame review | Round analysis uses its own YOLO/ONNX OCR pipeline. |
| `vod-review/unit_id/` | Unit embeddings, clustering, training and identification | The review page classifies rounds only. |
| `vod-review/unit_segmentation/` | Unit detector training and standalone inference | Round crops use the text detector. |
| `vod-review/augment_classifier/` | Augment template matching | No review-page caller uses it. |
| `backend/annotations.py`, `config/annotation_tasks.json` | Annotation queues, dataset authoring and task configuration | Round labels now load independently from `config/round_labels.json`. |
| Frontend `AnnotationWorkspace`, `WispResults`, `WispFrameReview` | Annotate/Wisp modes and their API clients | The root page opens the round analyzer directly. |
| `text_detection/train.py`, `text_detection/inference.py` | Standalone detector training and annotated-image export | Runtime model loading remains in `text_detection/model.py`. |
| `backend/data.py`, `script.sh`, unused frontend primitives/hooks | Empty module, old training launcher and unused UI scaffolding | No remaining application imports use them. |
| Desktop Wisps navigation/menu/launcher option | Separate Wisps view and `--wisps` option | VOD Review is the sole VOD view. |

Retired feature tests, request models, endpoints and styles were removed alongside
their implementations. The dependency lock drops scikit-learn and the macOS
Apple Vision bridge. Torchvision remains an Ultralytics transitive dependency.
No installed environment was synchronized or uninstalled during cleanup.

## Retained review flow

Uploads and URL downloads (including checkpoints, resume, ranges, quality and
FPS controls), replay discovery and scheduled imports, playback preparation,
video selection/deletion, crop editing, interval/batch controls, sampled frame
caching, round text detection/recognition, OCR reruns, timestamp seeking, game
grouping, round selection/export and Google Drive clip uploads remain available.
Audio transcription and shared-media import/publication remain available too.

`round_classifier/`, runtime `text_detection/`, the backend processor/cache,
round benchmarks/evaluation scripts and their tests remain required. The 49
round labels retain their original IDs and order; `VOD_ROUND_LABEL_CONFIG` can
override the JSON array. YOLO weights retain their existing storage path.

## Preserved data

This cleanup deletes source files, not live videos, transcripts, SQLite databases,
authored datasets, model weights, credentials or other ignored runtime assets.
Existing legacy annotation/Wisp database tables are left intact; new databases
no longer create annotation tables. Video deletion does not delete legacy
annotation datasets. Retired directories may therefore still contain preserved
ignored assets or Python caches, which the application no longer imports.

The original source checkouts are unchanged. The migration manifest and original
verification report describe the initial import; intentional source retirement
documented here supersedes their file-presence expectations for this checkout.

Restart the desktop to load the reduced navigation and updated VOD backend.

## Validation

The remaining VOD Python suite passes 180 tests, the frontend passes 39 tests
and builds, and desktop tests pass 64 tests. Five cross-backend tests verify
media reuse, resource reads, transcript publication and protocol parity. A real
Linux/WSLg Electron smoke loaded all five remaining product views on disposable
ports and verified owned process shutdown. These checks use temporary video/data
fixtures and mocked inference; real GPU OCR, online downloads and Drive uploads
were not exercised. The smoke disables RDS, so it checks other views loading
rather than their database-backed functionality.
