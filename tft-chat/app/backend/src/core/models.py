"""Pydantic inputs consumed by TFT match ingestion and name normalization.

Only the Riot final-match slice and Community Dragon catalogue shapes used by
the runtime live here. Upstream payloads may carry more fields, so these models
ignore unknown keys and treat explicit ``null`` as absent when defaults exist.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


_SET_NUMBER_RE = re.compile(r"TFT(\d+)_", re.IGNORECASE)


def set_number_from_id(entity_id: str | None) -> Optional[int]:
    """Derive a TFT set number from an entity id such as ``TFT15_Ashe``."""
    if not entity_id:
        return None
    m = _SET_NUMBER_RE.search(entity_id)
    return int(m.group(1)) if m else None


class _LenientModel(BaseModel):
    """Base for models parsed from external JSON.

    Unknown keys are ignored and explicit ``null`` values are dropped so the
    field defaults take effect, matching the defensive ``.get(k) or default``
    parsing the codebase relied on.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def _drop_nones(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return data


# ===========================================================================
# Riot API input models
#
# These describe the parts of Riot's TFT match payload the ingestion pipeline
# reads. Field names match Riot's JSON, including selected camelCase aliases.
# ===========================================================================


class RiotUnit(_LenientModel):
    """One champion on a participant's final board (``info.participants[].units[]``)."""

    character_id: Optional[str] = Field(
        default=None, description="Riot unit id, e.g. 'TFT15_Ashe'."
    )
    name: Optional[str] = Field(default=None, description="Fallback display name.")
    tier: int = Field(default=1, description="Star level (1-3).")
    rarity: int = Field(default=0, description="Cost tier; Riot encodes cost-1 here.")
    itemNames: list[str] = Field(
        default_factory=list, description="Completed item apiNames held by this unit."
    )
    items: list[int] = Field(
        default_factory=list,
        description="Legacy integer item ids (unused; need a per-patch id map).",
    )

    @property
    def resolved_character_id(self) -> str:
        return self.character_id or self.name or ""

    @property
    def cost(self) -> int:
        """Shop gold cost normalized from Riot's zero-based rarity field."""
        return self.rarity + 1


class RiotCompanion(_LenientModel):
    """A participant's Little Legend / companion block in match payloads."""

    content_ID: Optional[str] = Field(default=None)
    item_ID: Optional[int] = Field(default=None)
    skin_ID: Optional[int] = Field(default=None)
    species: Optional[str] = None


class RiotTrait(_LenientModel):
    """A trait's activation state for one participant (``...participants[].traits[]``)."""

    name: str = Field(default="", description="Riot trait id, e.g. 'TFT15_Slayer'.")
    num_units: int = Field(default=0, description="Units contributing to the trait.")
    style: int = Field(
        default=0, description="Riot match activation style: 0=inactive, 1=bronze, 2=silver, 3=unique, 4=gold, 5=prismatic."
    )
    tier_current: int = Field(default=0, description="Current breakpoint tier reached.")
    tier_total: int = Field(default=0, description="Total breakpoints the trait has.")


class RiotParticipant(_LenientModel):
    """One player's end-of-game result within a match (``info.participants[]``)."""

    puuid: str = Field(default="", description="Player PUUID.")
    riot_id_game_name: Optional[str] = Field(default=None, alias="riotIdGameName")
    riot_id_tagline: Optional[str] = Field(default=None, alias="riotIdTagline")
    placement: int = Field(default=0, description="Final placement (1-8).")
    level: int = Field(default=0, description="Tactician level at game end.")
    last_round: int = Field(default=0, description="Last round reached.")
    players_eliminated: int = Field(default=0, description="Opponents this player eliminated.")
    total_damage_to_players: int = Field(default=0, description="Total damage dealt to players.")
    gold_left: int = Field(default=0, description="Unspent gold at elimination.")
    time_eliminated: float = Field(default=0.0)
    win: Optional[bool] = None
    partner_group_id: Optional[int] = None
    companion: Optional[RiotCompanion] = None
    units: list[RiotUnit] = Field(default_factory=list)
    traits: list[RiotTrait] = Field(default_factory=list)


class RiotMatchInfo(_LenientModel):
    """The ``info`` block of a TFT match payload."""

    end_of_game_result: Optional[str] = Field(default=None, alias="endOfGameResult")
    game_creation: Optional[int] = Field(default=None, alias="gameCreation")
    game_datetime: int = Field(default=0, description="Match start, unix ms.")
    game_length: float = Field(default=0.0, description="Match length in seconds.")
    game_version: str = Field(default="", description="Full game version string.")
    game_id: Optional[int] = Field(default=None, description="Numeric game id (match_id fallback).")
    game_variation: Optional[str] = None
    map_id: Optional[int] = Field(default=None, alias="mapId")
    queue_id: int = Field(default=0, description="Riot queue id (1100 = Ranked TFT).")
    queueId: Optional[int] = Field(default=None, description="Camel-case queue id variant.")
    tft_game_type: Optional[str] = None
    tft_set_number: Optional[int] = Field(default=None, description="TFT set number.")
    tft_set_core_name: Optional[str] = Field(default=None, description="Set core name, e.g. 'TFTSet15'.")
    participants: list[RiotParticipant] = Field(default_factory=list)


class RiotMatchMetadata(_LenientModel):
    """The ``metadata`` block of a TFT match payload."""

    data_version: Optional[str] = None
    match_id: Optional[str] = Field(default=None, description="Canonical match id, e.g. 'NA1_123'.")
    participants: list[str] = Field(
        default_factory=list, description="PUUIDs of every participant."
    )


class RiotMatch(_LenientModel):
    """A full TFT match as returned by TFT-Match-V1."""

    metadata: RiotMatchMetadata = Field(default_factory=RiotMatchMetadata)
    info: RiotMatchInfo = Field(default_factory=RiotMatchInfo)

    def match_id(self) -> str:
        """The id the ingestion pipeline keys on: metadata.match_id, else info.game_id."""
        if self.metadata.match_id:
            return self.metadata.match_id
        if self.info.game_id is not None:
            return str(self.info.game_id)
        return ""


# ===========================================================================
# Community Dragon (CDragon) static-data input models
#
# Community Dragon publishes the richer TFT payload Data Dragon lacks: set
# metadata, champion abilities/stats/traits, trait thresholds, and item
# composition/effects. ``apiName`` matches Riot match payload ids such as
# ``TFT15_Ashe`` and remains the canonical static-data key.
# ===========================================================================


class _CDragonModel(_LenientModel):
    """Base for Community Dragon models with dict-like compatibility."""

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class CDragonItem(_CDragonModel):
    apiName: str = ""
    associated_traits: list[str] = Field(default_factory=list, alias="associatedTraits")
    composition: list[str] = Field(default_factory=list)
    desc: Optional[str] = None
    effects: dict[str, Any] = Field(default_factory=dict)
    from_: Optional[str] = Field(default=None, alias="from")
    icon: Optional[str] = None
    id: Optional[int] = None
    name: Optional[str] = None
    unique: Optional[bool] = None
    tags: list[str] = Field(default_factory=list)


class CDragonAbilityVariable(_CDragonModel):
    name: str = ""
    value: list[float] = Field(default_factory=list)


class CDragonChampionAbility(_CDragonModel):
    desc: Optional[str] = None
    icon: Optional[str] = None
    name: Optional[str] = None
    variables: list[CDragonAbilityVariable] = Field(default_factory=list)


class CDragonChampionStats(_CDragonModel):
    armor: Optional[float] = None
    attack_speed: Optional[float] = Field(default=None, alias="attackSpeed")
    crit_chance: Optional[float] = Field(default=None, alias="critChance")
    crit_multiplier: Optional[float] = Field(default=None, alias="critMultiplier")
    damage: Optional[float] = None
    hp: Optional[float] = None
    initial_mana: Optional[float] = Field(default=None, alias="initialMana")
    magic_resist: Optional[float] = Field(default=None, alias="magicResist")
    mana: Optional[float] = None
    range: Optional[float] = None


class CDragonChampion(_CDragonModel):
    ability: Optional[CDragonChampionAbility] = None
    apiName: str = ""
    characterName: Optional[str] = None
    cost: Optional[int] = None
    icon: Optional[str] = None
    name: Optional[str] = None
    squareIcon: Optional[str] = None
    role: Optional[str] = None
    stats: Optional[CDragonChampionStats] = None
    tileIcon: Optional[str] = None
    traits: list[str] = Field(default_factory=list)

    @property
    def id(self) -> str:
        return self.apiName

    @property
    def set_number(self) -> Optional[int]:
        return set_number_from_id(self.apiName or self.characterName)


class CDragonTraitEffect(_CDragonModel):
    max_units: Optional[int] = Field(default=None, alias="maxUnits")
    min_units: Optional[int] = Field(default=None, alias="minUnits")
    style: Optional[int] = None
    variables: dict[str, Any] = Field(default_factory=dict)


class CDragonTrait(_CDragonModel):
    apiName: str = ""
    desc: Optional[str] = None
    effects: list[CDragonTraitEffect] = Field(default_factory=list)
    icon: Optional[str] = None
    name: Optional[str] = None

    @property
    def id(self) -> str:
        return self.apiName

    @property
    def set_number(self) -> Optional[int]:
        return set_number_from_id(self.apiName)


class CDragonSet(_CDragonModel):
    number: Optional[float] = None
    name: Optional[str] = None
    mutator: Optional[str] = None
    champions: list[CDragonChampion] = Field(default_factory=list)
    traits: list[CDragonTrait] = Field(default_factory=list)
    augments: list[str] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)


class CDragonData(_CDragonModel):
    items: list[CDragonItem] = Field(default_factory=list)
    set_data: list[CDragonSet] = Field(default_factory=list, alias="setData")
    sets: dict[str, CDragonSet] = Field(default_factory=dict)
