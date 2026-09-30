"""State carried between the Drive API and background clip workers."""

from dataclasses import dataclass, field

from pydantic import BaseModel, Field


class DriveUploadOptions(BaseModel):
    """Select rounds and bounded clip timing for one immutable upload batch."""

    key_rounds_only: bool = False
    offset_seconds: float = Field(default=0, ge=-3600, le=3600, allow_inf_nan=False)
    duration_seconds: float = Field(default=60, ge=1, le=180, allow_inf_nan=False)


@dataclass
class UploadJob:
    """Track one immutable set of parsed rounds and resumable batch progress."""

    id: str
    video_id: str
    classification_id: str
    clips: list[dict]
    options: DriveUploadOptions = field(default_factory=DriveUploadOptions)
    status: str = "running"
    completed: int = 0
    folder_id: str | None = None
    error: str | None = None
    files: list[dict] = field(default_factory=list)

    def payload(self) -> dict:
        """Expose progress without local paths or Google credentials."""
        return {"id": self.id, "status": self.status, "completed": self.completed,
                "total": len(self.clips), "error": self.error, "options": self.options.model_dump(),
                "folder_url": f"https://drive.google.com/drive/folders/{self.folder_id}" if self.folder_id else None}
