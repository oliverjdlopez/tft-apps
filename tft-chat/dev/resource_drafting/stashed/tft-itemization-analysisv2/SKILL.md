---
name: tft-itemization-analysisv2
description: Reason about TFT item allocation and build coherence using unit kits, existing items, board roles, component opportunity costs, and competing holders. Use for build choices, item distribution, flexible alternatives, and crafting tradeoffs. Not a general item ranking or artifact-mechanic reference.
---

# Item allocation and build coherence

Evaluate an item as part of a holder's build and the board's allocation. The
question is what this item adds in this position, including what another holder
or craft would have contributed instead.

## Match the build to the job

Establish how the holder delivers its contribution: attacks, casts, sustained
damage, burst, frontline survival, healing, shielding, or utility application.
Use actual kit and effect descriptions. AD/AP labels or a recommended-item list
do not establish cast frequency, targeting, scaling, or survival requirements.

An item's value can come from enabling that contribution, increasing it, or
keeping it available. For example, a useful utility cast may depend on surviving
until it occurs; a damage build may depend on reliable attack access. Extra
stats do not solve a delivery problem unless their mechanics address it.

## Consider the complete build

Assess remaining needs after accounting for existing items, traits, augments,
and allied effects. Check the particular interaction rather than applying a
fixed recipe such as damage plus speed plus sustain.

- An enabling item can make the rest of a build productive, but only if it
  addresses a real restriction.
- Repeating a stat can remain valuable. A smaller proportional increase is not
  by itself proof that another stat produces a better outcome.
- Repeating a unique or non-stacking effect needs a different justification,
  such as other stats, coverage, or uptime; verify the exact stacking rule.
- Survival and sustain depend on the incoming threat and time available to
  benefit. Healing that occurs after damage is dealt cannot be assumed to rescue
  a holder killed before it acts.

Treat a final slot as a complement to the fixed build. Do not rank it solely
from the item's average across all builds on that unit.

## Allocate across holders

Compare the marginal benefit of completing an established holder with enabling
another useful holder. Neither concentrating all investment nor spreading it
evenly is a general rule. Consider which units are upgraded, which have a
functioning kit with their current items, and which still lack a necessary piece.

For shared utility, identify who can apply the effect to relevant targets while
preserving valuable slots elsewhere. A convenient utility holder may have poor
reach or uptime. For temporary holders, consider the supplied transfer or selling
constraints; an ideal eventual allocation is not necessarily available now.

## Account for components and alternatives

Use verified recipes and the components actually available. Compare feasible
crafts, including the second craft enabled or blocked by the first. A superficially
better carry item can consume a component needed for a more important frontline
or utility function.

When discussing immediate crafting versus waiting, distinguish present combat
value from uncertain future flexibility. Do not assume a later component drop,
an item remover, or a replacement holder. Explain which supplied constraint
makes a choice attractive instead of deriving slam timing from final-board stats.

## Worked allocation distinctions

These hypothetical situations illustrate reasoning; they are not fixed builds.

- **Same carry, different protection:** with reliable protection and attack
  access, another offensive item may increase useful output. If that same carry
  is repeatedly killed before contributing, a survival option may enable more
  of its existing investment. The correct choice depends on the observed threat
  and the item's actual protection, not the carry's identity alone.
- **Third carry item versus first frontline item:** if frontline collapse is
  cutting off an already functional carry, frontline investment may buy more
  useful output. If the frontline holds but the carry cannot remove targets,
  the argument for the same allocation changes. Do not infer either situation
  merely from item counts.
- **Utility already supplied:** `set18/items/selected-effect-tables` describes
  Last Whisper's Sunder as non-stacking in patch 18.2. If the relevant targets
  already receive that reduction reliably, do not count another copy as a
  second reduction. Compare its other benefits with an alternative; if coverage
  is incomplete, another applicator may still help. Verify current applicability.
- **Competing crafts:** suppose verified recipes show that two desired crafts
  consume the same sole component. Evaluate the resulting pair of allocations
  using the remaining components, rather than recommending both incompatible
  crafts. Missing components are future possibilities, not current resources.

## Connect item reasoning to evidence

Use holder-specific evidence for a holder claim and fixed-loadout evidence for
an interaction with existing items. Preserve star level and item investment
where the supported comparison requires them. Overall item performance does
not establish value in a particular slot; popularity does not prove compatibility.

Explain the proposed allocation through the job it enables, the tradeoff it
accepts, and the condition under which another allocation would be preferable.
Keep named effects and recipes grounded in accessible references or supplied
source material. Use a playbook for broader investigation structure when needed;
this skill supplies the itemization judgment within that investigation.
