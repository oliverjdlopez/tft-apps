# Set 18 player reference import

The September 20, 2026 user-supplied reference targets patch 18.2 while retaining
source disagreements and later corrections. Source-check claims belong to the
supplied document; this import did not independently recheck the external pages.
The [source archive](references/set18-player-reference.md) retains all numbered
sections, coverage appendices, source links and ledger records. The malformed
champion-pool / XP splice was repaired by rejoining its supplied cells: the
2-cost pool row is 13 champions / 25 copies, and 5 → 6 requires 20 XP in that table.
No missing probabilities or contradictory values were resolved during import.

## Runtime organization

Each file below is a complete selectable Markdown collection with a unique
`set-18-reference-` identity and `sets: 18`. Systems, traits, items, augments and
Wisp effects have separate routing descriptions. Ledger chunks group Wisp rows
by tier and variant, augment rows by rarity (encounters separately), and Bonus
Gift rows by source type. Every chunk repeats its field legend and includes all
requirement definitions it uses; conditions never depend on another retrieval.
All groups must be selected for exhaustive counts or population comparisons.
These ledger files use ordinary whole-file selection, not automatic Wisp stage
partitioning. Exact round bands remain in every offer record.

Existing baseline Markdown and JSON files are retained. The new dated files
supplement them; they are not a wholesale patch refresh or a replacement for
existing effect descriptions. In particular, the uploaded Wisp ledger retains
all 366 records, including the previously documented Tiger/Bear mismatch;
the older category corpus retains its 365-record exclusion. Neither count is a
verified currently eligible selection population. The copied archive preserves
the distinction for maintenance rather than silently resolving it.

Source URLs and the research coverage appendices live in documentation.
Runtime chunks retain numerical disagreements and source labels needed to
interpret them, but omit citation URLs. No JSON companions were generated:
duplicate companions would add another selectable copy of the same facts.

## Imported collections

| Runtime path under `context/set18/` | Topic |
| --- | --- |
| [`systems/shops-pools-leveling.md`](../../app/backend/src/resources/context/set18/systems/shops-pools-leveling.md) | Shops, champion pools, and leveling |
| [`systems/augment-tier-odds.md`](../../app/backend/src/resources/context/set18/systems/augment-tier-odds.md) | Augment tier sequences |
| [`systems/player-damage.md`](../../app/backend/src/resources/context/set18/systems/player-damage.md) | Player damage |
| [`systems/encounters.md`](../../app/backend/src/resources/context/set18/systems/encounters.md) | Encounters |
| [`systems/loot-orbs.md`](../../app/backend/src/resources/context/set18/systems/loot-orbs.md) | Loot orbs |
| [`traits/coven-tables.md`](../../app/backend/src/resources/context/set18/traits/coven-tables.md) | Coven |
| [`traits/blackthorn-tables.md`](../../app/backend/src/resources/context/set18/traits/blackthorn-tables.md) | Blackthorn |
| [`traits/riftbeast-tables.md`](../../app/backend/src/resources/context/set18/traits/riftbeast-tables.md) | Riftbeast |
| [`traits/fae-tables.md`](../../app/backend/src/resources/context/set18/traits/fae-tables.md) | Fae |
| [`traits/lux-avatar-tables.md`](../../app/backend/src/resources/context/set18/traits/lux-avatar-tables.md) | Lux and Avatar variants |
| [`traits/sprykin-tables.md`](../../app/backend/src/resources/context/set18/traits/sprykin-tables.md) | Sprykin and the BFF |
| [`traits/blossom-tables.md`](../../app/backend/src/resources/context/set18/traits/blossom-tables.md) | Blossom |
| [`traits/elderwood-tables.md`](../../app/backend/src/resources/context/set18/traits/elderwood-tables.md) | Elderwood plants |
| [`traits/primal-tables.md`](../../app/backend/src/resources/context/set18/traits/primal-tables.md) | Primal |
| [`traits/solar-lunar-eclipse-tables.md`](../../app/backend/src/resources/context/set18/traits/solar-lunar-eclipse-tables.md) | Solar, Lunar, and Eclipse |
| [`augments/call-to-chaos.md`](../../app/backend/src/resources/context/set18/augments/call-to-chaos.md) | Call to Chaos |
| [`augments/golden-egg.md`](../../app/backend/src/resources/context/set18/augments/golden-egg.md) | Golden Egg |
| [`augments/expedition.md`](../../app/backend/src/resources/context/set18/augments/expedition.md) | Expedition |
| [`augments/other-rules.md`](../../app/backend/src/resources/context/set18/augments/other-rules.md) | Other recovered augment rules |
| [`augments/offer-restrictions.md`](../../app/backend/src/resources/context/set18/augments/offer-restrictions.md) | Offer restrictions |
| [`augments/dark-ritual.md`](../../app/backend/src/resources/context/set18/augments/dark-ritual.md) | Dark Ritual |
| [`augments/trait-ladder.md`](../../app/backend/src/resources/context/set18/augments/trait-ladder.md) | Trait Ladder |
| [`augments/loaded-dice.md`](../../app/backend/src/resources/context/set18/augments/loaded-dice.md) | Loaded Dice interactions |
| [`augments/blossoms-call.md`](../../app/backend/src/resources/context/set18/augments/blossoms-call.md) | Blossom’s Call |
| [`augments/booster-pack.md`](../../app/backend/src/resources/context/set18/augments/booster-pack.md) | Booster Pack / + / ++ |
| [`augments/frontline-backline.md`](../../app/backend/src/resources/context/set18/augments/frontline-backline.md) | Frontline Foundation and Backline Blueprint |
| [`augments/warpath.md`](../../app/backend/src/resources/context/set18/augments/warpath.md) | Warpath |
| [`augments/slightly-magic-roll.md`](../../app/backend/src/resources/context/set18/augments/slightly-magic-roll.md) | Slightly Magic Roll |
| [`augments/magic-roll.md`](../../app/backend/src/resources/context/set18/augments/magic-roll.md) | A Magic Roll |
| [`augments/expected-unexpectedness.md`](../../app/backend/src/resources/context/set18/augments/expected-unexpectedness.md) | Expected Unexpectedness |
| [`augments/missed-connections-slice-of-life.md`](../../app/backend/src/resources/context/set18/augments/missed-connections-slice-of-life.md) | Missed Connections and Slice of Life |
| [`augments/hard-commit.md`](../../app/backend/src/resources/context/set18/augments/hard-commit.md) | Hard Commit |
| [`augments/solo-leveling.md`](../../app/backend/src/resources/context/set18/augments/solo-leveling.md) | Solo Leveling |
| [`augments/bonus-gift.md`](../../app/backend/src/resources/context/set18/augments/bonus-gift.md) | Bonus Gift qualifying sources |
| [`mechanics/wisp-offer-rules.md`](../../app/backend/src/resources/context/set18/mechanics/wisp-offer-rules.md) | Wisp offers, purchases, and eligibility |
| [`mechanics/wisp-heroic-sacrifice-hand-of-baron.md`](../../app/backend/src/resources/context/set18/mechanics/wisp-heroic-sacrifice-hand-of-baron.md) | Heroic Sacrifice and Hand of Baron |
| [`mechanics/wisp-preppers.md`](../../app/backend/src/resources/context/set18/mechanics/wisp-preppers.md) | Preppers |
| [`mechanics/wisp-potions-potioncraft.md`](../../app/backend/src/resources/context/set18/mechanics/wisp-potions-potioncraft.md) | Potions and Potioncraft |
| [`mechanics/wisp-prismatic-blossom.md`](../../app/backend/src/resources/context/set18/mechanics/wisp-prismatic-blossom.md) | Prismatic Blossom Wisp effects |
| [`items/selected-effect-tables.md`](../../app/backend/src/resources/context/set18/items/selected-effect-tables.md) | Selected item and effect references |
| [`items/emblem-recipes.md`](../../app/backend/src/resources/context/set18/items/emblem-recipes.md) | Emblem recipes and bonuses |
| [`systems/solo-stage-one.md`](../../app/backend/src/resources/context/set18/systems/solo-stage-one.md) | Solo Stage 1 reference |
| [`systems/reference-conflicts.md`](../../app/backend/src/resources/context/set18/systems/reference-conflicts.md) | Published differences and incomplete fields |
| [`mechanics/wisp-offers-tier-3-base.md`](../../app/backend/src/resources/context/set18/mechanics/wisp-offers-tier-3-base.md) | Wisp offer ledger — tier 3 base |
| [`mechanics/wisp-offers-tier-3-blossom.md`](../../app/backend/src/resources/context/set18/mechanics/wisp-offers-tier-3-blossom.md) | Wisp offer ledger — tier 3 blossom |
| [`mechanics/wisp-offers-tier-2-base.md`](../../app/backend/src/resources/context/set18/mechanics/wisp-offers-tier-2-base.md) | Wisp offer ledger — tier 2 base |
| [`mechanics/wisp-offers-tier-2-blossom.md`](../../app/backend/src/resources/context/set18/mechanics/wisp-offers-tier-2-blossom.md) | Wisp offer ledger — tier 2 blossom |
| [`mechanics/wisp-offers-tier-1-base.md`](../../app/backend/src/resources/context/set18/mechanics/wisp-offers-tier-1-base.md) | Wisp offer ledger — tier 1 base |
| [`mechanics/wisp-offers-tier-1-blossom.md`](../../app/backend/src/resources/context/set18/mechanics/wisp-offers-tier-1-blossom.md) | Wisp offer ledger — tier 1 blossom |
| [`mechanics/wisp-offers-tier-3-prismatic.md`](../../app/backend/src/resources/context/set18/mechanics/wisp-offers-tier-3-prismatic.md) | Wisp offer ledger — tier 3 prismatic |
| [`augments/offers-encounter.md`](../../app/backend/src/resources/context/set18/augments/offers-encounter.md) | Augment offer ledger — encounter |
| [`augments/offers-gold.md`](../../app/backend/src/resources/context/set18/augments/offers-gold.md) | Augment offer ledger — gold |
| [`augments/offers-silver.md`](../../app/backend/src/resources/context/set18/augments/offers-silver.md) | Augment offer ledger — silver |
| [`augments/offers-prismatic.md`](../../app/backend/src/resources/context/set18/augments/offers-prismatic.md) | Augment offer ledger — prismatic |
| [`augments/bonus-gift-sources-wisp.md`](../../app/backend/src/resources/context/set18/augments/bonus-gift-sources-wisp.md) | Bonus Gift source ledger — wisp |
| [`augments/bonus-gift-sources-augment.md`](../../app/backend/src/resources/context/set18/augments/bonus-gift-sources-augment.md) | Bonus Gift source ledger — augment |
| [`augments/bonus-gift-sources-trait.md`](../../app/backend/src/resources/context/set18/augments/bonus-gift-sources-trait.md) | Bonus Gift source ledger — trait |
| [`augments/bonus-gift-sources-champion.md`](../../app/backend/src/resources/context/set18/augments/bonus-gift-sources-champion.md) | Bonus Gift source ledger — champion |

## Integrity checks

- Wisp ledger: 366 rows.
- Augment/encounter ledger: 252 rows.
- Bonus Gift ledger: 267 rows.
- Shared requirement key: 87 definitions, repeated where used.
- Runtime collections added: 58.
- Uploaded file SHA-256: `8e15dec768c70fbc1da55614e390748d6d1be74b435aa59bb3832f86a9a0a4b7`.

The import checks compare ledger rows as multisets against the upload, verify
all requirement references resolve inside each chunk, validate Markdown table
widths, and load every file through the repository provider. Run the existing
context and assistant suites for selection, set isolation and injection checks.

Validation result: all 58 files loaded successfully; all 885 ledger rows matched
the upload exactly as multisets, every referenced condition was defined locally,
and table widths, set isolation, representative retrieval and local inventory
links passed. Existing assistant/context/skill/chat suites: **77 passed, 1 failed**.
The failure is `test_assistant_spec_coerces_model_and_reasoning_enums`: it requests
`gpt-5.5`, which the existing `OpenAIModels` enum does not accept. It does not
exercise the imported content. No provider or model configuration was changed.
