"""Persistent, train-ready video annotation projects."""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from PIL import Image

try:
    from . import db
    from .models import (
        AnnotationFrameRequest,
        AnnotationProjectRequest,
        ClassificationFrameRequest,
        DetectionFrameRequest,
        TaskKey,
        TemplateFrameRequest,
    )
    from .processor import box_to_pixels, decode_frame_at_timestamp, sample_schedule
except ImportError:  # Running with uvicorn from the backend directory.
    import db
    from models import (
        AnnotationFrameRequest,
        AnnotationProjectRequest,
        ClassificationFrameRequest,
        DetectionFrameRequest,
        TaskKey,
        TemplateFrameRequest,
    )
    from processor import box_to_pixels, decode_frame_at_timestamp, sample_schedule


ROOT = Path(__file__).resolve().parent.parent
TASK_CONFIG_PATH = Path(os.environ.get("VOD_ANNOTATION_TASK_CONFIG", ROOT / "config" / "annotation_tasks.json"))
DATASET_DIR = Path(os.environ.get("VOD_DATASET_DIR", db.DATA_DIR / "datasets"))
TASKS = ("unit_segmentation", "text_detection", "round_classifier", "unit_id", "augment_classifier")
SAFE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TASK_CONFIG: dict[str, dict[str, Any]] | None = None


def _validate_task_config(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict) or set(payload) != set(TASKS):
        raise RuntimeError(f"Annotation config must define exactly: {', '.join(TASKS)}")
    validated: dict[str, dict[str, Any]] = {}
    for task in TASKS:
        raw = payload[task]
        if not isinstance(raw, dict):
            raise RuntimeError(f"Annotation task {task} must be an object")
        expected_kind = "detection" if task in ("unit_segmentation", "text_detection") else "template" if task == "augment_classifier" else "classification"
        if raw.get("kind") != expected_kind:
            raise RuntimeError(f"Annotation task {task} must use kind={expected_kind}")
        display_name = raw.get("display_name")
        labels = raw.get("labels")
        if not isinstance(display_name, str) or not display_name.strip():
            raise RuntimeError(f"Annotation task {task} needs a display_name")
        if not isinstance(labels, list):
            raise RuntimeError(f"Annotation task {task} labels must be a list")
        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for entry in labels:
            if not isinstance(entry, dict):
                raise RuntimeError(f"Annotation task {task} has an invalid label entry")
            label_id = entry.get("id")
            label_name = entry.get("display_name")
            if not isinstance(label_id, str) or not SAFE_LABEL.fullmatch(label_id):
                raise RuntimeError(f"Annotation task {task} has unsafe label id: {label_id!r}")
            if label_id in seen:
                raise RuntimeError(f"Annotation task {task} repeats label id: {label_id}")
            if not isinstance(label_name, str) or not label_name.strip():
                raise RuntimeError(f"Annotation label {label_id} needs a display_name")
            seen.add(label_id)
            normalized.append({"id": label_id, "display_name": label_name.strip()})
        if task == "unit_segmentation" and [label["id"] for label in normalized] != ["unit"]:
            raise RuntimeError("unit_segmentation must define the single label id 'unit'")
        if task == "text_detection" and [label["id"] for label in normalized] != ["text"]:
            raise RuntimeError("text_detection must define the single label id 'text'")
        validated[task] = {
            "key": task,
            "display_name": display_name.strip(),
            "kind": expected_kind,
            "labels": normalized,
            "enabled": expected_kind in ("detection", "template") or bool(normalized),
        }
    return validated


def load_task_config(*, force: bool = False) -> dict[str, dict[str, Any]]:
    global _TASK_CONFIG
    if _TASK_CONFIG is None or force:
        try:
            payload = json.loads(TASK_CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not load annotation task config at {TASK_CONFIG_PATH}") from exc
        _TASK_CONFIG = _validate_task_config(payload)
    return _TASK_CONFIG


def task_definitions() -> list[dict[str, Any]]:
    return [dict(load_task_config()[task]) for task in TASKS]


def initialize_datasets() -> None:
    config = load_task_config(force=True)
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    for task, label in (("unit_segmentation", "unit"), ("text_detection", "text")):
        detection_root = DATASET_DIR / task
        for split in ("train", "val"):
            (detection_root / "images" / split).mkdir(parents=True, exist_ok=True)
            (detection_root / "labels" / split).mkdir(parents=True, exist_ok=True)
        yaml = (
            f"path: {detection_root.resolve()}\n"
            "train: images/train\n"
            "val: images/val\n"
            "names:\n"
            f"  0: {label}\n"
        )
        _write_text_atomic(detection_root / "data.yaml", yaml)
    for task in ("round_classifier", "unit_id"):
        for split in ("train", "val"):
            for label in config[task]["labels"]:
                (DATASET_DIR / task / split / label["id"]).mkdir(parents=True, exist_ok=True)


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _save_png_atomic(path: Path, image: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        image.save(temporary, format="PNG")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _video_row(connection, video_id: str):
    row = connection.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")
    return row


def _project_row(connection, video_id: str, task: str):
    return connection.execute(
        "SELECT * FROM annotation_projects WHERE video_id=? AND task=?",
        (video_id, task),
    ).fetchone()


def _require_task(task: str) -> dict[str, Any]:
    if task not in TASKS:
        raise HTTPException(status_code=404, detail="Annotation task not found")
    return load_task_config()[task]


def _serialize_project(connection, project, video) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT * FROM annotation_frames WHERE project_id=? ORDER BY sample_index",
        (project["id"],),
    ).fetchall()
    by_index = {row["sample_index"]: row for row in rows}
    queue: list[dict[str, Any]] = []
    saved = skipped = 0
    for sample_index, timestamp in enumerate(
        sample_schedule(video["duration"], project["sample_interval_seconds"]),
        start=1,
    ):
        row = by_index.get(sample_index)
        items: list[dict[str, Any]] = []
        if row is not None:
            item_rows = connection.execute(
                "SELECT * FROM annotation_items WHERE frame_id=? ORDER BY item_index",
                (row["id"],),
            ).fetchall()
            items = [
                {
                    "label_id": item["label_id"],
                    "x": item["x"],
                    "y": item["y"],
                    "width": item["width"],
                    "height": item["height"],
                }
                for item in item_rows
            ]
            saved += row["status"] == "saved"
            skipped += row["status"] == "skipped"
        queue.append(
            {
                "sample_index": sample_index,
                "requested_timestamp_seconds": timestamp,
                "actual_timestamp_seconds": row["actual_timestamp_seconds"] if row else None,
                "status": row["status"] if row else "pending",
                "items": items,
            }
        )
    return {
        "id": project["id"],
        "video_id": project["video_id"],
        "task": project["task"],
        "kind": load_task_config()[project["task"]]["kind"],
        "split": project["split"],
        "sample_interval_seconds": project["sample_interval_seconds"],
        "locked": project["locked_at"] is not None,
        "created_at": project["created_at"],
        "updated_at": project["updated_at"],
        "counts": {"saved": saved, "skipped": skipped, "pending": len(queue) - saved - skipped},
        "queue": queue,
    }


def get_project(video_id: str, task: TaskKey) -> dict[str, Any] | None:
    _require_task(task)
    connection = db.get_db()
    try:
        video = _video_row(connection, video_id)
        project = _project_row(connection, video_id, task)
        return _serialize_project(connection, project, video) if project else None
    finally:
        connection.close()


def put_project(video_id: str, task: TaskKey, request: AnnotationProjectRequest) -> dict[str, Any]:
    definition = _require_task(task)
    if not definition["enabled"]:
        raise HTTPException(status_code=409, detail=f"Configure labels for {task} before annotating")
    connection = db.get_db()
    try:
        video = _video_row(connection, video_id)
        project = _project_row(connection, video_id, task)
        now = db.utc_now()
        if project is None:
            project_id = uuid.uuid4().hex
            connection.execute(
                "INSERT INTO annotation_projects(id, video_id, task, split, sample_interval_seconds, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (project_id, video_id, task, request.split, request.sample_interval_seconds, now, now),
            )
        else:
            changed = project["split"] != request.split or project["sample_interval_seconds"] != request.sample_interval_seconds
            if changed and project["locked_at"] is not None:
                raise HTTPException(status_code=409, detail="Reset this annotation project before changing its split or interval")
            connection.execute(
                "UPDATE annotation_projects SET split=?, sample_interval_seconds=?, updated_at=? WHERE id=?",
                (request.split, request.sample_interval_seconds, now, project["id"]),
            )
        connection.commit()
        project = _project_row(connection, video_id, task)
        return _serialize_project(connection, project, video)
    finally:
        connection.close()


def _collect_paths(connection, project_id: str, sample_index: int | None = None) -> set[Path]:
    parameters: tuple[Any, ...]
    predicate = "f.project_id=?"
    parameters = (project_id,)
    if sample_index is not None:
        predicate += " AND f.sample_index=?"
        parameters += (sample_index,)
    rows = connection.execute(
        "SELECT f.image_path AS frame_image, f.annotation_path, i.image_path AS item_image "
        "FROM annotation_frames f LEFT JOIN annotation_items i ON i.frame_id=f.id WHERE " + predicate,
        parameters,
    ).fetchall()
    paths: set[Path] = set()
    for row in rows:
        for key in ("frame_image", "annotation_path", "item_image"):
            if row[key]:
                paths.add(Path(row[key]))
    return paths


def _remove_paths(paths: set[Path]) -> None:
    root = DATASET_DIR.resolve()
    for path in paths:
        try:
            resolved = path.resolve()
            if resolved.is_relative_to(root):
                resolved.unlink(missing_ok=True)
        except OSError:
            continue


def delete_project(video_id: str, task: TaskKey) -> None:
    _require_task(task)
    connection = db.get_db()
    try:
        _video_row(connection, video_id)
        project = _project_row(connection, video_id, task)
        if project is None:
            return
        paths = _collect_paths(connection, project["id"])
        connection.execute(
            "DELETE FROM annotation_items WHERE frame_id IN (SELECT id FROM annotation_frames WHERE project_id=?)",
            (project["id"],),
        )
        connection.execute("DELETE FROM annotation_frames WHERE project_id=?", (project["id"],))
        connection.execute("DELETE FROM annotation_projects WHERE id=?", (project["id"],))
        connection.commit()
    finally:
        connection.close()
    _remove_paths(paths)


def _decode_rgb(video_path: Path, target: float) -> tuple[Image.Image, float]:
    try:
        import av
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="PyAV is required for annotation") from exc
    container = av.open(str(video_path))
    try:
        if not container.streams.video:
            raise HTTPException(status_code=400, detail="Video does not contain a video stream")
        frame, actual = decode_frame_at_timestamp(container, container.streams.video[0], target)
        return Image.fromarray(frame.to_ndarray(format="rgb24"), mode="RGB"), actual
    finally:
        container.close()


def _validate_frame_request(task: str, definition: dict[str, Any], request: AnnotationFrameRequest) -> None:
    if definition["kind"] != request.kind:
        raise HTTPException(status_code=422, detail=f"{task} requires a {definition['kind']} payload")
    if request.status == "skipped":
        return
    if isinstance(request, TemplateFrameRequest):
        if request.label_id is None or not SAFE_LABEL.fullmatch(request.label_id):
            raise HTTPException(status_code=422, detail="Template label must be filesystem-safe")
        return
    if isinstance(request, DetectionFrameRequest):
        return
    labels = {entry["id"] for entry in definition["labels"]}
    if task == "round_classifier" and len(request.crops) != 1:
        raise HTTPException(status_code=422, detail="Round classification requires exactly one labeled crop")
    if task == "unit_id" and not request.crops:
        raise HTTPException(status_code=422, detail="Unit identification requires at least one labeled crop")
    unknown = sorted({crop.label_id for crop in request.crops} - labels)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown label for {task}: {', '.join(unknown)}")


def put_frame(
    video_id: str,
    task: TaskKey,
    sample_index: int,
    request: AnnotationFrameRequest,
) -> dict[str, Any]:
    if sample_index < 1:
        raise HTTPException(status_code=404, detail="Sample not found")
    definition = _require_task(task)
    _validate_frame_request(task, definition, request)
    connection = db.get_db()
    new_paths: set[Path] = set()
    try:
        video = _video_row(connection, video_id)
        project = _project_row(connection, video_id, task)
        if project is None:
            raise HTTPException(status_code=404, detail="Create the annotation project first")
        schedule = sample_schedule(video["duration"], project["sample_interval_seconds"])
        if sample_index > len(schedule):
            raise HTTPException(status_code=404, detail="Sample not found")
        requested_timestamp = schedule[sample_index - 1]
        old_paths = _collect_paths(connection, project["id"], sample_index)
        actual_timestamp: float | None = None
        frame_image_path: Path | None = None
        annotation_path: Path | None = None
        item_payloads: list[dict[str, Any]] = []
        base_name = f"{video_id}_{sample_index:06d}"
        if request.status == "saved":
            image, actual_timestamp = _decode_rgb(Path(video["path"]), requested_timestamp)
            if isinstance(request, DetectionFrameRequest):
                frame_image_path = DATASET_DIR / task / "images" / project["split"] / f"{base_name}.png"
                annotation_path = DATASET_DIR / task / "labels" / project["split"] / f"{base_name}.txt"
                _save_png_atomic(frame_image_path, image)
                lines = [
                    f"0 {box.x + box.width / 2:.8f} {box.y + box.height / 2:.8f} {box.width:.8f} {box.height:.8f}"
                    for box in request.boxes
                ]
                _write_text_atomic(annotation_path, "\n".join(lines) + ("\n" if lines else ""))
                new_paths.update((frame_image_path, annotation_path))
                item_payloads = [box.model_dump() | {"label_id": "unit", "image_path": None} for box in request.boxes]
            elif isinstance(request, ClassificationFrameRequest):
                for item_index, crop in enumerate(request.crops, start=1):
                    x0, y0, x1, y1 = box_to_pixels(crop.model_dump(), image.width, image.height)
                    crop_path = DATASET_DIR / task / project["split"] / crop.label_id / f"{base_name}_{item_index:03d}.png"
                    _save_png_atomic(crop_path, image.crop((x0, y0, x1, y1)))
                    new_paths.add(crop_path)
                    item_payloads.append(crop.model_dump() | {"image_path": str(crop_path)})
            elif isinstance(request, TemplateFrameRequest):
                assert request.label_id is not None
                frame_image_path = (
                    DATASET_DIR / task / "templates" / request.label_id / f"{base_name}.png"
                )
                _save_png_atomic(frame_image_path, image)
                new_paths.add(frame_image_path)
                item_payloads.append(
                    {
                        "label_id": request.label_id,
                        "x": 0.0,
                        "y": 0.0,
                        "width": 1.0,
                        "height": 1.0,
                        "image_path": str(frame_image_path),
                    }
                )

        now = db.utc_now()
        existing = connection.execute(
            "SELECT * FROM annotation_frames WHERE project_id=? AND sample_index=?",
            (project["id"], sample_index),
        ).fetchone()
        frame_id = existing["id"] if existing else uuid.uuid4().hex
        if existing:
            connection.execute(
                "UPDATE annotation_frames SET requested_timestamp_seconds=?, actual_timestamp_seconds=?, status=?, "
                "image_path=?, annotation_path=?, updated_at=? WHERE id=?",
                (requested_timestamp, actual_timestamp, request.status, str(frame_image_path) if frame_image_path else None,
                 str(annotation_path) if annotation_path else None, now, frame_id),
            )
            connection.execute("DELETE FROM annotation_items WHERE frame_id=?", (frame_id,))
        else:
            connection.execute(
                "INSERT INTO annotation_frames(id, project_id, sample_index, requested_timestamp_seconds, "
                "actual_timestamp_seconds, status, image_path, annotation_path, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (frame_id, project["id"], sample_index, requested_timestamp, actual_timestamp, request.status,
                 str(frame_image_path) if frame_image_path else None, str(annotation_path) if annotation_path else None,
                 now, now),
            )
        for item_index, item in enumerate(item_payloads, start=1):
            connection.execute(
                "INSERT INTO annotation_items(id, frame_id, item_index, label_id, x, y, width, height, image_path) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, frame_id, item_index, item.get("label_id"), item["x"], item["y"],
                 item["width"], item["height"], item.get("image_path")),
            )
        connection.execute(
            "UPDATE annotation_projects SET locked_at=COALESCE(locked_at, ?), updated_at=? WHERE id=?",
            (now, now, project["id"]),
        )
        connection.commit()
        _remove_paths(old_paths - new_paths)
        project = _project_row(connection, video_id, task)
        return _serialize_project(connection, project, video)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def delete_frame(video_id: str, task: TaskKey, sample_index: int) -> dict[str, Any]:
    _require_task(task)
    connection = db.get_db()
    try:
        video = _video_row(connection, video_id)
        project = _project_row(connection, video_id, task)
        if project is None:
            raise HTTPException(status_code=404, detail="Annotation project not found")
        frame = connection.execute(
            "SELECT * FROM annotation_frames WHERE project_id=? AND sample_index=?",
            (project["id"], sample_index),
        ).fetchone()
        if frame is not None:
            paths = _collect_paths(connection, project["id"], sample_index)
            connection.execute("DELETE FROM annotation_items WHERE frame_id=?", (frame["id"],))
            connection.execute("DELETE FROM annotation_frames WHERE id=?", (frame["id"],))
            connection.execute("UPDATE annotation_projects SET updated_at=? WHERE id=?", (db.utc_now(), project["id"]))
            connection.commit()
            _remove_paths(paths)
        project = _project_row(connection, video_id, task)
        return _serialize_project(connection, project, video)
    finally:
        connection.close()
