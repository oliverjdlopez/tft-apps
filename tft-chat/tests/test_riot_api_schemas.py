from __future__ import annotations

from core.models import RiotMatch


def test_riot_match_schema_accepts_extended_payload() -> None:
    payload = {
        "metadata": {
            "data_version": "5",
            "match_id": "NA1_123",
            "participants": ["p1"],
        },
        "info": {
            "endOfGameResult": "GameComplete",
            "gameCreation": 1710000000000,
            "game_datetime": 1710000001000,
            "game_length": 1800.5,
            "game_version": "Version 14.10.1",
            "game_variation": "TFT3_GameVariation_TwoItemMax",
            "mapId": 22,
            "queue_id": 1100,
            "tft_game_type": "standard",
            "tft_set_number": 11,
            "tft_set_core_name": "TFTSet11",
            "participants": [
                {
                    "puuid": "p1",
                    "riotIdGameName": "Player",
                    "riotIdTagline": "NA1",
                    "placement": 1,
                    "level": 9,
                    "last_round": 37,
                    "players_eliminated": 3,
                    "total_damage_to_players": 120,
                    "gold_left": 8,
                    "time_eliminated": 1800.5,
                    "win": True,
                    "partner_group_id": 2,
                    "companion": {
                        "content_ID": "abc",
                        "item_ID": 1,
                        "skin_ID": 2,
                        "species": "species",
                    },
                    "traits": [
                        {
                            "name": "TFT_Trait",
                            "num_units": 4,
                            "style": 3,
                            "tier_current": 2,
                            "tier_total": 3,
                        }
                    ],
                    "units": [
                        {
                            "character_id": "TFT_Unit",
                            "tier": 2,
                            "rarity": 4,
                            "itemNames": ["TFT_Item"],
                        }
                    ],
                }
            ],
        },
    }

    parsed = RiotMatch.model_validate(payload)

    assert parsed.match_id() == "NA1_123"
    assert parsed.info.participants[0].companion is not None
    assert parsed.info.participants[0].riot_id_game_name == "Player"
