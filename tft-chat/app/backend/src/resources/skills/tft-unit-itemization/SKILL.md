---
name: tft-unit-itemization
description: Analyze generic TFT itemization for a named unit, including common craftable items, carry or frontline allocations, holder patterns, and notable artifact usage. Use for questions such as "Does Shen prefer tank or damage items?", "What are the best artifacts on Vi?", holder, or item-frequency questions.
---
# Itemization Investigation Workflow



## Crystallize the question and define the scope

Cystallizing the question and emit a text part describing it in one sentence before you begin your investigation. Then, your investigation should follow this series of steps:

1. The relevant analytical dimensions are the named unit and whether the subject is frequency, outcome performance, item role, artifact usage, or a comparison such as tank versus damage.
2. Scope and constraints determine which evidence is relevant. A generic itemization analysis does not require transition paths, early-game slams, or unrelated composition choices.
3. Resolve every player-language unit, item, and trait name used as a filter together in one `resolve_tft_names` call before every named-entity lookup. Use the exact stored names returned by that call. Do not resolve category words such as "craftable", "Artifact", or "tank" as entity names.


## Initial Evidence Gathering

### Use ranking tools

1. Use rank_items to ground your investigation. The rankings will give your a sense of direction. They may immediately show core patterns, but this is not the end of the investigation.

### Use delta tools
2. Emit at least one tool call to all of the delta tools, `get_cohort_unit_deltas`, `get_cohort_item_deltas`, `get_cohort_trait_deltas`. These will give you a sense of the context of the unit's itemization and how it compares to other units, items, and traits. 

## Determining Direction for Further Investigation

There are several signals to look for. A single investigation may not have all of these signals, and the existing ones will not have equivalent signal strenght. 

### Identifying line-enabling items

`Artifact` items and `Emblems` can be "line-enabling." Since they give a new trait or ability, they can enable a composition or a particular line to go from, in the most extreme cases, an unviable line to one of the best lines in the game. 


### Itemization archetypes

#### Tanks

Tanks want items which let them absorb as much damage as possible before they die. Tank items typically provide Health, Armor, Magic Resist, shields, healing, or damage reduction. The best mix depends on the kind of damage the tank is taking and the unit's own abilities. Mana items can also be valuable when casting gives the unit more durability or crowd control.

#### Fighters

Fighters are melee damage dealers which need enough damage to kill units and enough durability to survive while doing it. They can often use damage, healing, Health, resistances, or hybrid items. The right balance depends on what the unit already gets from its abilities: a fighter with built-in durability may prefer more damage, while one with strong base damage may need help staying alive.

#### Ranged damage

Ranged damage dealers usually stay behind the frontline and want to maximize the damage they deal while protected. Their items commonly provide AD or AP, Attack Speed, Mana, critical strike, or damage amplification. Full damage is not always correct. A defensive item can be worthwhile when the unit is vulnerable to backline access, while a unit that needs to cast or attack more often may value Mana or Attack Speed over raw damage.

#### Quick casters

Quick casters are itemized to prioritize time to first cast. For example, a tank with a large crowd control effect may be itemized to prioritize getting off a fast initial cast, since crowd control is better the earlier it is used. Likewise, a unit with a team buff ability may fall into this archetype. A staple of these itemizations is `Protector's Vow` because it gives starting mana and a strong shield to prevent the unit from dying before it can cast.

#### Utility item holders

Some units are not primarily damage dealers or tanks, but instead hold utility items for the team. For example, a backline unit with an ability that hits many enemies may perform when well when holding `Void Staff` and / or `Morellonomicon`. The best kinds of these units are those who can also provide supplementary damage, healing, or crowd control.

### Itemization Prioritization

Some compositions can succeed with a variety of itemizations and do not require any one specific item to place well, as long as the itemized units have cohesive and complementary loadouts. Other compositions may be highly dependent on a specific item on a specific unit or even a specific build taken from a small set of options.



## Considerations

Retain this information in the back of your mind as you investigate. It may not be relevant to the specific question, but it is important to keep in mind to notice subtle patterns and most importantly, to avoid misinterpretation of the data.

### Understanding Different Item Types


#### Craftable 

The standard type of item, made my combining two components. They are the most common type of item and the core of every game's item enconomy. Good players decide to make, or not make items, based on their particular spot in a game. Itemization decisions typically weigh around what items make the board strong at the moment and which components are important enough to save for later in the game when they can be made into optimal or near-optimal items.

### Emblems

Emblem items give the holder a trait they don't have my default. Some emblems are craftable by combining a normal `component` with a spatula or pan, while others can only be gotten through a special condition such as an augment or carousel round. 


### Artifact 

Artifact items are a class of items which can only be obtained in certain scenarios. Artifacts items are more powerful than regular items and have unique and comparatively complex effects. 

A rule of thumb is that regular items are usable on a 'family' of holders. For example, if `Deathblade` is a holder's best item, then `Infinity Edge` might be slightly to moderately worse but it will probably be comparable. Due to the specificity of Artifact items effects, they can be very well used by a few select units, but not broadly. 


This is NOT a hard rule. There are plenty of artifacts which are generally usable. `Infinity Force`, for example, doesn't even have an effect, it just gives every kind of stat. So it is notably best on `Fighters` because they can use the damage stats like AD as well as the tank stats like Armor and MR, but it certain situations, it could be conceivably passable on any unit. `Hullcrusher` gives tank stats and HP if the user does not have any adjacent allies. It could be used by any `Tank`. 


### Radiant items

Radiant items are more powerful versions of other items. They are always named by placing "Radiant" in front of the base item name. For example, `Radiant Deathblade` is a more powerful version of `Deathblade`. Radiant items are only obtainable in certain scenarios and are more powerful than regular items. They don't have unique effects like artifact items, but they give greatly enhanced stats may extend the effects of the base item (e.g. "`Radiant Edge of Night` give much more AD than `Edge of Night` and also gives the holder two invulnerable periods instead of one"). Only consider radiant items when if the user's question specifically requires or references them. 


## Tips


### Interpret rankings correctly

Separate common from strong:

- "Best", "strongest", or "performs best" ordinarily refers to outcome performance unless frequency is specified. Lower average placement is the primary ranking signal, with top-four rate, win rate, and the relevant board sample providing supporting context.
- "Most common", "most played", or "popular" refers to frequency. Individual-item frequency is measured by `boards` or `pick_rate_per_board`; `holds` measures item instances.
- A generic itemization overview can usually be supported by up to five individual items. Frequency and performance are distinct signals and may identify different leaders.
- Fewer than 50 boards is non-reportable, 50–499 is suggestive, and 500 or more is solid for this store. A low-sample row does not support a best-in-slot conclusion.
- Keep dimensions comparable. Do not mix all-star rollups with exact-star rows or holder-specific rows with item-overall rows.

### Read allocation patterns

Item-class preference and build rigidity depend on the distribution of allocations:

- Leading items are comparable only within the same unit and stated scope, and board counts provide necessary context for headline metrics.
- Rigidity is supported when one or a small set of allocations dominates a meaningful sample and alternatives are materially less common or worse in a comparable view.
- Flexibility is supported when several allocations recur without a clear frequency or outcome break. Other distributions are better understood as mixed evidence.
- Motifs such as damage, durability, mana or ability access, attack speed, AD/AP, shred, anti-heal, or utility are supported only when the returned item names and supplied context establish them. Item data alone does not establish a unit's ability scaling or in-game role.
- Tank-versus-damage comparisons may reflect allocation frequency, outcomes, or both. Final-board association alone is not a causal relationship.
- Meaningful non-carry allocation can represent coherent support allocation, spare-item usage, or a selection artifact; those possibilities require distinct evidence.
- Artifacts and other special item families are analytically distinct from craftable items and require both identified family context and a notable sample.

### Practical interpretation

A practical itemization interpretation depends on the effective scope and board sample, the relevant item rankings, and the observed holder pattern. Craftable items, artifacts, and other special families belong to different acquisition contexts and should not be treated as one population. The most decision-relevant uncertainty usually comes from sample size, survivorship, or an unobserved acquisition and timing constraint.
