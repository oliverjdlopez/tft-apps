---
name: tft-artifact-itemsv2
description: Reason about TFT artifact compatibility, enabling mechanics, build-around requirements, and holder tradeoffs. Use whenever an artifact materially changes a build, board, or offer evaluation, including when it emerges during another analysis. Not needed for a simple effect lookup.
---

# Artifact compatibility and build-around requirements

An artifact's value depends on whether a holder can exploit its particular
effect. Treat the artifact as a mechanical requirement to understand, not an
automatically stronger replacement for a standard item.

## Compatibility is more than a stat match

Separate the artifact's base stats from its distinctive effect. Identify what
activates that effect, who receives it, and what limits its use. Relevant details
can include attacks versus ability hits, damage type, casts, shielding, crowd
control, takedowns, range, and survival time. An AP user is not necessarily a
good holder for every artifact with AP.

Read the applicable item and unit effects when a conclusion depends on them.
The catalogue `set18/items/catalogue` contains mechanical summaries; its patch
coverage and incomplete tooltips matter. Missing trigger details, stacking rules,
or interactions remain unknown until supported by a fuller source. Resource
access still depends on the active assistant's permissions.

Judge compatibility along three separate dimensions:

- **Activation:** can the holder trigger the effect under the stated conditions?
- **Conversion:** does the benefit improve the holder's actual job, or support
  another important unit?
- **Realization:** can the holder survive, reach targets, or complete enough
  attacks and casts to obtain that benefit in the relevant fight?

A legal interaction can be strategically weak. A promising interaction can be
too dependent on missing support to recommend from the player's current board.

## Identify the cost of making it work

Distinguish an artifact that fits an existing build from one that changes the
build's requirements. Ask what other items, protection, positioning, or allied
effects are needed only when they affect the proposed use. Count those demands
against the benefit: the artifact occupies a slot, and its supporting pieces
may also displace damage, survival, or utility.

Describe broad versus narrow usability in terms of qualifying mechanics, rather
than maintaining a timeless list of good holders. A generally useful stat bundle
can still be inefficient on a specific unit; a narrow effect can be exceptional
when its requirements are satisfied. For an artifact offer, distinguish access
to a compatible holder now from a plan that depends on finding one later.

## Worked mechanical distinctions

These examples use the patch 18.1 summaries in `set18/items/catalogue`; reread
the applicable source before applying them to another revision. They illustrate
compatibility, not measured rankings.

- **Lich Bane:** the described effect occurs on the first attack after casting.
  A hypothetical holder that repeatedly casts and then attacks can exploit that
  sequence. Frequent casts alone do not establish value if the holder cannot
  deliver the following attack. Check the attack-and-cast pattern before calling
  it a spellcaster item.
- **Horizon Focus:** the summary ties damage to stuns. A hypothetical unit with
  no stun has no demonstrated way to activate that effect through its own kit.
  An external source might change the analysis, but do not assume allied stuns
  count as the holder's triggers without supporting rules.
- **Manazane:** the summary places Mana recovery after the first cast. For a
  holder that dies before casting, this described recovery does not solve the
  first-cast problem. For one that casts and survives, investigate subsequent
  cast access and any Mana restrictions before estimating its benefit.

## Use performance evidence for the question it answers

Holder-specific outcomes can support practical relevance, but different holders
also differ in stars, investment, and supporting boards. Artifact acquisition
can correlate with augments or other advantages; a strong observed result need
not come entirely from the item. Do not infer trigger behavior from a ranking.

Explain the compatibility, the support it requires, and the alternative it
displaces. If a missing rule would reverse the recommendation, identify that
rule and keep the recommendation conditional rather than inventing an effect.
