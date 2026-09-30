"""Private immutable composition snapshots and append-only experiment results."""

from datetime import datetime
from typing import Any
from sqlalchemy import JSON, String, Float, ForeignKey, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, utc_now


class CompositionSnapshot(Base):
    """Retain anonymous inputs independently of source rebuilds and deletions."""

    __tablename__ = "composition_snapshots"
    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class CompositionSnapshotSummary(Base):
    """Cache the small, immutable snapshot fields shown beside every saved run.

    History and run polling read this row instead of the snapshot payload, which
    can hold hundreds of megabytes of frozen boards for full-population runs.
    """

    __tablename__ = "composition_snapshot_summaries"
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("composition_snapshots.snapshot_id"), primary_key=True
    )
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class CompositionExperiment(Base):
    """Persist the queue and one immutable terminal experiment result."""

    __tablename__ = "composition_experiments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','completed','cancelled','interrupted','failed')",
            name="ck_composition_experiment_status",
        ),
    )
    experiment_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("composition_snapshots.snapshot_id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(default=utc_now, index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(40), default="queued")
    elapsed_seconds: Mapped[float] = mapped_column(Float, default=0)
    request: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(String)


COMPOSITION_MODELS = (
    CompositionSnapshot,
    CompositionSnapshotSummary,
    CompositionExperiment,
)
