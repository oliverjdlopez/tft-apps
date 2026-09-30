# Rolldown probability

`rolldown_probabilities` estimates the outcome distribution for one to twelve
wanted units over a bounded gold or roll budget. It uses the current
CommunityDragon champion roster only to resolve unit names, costs, and the
number of champions in each rarity. Shop odds and champion bag sizes are
explicit parameters in the calculator so they can be updated together when a
game patch changes them.

All internal unit-name comparisons use `TFTNameResolver.normalize_name`, the
same canonical identity rule used by CommunityDragon ingestion and lookup.

The model reflects the basic shop rules documented by Riot and the League of
Legends Wiki: each shop has five slots, the cost selected for a slot depends on
player level, and champion copies come from a shared finite pool. Different
rarities have different copies per champion. Sources consulted:

- [Riot Games, TFT gameplay guide](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-gameplay-guide/)
- [League of Legends Wiki, TFT shop](https://wiki.leagueoflegends.com/en-us/Teamfight_Tactics/Shop)
- [CommunityDragon current TFT data](https://raw.communitydragon.org/latest/cdragon/tft/en_us.json)

## Inputs and interpretation

Targets accept a champion name or a generic `1-cost` through `5-cost` label.
For example, `{"unit": "3-cost", "copies_needed": 3}` asks for three additional
purchases of one unspecified 3-cost champion. It therefore has the same
per-slot odds and cost-specific bag size as a named 3-cost champion; the tool
does not pick or disclose a name. Returned targets identify it as
`target_kind: "unspecified_cost_unit"`. Different-cost generic and named
targets can mix; a generic target cannot overlap another target at the same
cost because it might represent that named champion.

For generic targets, `copies_out` is the number removed from that unspecified
champion's cost-specific bag. Named `other_copies_out` entries are additional
removals from the tier denominator; do not include the same removed copies in
both fields. The same resolution supports direct API calculations and prepared
purchase/outcome requests; the dedicated browser champion picker continues to
list named champions.

- `level` selects the normal level 1–10 rarity odds.
- `budget` is available gold by default. Refreshes cost two gold and every
  target found and bought costs its shop price, so hits can shorten the
  rolldown. With `budget_type: "rolls"`, `budget` instead counts refreshes and
  purchase prices do not affect the limit. Every refresh produces five slots.
- `targets[].copies_needed` is the number of **additional** copies wanted,
  from zero through nine. A zero-copy goal is satisfied before the first shop.
- `targets[].copies_out` includes copies of that target removed from the pool
  by every player, including copies on the caller's board and bench. Its upper
  bound is the selected or unspecified champion's cost-specific bag size.
- `target_mode` controls whether the outcome requires `all` unit goals, `any`
  unit goal, or `at_least` a specified `minimum_targets` count.
- `other_copies_out` optionally describes non-target champions removed from
  their rarity pool. This matters because all champions of a rarity share its
  denominator.

The result contains the chance to satisfy the configured target rule, each
unit goal's completion probability, and its full capped copy-count distribution. The
calculation assumes every wanted copy is bought and accounts for the fact that
all five visible shop units temporarily leave the pool. It deliberately does
not model set mechanics or modifiers such as free rerolls, special shop slots,
augments, or encounters.

`hit_all_by_shop_confidence_95` contains a pointwise Wilson 95% interval aligned
with every cumulative probability in `hit_all_by_shop`. These bounds quantify
finite Monte Carlo sampling uncertainty at each shop; they do not account for
model assumptions and are not a simultaneous confidence band for the full
curve.

## Browser analysis flow

The Rolldown analysis tab separates run generation from target evaluation.
`POST /api/rolldown/runs` accepts `sweeps`, an array containing one or two
distinct level, budget, or pool-pressure dimensions, without accepting
targets. A two-dimensional request prepares the full Cartesian product and
does not impose a combination limit. Each returned run includes its axis
`coordinates`; the browser does not add a separate baseline. The singular
`sweep` field remains accepted for older clients.

The service retains a bounded roster snapshot and shared trial set for 30
minutes. After preparation, the browser separates two ideas that used to be a
single target:

- The **purchase plan** lists units to buy whenever they appear. The simulator
  buys every listed unit it can afford and plays out the full budget, regardless
  of when an outcome query first becomes true.
- The **outcome query** contains one or more groups of copy-count conditions.
  Conditions inside a group use `all` or `any`, and the groups themselves use
  an outer `all` or `any`. For example, `(A >= 3 AND B >= 9) OR (A >= 9 AND B
  >= 3)` is represented as two `all` groups joined by outer `any`.

The browser can select any subset of prepared runs and send the purchase plan
and Boolean query to `POST /api/rolldown/runs/analyze`; each query reuses the
prepared samples so comparisons stay repeatable while the question changes.
An impossible threshold is a valid query and produces zero probability rather
than rejecting the request. Two-dimensional results default to a probability
heatmap with contour lines and can be switched to a pointer-drag rotatable 3D
surface.

The Run explorer is a separate, sample-based analysis view. It filters one
selected run's retained trial outcomes with `all` or `any` copy-count filters,
then shows the matching share, average shops and spend, and conditional copy
distributions for every purchased unit. It updates locally without another
simulation request. Because the browser retains at most 2,000 sampled trials,
this view is exploratory; headline probabilities continue to use every Monte
Carlo trial.
