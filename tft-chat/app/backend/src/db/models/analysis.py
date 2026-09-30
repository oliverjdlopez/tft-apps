"""Private scoped-analysis ledger and anonymous fact ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utc_now
from .raw import RawMatch


class AnalysisScope(Base):
    """Track one patch, queue, and TFT-set analytics population."""

    __tablename__ = "analysis_scopes"
    __table_args__ = (
        UniqueConstraint("patch", "queue_id", "tft_set_number", name="uq_analysis_scope"),
        Index(
            "uq_analysis_scopes_one_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
            sqlite_where=text("is_active = 1"),
        ),
    )

    scope_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patch: Mapped[str] = mapped_column(String, nullable=False)
    queue_id: Mapped[int] = mapped_column(Integer, nullable=False)
    tft_set_number: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    universe_boards: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_details: Mapped[str | None] = mapped_column(Text)

    processed_matches: Mapped[list["AnalysisProcessedMatch"]] = relationship(
        back_populates="scope",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AnalysisProcessedMatch(Base):
    """Record a raw match already incorporated into an analysis scope."""

    __tablename__ = "analysis_processed_matches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["scope_id"],
            ["analysis_scopes.scope_id"],
            name="fk_processed_scope",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["match_id"],
            ["raw_matches.match_id"],
            name="fk_processed_match",
            ondelete="CASCADE",
        ),
        Index("ix_processed_matches_match_id", "match_id"),
    )

    scope_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[str] = mapped_column(String, primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    board_count: Mapped[int] = mapped_column(Integer, nullable=False)

    scope: Mapped[AnalysisScope] = relationship(back_populates="processed_matches")
    match: Mapped[RawMatch] = relationship(back_populates="processed_scopes")


ANALYSIS_FACT_SCHEMA_VERSION = 3


# Set-specific wide schemas intentionally trade migrations at set boundaries
# for fast, fixed-column board comparisons. Values are display-name keyed here
# while the database follows the repository's snake_case column convention.
SET_17_UNIT_COLUMNS = {
    "Aatrox": "aatrox",
    "Akali": "akali",
    "Apex Primordian": "apex_primordian",
    "Artifact Item Anvil": "artifact_item_anvil",
    "Aurelion Sol": "aurelion_sol",
    "Aurora": "aurora",
    "Bard": "bard",
    "Bel'Veth": "bel_veth",
    "Bia & Bayin": "bia_and_bayin",
    "Blitzcrank": "blitzcrank",
    "Briar": "briar",
    "Caitlyn": "caitlyn",
    "Cho'Gath": "cho_gath",
    "Completed Item Anvil": "completed_item_anvil",
    "Component Anvil": "component_anvil",
    "Corki": "corki",
    "Cosmic Bruiser": "cosmic_bruiser",
    "Cosmic Elder Dragon": "cosmic_elder_dragon",
    "Cosmic Flutterbye": "cosmic_flutterbye",
    "Cosmic Gromp": "cosmic_gromp",
    "Cosmic Scrapper": "cosmic_scrapper",
    "Cosmic Squid": "cosmic_squid",
    "Diana": "diana",
    "Ezreal": "ezreal",
    "Fiora": "fiora",
    "Fizz": "fizz",
    "Gnar": "gnar",
    "Golem": "golem",
    "Gragas": "gragas",
    "Graves": "graves",
    "Gwen": "gwen",
    "Illaoi": "illaoi",
    "Jax": "jax",
    "Jhin": "jhin",
    "Jinx": "jinx",
    "Kai'Sa": "kai_sa",
    "Karma": "karma",
    "Kindred": "kindred",
    "LeBlanc": "le_blanc",
    "Leona": "leona",
    "Lissandra": "lissandra",
    "Lulu": "lulu",
    "Maokai": "maokai",
    "Master Yi": "master_yi",
    "Meepsie": "meepsie",
    "Mercenary Chest": "mercenary_chest",
    "Milio": "milio",
    "Mini Black Hole": "mini_black_hole",
    "Miss Fortune": "miss_fortune",
    "Mordekaiser": "mordekaiser",
    "Morgana": "morgana",
    "Nami": "nami",
    "Nasus": "nasus",
    "Nunu & Willump": "nunu_and_willump",
    "Ornn": "ornn",
    "Pantheon": "pantheon",
    "Poppy": "poppy",
    "Pyke": "pyke",
    "Rammus": "rammus",
    "Rek'Sai": "rek_sai",
    "Rhaast": "rhaast",
    "Rift Scuttler": "rift_scuttler",
    "Riven": "riven",
    "Samira": "samira",
    "Shen": "shen",
    "Sona": "sona",
    "Support item anvil": "support_item_anvil",
    "Tahm Kench": "tahm_kench",
    "Talon": "talon",
    "Teemo": "teemo",
    "The Mighty Mech": "the_mighty_mech",
    "TimebreakerCore": "timebreaker_core",
    "Tome of Traits": "tome_of_traits",
    "Training Dummy": "training_dummy",
    "Twisted Fate": "twisted_fate",
    "Urgot": "urgot",
    "Veigar": "veigar",
    "Vex": "vex",
    "Viktor": "viktor",
    "Xayah": "xayah",
    "Zed": "zed",
    "Zoe": "zoe",
}

SET_17_TRAIT_COLUMNS = {
    "Anima": "anima",
    "Arbiter": "arbiter",
    "Bastion": "bastion",
    "Brawler": "brawler",
    "Bulwark": "bulwark",
    "Challenger": "challenger",
    "Choose Trait": "choose_trait",
    "Commander": "commander",
    "Conduit": "conduit",
    "Dark Lady": "dark_lady",
    "Dark Star": "dark_star",
    "Divine Duelist": "divine_duelist",
    "Doomer": "doomer",
    "Eradicator": "eradicator",
    "Factory New": "factory_new",
    "Fateweaver": "fateweaver",
    "Galaxy Hunter": "galaxy_hunter",
    "God-Blessed": "god_blessed",
    "Gun Goddess": "gun_goddess",
    "Marauder": "marauder",
    "Mecha": "mecha",
    "Meeple": "meeple",
    "N.O.V.A.": "n_o_v_a",
    "Oracle": "oracle",
    "Party Animal": "party_animal",
    "Primordian": "primordian",
    "Psionic": "psionic",
    "Redeemer": "redeemer",
    "Replicator": "replicator",
    "Rogue": "rogue",
    "Shepherd": "shepherd",
    "Sniper": "sniper",
    "Space Groove": "space_groove",
    "Stargazer": "stargazer",
    "Timebreaker": "timebreaker",
    "Vanguard": "vanguard",
    "Voyager": "voyager",
}


class AnalysisFactBuild(Base):
    """Mark publication and validation state for one anonymous fact layer."""

    __tablename__ = "analysis_fact_builds"
    __table_args__ = (
        ForeignKeyConstraint(
            ["scope_id"], ["analysis_scopes.scope_id"], ondelete="CASCADE"
        ),
        CheckConstraint(
            "status IN ('incomplete', 'ready', 'dirty')",
            name="ck_analysis_fact_build_status",
        ),
    )

    scope_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=ANALYSIS_FACT_SCHEMA_VERSION
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="incomplete")
    processed_match_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lobby_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    board_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    unit_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    item_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    trait_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_details: Mapped[str | None] = mapped_column(Text)


class AnalysisBoard(Base):
    """Represent one anonymous board in a private scope-owned fact layer."""

    __tablename__ = "analysis_boards"
    __table_args__ = (
        ForeignKeyConstraint(
            ["scope_id"], ["analysis_scopes.scope_id"], ondelete="CASCADE"
        ),
        Index("ix_analysis_boards_scope_lobby", "scope_id", "lobby_key"),
        Index(
            "ix_analysis_boards_scope_outcomes",
            "scope_id",
            "placement",
            "level",
            "region",
            "platform",
        ),
        Index(
            "ix_analysis_boards_scope_shape",
            "scope_id",
            "unit_count",
            "completed_item_count",
        ),
    )

    scope_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    board_key: Mapped[str] = mapped_column(String(36), primary_key=True)
    lobby_key: Mapped[str] = mapped_column(String(36), nullable=False)
    placement: Mapped[int | None] = mapped_column(Integer)
    level: Mapped[int | None] = mapped_column(Integer)
    last_round: Mapped[int | None] = mapped_column(Integer)
    eliminations: Mapped[int | None] = mapped_column(Integer)
    player_damage: Mapped[int | None] = mapped_column(Integer)
    gold_left: Mapped[int | None] = mapped_column(Integer)
    elimination_time: Mapped[float | None] = mapped_column(Float)
    win: Mapped[bool | None] = mapped_column(Boolean)
    region: Mapped[str] = mapped_column(String, nullable=False)
    platform: Mapped[str | None] = mapped_column(String)
    game_length: Mapped[float] = mapped_column(Float, nullable=False)
    unit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    units: Mapped["AnalysisBoardUnitList"] = relationship(
        back_populates="board",
        cascade="all, delete-orphan",
        passive_deletes=True,
        single_parent=True,
        uselist=False,
    )
    traits: Mapped["AnalysisBoardTraitList"] = relationship(
        back_populates="board",
        cascade="all, delete-orphan",
        passive_deletes=True,
        single_parent=True,
        uselist=False,
    )


class AnalysisBoardUnitList(Base):
    """Store one Set 17 unit-star feature column for every anonymous board."""

    __tablename__ = "analysis_board_unit_lists"
    __table__ = Table(
        __tablename__,
        Base.metadata,
        Column("scope_id", Integer, primary_key=True),
        Column("board_key", String(36), primary_key=True),
        *(
            Column(
                column_name,
                Integer,
                nullable=False,
                default=0,
                server_default=text("0"),
            )
            for column_name in SET_17_UNIT_COLUMNS.values()
        ),
        ForeignKeyConstraint(
            ["scope_id", "board_key"],
            ["analysis_boards.scope_id", "analysis_boards.board_key"],
            name="fk_analysis_board_unit_lists_board",
            ondelete="CASCADE",
        ),
    )

    board: Mapped[AnalysisBoard] = relationship(back_populates="units")


class AnalysisBoardTraitList(Base):
    """Store one Set 17 active-tier feature column for every anonymous board."""

    __tablename__ = "analysis_board_trait_lists"
    __table__ = Table(
        __tablename__,
        Base.metadata,
        Column("scope_id", Integer, primary_key=True),
        Column("board_key", String(36), primary_key=True),
        *(
            Column(
                column_name,
                Integer,
                nullable=False,
                default=0,
                server_default=text("0"),
            )
            for column_name in SET_17_TRAIT_COLUMNS.values()
        ),
        ForeignKeyConstraint(
            ["scope_id", "board_key"],
            ["analysis_boards.scope_id", "analysis_boards.board_key"],
            name="fk_analysis_board_trait_lists_board",
            ondelete="CASCADE",
        ),
    )

    board: Mapped[AnalysisBoard] = relationship(back_populates="traits")


class AnalysisBoardUnit(Base):
    """Represent one anonymous unit occurrence and its canonical loadout."""

    __tablename__ = "analysis_board_units"
    __table_args__ = (
        ForeignKeyConstraint(
            ["scope_id", "board_key"],
            ["analysis_boards.scope_id", "analysis_boards.board_key"],
            ondelete="CASCADE",
        ),
        Index(
            "ix_analysis_board_units_lookup",
            "scope_id",
            "unit_name",
            "star_level",
            "loadout_key",
        ),
    )

    scope_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    board_key: Mapped[str] = mapped_column(String(36), primary_key=True)
    unit_idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_name: Mapped[str] = mapped_column(String, nullable=False)
    star_level: Mapped[int] = mapped_column(Integer, nullable=False)
    cost: Mapped[int | None] = mapped_column(Integer)
    completed_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    loadout_key: Mapped[str] = mapped_column(String, nullable=False)
    item_1: Mapped[str | None] = mapped_column(String)
    item_2: Mapped[str | None] = mapped_column(String)
    item_3: Mapped[str | None] = mapped_column(String)


class AnalysisBoardItem(Base):
    """Represent one completed item occurrence on an anonymous unit."""

    __tablename__ = "analysis_board_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["scope_id", "board_key", "unit_idx"],
            [
                "analysis_board_units.scope_id",
                "analysis_board_units.board_key",
                "analysis_board_units.unit_idx",
            ],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "item_slot >= 0 AND item_slot <= 2", name="ck_analysis_board_items_slot"
        ),
        Index("ix_analysis_board_items_lookup", "scope_id", "item_name"),
        Index(
            "ix_analysis_board_items_api_lookup",
            "scope_id",
            "item_api_name",
        ),
    )

    scope_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    board_key: Mapped[str] = mapped_column(String(36), primary_key=True)
    unit_idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_slot: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_api_name: Mapped[str] = mapped_column(String, nullable=False)
    item_name: Mapped[str] = mapped_column(String, nullable=False)

    def __init__(self, **kwargs: Any) -> None:
        """Accept display-name-only fixtures as their own fallback identity.

        Args:
            **kwargs: ORM values for one anonymous item occurrence.
        """
        kwargs.setdefault("item_api_name", kwargs.get("item_name"))
        super().__init__(**kwargs)


class AnalysisBoardTrait(Base):
    """Represent one active or inactive trait on an anonymous board."""

    __tablename__ = "analysis_board_traits"
    __table_args__ = (
        ForeignKeyConstraint(
            ["scope_id", "board_key"],
            ["analysis_boards.scope_id", "analysis_boards.board_key"],
            ondelete="CASCADE",
        ),
        Index(
            "ix_analysis_board_traits_lookup",
            "scope_id",
            "trait_name",
            "tier_current",
            "style",
        ),
    )

    scope_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    board_key: Mapped[str] = mapped_column(String(36), primary_key=True)
    trait_name: Mapped[str] = mapped_column(String, primary_key=True)
    num_units: Mapped[int | None] = mapped_column(Integer)
    style: Mapped[int | None] = mapped_column(Integer)
    tier_current: Mapped[int | None] = mapped_column(Integer)
    tier_total: Mapped[int | None] = mapped_column(Integer)


PRIVATE_ANALYSIS_MODELS = (
    AnalysisScope,
    AnalysisProcessedMatch,
    AnalysisFactBuild,
    AnalysisBoard,
    AnalysisBoardUnitList,
    AnalysisBoardTraitList,
    AnalysisBoardUnit,
    AnalysisBoardItem,
    AnalysisBoardTrait,
)


__all__ = [
    "ANALYSIS_FACT_SCHEMA_VERSION",
    "AnalysisBoard",
    "AnalysisBoardItem",
    "AnalysisBoardTrait",
    "AnalysisBoardTraitList",
    "AnalysisBoardUnit",
    "AnalysisBoardUnitList",
    "AnalysisFactBuild",
    "AnalysisProcessedMatch",
    "AnalysisScope",
    "PRIVATE_ANALYSIS_MODELS",
    "SET_17_TRAIT_COLUMNS",
    "SET_17_UNIT_COLUMNS",
]
