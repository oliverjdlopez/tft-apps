"""Model-visible aggregate query-table ORM models."""

from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Float, ForeignKeyConstraint, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

# Rollup sentinels are part of the public aggregate contract.
ALL_STARS = 0
ALL_TRAIT_TIERS = 0
ITEM_OVERALL_UNIT_NAME = "__overall__"


class _OutcomeCounters:
    """Provide shared internal additive counters to aggregate mappings."""

    placement_sum: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    outcome_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    top4_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    win_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class UnitStatQueryTable(_OutcomeCounters, Base):
    """Store scoped placement and pick-rate aggregates by unit and star level."""

    __tablename__ = "unit_stats"
    __table_args__ = (
        ForeignKeyConstraint(["scope_id"], ["analysis_scopes.scope_id"], ondelete="CASCADE"),
        Index("ix_unit_stats_name", "unit_name", "star_level"),
    )

    scope_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_name: Mapped[str] = mapped_column(String, primary_key=True)
    star_level: Mapped[int] = mapped_column(Integer, primary_key=True)
    tft_set_number: Mapped[int] = mapped_column(Integer, nullable=False)
    cost: Mapped[int | None] = mapped_column(Integer)
    games: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    avg_placement: Mapped[float | None] = mapped_column(Float)
    top4_rate: Mapped[float | None] = mapped_column(Float)
    win_rate: Mapped[float | None] = mapped_column(Float)
    pick_rate: Mapped[float | None] = mapped_column(Float)
    universe_games: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class ItemStatQueryTable(_OutcomeCounters, Base):
    """Store scoped item aggregates overall and by unit holder."""

    __tablename__ = "item_stats"
    __table_args__ = (
        ForeignKeyConstraint(["scope_id"], ["analysis_scopes.scope_id"], ondelete="CASCADE"),
        Index("ix_item_stats_name_holder", "item_name", "unit_name"),
        Index("ix_item_stats_type_holder", "scope_id", "item_type", "unit_name"),
    )

    scope_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_name: Mapped[str] = mapped_column(String, primary_key=True)
    unit_name: Mapped[str] = mapped_column(String, primary_key=True)
    item_api_name: Mapped[str] = mapped_column(String, nullable=False)
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)
    tft_set_number: Mapped[int] = mapped_column(Integer, nullable=False)
    holds: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    boards: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    avg_placement: Mapped[float | None] = mapped_column(Float)
    top4_rate: Mapped[float | None] = mapped_column(Float)
    win_rate: Mapped[float | None] = mapped_column(Float)
    pick_rate_per_board: Mapped[float | None] = mapped_column(Float)
    universe_games: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    def __init__(self, **kwargs: Any) -> None:
        """Accept legacy fixtures while making missing metadata explicit.

        Args:
            **kwargs: ORM values for one item aggregate.
        """
        kwargs.setdefault("item_api_name", kwargs.get("item_name"))
        kwargs.setdefault("item_type", "unknown")
        super().__init__(**kwargs)


class TraitStatQueryTable(_OutcomeCounters, Base):
    """Store scoped placement and pick-rate aggregates by trait tier."""

    __tablename__ = "trait_stats"
    __table_args__ = (
        ForeignKeyConstraint(["scope_id"], ["analysis_scopes.scope_id"], ondelete="CASCADE"),
        Index("ix_trait_stats_name_tier", "trait_name", "tier"),
    )

    scope_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trait_name: Mapped[str] = mapped_column(String, primary_key=True)
    tier: Mapped[int] = mapped_column(Integer, primary_key=True)
    tft_set_number: Mapped[int] = mapped_column(Integer, nullable=False)
    games: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    avg_placement: Mapped[float | None] = mapped_column(Float)
    top4_rate: Mapped[float | None] = mapped_column(Float)
    win_rate: Mapped[float | None] = mapped_column(Float)
    pick_rate: Mapped[float | None] = mapped_column(Float)
    universe_games: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class UnitLoadoutStatQueryTable(_OutcomeCounters, Base):
    """Store scoped aggregates for canonical item loadouts on units."""

    __tablename__ = "unit_loadout_stats"
    __table_args__ = (
        ForeignKeyConstraint(["scope_id"], ["analysis_scopes.scope_id"], ondelete="CASCADE"),
        Index("ix_loadout_stats_unit", "unit_name", "star_level"),
    )

    scope_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_name: Mapped[str] = mapped_column(String, primary_key=True)
    star_level: Mapped[int] = mapped_column(Integer, primary_key=True)
    loadout_key: Mapped[str] = mapped_column(String, primary_key=True)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    item_1: Mapped[str | None] = mapped_column(String)
    item_2: Mapped[str | None] = mapped_column(String)
    item_3: Mapped[str | None] = mapped_column(String)
    boards: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    avg_placement: Mapped[float | None] = mapped_column(Float)
    top4_rate: Mapped[float | None] = mapped_column(Float)
    win_rate: Mapped[float | None] = mapped_column(Float)
    unit_boards: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    loadout_pick_rate: Mapped[float | None] = mapped_column(Float)


QUERY_TABLE_MODELS = (
    UnitStatQueryTable,
    ItemStatQueryTable,
    TraitStatQueryTable,
    UnitLoadoutStatQueryTable,
)


__all__ = [
    "ALL_STARS",
    "ALL_TRAIT_TIERS",
    "ITEM_OVERALL_UNIT_NAME",
    "ItemStatQueryTable",
    "QUERY_TABLE_MODELS",
    "TraitStatQueryTable",
    "UnitLoadoutStatQueryTable",
    "UnitStatQueryTable",
]
