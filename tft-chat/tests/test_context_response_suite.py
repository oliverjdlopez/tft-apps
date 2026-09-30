"""Validate the portable 30-case context/answer smoke suite without model calls."""
import csv
import json
from pathlib import Path

import pytest

from evals.execution import score_attempt
from evals.langfuse.content import load_catalog, load_snapshot, validate_bundle
from evals.langfuse.contracts import ACTIVE_WORKFLOW_SUITES, DATASET_NAMES, legacy_execution_item
from evals.langfuse.utils import validate_case_semantics

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evals/datasets/context_response_smoke.json"
BUNDLE = json.loads(SOURCE.read_text())


# These are deliberately short, canonical answer fragments.  They exercise the
# authored regexes against the facts they are intended to require without
# turning this suite into a second reference-answer corpus.
POSITIVE_OUTPUTS = {
    "riftbeast_roster": "Cinderling, Pebbles, Gromp, Murkwolf, Scuttlecrab, Krug, Mama Beak, Brambleback, Sentinel, and Elder Dragon are the Riftbeasts.",
    "four_cost_adaptors": "Nidalee is the only 4-cost Adaptor.",
    "five_cost_count": "There are 10 five-cost champions in the set.",
    "taric_ability": "Taric uses Emerald Aspect: drag an ally onto the strongest Taric so the paired ally receives the ability benefits.",
    "potion_earliest_stages": "Mana Potion, Health Potion, and Blast Potion all first appear at 3-1, so the earliest stage is the same for each.",
    "most_expensive_wisp": "Circle of Elders is the most expensive Wisp at 45 gold.",
    "econ_wisp_uniform_odds": "Under a uniform model, the Econ/Gold-XP chance is 1/10 = 10%.",
    "blossom_roster": "Blossom champions are Karma, Yorick, Yunara, Master Yi, Ahri, Sett, Ashe, and Lux.",
    "one_cost_roster": "The 1-cost champions are Akali, Camille, Cinderling, Karma, Kobuko, Leona, Ornn, Pebbles, Rakan, Rek'Sai, Varus, Veigar, Xayah, and Yorick.",
    "riftbeast_adaptor_overlap": "Gromp is the only Riftbeast Adaptor.",
    "elder_dragon_slots": "Elder Dragon uses two team slots and contributes two Riftbeast counts.",
    "adaptor_mechanic": "Adaptor chooses the AD or AP form from the higher offensive stat.",
    "taric_pairing": "For Emerald Aspect, drag an ally onto the strongest Taric to pair it.",
    "blossom_wisp_thresholds": "At 3 Blossom Wisps upgrade after combat; at 5 they are offered every shop; at 7 a purchase refunds 4 gold.",
    "stage2_goldxp_pool": "Stage 2 includes Beggar's Wisp, Bronze Spoon, Coin Flip, Experienced, and Truce, with base and upgraded variants (2-1 to 2-7).",
    "stage3_goldxp_pool": "Stage 3 Gold/XP Wisps include Beggar's Wisp, Blood Money, Bronze Spoon, Die Roll, Grow Up, Pocket Change, Barter, and Slow Study, base and upgraded.",
    "stage2_item_pool": "At Stage 2, Artifactinate (base and upgraded) and Blood and Iron (upgraded) can be offered in the 2-1 to 2-7 window.",
    "stage3_stage4_overlap": "Yes. A 3-5 through 4-1 window includes both Stage 3 and Stage 4.",
    "all_band_variants": "No. All bands identifies a prismatic variant; it does not make the normal base Wisp purchasable in Stage 2.",
    "beggars_fallback": "Beggar's Wisp is a fallback, not a normal competing offer.",
    "wisp_offer_cadence": "No. An eligibility window does not guarantee an offer every round; normal Wisps appear in every other shop.",
    "wisp_cooldown_units": "Cooldowns are measured in Wisp shops, not combat rounds (or purchases).",
    "wisp_purchase_phase": "Wisps can only be purchased during the planning phase, not during combat.",
    "late_combat_guarantee": "After Stage 5, every other Wisp offer is guaranteed to be a Combat Wisp.",
    "coin_flip_cost": "Coin Flip costs 0 gold; a coin toss (heads or tails) determines whether it grants gold.",
    "bronze_spoon_variants": "Bronze Spoon costs 3 gold in base form and 2 gold upgraded; both first appear at 2-1 (Stage 2).",
    "artifactinate_conditions": "Artifactinate requires at least 3 item components, counting completed or equipped items.",
    "hand_of_baron_condition": "Yes. Hand Of Baron requires Riftbeast to be active.",
    "artifact_lookup": "Zhonya's Paradox is an Artifact that grants brief invulnerability and untargetability at low Health.",
    "forest_mage_shop": "Forest Mage creates a Wisp-only shop with one purchase allowed during the first 8 seconds.",
}


def test_suite_is_registered_portable_and_has_exactly_thirty_single_checks() -> None:
    """Keep seed, CSV, snapshot, and hosted workflow routing in agreement."""
    bundle = validate_bundle(BUNDLE)
    validate_case_semantics(bundle["suite"], bundle["items"])
    assert len(bundle["items"]) == 30
    assert len({item["input"] for item in bundle["items"]}) == 30
    assert bundle["schemas"]["input"] == {"type": "string"}
    assert bundle["suite"]["assistant"] == "chat"
    assert "context_response_smoke" in ACTIVE_WORKFLOW_SUITES
    assert DATASET_NAMES["context_response_smoke"] == bundle["dataset_name"] == "context-response"
    snapshots = ROOT / "evals/langfuse/snapshots"
    entry = next(e for e in load_catalog(snapshots) if e["name"] == "context_response_smoke")
    # The original bootstrap is immutable history; the catalog now points at
    # the fact-oriented export generated from the updated portable source.
    seed = "287990fc3eb4063fee5e10975b32126a0bc8dc1c25bfdad3e54dc94c9e890aa0"
    original_seed = load_snapshot(seed, snapshots)
    assert original_seed["dataset_name"] == "context-response-smoke"
    assert original_seed["items"][0]["metadata"]["placeholder_checks"] is True
    current = load_snapshot(entry["snapshot"], snapshots)
    assert current == bundle
    with SOURCE.with_suffix(".csv").open(newline="") as file:
        csv_rows = list(csv.DictReader(file))
    assert len(csv_rows) == 30
    for item, row in zip(bundle["items"], csv_rows):
        assert row["input"] == item["input"]
        assert json.loads(row["expected_output"]) == item["expected_output"]
        assert json.loads(row["metadata"]) == item["metadata"]
        checks = item["metadata"]["deterministic_checks"]
        assert len(checks) == 1 and checks[0]["check"]["type"] == "regex"
        assert item["metadata"]["quality_profile"] is None
        assert item["metadata"]["placeholder_checks"] is False
        assert "Fact-oriented response check" in item["metadata"]["description"]
        assert item["expected_output"] == ""
        assert len(legacy_execution_item(item)["expected_output"]["assertions"]) == 1


@pytest.mark.parametrize("item", BUNDLE["items"], ids=lambda item: item["metadata"]["case"])
def test_each_fact_check_runs_through_the_real_scoring_adapter(item: dict) -> None:
    """Prove each fact check accepts its intended facts and rejects empty output."""
    assert set(POSITIVE_OUTPUTS) == {entry["metadata"]["case"] for entry in BUNDLE["items"]}
    positive = score_attempt(item, {"output": POSITIVE_OUTPUTS[item["metadata"]["case"]], "success": True}, {})
    negative = score_attempt(item, {"output": "", "success": True}, {})
    check = next(score for score in positive if score["name"] == "reasonable_response")
    assert check["value"] == 1
    assert next(score for score in negative if score["name"] == "reasonable_response")["value"] == 0


@pytest.mark.parametrize("item", BUNDLE["items"], ids=lambda item: item["metadata"]["case"])
def test_question_echo_does_not_satisfy_fact_check(item: dict) -> None:
    """Prevent the input wording itself from satisfying an answer check."""
    scores = score_attempt(item, {"output": item["input"], "success": True}, {})
    assert next(score for score in scores if score["name"] == "reasonable_response")["value"] == 0


def test_original_user_examples_are_preserved_verbatim() -> None:
    """Retain the six supplied questions as stable benchmark starting points."""
    assert [item["input"] for item in BUNDLE["items"][:6]] == [
        "List all the riftbeast champs",
        "What are the 4 cost adaptors",
        "How many 5 costs are in the game",
        "What does taric do",
        "What is the earliest stage I can see mana potion wisp? Is it the same for health and blast?",
        "What’s the most expensive wisp in the game",
    ]
