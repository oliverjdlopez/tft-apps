import asyncio
import json
from pathlib import Path

import pytest
import httpx
from fastapi import HTTPException
from PIL import Image

from backend import annotations, app as app_module, db
from backend.models import (
    AnnotationBox,
    AnnotationProjectRequest,
    ClassificationCrop,
    ClassificationFrameRequest,
    DetectionFrameRequest,
    TemplateFrameRequest,
)


def configure_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, unit_labels: list[str] | None = None) -> None:
    db.DATA_DIR = tmp_path / "data"
    db.VIDEO_DIR = db.DATA_DIR / "videos"
    db.DB_PATH = db.DATA_DIR / "vod.sqlite3"
    annotations.DATASET_DIR = db.DATA_DIR / "datasets"
    source_config = Path(__file__).resolve().parents[2] / "config" / "annotation_tasks.json"
    payload = json.loads(source_config.read_text(encoding="utf-8"))
    if unit_labels is not None:
        payload["unit_id"]["labels"] = [
            {"id": label, "display_name": label.replace("_", " ").title()}
            for label in unit_labels
        ]
    config_path = tmp_path / "annotation_tasks.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    annotations.TASK_CONFIG_PATH = config_path
    annotations._TASK_CONFIG = None
    db.init_db()
    annotations.initialize_datasets()
    db.create_video("video-id", "sample.mp4", tmp_path / "sample.mp4", "video/mp4", 16, 100, 80)
    monkeypatch.setattr(annotations, "_decode_rgb", lambda _path, timestamp: (Image.new("RGB", (100, 80), "red"), timestamp + 0.02))


def test_task_config_and_detection_dataset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    configure_storage(monkeypatch, tmp_path)
    definitions = {task["key"]: task for task in annotations.task_definitions()}
    assert len(definitions["round_classifier"]["labels"]) == 49
    assert definitions["unit_id"]["enabled"] is False
    assert definitions["augment_classifier"]["enabled"] is True
    assert (annotations.DATASET_DIR / "unit_segmentation" / "data.yaml").exists()
    text_yaml = annotations.DATASET_DIR / "text_detection" / "data.yaml"
    assert text_yaml.exists()
    assert "0: text" in text_yaml.read_text()

    annotations.put_project(
        "video-id",
        "text_detection",
        AnnotationProjectRequest(split="val", sample_interval_seconds=5),
    )
    annotations.put_frame(
        "video-id",
        "text_detection",
        1,
        DetectionFrameRequest(
            kind="detection",
            boxes=[AnnotationBox(x=0.2, y=0.1, width=0.6, height=0.2)],
        ),
    )
    text_label = annotations.DATASET_DIR / "text_detection" / "labels" / "val" / "video-id_000001.txt"
    assert text_label.read_text() == "0 0.50000000 0.20000000 0.60000000 0.20000000\n"

    project = annotations.put_project(
        "video-id",
        "unit_segmentation",
        AnnotationProjectRequest(split="train", sample_interval_seconds=5),
    )
    assert [item["requested_timestamp_seconds"] for item in project["queue"]] == [5, 10, 15]
    round_project = annotations.put_project(
        "video-id",
        "round_classifier",
        AnnotationProjectRequest(split="val", sample_interval_seconds=10),
    )
    assert round_project["split"] == "val"
    assert annotations.get_project("video-id", "unit_segmentation")["split"] == "train"

    saved = annotations.put_frame(
        "video-id",
        "unit_segmentation",
        1,
        DetectionFrameRequest(kind="detection", boxes=[AnnotationBox(x=0.1, y=0.2, width=0.4, height=0.5)]),
    )
    assert saved["counts"] == {"saved": 1, "skipped": 0, "pending": 2}
    image_path = annotations.DATASET_DIR / "unit_segmentation" / "images" / "train" / "video-id_000001.png"
    label_path = annotations.DATASET_DIR / "unit_segmentation" / "labels" / "train" / "video-id_000001.txt"
    assert image_path.exists()
    assert label_path.read_text() == "0 0.30000000 0.45000000 0.40000000 0.50000000\n"

    annotations.put_frame(
        "video-id",
        "unit_segmentation",
        1,
        DetectionFrameRequest(kind="detection", boxes=[]),
    )
    assert label_path.read_text() == ""
    skipped = annotations.put_frame(
        "video-id",
        "unit_segmentation",
        2,
        DetectionFrameRequest(kind="detection", status="skipped", boxes=[]),
    )
    assert skipped["counts"] == {"saved": 1, "skipped": 1, "pending": 1}
    with pytest.raises(HTTPException, match="Reset") as error:
        annotations.put_project(
            "video-id",
            "unit_segmentation",
            AnnotationProjectRequest(split="val", sample_interval_seconds=5),
        )
    assert error.value.status_code == 409

    annotations.delete_project("video-id", "unit_segmentation")
    assert not image_path.exists()
    assert not label_path.exists()
    assert annotations.get_project("video-id", "unit_segmentation") is None


def test_classification_crops_labels_and_cleanup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    configure_storage(monkeypatch, tmp_path, unit_labels=["annie", "garen"])
    annotations.put_project(
        "video-id",
        "unit_id",
        AnnotationProjectRequest(split="val", sample_interval_seconds=5),
    )
    saved = annotations.put_frame(
        "video-id",
        "unit_id",
        2,
        ClassificationFrameRequest(
            kind="classification",
            crops=[
                ClassificationCrop(label_id="annie", x=0, y=0, width=0.5, height=0.5),
                ClassificationCrop(label_id="garen", x=0.5, y=0.5, width=0.5, height=0.5),
            ],
        ),
    )
    assert saved["queue"][1]["actual_timestamp_seconds"] == 10.02
    annie = annotations.DATASET_DIR / "unit_id" / "val" / "annie" / "video-id_000002_001.png"
    garen = annotations.DATASET_DIR / "unit_id" / "val" / "garen" / "video-id_000002_002.png"
    assert Image.open(annie).size == (50, 40)
    assert Image.open(garen).size == (50, 40)

    with pytest.raises(HTTPException, match="Unknown label"):
        annotations.put_frame(
            "video-id",
            "unit_id",
            1,
            ClassificationFrameRequest(
                kind="classification",
                crops=[ClassificationCrop(label_id="../escape", x=0, y=0, width=1, height=1)],
            ),
        )

    annotations.put_project(
        "video-id",
        "round_classifier",
        AnnotationProjectRequest(split="train", sample_interval_seconds=5),
    )
    with pytest.raises(HTTPException, match="exactly one"):
        annotations.put_frame(
            "video-id",
            "round_classifier",
            1,
            ClassificationFrameRequest(kind="classification", crops=[]),
        )

    updated = annotations.delete_frame("video-id", "unit_id", 2)
    assert updated["counts"]["pending"] == 3
    assert not annie.exists()
    assert not garen.exists()


def test_config_rejects_path_unsafe_label(tmp_path: Path):
    source_config = Path(__file__).resolve().parents[2] / "config" / "annotation_tasks.json"
    payload = json.loads(source_config.read_text(encoding="utf-8"))
    payload["unit_id"]["labels"] = [{"id": "../escape", "display_name": "Escape"}]
    with pytest.raises(RuntimeError, match="unsafe label"):
        annotations._validate_task_config(payload)


def test_saves_full_frame_as_augment_template(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    configure_storage(monkeypatch, tmp_path)
    annotations.put_project(
        "video-id",
        "augment_classifier",
        AnnotationProjectRequest(split="train", sample_interval_seconds=5),
    )

    saved = annotations.put_frame(
        "video-id",
        "augment_classifier",
        1,
        TemplateFrameRequest(kind="template", label_id="jeweled_lotus"),
    )

    template = (
        annotations.DATASET_DIR
        / "augment_classifier"
        / "templates"
        / "jeweled_lotus"
        / "video-id_000001.png"
    )
    assert template.exists()
    assert Image.open(template).size == (100, 80)
    assert saved["queue"][0]["items"][0]["label_id"] == "jeweled_lotus"

    with pytest.raises(HTTPException, match="filesystem-safe"):
        annotations.put_frame(
            "video-id",
            "augment_classifier",
            2,
            TemplateFrameRequest(kind="template", label_id="../escape"),
        )

    annotations.delete_frame("video-id", "augment_classifier", 1)
    assert not template.exists()


def test_annotation_api_project_frame_and_reset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    configure_storage(monkeypatch, tmp_path)

    async def exercise() -> None:
        transport = httpx.ASGITransport(app=app_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            tasks = await client.get("/api/annotation-tasks")
            assert tasks.status_code == 200
            assert len(tasks.json()) == 5
            created = await client.put(
                "/api/videos/video-id/annotation-projects/unit_segmentation",
                json={"split": "train", "sample_interval_seconds": 5},
            )
            assert created.status_code == 200
            saved = await client.put(
                "/api/videos/video-id/annotation-projects/unit_segmentation/frames/1",
                json={"kind": "detection", "status": "saved", "boxes": []},
            )
            assert saved.status_code == 200
            assert saved.json()["counts"]["saved"] == 1
            wrong_kind = await client.put(
                "/api/videos/video-id/annotation-projects/unit_segmentation/frames/2",
                json={"kind": "classification", "status": "saved", "crops": []},
            )
            assert wrong_kind.status_code == 422
            reset = await client.delete("/api/videos/video-id/annotation-projects/unit_segmentation")
            assert reset.status_code == 204
            assert (await client.get("/api/videos/video-id/annotation-projects/unit_segmentation")).json() is None

    asyncio.run(exercise())
