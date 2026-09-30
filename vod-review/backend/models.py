from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

try:
    from .constants import (
        DEFAULT_BATCH_SIZE,
        MAX_BATCH_SIZE,
        MAX_SAMPLE_INTERVAL_SECONDS,
        MIN_BATCH_SIZE,
        MIN_SAMPLE_INTERVAL_SECONDS,
        SAMPLE_INTERVAL_SECONDS,
    )
except ImportError:  # Running modules directly from the backend directory.
    from constants import (
        DEFAULT_BATCH_SIZE,
        MAX_BATCH_SIZE,
        MAX_SAMPLE_INTERVAL_SECONDS,
        MIN_BATCH_SIZE,
        MIN_SAMPLE_INTERVAL_SECONDS,
        SAMPLE_INTERVAL_SECONDS,
    )


class BoundingBox(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)
    frame_time: float = Field(ge=0)

    @model_validator(mode="after")
    def fits_inside_frame(self) -> "BoundingBox":
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("Bounding box must stay inside the video")
        return self


DownloadQuality = Literal["480p", "720p", "1080p", "best"]
DownloadMediaType = Literal["video", "audio"]


class VideoUrlRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, gt=0)
    checkpoint_interval_seconds: float | None = Field(default=None, ge=60, le=6 * 60 * 60)
    quality: DownloadQuality = "720p"
    target_fps: float | None = Field(default=None, ge=1, le=120, allow_inf_nan=False)
    media_type: DownloadMediaType = "video"
    transcribe: bool = False

    @model_validator(mode="after")
    def has_valid_download_range(self) -> "VideoUrlRequest":
        if self.start_seconds is not None and self.end_seconds is not None:
            if self.end_seconds <= self.start_seconds:
                raise ValueError("Download end must be after its start")
        return self


class ReplayDiscoveryRequest(BaseModel):
    sources: list[str] = Field(min_length=1, max_length=25)

    @model_validator(mode="after")
    def has_unique_sources(self) -> "ReplayDiscoveryRequest":
        normalized = [source.strip() for source in self.sources]
        if any(not source or len(source) > 2048 for source in normalized):
            raise ValueError("Each replay source must be a non-empty URL")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Replay sources must be unique")
        self.sources = normalized
        return self


class ProcessingRequest(BaseModel):
    batch_size: int = Field(default=DEFAULT_BATCH_SIZE, ge=MIN_BATCH_SIZE, le=MAX_BATCH_SIZE)
    reuse_cached_crops: bool = False
    sample_interval_seconds: float = Field(
        default=SAMPLE_INTERVAL_SECONDS,
        ge=0,
        allow_inf_nan=False,
        le=MAX_SAMPLE_INTERVAL_SECONDS,
    )


class WispProcessingRequest(BaseModel):
    sample_interval_seconds: float = Field(default=0, ge=0, le=3600, allow_inf_nan=False)


class RoundExportClip(BaseModel):
    label: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._-]+$")
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def has_valid_duration(self) -> "RoundExportClip":
        duration = self.end_seconds - self.start_seconds
        if duration <= 0:
            raise ValueError("Clip end must be after its start")
        if duration > 180:
            raise ValueError("Each round clip must be no longer than 180 seconds")
        return self


class RoundExportRequest(BaseModel):
    game_number: int = Field(ge=1, le=999)
    clips: list[RoundExportClip] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def has_bounded_total_duration(self) -> "RoundExportRequest":
        total_duration = sum(clip.end_seconds - clip.start_seconds for clip in self.clips)
        if total_duration > 30 * 60:
            raise ValueError("The combined export must be no longer than 30 minutes")
        return self


TaskKey = Literal["unit_segmentation", "text_detection", "round_classifier", "unit_id", "augment_classifier"]
DatasetSplit = Literal["train", "val"]


class AnnotationProjectRequest(BaseModel):
    split: DatasetSplit
    sample_interval_seconds: float = Field(
        default=SAMPLE_INTERVAL_SECONDS,
        ge=MIN_SAMPLE_INTERVAL_SECONDS,
        le=MAX_SAMPLE_INTERVAL_SECONDS,
    )


class AnnotationBox(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def fits_inside_frame(self) -> "AnnotationBox":
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("Annotation box must stay inside the video")
        return self


class ClassificationCrop(AnnotationBox):
    label_id: str = Field(min_length=1, max_length=128)


class DetectionFrameRequest(BaseModel):
    kind: Literal["detection"]
    status: Literal["saved", "skipped"] = "saved"
    boxes: list[AnnotationBox] = Field(default_factory=list)


class ClassificationFrameRequest(BaseModel):
    kind: Literal["classification"]
    status: Literal["saved", "skipped"] = "saved"
    crops: list[ClassificationCrop] = Field(default_factory=list)


class TemplateFrameRequest(BaseModel):
    kind: Literal["template"]
    status: Literal["saved", "skipped"] = "saved"
    label_id: str | None = Field(default=None, min_length=1, max_length=128)


AnnotationFrameRequest = Annotated[
    DetectionFrameRequest | ClassificationFrameRequest | TemplateFrameRequest,
    Field(discriminator="kind"),
]
