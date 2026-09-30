"""Private player-authored flowchart workspaces and saved groups for the desktop Flowchart tab."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utc_now


class DevWorkspace(Base):
    """Store one named patch workspace document with an optimistic-lock revision.

    The ``document`` column holds a validated ``PatchWorkspace`` JSON document
    (see ``services.flowchart.models``). It is never read by match analytics,
    projections, or model-facing tools.
    """

    __tablename__ = "chat_tft_dev_workspaces"
    workspace_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)
    document: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class DevFlowchartGroup(Base):
    """Store one named, reusable group of flowchart elements for the Flowchart library.

    The ``fragment`` column holds a validated ``FlowchartFragment`` (elements
    and the connections between them, positioned relative to the group's
    top-left corner). Groups are shared across workspaces; ``set_number``
    records the set they were built for, since entity chips are set-specific.
    """

    __tablename__ = "chat_tft_dev_flowchart_groups"
    group_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    set_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)
    fragment: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


WORKSPACE_MODELS = (DevWorkspace, DevFlowchartGroup)
