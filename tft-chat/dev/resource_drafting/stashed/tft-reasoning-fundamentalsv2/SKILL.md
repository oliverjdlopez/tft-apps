---
name: tft-reasoning-fundamentalsv2
description: Assess TFT board strength through combat roles, damage delivery, survival, cast access, utility coverage, and bottlenecks. Use to explain why a board functions or fails and which kind of upgrade addresses its weakness. Not a general statistical investigation or economy and transition guide.
---

# Board strength and combat bottlenecks

Assess what the board can accomplish during combat. Unit cost, star level,
completed items, and active traits describe investment; their contribution
depends on which combat functions they enable and whether those functions
remain available long enough to matter.

## Connect roles to actual behavior

Understand the board's damage sources, protection, and utility using known kits,
items, and supplied combat observations. A nominal tank may contribute crucial
control; a carry may need protection more than additional damage. Do not infer
every unit's role from its position, traits, or item count.

Trace the relevant dependencies: which units buy time, which units use that
time, which targets they can reach, and which effects enable their damage.
Durable frontline does not automatically protect against threats that bypass
it. A strong damage source contributes little while unable to attack or cast.

## Distinguish bottlenecks

Use these as possible explanations, not a checklist that every answer must run:

- **Survival:** a key unit dies before delivering its important damage or cast.
  Identify whether the exposed unit is the frontline, a secondary holder, or the
  main carry; extra durability elsewhere may not address the problem.
- **Cast access:** the useful ability arrives too late or too infrequently.
  Examine the actual Mana rules, attack access, cast time, and control effects
  before assuming any Mana or attack-speed item solves it.
- **Damage conversion:** the board survives but fails to remove relevant
  enemies. Consider damage type, mitigation, healing, and target access before
  concluding that it simply needs more offensive stats.
- **Delivery and coverage:** damage or utility exists but does not reach the
  enemies that matter, or arrives after the decisive part of the fight.
  Positioning and application can matter as much as effect ownership.
- **Dependence on one unit:** losing or disabling one holder removes most of the
  board's output. A secondary threat may help, but investment spread too thinly
  can leave neither threat functional.

Combat evidence can distinguish these explanations. A final board and placement
usually cannot. Without observations, describe the plausible dependency and
what would confirm it rather than diagnosing an unseen fight as fact.

## Evaluate the marginal contribution of an upgrade

Compare what the change adds with what it removes. A trait breakpoint can cost
an upgraded unit or useful ability; a stronger individual unit may leave a
required function uncovered. Count existing coverage before crediting a new
source of an effect, including whether it reaches the same targets at the same
time. Duplicate ownership is not automatically duplicate value or zero value.

Avoid a blanket additive-versus-multiplicative rule. Two sources can complement
each other mechanically without multiplying overall board strength. Attack
speed, Mana generation, damage, healing, shields, and resistances interact
through specific rules, caps, and combat conditions. Explain the interaction
that matters instead of calling every combination a multiplier.

## Contrasting situations

The following are hypothetical observations, not claims about particular units:

- **The carry keeps attacking, but the frontline collapses before its scaling
  pays off.** Extending the frontline's survival is a candidate improvement
  because it could buy useful carry uptime. Compare that with damage sufficient
  to end the fight sooner; the observation does not establish one universal fix.
- **The frontline survives, but an enemy reaches and kills the carry early.**
  More frontline durability does not directly address the observed failure.
  Investigate protection, positioning, target access, or carry survival using
  the relevant mechanics.
- **A utility unit dies just before its first cast.** Survival or earlier cast
  access may unlock its contribution. If it already casts reliably, the same
  investment needs a different justification, such as a useful second cast.

For a concrete coverage example, the patch 18.2 reference
`set18/items/selected-effect-tables` describes Last Whisper's Sunder as
non-stacking and applied by attacks and ability damage. Another source should
not be credited with doubling that reduction on the same target. It could
still improve coverage or uptime. Recheck source applicability and the other
effect's rules before extending that conclusion to a named build.

## Make the explanation useful

Identify the important function, what currently limits it, and how the proposed
change would help. Mention the sacrificed function when relevant. Distinguish
mechanical reasoning from observed combat behavior and aggregate performance;
none alone proves that a proposed change wins a particular matchup.
