"""Deterministic TFT shop and shared-pool rolldown probabilities."""

from __future__ import annotations

import asyncio
from collections import defaultdict
import math
import random
from typing import Annotated, Literal, Sequence

from agents import function_tool
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.cdragon import CDragon
from core.config import load_config
from core.models import CDragonChampion, CDragonSet
from domain.types import AssistantToolGroup
from utils.tft import TFTNameResolver

# Normal ranked-shop parameters.  Keeping these in one small table makes a shop
# odds or bag-size patch a data update rather than a change to the calculator.
SHOP_ODDS: dict[int, tuple[float, ...]] = {
    1: (1.00, 0.00, 0.00, 0.00, 0.00),
    2: (1.00, 0.00, 0.00, 0.00, 0.00),
    3: (0.75, 0.25, 0.00, 0.00, 0.00),
    4: (0.55, 0.30, 0.15, 0.00, 0.00),
    5: (0.45, 0.33, 0.20, 0.02, 0.00),
    6: (0.30, 0.40, 0.25, 0.05, 0.00),
    7: (0.19, 0.30, 0.40, 0.10, 0.01),
    8: (0.17, 0.24, 0.32, 0.24, 0.03),
    9: (0.15, 0.20, 0.25, 0.30, 0.10),
    10: (0.05, 0.10, 0.20, 0.40, 0.25),
}
COPIES_PER_CHAMPION = {1: 30, 2: 25, 3: 18, 4: 10, 5: 9}
SHOP_SIZE = 5


class RolldownTarget(BaseModel):
    """A named unit or unspecified cost-tier champion and desired copies."""

    model_config = ConfigDict(extra="forbid")

    unit: Annotated[
        str,
        Field(
            min_length=1, max_length=80,
            description=("Champion name or 1-cost through 5-cost; a cost label "
                         "means one unspecified champion of that cost."),
        ),
    ]
    copies_needed: Annotated[int, Field(ge=0, le=9)]
    copies_out: Annotated[
        int,
        Field(
            ge=0, le=30,
            description=("Removed copies of the selected or unspecified champion. "
                         "Do not repeat other_copies_out entries here."),
        ),
    ] = 0


class RolldownPurchase(BaseModel):
    """A unit or unspecified cost-tier champion bought when it appears."""

    model_config = ConfigDict(extra="forbid")

    unit: Annotated[str, Field(min_length=1, max_length=80)]
    copies_out: Annotated[int, Field(ge=0, le=30)] = 0


class RolldownOutcomeCondition(BaseModel):
    """One copy-count predicate in a post-run Boolean outcome query."""

    model_config = ConfigDict(extra="forbid")

    unit: Annotated[str, Field(min_length=1, max_length=80)]
    copies_at_least: Annotated[int, Field(ge=0, le=9)]


class RolldownOutcomeGroup(BaseModel):
    """A Boolean group combining one or more copy-count predicates."""

    model_config = ConfigDict(extra="forbid")

    operator: Literal["all", "any"] = "all"
    conditions: Annotated[
        list[RolldownOutcomeCondition], Field(min_length=1, max_length=12)
    ]

    @model_validator(mode="after")
    def unique_conditions(self) -> "RolldownOutcomeGroup":
        """Reject identical predicates inside one group.

        Returns:
            The validated Boolean group.
        """
        keys = [
            (TFTNameResolver.normalize_name(condition.unit), condition.copies_at_least)
            for condition in self.conditions
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("Each condition in a group must be unique")
        return self


class OtherCopiesOut(BaseModel):
    """Copies of a non-target unit already removed from the shared pool."""

    model_config = ConfigDict(extra="forbid")

    unit: Annotated[str, Field(min_length=1, max_length=80)]
    copies_out: Annotated[int, Field(ge=1, le=30)]


class RolldownRunParameters(BaseModel):
    """Target-independent inputs used to prepare reusable trial samples."""

    model_config = ConfigDict(extra="forbid")

    level: Annotated[int, Field(ge=1, le=10)]
    budget: Annotated[int, Field(ge=1, le=200)]
    budget_type: Literal["gold", "rolls"] = "gold"
    pool_pressure: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    simulations: Annotated[int, Field(ge=800, le=100_000)] = 20_000
    seed: Annotated[int, Field(ge=0, le=2_147_483_647)] = 0

    @model_validator(mode="after")
    def validate_roll_budget(self) -> "RolldownRunParameters":
        """Keep refresh-count runs within the simulator's bounded workload.

        Returns:
            The validated run parameters.
        """
        if self.budget_type == "rolls" and self.budget > 100:
            raise ValueError("roll budgets cannot exceed 100")
        return self


class RolldownTargetDefinition(BaseModel):
    """A legacy target or purchase plan plus Boolean post-run outcome query."""

    model_config = ConfigDict(extra="forbid")

    targets: Annotated[list[RolldownTarget], Field(max_length=4)] = Field(
        default_factory=list
    )
    target_mode: Literal["all", "any", "at_least"] = "all"
    minimum_targets: Annotated[int | None, Field(ge=1, le=4)] = None
    purchases: Annotated[list[RolldownPurchase], Field(max_length=12)] = Field(
        default_factory=list
    )
    groups: Annotated[list[RolldownOutcomeGroup], Field(max_length=12)] = Field(
        default_factory=list
    )
    outcome_operator: Literal["all", "any"] = "any"
    stop_at_hit: bool = True
    buy_extras: bool = False
    include_trials: bool = True
    trials_sample_cap: Annotated[int, Field(ge=0, le=5_000)] = 2_000

    @model_validator(mode="after")
    def validate_target_rule(self) -> "RolldownTargetDefinition":
        """Validate unique units and the optional threshold target type.

        Returns:
            The validated target definition.
        """
        if self.targets and (self.purchases or self.groups):
            raise ValueError("use either legacy targets or purchases and groups")
        if not self.targets and not self.purchases:
            raise ValueError("at least one purchase is required")
        if self.targets:
            names = [TFTNameResolver.normalize_name(target.unit) for target in self.targets]
            if len(names) != len(set(names)):
                raise ValueError("Each target unit may appear only once")
        else:
            names = [
                TFTNameResolver.normalize_name(purchase.unit)
                for purchase in self.purchases
            ]
            if len(names) != len(set(names)):
                raise ValueError("Each purchased unit may appear only once")
            if not self.groups:
                raise ValueError("at least one outcome group is required")
            purchase_names = set(names)
            condition_names = {
                TFTNameResolver.normalize_name(condition.unit)
                for group in self.groups
                for condition in group.conditions
            }
            if not condition_names.issubset(purchase_names):
                raise ValueError("Outcome conditions must reference purchased units")
        if self.targets and self.target_mode == "at_least":
            if self.minimum_targets is None:
                raise ValueError("minimum_targets is required for at_least targets")
            if self.minimum_targets > len(self.targets):
                raise ValueError("minimum_targets cannot exceed the number of targets")
        return self


class RolldownRequest(BaseModel):
    """Bounded inputs for one normal-shop rolldown."""

    model_config = ConfigDict(extra="forbid")

    level: Annotated[int, Field(ge=1, le=10)]
    budget: Annotated[
        int,
        Field(
            ge=1,
            le=200,
            description="Gold available, or number of rolls when budget_type is rolls.",
        ),
    ]
    budget_type: Literal["gold", "rolls"] = "gold"
    targets: Annotated[list[RolldownTarget], Field(min_length=1, max_length=12)]
    target_mode: Literal["all", "any", "at_least"] = "all"
    minimum_targets: Annotated[int | None, Field(ge=1, le=12)] = None
    other_copies_out: Annotated[list[OtherCopiesOut], Field(max_length=30)] = []
    pool_pressure: Annotated[
        float,
        Field(
            ge=0.0,
            le=1.0,
            description="Fraction of each shared cost pool removed by other players.",
        ),
    ] = 0.0
    stop_at_hit: Annotated[
        bool,
        Field(description="Stop rolling as soon as the configured target rule is satisfied."),
    ] = True
    buy_extras: Annotated[
        bool,
        Field(description="Buy wanted units beyond the requested copy counts."),
    ] = False
    include_trials: Annotated[
        bool,
        Field(description="Include a bounded sample of synthetic trial outcomes."),
    ] = False
    trials_sample_cap: Annotated[
        int,
        Field(ge=0, le=5_000, description="Maximum sampled trials to return."),
    ] = 2_000
    simulations: Annotated[int, Field(ge=800, le=100_000)] = 20_000
    seed: Annotated[int, Field(ge=0, le=2_147_483_647)] = 0

    @model_validator(mode="after")
    def unique_units(self) -> "RolldownRequest":
        """Validate budget bounds, target rules, and unique pool inputs.

        Returns:
            The validated rolldown request.
        """
        if self.budget_type == "rolls" and self.budget > 100:
            raise ValueError("roll budgets cannot exceed 100")
        if self.target_mode == "at_least":
            if self.minimum_targets is None:
                raise ValueError("minimum_targets is required for at_least targets")
            if self.minimum_targets > len(self.targets):
                raise ValueError("minimum_targets cannot exceed the number of targets")
        names = [TFTNameResolver.normalize_name(target.unit) for target in self.targets]
        names += [
            TFTNameResolver.normalize_name(unit.unit) for unit in self.other_copies_out
        ]
        if len(names) != len(set(names)):
            raise ValueError("Each unit may appear only once across pool inputs")
        return self


def _rounded(probability: float) -> float:
    return round(max(0.0, min(1.0, probability)), 8)


def _wilson_score_interval_95(successes: int, trials: int) -> tuple[float, float]:
    """Return a pointwise 95% Wilson score interval for a binomial rate.

    Args:
        successes: Number of trials in which the event occurred.
        trials: Total number of independent Monte Carlo trials.

    Returns:
        Lower and upper probability bounds, clipped to zero through one.

    Raises:
        ValueError: If trials is not positive or successes is out of range.
    """
    if trials < 1:
        raise ValueError("trials must be positive")
    if not 0 <= successes <= trials:
        raise ValueError("successes must be between zero and trials")
    z = 1.96
    probability = successes / trials
    denominator = 1 + (z * z / trials)
    center = (probability + (z * z / (2 * trials))) / denominator
    margin = (
        z
        * math.sqrt(
            probability * (1 - probability) / trials
            + (z * z / (4 * trials * trials))
        )
        / denominator
    )
    return _rounded(center - margin), _rounded(center + margin)


def _normal_roster_counts(champions: list[CDragonChampion]) -> dict[int, int]:
    """Count normal-shop champions by cost.

    Args:
        champions: CommunityDragon champion records.

    Returns:
        Counts for each normal shop cost.
    """
    counts: defaultdict[int, int] = defaultdict(int)
    for champion in champions:
        if champion.cost in COPIES_PER_CHAMPION:
            counts[champion.cost] += 1
    return dict(counts)


def _is_complete_normal_roster(champions: list[CDragonChampion]) -> bool:
    """Return whether every normal shop tier has at least one champion.

    Args:
        champions: CommunityDragon champion records.

    Returns:
        True when costs one through five are all populated.
    """
    counts = _normal_roster_counts(champions)
    return all(counts.get(cost, 0) > 0 for cost in COPIES_PER_CHAMPION)


async def load_rolldown_champions(client: CDragon) -> list[CDragonChampion]:
    """Load the configured roster or highest complete current roster.

    CommunityDragon can publish a higher-numbered future set before its shop
    roster is complete. When no set is configured, skip those partial sets so
    normal shop-tier probabilities always have a real pool.

    Args:
        client: CommunityDragon client to use.

    Returns:
        Champion records for the selected rolldown roster.

    Raises:
        ValueError: If an explicitly configured set has an incomplete roster.
        RuntimeError: If CommunityDragon has no complete normal-shop roster.
    """
    configured_set = load_config().chat.set_number
    if configured_set is not None:
        champions = await client.champions(set_number=configured_set)
        if not _is_complete_normal_roster(champions):
            raise ValueError(
                f"Configured TFT set {configured_set} does not have a complete "
                "1-5 cost shop roster"
            )
        return champions

    candidates = [
        set_data for set_data in await client.all_sets()
        if _is_complete_normal_roster(set_data.champions)
    ]
    if not candidates:
        raise RuntimeError("Community Dragon returned no complete 1-5 cost shop roster")

    def set_number(set_data: CDragonSet) -> float:
        """Return a sortable CommunityDragon set number.

        Args:
            set_data: CommunityDragon set record.

        Returns:
            Numeric set number, or negative one when it is invalid.
        """
        try:
            return float(set_data.number)
        except (TypeError, ValueError):
            return -1.0

    return max(candidates, key=set_number).champions


def calculate_rolldown(
    *,
    level: int,
    budget: int,
    budget_type: Literal["gold", "rolls"] = "gold",
    targets: list[tuple[str, int, int, int]],
    roster_counts: dict[int, int],
    unspecified_cost_target_indexes: frozenset[int] = frozenset(),
    target_mode: Literal["all", "any", "at_least"] = "all",
    minimum_targets: int | None = None,
    outcome_groups: list[tuple[str, list[tuple[int, int]]]] | None = None,
    outcome_operator: Literal["all", "any"] = "any",
    other_removed_by_cost: dict[int, int] | None = None,
    pool_pressure: float = 0.0,
    stop_at_hit: bool = True,
    buy_extras: bool = False,
    include_trials: bool = False,
    trials_sample_cap: int = 2_000,
    simulations: int = 20_000,
    seed: int = 0,
    trial_seeds: Sequence[int] | None = None,
) -> dict[str, object]:
    """Estimate a normal-shop rolldown with seeded Monte Carlo trials.

    Each target tuple is ``(name, cost, copies_needed, copies_out)``. Units in
    a generated shop temporarily leave the bag. Wanted units are bought in
    target-list order when affordable, and all unbought units return on refresh.

    Args:
        level: Player level used for shop-tier odds.
        budget: Available gold or maximum paid refreshes.
        budget_type: Whether budget represents gold or refresh count.
        targets: Resolved name, cost, copies-needed, and copies-out tuples.
        roster_counts: Normal-shop champion count by cost.
        unspecified_cost_target_indexes: Targets for an unspecified champion at
            their listed cost. These must not overlap another target at the
            same cost, because that champion could be the named target.
        target_mode: Whether all, any, or a minimum count of unit goals must hit.
        minimum_targets: Unit-goal count required when target_mode is at_least.
        outcome_groups: Optional Boolean groups of target indexes and thresholds.
        outcome_operator: Whether all or any Boolean groups must match.
        other_removed_by_cost: Non-target copies removed from each cost pool.
        pool_pressure: Fraction of each cost pool removed by other players.
        stop_at_hit: Whether a trial stops when the configured target rule is satisfied.
        buy_extras: Whether completed targets continue to be bought when seen.
        include_trials: Whether to include a bounded sample of trial records.
        trials_sample_cap: Maximum number of sampled trial records to return.
        simulations: Number of independent Monte Carlo trials.
        seed: Seed for reproducible pseudo-random trials.
        trial_seeds: Optional prepared random seeds, one for each trial.

    Returns:
        Estimated joint, per-target, and shops-seen distributions.
    """
    if simulations < 1:
        raise ValueError("simulations must be positive")
    if not targets:
        raise ValueError("at least one target is required")
    if target_mode not in {"all", "any", "at_least"}:
        raise ValueError("target_mode must be 'all', 'any', or 'at_least'")
    if outcome_groups:
        if outcome_operator not in {"all", "any"}:
            raise ValueError("outcome_operator must be 'all' or 'any'")
        for operator, conditions in outcome_groups:
            if operator not in {"all", "any"} or not conditions:
                raise ValueError("Each outcome group needs an all/any operator and conditions")
            if any(not 0 <= index < len(targets) for index, _ in conditions):
                raise ValueError("Outcome condition references an unknown target index")
        required_targets = 1
    else:
        required_targets = (
            len(targets)
            if target_mode == "all"
            else 1
            if target_mode == "any"
            else minimum_targets
        )
        if required_targets is None or not 1 <= required_targets <= len(targets):
            raise ValueError("minimum_targets must be between 1 and the number of targets")
    if trial_seeds is not None and len(trial_seeds) != simulations:
        raise ValueError("trial_seeds must contain one seed per simulation")
    if not 0.0 <= pool_pressure <= 1.0:
        raise ValueError("pool_pressure must be between 0 and 1")
    if not 0 <= trials_sample_cap <= 5_000:
        raise ValueError("trials_sample_cap must be between 0 and 5000")
    other_removed_by_cost = other_removed_by_cost or {}
    costs = tuple(target[1] for target in targets)
    needed = tuple(target[2] for target in targets)
    for index in unspecified_cost_target_indexes:
        if not 0 <= index < len(targets):
            raise ValueError("Unspecified cost target index is out of range")
        if costs.count(costs[index]) != 1:
            raise ValueError(
                "An unspecified cost target cannot overlap another target at the same cost"
            )

    unpressured_tier_totals = {
        cost: roster_counts.get(cost, 0) * COPIES_PER_CHAMPION[cost]
        - other_removed_by_cost.get(cost, 0)
        - sum(target[3] for target in targets if target[1] == cost)
        for cost in COPIES_PER_CHAMPION
    }
    empty_costs = [cost for cost, total in unpressured_tier_totals.items() if total <= 0]
    if empty_costs:
        labels = ", ".join(f"{cost}-cost" for cost in empty_costs)
        raise ValueError(f"Copies-out inputs leave the {labels} champion pool empty")
    tier_totals = {
        cost: max(1, math.floor(total * (1.0 - pool_pressure)))
        for cost, total in unpressured_tier_totals.items()
    }
    initial_available = tuple(
        COPIES_PER_CHAMPION[cost] - target[3]
        for target, cost in zip(targets, costs)
    )
    for index, available in enumerate(initial_available):
        if available < needed[index] and not outcome_groups:
            raise ValueError(
                f"Not enough {targets[index][0]} copies remain: need {needed[index]}, "
                f"but only {available} are in the pool"
            )

    if budget_type not in {"gold", "rolls"}:
        raise ValueError("budget_type must be 'gold' or 'rolls'")
    if budget < 1:
        raise ValueError("budget must be positive")

    tier_cumulative: list[float] = []
    cumulative = 0.0
    for probability in SHOP_ODDS[level]:
        cumulative += probability
        tier_cumulative.append(cumulative)

    rng = random.Random(seed)
    outcomes: defaultdict[tuple[int, ...], int] = defaultdict(int)
    shops_distribution: defaultdict[int, int] = defaultdict(int)
    max_shops = budget if budget_type == "rolls" else budget // 2
    hits_by_shop = [0] * (max_shops + 1)
    spend_by_shop_totals = [0.0] * (max_shops + 1)
    sampled_trials: list[dict[str, object]] = []
    sample_rng = random.Random(seed ^ 0x5DEECE66D)
    total_shops = 0
    total_gold_spent = 0

    def target_rule_hit(found: list[int] | tuple[int, ...]) -> bool:
        """Return whether a copy-count state satisfies the active target rule.

        Args:
            found: Copies found for each target in request order.

        Returns:
            True when enough individual unit goals have been completed.
        """
        if outcome_groups:
            matches = []
            for operator, conditions in outcome_groups:
                condition_matches = [
                    found[index] >= threshold for index, threshold in conditions
                ]
                matches.append(
                    all(condition_matches) if operator == "all" else any(condition_matches)
                )
            return all(matches) if outcome_operator == "all" else any(matches)
        completed = sum(found[i] >= needed[i] for i in range(len(found)))
        return completed >= required_targets

    for trial_index in range(simulations):
        trial_rng = (
            random.Random(trial_seeds[trial_index])
            if trial_seeds is not None
            else rng
        )
        found = [0] * len(targets)
        resource = budget
        shops_seen = 0
        hit_shop = 0
        hit = target_rule_hit(found)
        gold_spent = 0
        trial_spend_by_shop = [0] * (max_shops + 1)

        while shops_seen < max_shops:
            if stop_at_hit and target_rule_hit(found):
                break
            refresh_cost = 2 if budget_type == "gold" else 1
            if resource < refresh_cost:
                break
            resource -= refresh_cost
            gold_spent += 2
            shops_seen += 1

            shown = [0] * len(targets)
            temporary_by_cost: defaultdict[int, int] = defaultdict(int)
            for _slot in range(SHOP_SIZE):
                tier_roll = trial_rng.random()
                tier_index = next(
                    index for index, threshold in enumerate(tier_cumulative)
                    if tier_roll < threshold
                )
                cost = tier_index + 1
                denominator = max(
                    1,
                    tier_totals[cost]
                    - sum(
                        found[i]
                        for i, target_cost in enumerate(costs)
                        if target_cost == cost
                    )
                    - temporary_by_cost[cost],
                )

                unit_roll = trial_rng.random() * denominator
                target_weight = 0
                selected_target = None
                for i, target_cost in enumerate(costs):
                    wanted_copies = initial_available[i] if buy_extras else needed[i]
                    if target_cost != cost or found[i] + shown[i] >= wanted_copies:
                        continue
                    available = initial_available[i] - found[i] - shown[i]
                    if available <= 0:
                        continue
                    target_weight += available
                    if selected_target is None and unit_roll < target_weight:
                        selected_target = i
                if selected_target is not None:
                    shown[selected_target] += 1
                temporary_by_cost[cost] += 1

            for i, copies_shown in enumerate(shown):
                for _copy in range(copies_shown):
                    if budget_type == "gold":
                        if resource < costs[i]:
                            break
                        resource -= costs[i]
                    gold_spent += costs[i]
                    found[i] += 1

            if not hit and target_rule_hit(found):
                hit = True
                hit_shop = shops_seen
            trial_spend_by_shop[shops_seen] = gold_spent

        for shop in range(1, max_shops + 1):
            if shop > shops_seen:
                trial_spend_by_shop[shop] = gold_spent
            spend_by_shop_totals[shop] += trial_spend_by_shop[shop]
        if hit:
            hits_by_shop[hit_shop] += 1

        outcome = tuple(found)
        outcomes[outcome] += 1
        shops_distribution[shops_seen] += 1
        total_shops += shops_seen
        total_gold_spent += gold_spent
        if include_trials and trials_sample_cap:
            trial_record: dict[str, object] = {
                "hit": hit,
                "hit_shop": hit_shop,
                "shops_seen": shops_seen,
                "gold_spent": gold_spent,
                "copies": list(found),
            }
            if len(sampled_trials) < trials_sample_cap:
                sampled_trials.append(trial_record)
            else:
                replacement = sample_rng.randrange(trial_index + 1)
                if replacement < trials_sample_cap:
                    sampled_trials[replacement] = trial_record

    per_target = []
    for i, (name, cost, target_needed, copies_out) in enumerate(targets):
        maximum_found = max(target_needed, max(state[i] for state in outcomes))
        hit_distribution = {
            str(count): _rounded(
                sum(trials for state, trials in outcomes.items() if state[i] == count)
                / simulations
            )
            for count in range(maximum_found + 1)
        }
        probability_find_all = sum(
            trials for state, trials in outcomes.items() if state[i] >= target_needed
        ) / simulations
        per_target.append(
            {
                "unit": name,
                "target_kind": (
                    "unspecified_cost_unit"
                    if i in unspecified_cost_target_indexes
                    else "unit"
                ),
                "cost": cost,
                "copies_needed": target_needed,
                "copies_out_before_roll": copies_out,
                "probability_find_all": _rounded(probability_find_all),
                "confidence_95_half_width": _rounded(
                    1.96 * math.sqrt(probability_find_all * (1 - probability_find_all) / simulations)
                ),
                "copies_found_distribution": hit_distribution,
            }
        )
    probability_hit = sum(
        trials
        for state, trials in outcomes.items()
        if target_rule_hit(state)
    ) / simulations
    group_results = []
    for group_index, (operator, conditions) in enumerate(outcome_groups or []):
        matches = sum(
            trial_count
            for state, trial_count in outcomes.items()
            if (
                all(state[index] >= threshold for index, threshold in conditions)
                if operator == "all"
                else any(state[index] >= threshold for index, threshold in conditions)
            )
        )
        group_results.append(
            {
                "index": group_index,
                "operator": operator,
                "probability": _rounded(matches / simulations),
            }
        )
    cumulative_hits = 0
    hit_all_by_shop = []
    hit_all_by_shop_confidence_95 = []
    for hits in hits_by_shop:
        cumulative_hits += hits
        probability_by_shop = _rounded(cumulative_hits / simulations)
        lower, upper = _wilson_score_interval_95(cumulative_hits, simulations)
        hit_all_by_shop.append(probability_by_shop)
        hit_all_by_shop_confidence_95.append(
            {"lower": lower, "upper": upper}
        )
    result: dict[str, object] = {
        "level": level,
        "budget": budget,
        "budget_type": budget_type,
        "simulations": simulations,
        "seed": seed,
        "max_shops": max_shops,
        "expected_shops_seen": round(total_shops / simulations, 8),
        "expected_gold_spent": round(total_gold_spent / simulations, 8),
        "hit_all_by_shop": hit_all_by_shop,
        "hit_all_by_shop_confidence_95": hit_all_by_shop_confidence_95,
        "spend_by_shop": [
            round(total / simulations, 8) for total in spend_by_shop_totals
        ],
        "shops_seen_distribution": {
            str(shops): _rounded(trials / simulations)
            for shops, trials in sorted(shops_distribution.items())
        },
        "probability_hit": _rounded(probability_hit),
        # Kept for the model-facing tool and older browser consumers. For
        # non-"all" rules this is the probability of satisfying that rule.
        "probability_find_all_targets": _rounded(probability_hit),
        "confidence_95_half_width": _rounded(
            1.96
            * math.sqrt(
                probability_hit
                * (1 - probability_hit)
                / simulations
            )
        ),
        "target_mode": target_mode,
        "minimum_targets": required_targets,
        "outcome_operator": outcome_operator if outcome_groups else None,
        "outcome_groups": group_results,
        "targets": per_target,
        "assumptions": [
            "Targets are bought in their listed order when enough gold remains.",
            "Cost-tier targets represent one unspecified champion at that cost.",
            "Roll budgets assume enough separate gold to buy every requested target shown.",
            (
                "Each trial stops after the target rule is satisfied or the budget is exhausted."
                if stop_at_hit
                else "Each trial keeps rolling until the budget is exhausted."
            ),
            "Non-target units in a shop temporarily leave the shared pool and return on refresh.",
            "copies_out includes every copy already removed by all players, including your board and bench.",
            "Natural shops, free rerolls, Headliner/Chosen slots, augments, encounters, and other shop modifiers are excluded.",
        ],
        "parameters": {
            "shop_odds": list(SHOP_ODDS[level]),
            "copies_per_champion_by_cost": COPIES_PER_CHAMPION,
            "champions_in_current_roster_by_cost": roster_counts,
            "simulations": simulations,
            "seed": seed,
            "pool_pressure": pool_pressure,
            "stop_at_hit": stop_at_hit,
            "buy_extras": buy_extras,
            "target_mode": target_mode,
            "minimum_targets": required_targets,
            "outcome_operator": outcome_operator if outcome_groups else None,
        },
    }
    if include_trials:
        result["trials"] = sampled_trials
    return result


async def calculate_rolldown_request(request: RolldownRequest) -> dict[str, object]:
    """Resolve current champion names and calculate one rolldown request.

    Args:
        request: Validated normal-shop rolldown inputs.

    Returns:
        Estimated joint and per-target hit distributions.
    """
    client = CDragon()
    try:
        champions = await load_rolldown_champions(client)
    finally:
        await client.aclose()
    return await asyncio.to_thread(calculate_rolldown_for_roster, request, champions)


def calculate_rolldown_for_roster(
    request: RolldownRequest,
    champions: list[CDragonChampion],
    *,
    trial_seeds: Sequence[int] | None = None,
    outcome_query: RolldownTargetDefinition | None = None,
) -> dict[str, object]:
    """Resolve champion inputs and run one CPU-bound simulation.

    Args:
        request: Validated normal-shop rolldown inputs.
        champions: Current normal-shop roster used to resolve units and pools.
        trial_seeds: Optional prepared random seeds, one for each trial.
        outcome_query: Optional Boolean query over the purchased-unit outcomes.

    Returns:
        Estimated joint and per-target hit distributions.
    """
    roster = {
        TFTNameResolver.normalize_name(champion.name or champion.apiName): champion
        for champion in champions
    }
    roster_counts = _normal_roster_counts(champions)

    resolved_targets: list[tuple[str, int, int, int]] = []
    unspecified_cost_target_indexes: set[int] = set()
    tier_names = {f"{cost}cost": cost for cost in COPIES_PER_CHAMPION}
    for index, target in enumerate(request.targets):
        normalized = TFTNameResolver.normalize_name(target.unit)
        if cost := tier_names.get(normalized):
            if target.copies_out > COPIES_PER_CHAMPION[cost]:
                raise ValueError(
                    f"copies_out exceeds the bag size for an unspecified {cost}-cost champion"
                )
            resolved_targets.append(
                (f"{cost}-cost", cost, target.copies_needed, target.copies_out)
            )
            unspecified_cost_target_indexes.add(index)
            continue
        champion = roster.get(normalized)
        if champion is None or champion.cost not in COPIES_PER_CHAMPION:
            raise ValueError(f"{target.unit!r} is not a normal 1-5 cost unit in the current roster")
        if target.copies_out > COPIES_PER_CHAMPION[champion.cost]:
            raise ValueError(f"copies_out exceeds the bag size for {champion.name}")
        resolved_targets.append(
            (champion.name or champion.apiName, champion.cost, target.copies_needed, target.copies_out)
        )
    other_removed: defaultdict[int, int] = defaultdict(int)
    for entry in request.other_copies_out:
        champion = roster.get(TFTNameResolver.normalize_name(entry.unit))
        if champion is None or champion.cost not in COPIES_PER_CHAMPION:
            raise ValueError(f"{entry.unit!r} is not a normal 1-5 cost unit in the current roster")
        if entry.copies_out > COPIES_PER_CHAMPION[champion.cost]:
            raise ValueError(f"copies_out exceeds the bag size for {champion.name}")
        other_removed[champion.cost] += entry.copies_out

    resolved_outcome_groups = None
    if outcome_query is not None and outcome_query.groups:
        target_indexes = {
            TFTNameResolver.normalize_name(target.unit): index
            for index, target in enumerate(request.targets)
        }
        resolved_outcome_groups = [
            (
                group.operator,
                [
                    (
                        target_indexes[TFTNameResolver.normalize_name(condition.unit)],
                        condition.copies_at_least,
                    )
                    for condition in group.conditions
                ],
            )
            for group in outcome_query.groups
        ]

    return calculate_rolldown(
        level=request.level,
        budget=request.budget,
        budget_type=request.budget_type,
        targets=resolved_targets,
        roster_counts=roster_counts,
        unspecified_cost_target_indexes=frozenset(unspecified_cost_target_indexes),
        target_mode=request.target_mode,
        minimum_targets=request.minimum_targets,
        outcome_groups=resolved_outcome_groups,
        outcome_operator=(
            outcome_query.outcome_operator if outcome_query is not None else "any"
        ),
        other_removed_by_cost=dict(other_removed),
        pool_pressure=request.pool_pressure,
        stop_at_hit=request.stop_at_hit,
        buy_extras=request.buy_extras,
        include_trials=request.include_trials,
        trials_sample_cap=request.trials_sample_cap,
        simulations=request.simulations,
        seed=request.seed,
        trial_seeds=trial_seeds,
    )


@function_tool(strict_mode=True)
async def rolldown_probabilities(request: RolldownRequest) -> dict[str, object]:
    """Estimate odds of hitting one or more units during a normal TFT rolldown.

    Uses the current CommunityDragon champion roster, level-dependent shop-tier
    odds, finite champion bags, and copies removed from the shared pool. The
    budget defaults to gold, including refreshes and purchased targets; set
    budget_type to rolls to limit by refresh count instead. Use copies_out for
    copies held by any player (including the caller); do not count the current
    unbought shop because it returns before a refresh. Results are seeded Monte
    Carlo estimates and include a 95% confidence half-width.
    A target unit may also be "1-cost" through "5-cost", representing one
    unspecified champion of that cost. Generic and named targets cannot share
    the same cost because their targets could overlap.
    """
    return await calculate_rolldown_request(request)


PROBABILITY_TOOL_GROUP = AssistantToolGroup(
    key="probability",
    label="Rolldown Probability",
    description="Monte Carlo normal-shop rolldown odds using the current roster and shared champion pool.",
    tools=(rolldown_probabilities,),
)

__all__ = [
    "COPIES_PER_CHAMPION",
    "PROBABILITY_TOOL_GROUP",
    "RolldownRunParameters",
    "RolldownTargetDefinition",
    "SHOP_ODDS",
    "calculate_rolldown",
    "calculate_rolldown_for_roster",
    "calculate_rolldown_request",
    "load_rolldown_champions",
    "rolldown_probabilities",
]
