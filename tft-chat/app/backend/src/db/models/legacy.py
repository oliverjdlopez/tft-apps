"""Retained migration and compatibility ORM mappings."""

from __future__ import annotations

from sqlalchemy import BigInteger, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AllMatch(Base):
    """Map the denormalized legacy match-participant source table."""

    __tablename__ = "all_matches"
    __table_args__ = (Index("ix_all_matches_queue_patch", "queue_id", "patch"),)

    match_id: Mapped[str] = mapped_column(String, primary_key=True)
    puuid: Mapped[str] = mapped_column(String, primary_key=True)
    region: Mapped[str] = mapped_column(String, nullable=False)
    platform: Mapped[str | None] = mapped_column(String)
    game_datetime: Mapped[int] = mapped_column(BigInteger, nullable=False)
    game_length: Mapped[float] = mapped_column(Float, nullable=False)
    game_version: Mapped[str] = mapped_column(String, nullable=False)
    patch: Mapped[str | None] = mapped_column(String)
    queue_id: Mapped[int] = mapped_column(Integer, nullable=False)
    tft_set_number: Mapped[int | None] = mapped_column(Integer)
    tft_set_core_name: Mapped[str | None] = mapped_column(String)
    ingested_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class Match(Base):
    """Map the current-scope board projection retained for API compatibility."""

    __tablename__ = "matches"
    match_id: Mapped[str] = mapped_column(String, primary_key=True)
    puuid: Mapped[str] = mapped_column(String, primary_key=True)
    region: Mapped[str] = mapped_column(String, nullable=False)
    platform: Mapped[str | None] = mapped_column(String)
    game_datetime: Mapped[int] = mapped_column(BigInteger, nullable=False)
    game_length: Mapped[float] = mapped_column(Float, nullable=False)
    game_version: Mapped[str] = mapped_column(String, nullable=False)
    tft_set_number: Mapped[int | None] = mapped_column(Integer)
    tft_set_core_name: Mapped[str | None] = mapped_column(String)
    ingested_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class LegacyPlayerBoard(Base):
    """Map packed legacy participant-board rows during migration."""

    __tablename__ = "player_board"
    match_id: Mapped[str] = mapped_column(String, primary_key=True)
    puuid: Mapped[str] = mapped_column(String, primary_key=True)
    comp_name: Mapped[str | None] = mapped_column(String)
    comp_code: Mapped[str | None] = mapped_column(String)
    star_levels: Mapped[str] = mapped_column(String, nullable=False)
    traits: Mapped[str] = mapped_column(String, nullable=False)
    placement: Mapped[int | None] = mapped_column(Integer)


class LegacyPlayerUnit(Base):
    """Map packed legacy unit rows during migration and rollback."""

    __tablename__ = "player_units"
    __table_args__ = (Index("ix_player_units_unit_name", "unit_name"),)
    match_id: Mapped[str] = mapped_column(String, primary_key=True)
    puuid: Mapped[str] = mapped_column(String, primary_key=True)
    unit_name: Mapped[str] = mapped_column(String, primary_key=True)
    unit_idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    star_level: Mapped[int] = mapped_column(Integer, nullable=False)
    item1: Mapped[str | None] = mapped_column(String)
    item2: Mapped[str | None] = mapped_column(String)
    item3: Mapped[str | None] = mapped_column(String)
    placement: Mapped[int] = mapped_column(Integer, nullable=False)
    cost: Mapped[int] = mapped_column(Integer, nullable=False)


class LegacyPlayerItem(Base):
    """Map packed legacy item rows during migration and rollback."""

    __tablename__ = "player_items"
    __table_args__ = (
        Index("ix_player_items_item_name", "item_name"),
        Index("ix_player_items_unit_name", "unit_name"),
    )
    match_id: Mapped[str] = mapped_column(String, primary_key=True)
    puuid: Mapped[str] = mapped_column(String, primary_key=True)
    unit_name: Mapped[str] = mapped_column(String, primary_key=True)
    item_name: Mapped[str] = mapped_column(String, primary_key=True)
    idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    placement: Mapped[int] = mapped_column(Integer, nullable=False)
    other_item1: Mapped[str | None] = mapped_column(String)
    other_item2: Mapped[str | None] = mapped_column(String)


LEGACY_MODELS = (AllMatch, Match, LegacyPlayerBoard, LegacyPlayerUnit, LegacyPlayerItem)


__all__ = [
    "AllMatch",
    "LEGACY_MODELS",
    "LegacyPlayerBoard",
    "LegacyPlayerItem",
    "LegacyPlayerUnit",
    "Match",
]
