"""Normalized private match-graph ORM models written by ingestion."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class ItemMetadata(Base):
    """Store canonical item identity and family for one patch and TFT set."""

    __tablename__ = "item_metadata"
    __table_args__ = (
        Index("ix_item_metadata_type", "patch", "tft_set_number", "item_type"),
    )

    patch: Mapped[str] = mapped_column(String, primary_key=True)
    tft_set_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_api_name: Mapped[str] = mapped_column(String, primary_key=True)
    item_name: Mapped[str] = mapped_column(String, nullable=False)
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)


class RawMatch(Base):
    """Represent one Riot match without repeating metadata per participant."""

    __tablename__ = "raw_matches"
    __table_args__ = (
        Index("ix_raw_matches_queue_patch_set", "queue_id", "patch", "tft_set_number"),
    )

    match_id: Mapped[str] = mapped_column(String, primary_key=True)
    region: Mapped[str] = mapped_column(String, nullable=False)
    platform: Mapped[str | None] = mapped_column(String)
    data_version: Mapped[str | None] = mapped_column(String)
    game_datetime: Mapped[int] = mapped_column(BigInteger, nullable=False)
    game_creation: Mapped[int | None] = mapped_column(BigInteger)
    game_length: Mapped[float] = mapped_column(Float, nullable=False)
    game_version: Mapped[str] = mapped_column(String, nullable=False)
    patch: Mapped[str | None] = mapped_column(String)
    game_id: Mapped[int | None] = mapped_column(BigInteger)
    queue_id: Mapped[int] = mapped_column(Integer, nullable=False)
    map_id: Mapped[int | None] = mapped_column(Integer)
    tft_set_number: Mapped[int | None] = mapped_column(Integer)
    tft_set_core_name: Mapped[str | None] = mapped_column(String)
    tft_game_type: Mapped[str | None] = mapped_column(String)
    game_variation: Mapped[str | None] = mapped_column(String)
    end_of_game_result: Mapped[str | None] = mapped_column(String)
    ingested_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    boards: Mapped[list["PlayerBoard"]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    processed_scopes: Mapped[list["AnalysisProcessedMatch"]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PlayerBoard(Base):
    """Represent one participant's final board and match outcome."""

    __tablename__ = "player_boards"
    __table_args__ = (
        ForeignKeyConstraint(
            ["match_id"],
            ["raw_matches.match_id"],
            name="fk_player_boards_match",
            ondelete="CASCADE",
        ),
        Index("ix_player_boards_placement", "placement"),
    )

    match_id: Mapped[str] = mapped_column(String, primary_key=True)
    puuid: Mapped[str] = mapped_column(String, primary_key=True)
    riot_id_game_name: Mapped[str | None] = mapped_column(String)
    riot_id_tagline: Mapped[str | None] = mapped_column(String)
    placement: Mapped[int | None] = mapped_column(Integer)
    level: Mapped[int | None] = mapped_column(Integer)
    last_round: Mapped[int | None] = mapped_column(Integer)
    players_eliminated: Mapped[int | None] = mapped_column(Integer)
    total_damage_to_players: Mapped[int | None] = mapped_column(Integer)
    gold_left: Mapped[int | None] = mapped_column(Integer)
    time_eliminated: Mapped[float | None] = mapped_column(Float)
    win: Mapped[bool | None] = mapped_column(Boolean)
    partner_group_id: Mapped[int | None] = mapped_column(Integer)
    companion_content_id: Mapped[str | None] = mapped_column(String)
    companion_item_id: Mapped[int | None] = mapped_column(Integer)
    companion_skin_id: Mapped[int | None] = mapped_column(Integer)
    companion_species: Mapped[str | None] = mapped_column(String)

    match: Mapped[RawMatch] = relationship(back_populates="boards")
    units: Mapped[list["BoardUnit"]] = relationship(
        back_populates="board",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="BoardUnit.unit_idx",
    )
    trait_rows: Mapped[list["BoardTrait"]] = relationship(
        back_populates="board",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __init__(self, **kwargs: Any) -> None:
        """Accept packed legacy fixture fields without persisting them.

        This compatibility path is deliberately not used by ingestion. It lets
        maintenance code inspect old payload-shaped objects while all durable
        relational data remains normalized.
        """
        self._legacy_comp_name = kwargs.pop("comp_name", None)
        self._legacy_comp_code = kwargs.pop("comp_code", None)
        self._legacy_star_levels = kwargs.pop("star_levels", None)
        packed_traits = kwargs.pop("traits", None)
        super().__init__(**kwargs)
        if packed_traits:
            self._legacy_traits = str(packed_traits)
            for segment in str(packed_traits).split("#"):
                name, separator, tier_text = segment.rpartition("_")
                if not separator or not name:
                    continue
                try:
                    tier = int(tier_text)
                except ValueError:
                    continue
                self.trait_rows.append(
                    BoardTrait(
                        trait_name=name,
                        num_units=None,
                        style=1,
                        tier_current=tier,
                        tier_total=None,
                    )
                )

    @property
    def comp_name(self) -> str | None:
        """Return the legacy display composition name when supplied."""
        return getattr(self, "_legacy_comp_name", None)

    @property
    def comp_code(self) -> str | None:
        """Return the supplied legacy composition code or derive it from units."""
        legacy = getattr(self, "_legacy_comp_code", None)
        if legacy is not None:
            return legacy
        names = [unit.unit_name for unit in sorted(self.units, key=lambda row: row.unit_idx)]
        return "#".join(names) if names else None

    @property
    def star_levels(self) -> str:
        """Return the packed legacy star-level string for compatibility."""
        legacy = getattr(self, "_legacy_star_levels", None)
        if legacy is not None:
            return legacy
        return "".join(
            str(unit.star_level)
            for unit in sorted(self.units, key=lambda row: row.unit_idx)
        )

    @property
    def traits(self) -> str:
        """Return active board traits in the legacy packed representation."""
        legacy = getattr(self, "_legacy_traits", None)
        if legacy is not None:
            return legacy
        active = sorted(
            (row.trait_name, row.tier_current)
            for row in self.trait_rows
            if (row.style or 0) > 0 and (row.tier_current or 0) > 0
        )
        return "#".join(f"{name}_{tier}" for name, tier in active)


class BoardUnit(Base):
    """Represent one exact unit copy identified by board occurrence index."""

    __tablename__ = "board_units"
    __table_args__ = (
        ForeignKeyConstraint(
            ["match_id", "puuid"],
            ["player_boards.match_id", "player_boards.puuid"],
            name="fk_board_units_board",
            ondelete="CASCADE",
        ),
        Index("ix_board_units_unit_name", "unit_name"),
    )

    match_id: Mapped[str] = mapped_column(String, primary_key=True)
    puuid: Mapped[str] = mapped_column(String, primary_key=True)
    unit_idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_name: Mapped[str] = mapped_column(String, nullable=False)
    star_level: Mapped[int] = mapped_column(Integer, nullable=False)
    cost: Mapped[int | None] = mapped_column(Integer)

    board: Mapped[PlayerBoard] = relationship(back_populates="units")
    items: Mapped[list["UnitItem"]] = relationship(
        back_populates="unit",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="UnitItem.item_slot",
    )

    def __init__(self, **kwargs: Any) -> None:
        """Accept legacy packed item and placement fields for fixture compatibility."""
        legacy_items = [kwargs.pop(name, None) for name in ("item1", "item2", "item3")]
        self._legacy_placement = kwargs.pop("placement", None)
        super().__init__(**kwargs)
        # Ingestion constructs normalized UnitItem rows, while old fixtures may
        # still rely on these transient packed values.
        self._legacy_items = legacy_items

    def _item_at(self, slot: int) -> str | None:
        """Resolve one normalized item slot with a legacy-fixture fallback."""
        normalized = {row.item_slot: row.item_name for row in self.items}
        if slot in normalized:
            return normalized[slot]
        legacy = getattr(self, "_legacy_items", [])
        return legacy[slot] if slot < len(legacy) else None

    @property
    def item1(self) -> str | None:
        """Return the first item slot through the compatibility interface."""
        return self._item_at(0)

    @property
    def item2(self) -> str | None:
        """Return the second item slot through the compatibility interface."""
        return self._item_at(1)

    @property
    def item3(self) -> str | None:
        """Return the third item slot through the compatibility interface."""
        return self._item_at(2)

    @property
    def placement(self) -> int | None:
        """Return the owning board placement or its legacy-fixture fallback."""
        if self.board is not None and self.board.placement is not None:
            return self.board.placement
        return getattr(self, "_legacy_placement", None)


class UnitItem(Base):
    """Represent one completed item bound to an exact unit copy and slot."""

    __tablename__ = "unit_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["match_id", "puuid", "unit_idx"],
            ["board_units.match_id", "board_units.puuid", "board_units.unit_idx"],
            name="fk_unit_items_unit",
            ondelete="CASCADE",
        ),
        CheckConstraint("item_slot >= 0 AND item_slot <= 2", name="ck_unit_items_slot"),
        Index("ix_unit_items_item_name", "item_name"),
        Index("ix_unit_items_item_api_name", "item_api_name"),
    )

    match_id: Mapped[str] = mapped_column(String, primary_key=True)
    puuid: Mapped[str] = mapped_column(String, primary_key=True)
    unit_idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_slot: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_api_name: Mapped[str] = mapped_column(String, nullable=False)
    item_name: Mapped[str] = mapped_column(String, nullable=False)

    unit: Mapped[BoardUnit] = relationship(back_populates="items")

    def __init__(self, **kwargs: Any) -> None:
        """Translate legacy item fixture fields to their normalized equivalents."""
        idx = kwargs.pop("idx", None)
        self._legacy_unit_name = kwargs.pop("unit_name", None)
        self._legacy_placement = kwargs.pop("placement", None)
        kwargs.pop("other_item1", None)
        kwargs.pop("other_item2", None)
        kwargs.setdefault("item_api_name", kwargs.get("item_name"))
        kwargs.setdefault("unit_idx", 0)
        if "item_slot" not in kwargs:
            kwargs["item_slot"] = 0 if idx is None else idx
        super().__init__(**kwargs)

    @property
    def idx(self) -> int:
        """Return the normalized item slot under its legacy name."""
        return self.item_slot

    @property
    def unit_name(self) -> str | None:
        """Return the owning unit name or its legacy-fixture fallback."""
        if self.unit is not None:
            return self.unit.unit_name
        return getattr(self, "_legacy_unit_name", None)

    @property
    def placement(self) -> int | None:
        """Return the owning board placement or its legacy-fixture fallback."""
        if self.unit is not None:
            return self.unit.placement
        return getattr(self, "_legacy_placement", None)

    @property
    def other_item1(self) -> str | None:
        """Retain the removed legacy co-item field as an empty property."""
        return None

    @property
    def other_item2(self) -> str | None:
        """Retain the second removed legacy co-item field as an empty property."""
        return None


class BoardTrait(Base):
    """Represent one raw trait state, including inactive trait rows."""

    __tablename__ = "board_traits"
    __table_args__ = (
        ForeignKeyConstraint(
            ["match_id", "puuid"],
            ["player_boards.match_id", "player_boards.puuid"],
            name="fk_board_traits_board",
            ondelete="CASCADE",
        ),
        Index("ix_board_traits_name_tier", "trait_name", "tier_current"),
    )

    match_id: Mapped[str] = mapped_column(String, primary_key=True)
    puuid: Mapped[str] = mapped_column(String, primary_key=True)
    trait_name: Mapped[str] = mapped_column(String, primary_key=True)
    num_units: Mapped[int | None] = mapped_column(Integer)
    style: Mapped[int | None] = mapped_column(Integer)
    tier_current: Mapped[int | None] = mapped_column(Integer)
    tier_total: Mapped[int | None] = mapped_column(Integer)

    board: Mapped[PlayerBoard] = relationship(back_populates="trait_rows")


# Compatibility aliases for callers that used the old per-unit class names.
PlayerUnit = BoardUnit
PlayerItem = UnitItem

RAW_GRAPH_MODELS = (RawMatch, PlayerBoard, BoardUnit, UnitItem, BoardTrait, ItemMetadata)


__all__ = [
    "BoardTrait",
    "BoardUnit",
    "ItemMetadata",
    "PlayerBoard",
    "PlayerItem",
    "PlayerUnit",
    "RAW_GRAPH_MODELS",
    "RawMatch",
    "UnitItem",
]
