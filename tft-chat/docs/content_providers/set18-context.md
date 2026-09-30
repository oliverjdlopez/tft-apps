# Set 18 context coverage and sources

The Set 18 factual corpus lives in
`app/backend/src/resources/context/set18/`. It uses the existing
frontmatter fields (`name`, `description`, `kind`, `sets`), cost/rarity sections,
bold entity entries and concise mechanical descriptions. Every document is
restricted to `sets: 18` and has a unique `set-18-` name. This is the only
retained runtime context corpus. Provider behavior and configured application
set are unchanged.

The original baseline reference date is **2026-09-06**, targeting **patch 18.1**, including
Riot's August 31 balance and September 1 bug-fix notes. The patch-notes index
was checked for a newer patch before authoring.

## September 20 player reference supplement

The [player reference import](set18-player-reference-import.md) adds 58 scoped
Markdown collections from the supplied patch 18.2 document, including systems,
trait calculations, augment rewards, Wisp effects and complete offer/delivery
ledgers. It preserves source disagreements and does not declare the older
baseline or its JSON companions refreshed. The linked import inventory records
all paths, provenance, table repair and validation boundaries.

## Coverage

| Resource under `context/set18/` | Coverage |
| --- | --- |
| `unit_context.md` | 65 champions, grouped by cost; traits and combat/scaling roles; Lux's nine origin variants and Adaptor form dependence |
| `traits/major.md` | 11 shared origins plus the combined Eclipse mechanic |
| `traits/horizontal.md` | 12 combat classes |
| `traits/unique.md` | 12 exclusive or small traits with their owners |
| `items/catalogue.md` | 104 completed, Radiant and Artifact entries; explicit removed-Artifact note |
| `items/special.md` | 20 emblem families, bonus effects, special variants and component families |
| `items/mechanic-items.md` | Temporary potions, permanent stat consumables and trait selectors |
| `augment_context.md` | 246 distinct displayed augment names across the three rarities, including an explicitly disabled entry |
| `mechanics/wisps.md` | Shop cadence, purchase restrictions, Blossom exceptions, stage bands, cooldown meaning and eligibility dimensions |
| `mechanics/wisps-*.md` | 174 named Wisps across seven categories; 365 non-conflicting variant records with prices, tiers, windows, cooldowns, requirements, modes and augment exclusions |
| `system_context.md` | Live Carousel, targeting, PvE-loot and encounter changes |

The original baseline contains 17 Markdown context documents. Wisp effect descriptions, like the existing
item and unit references, summarize mechanical identity instead of reproducing
full tooltips. Each Wisp record labels its base, upgraded or prismatic variant. External
variant IDs and citations are omitted from runtime context. Exact effect values can differ between
variants even when they share an effect summary.

## External reference data

| Reference | Used for |
| --- | --- |
| [Riot patch-notes index](https://teamfighttactics.leagueoflegends.com/en-us/news/tags/patch-notes/) | Latest published patch check |
| [Riot patch 18.1](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-18-1/) | Live corrections, removals, disabled augment, systems and late Wisp guarantee |
| [Riot Enchanted Wilds overview](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/enchanted-wilds-overview/) | Wisp fundamentals and champion-specific mechanics; reveal numbers do not override live data |
| [Tactics.tools Set 18 reference](https://tactics.tools/info/set-update) | Champion role labels, variants and mechanical identity |
| [Tactics.tools units](https://tactics.tools/info/units) | Cross-check of all 73 named champion/form records' costs and trait memberships; Lux forms collapse to one roster champion |
| [Tactics.tools traits](https://tactics.tools/info/traits) | Live trait identities and breakpoints |
| [Tactics.tools items](https://tactics.tools/info/items) | Equipment effects and families |
| [Tactics.tools augments](https://tactics.tools/info/augments) | Rarity and direct augment effects; duplicate names consolidated |
| [OP.GG Set 18](https://op.gg/tft/set/18) | Emblem effects and Consuming Flora variant distinction |
| [Little Buddy Bot Wisp database](https://www.littlebuddybot.com/tft-wisps) | Named Wisp variants, offer constraints, cooldown definitions and band mapping |
| [Published Wisp CSV](https://docs.google.com/spreadsheets/d/e/2PACX-1vT7Tuku8zc7N5ZaEvVy5XAicB1hOOrlNdAZD_R_xIyoi8lhW82-kgUMrnJzjpm1dqH6pJyK2wYobO4r/pub?gid=0&single=true&output=csv) | The public dataset linked by the Wisp page; 366 source records before excluding one conflicting record |

The Wisp CSV downloaded for this update has SHA-256
`a4db501b302e95ebeab761e2bddd155e528be83dfa46af37b2044890689b8776`.
The pages and published CSV are mutable references; the access date identifies
this snapshot rather than promising automatic future updates.

Baseline runtime context states mechanics directly without citation URLs. The
September 20 supplements retain source labels where published values conflict;
URLs and research coverage notes remain in documentation for maintenance.
Unlisted conditions are omitted rather than asserted to be unrestricted.

## Conflicts and evidence boundaries

- Riot's live Wisp rule takes precedence over third-party descriptions that
  claim all late Wisps become Combat: the guarantee applies to every other Wisp
  after Stage 5. The wording is retained without inventing a different boundary.
- Riftbeast's AD/AP/AS growth is corrected to 5% using the August 31 patch notes;
  the third-party trait page still displayed 6%.
- Death's Defiance is still visible in a third-party item list but is explicitly
  removed by Riot, alongside Hullcrusher and Sniper's Focus. It is not listed as
  an available Set 18 Artifact here.
- Forge A Friend is identified as disabled by Riot's August 28 update rather
  than presented as an available augment solely because it remains in a list.
- `DA_BearsVisit18_Upgrade` has Tiger's Visit as its name and effect but Bear
  requirements in the Wisp CSV. This one record is excluded pending correction;
  it is not silently renamed or treated as another Tiger upgrade.
- The source contains multiple Beast Within reward variants and duplicate
  display names. The corpus consolidates names and explicitly mentions the
  Nidalee/Sivir alternatives rather than assigning one reward universally.
- Published offer bands and cooldowns do not establish exact per-Wisp odds.
  No uniform distribution or undocumented selection weights are invented.
- Blank conditional fields mean no condition is listed in that source. They do
  not prove the absence of hidden eligibility rules. Unresolved localization
  placeholders, detailed cashout probabilities and a currently unpopulated
  Support-item pool are not filled from old-set assumptions.

## Validation

- Checked all 73 external champion/form records against the live unit page for
  cost and trait agreement; the extra generic Lux card is not a separate unit.
- Verified 65 roster entries, 36 trait entries, 246 distinct augment names and
  365 retained Wisp variant records; checked unique context names and set tags.
- Added retrieval regressions in `tests/test_context_service.py` for Set 18
  entity selection, unsupported-set isolation, unrelated-query abstention, excerpt budget
  preservation and Wisp eligibility retention and citation-free excerpts.
- Assistant, context and skill suites: **39 passed**, using assistant tests
  first to avoid an existing import-order circular dependency.
- The wider chat suite has three failures reproduced with the Set 18 directory
  removed: an existing tool-list expectation mismatch and two failures caused
  by the environment's SOCKS proxy dependency. These are not introduced by the
  context changes. Directly collecting the context suite first also exposes an
  existing `domain.assistants` / context-provider circular import.

Refresh the cited data and update this snapshot note when patch behavior
changes. Keep reference files scoped to their set and do not change provider logic
merely to add another set's reference files.
