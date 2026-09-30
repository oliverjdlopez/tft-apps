# TFT Statistics Analysis Skill

## Purpose

Use this skill when acting as an agent that can query a Teamfight Tactics (TFT) statistics database and must make grounded decisions about what to query, how to interpret results, and how to convert data into gameplay recommendations.

This skill is **set-agnostic**. Do not assume specific champions, traits, augments, items, portals, encounters, artifacts, anomalies, mechanics, cost distributions, stage timings, or patch details unless they exist in the database, are provided by the user, or are retrieved from a trusted current source.

The goal is not to blindly rank by average placement. The goal is to understand **why a line, item, augment, unit, trait, or decision context appears strong or weak**, and whether that conclusion is robust enough to act on.

---

## Core Operating Principle

TFT data is conditional. A statistic is only meaningful after understanding the situation that produced it.

Always ask:

1. **What population is this statistic drawn from?**
2. **What decision was available to the player at that point?**
3. **What hidden filters or survivorship effects may be present?**
4. **Is the observed result caused by the object itself, or by the conditions under which it is usually selected?**
5. **Would this finding still hold after controlling for patch, rank, stage, placement, itemization, star level, board state, economy, and contesting?**

A TFT database should be treated as a record of **decision contexts**, not merely a leaderboard of game objects.

---

## The Agent's Job

When using a TFT statistics database, the agent should:

* Translate broad questions into precise statistical queries.
* Identify the relevant unit of analysis: match, player-game, round, board snapshot, shop decision, augment choice, item holder, final board, or lobby.
* Apply filters that match the decision context.
* Compare against meaningful baselines.
* Separate macro trends from micro optimizations.
* Detect sample size issues, selection bias, survivorship bias, patch drift, rank effects, and confounding variables.
* Produce conclusions with calibrated confidence.
* Recommend follow-up queries when the current evidence is incomplete.

The agent should avoid answering as though raw stats are self-explanatory.

---

## Important Statistical Measures

### Average Placement

Average placement is the most common TFT stat, but it is easy to misuse.

Use average placement for broad comparisons, but always ask what conditions led to the sample. A line with a 3.8 average placement may be strong, or it may simply be selected mostly from highroll positions.

Good uses:

* Comparing similar options in similar contexts.
* Measuring overall success of a comp, augment, item, or trait breakpoint.
* Detecting broad meta strength.

Bad uses:

* Comparing rare capped boards against common midgame boards.
* Comparing final-board stats against early-game decisions.
* Ranking augment choices without controlling for stage and offered alternatives.
* Ranking items without considering holders, unit star levels, and whether the item was slammed early or made late.

### Top 4 Rate

Top 4 rate measures consistency. It is useful for identifying stable, low-variance lines.

A line can have a strong top 4 rate but a mediocre win rate if it reliably stabilizes but lacks a high cap. This often indicates a safe laddering line rather than a first-place line.

### Win Rate

Win rate measures ceiling. It is useful for identifying high-cap boards, chase traits, late-game transitions, and conditions that convert strong games into firsts.

Win rate is highly sensitive to survivorship bias. Rare boards with high win rates may only appear when the player was already rich, healthy, and highrolling.

### Bot 4 Rate / Eighth Rate

Failure-rate stats are often more useful than average placement when evaluating risk.

A line with a strong average but high eighth rate may be a high-variance line. It may be good when uncontested or highrolled but dangerous when forced.

### Play Rate

Play rate measures popularity, not strength.

High play rate can indicate:

* The option is genuinely strong.
* The option is easy to recognize or force.
* The option is overhyped.
* The option is commonly encountered due to flexible components or openers.

Low play rate can indicate:

* The option is weak.
* The option is hard to recognize.
* The option requires rare conditions.
* The option is underexplored.

Play rate must be read alongside placement, contesting, sample size, and context.

### Delta / Lift

Prefer relative comparisons over isolated values.

Examples:

* This augment averages 4.15 overall, but 3.72 when taken with this opener.
* This item averages 4.40 on the unit overall, but 3.95 when paired with two specific complementary items.
* This comp averages 4.05 uncontested but 4.80 when two or more players contest it.

Useful derived metrics:

* Placement delta versus the population baseline.
* Placement delta versus similar lines.
* Top 4 lift versus baseline.
* Win-rate lift versus baseline.
* Conditional improvement after adding an item, trait, upgrade, or unit.

### Sample Size

Never treat low-sample stats as equivalent to high-sample stats.

Use sample size thresholds appropriate to the question:

* Broad meta trend: needs large samples.
* Common augment/item/unit comparison: moderate to large samples.
* Rare capped board or niche interaction: smaller samples may be acceptable, but confidence should be lower.
* Exploratory hypothesis: low samples can generate questions, not final conclusions.

When sample size is low, say so clearly.

---

## Macro vs Micro Trends

### Macro Trends

Macro trends describe the environment of the patch or meta.

Examples:

* Which lines are common and successful.
* Whether the patch rewards fast leveling, reroll, tempo, or greed.
* Whether AD or AP item trees are more flexible.
* Whether specific traits or unit costs dominate late-game boards.
* Whether players are dying faster or slower than usual.
* Whether high cap boards require specific augments/items or are broadly accessible.
* Whether contesting punishes a line heavily.

Macro analysis should usually query large populations and use broad filters:

* Patch/version.
* Rank bracket.
* Region if available.
* Queue type.
* Time window.
* Player-game level outcomes.
* Common final boards and midgame transition points.

Macro findings should produce recommendations like:

* The meta appears tempo-heavy; prioritize early HP and stable Stage 3 boards.
* Several successful lines share the same item components; these components are flexible openers.
* The strongest capped boards are rare and require high economy, so they should be played from advantaged spots rather than forced.
* A popular comp has declining results when contested, so scout density before committing.

### Micro Trends

Micro trends describe specific optimizations inside a decision context.

Examples:

* Best third item for a carry after two fixed items.
* Whether a unit performs better in one trait shell than another.
* Whether an augment is strong only when taken on Stage 2 but poor on Stage 3 or 4.
* Whether a reroll line should roll on level 5, 6, or 7.
* Whether a secondary carry meaningfully improves top 4 rate or mainly increases win rate.
* Whether a trait breakpoint is worth playing over a stronger upgraded unit.
* Whether positioning adjustments matter against common enemy boards.

Micro analysis should use narrow filters and careful baselines:

* Same patch.
* Same line or board family.
* Same carry.
* Same star level.
* Same item count.
* Same augment count/stage.
* Same level or round window.
* Same player HP/economy bracket when possible.

Micro findings should produce recommendations like:

* In this line, the third damage item improves average placement less than the sustain item, suggesting the carry already has enough damage but needs uptime.
* This trait breakpoint performs well only when it does not require dropping upgraded frontline.
* This augment is a strong opener but not a reliable late pick.
* The line is statistically strong, but only when stabilized before Stage 4.

---

## Decision Context First

Before querying, classify the user's question.

### Common Question Types

#### 1. Meta Overview

User intent: “What is strong right now?”

Query for:

* Common comps/lines.
* Average placement, top 4 rate, win rate, play rate.
* Rank and patch filters.
* Contesting sensitivity.
* Item/augment dependency.
* Recent trend movement if timestamps exist.

Avoid:

* Declaring rare highroll boards as best.
* Ignoring popularity and contesting.
* Mixing patches.

#### 2. Line Selection

User intent: “What should I play from this spot?”

Query for:

* Lines matching current items/components.
* Lines matching current opener units/traits.
* Lines matching augments already taken.
* Lines with viable transition paths from current stage/level.
* Lines that are under-contested in the current lobby if live scouting data exists.

Avoid:

* Recommending a statistically best comp that the player's spot cannot realistically reach.
* Ignoring HP/economy constraints.

#### 3. Itemization

User intent: “What items are best?”

Query for:

* Item performance by holder.
* Holder star level.
* Item slot count: one-item, two-item, three-item contexts.
* Item combinations, not just individual items.
* Timing if available: slammed early versus completed late.
* Board family or trait shell.

Avoid:

* Ranking items globally without holders.
* Treating best-in-slot as mandatory.
* Ignoring item flexibility and opportunity cost.

#### 4. Augment Evaluation

User intent: “Which augment should I take?”

Query for:

* Augment stage.
* Augment tier.
* Current board/item/trait context.
* Other augments already taken.
* Offered alternatives if available.
* Interaction with specific lines.
* Floor versus ceiling: top 4 rate and win rate.

Avoid:

* Using augment global average placement alone.
* Ignoring selection bias: players choose augments when they already fit.
* Comparing augments from different stages or tiers without normalization.

#### 5. Reroll Timing

User intent: “When do I roll?”

Query for:

* Target unit cost.
* Star-level success rates by level and stage.
* Average placement by roll timing.
* Gold spent / remaining economy after rolldown.
* HP at rolldown.
* Number of copies hit by round.
* Contested copies if available.

Avoid:

* Evaluating final 3-star boards only; this ignores failed reroll games.
* Ignoring games where players rolled and missed.

#### 6. Leveling / Tempo

User intent: “Should I level or greed?”

Query for:

* Outcomes by level on specific rounds.
* HP/economy at key stages.
* Board strength proxies.
* Streak status.
* Stabilization timing.
* Final placement by tempo line.

Avoid:

* Treating standard leveling intervals as universal.
* Ignoring whether the player had a board worth leveling for.

#### 7. Contesting

User intent: “Can I still play this if others are playing it?”

Query for:

* Number of players holding key units.
* Number of players ending in same comp family.
* Placement by contest count.
* Hit rates for 2-star / 3-star targets under contesting.
* Alternative lines using similar items.

Avoid:

* Assuming all contesting is equally bad.
* Ignoring whether the line uses shared carries, shared tanks, shared items, or just shared traits.

#### 8. Patch Trend / Emerging Tech

User intent: “Is this becoming good?”

Query for:

* Time-bucketed performance within the same patch.
* Play-rate growth.
* Placement movement.
* Rank-bracket adoption.
* Whether performance falls as play rate rises.
* Whether high-MMR players adopted it before broad population.

Avoid:

* Mistaking one-day noise for a trend.
* Combining data before and after hotfixes.

---

## Query Planning Framework

Before running database queries, write or internally form a plan with these fields:

1. **Decision being analyzed**: What action or judgment is being made?
2. **Available context**: Patch, rank, stage, level, HP, gold, items, augments, units, traits, lobby state.
3. **Primary population**: Which games/rounds/boards are relevant?
4. **Comparison baseline**: What should the result be compared against?
5. **Controls**: Which variables must be held constant or stratified?
6. **Metrics**: Average placement, top 4, win rate, play rate, delta, sample size, hit rate, etc.
7. **Failure modes**: Selection bias, survivorship bias, low sample, confounding, patch drift.
8. **Follow-up query**: What would validate or challenge the first result?

Example:

User asks: “Is this augment good with my opener?”

Good query plan:

* Filter to same patch and rank bracket.
* Filter to games where the augment was offered or taken at the same augment stage if offered data exists; otherwise taken data only with selection-bias warning.
* Filter to similar opener traits/units/items before augment selection.
* Compare to all other augments taken from similar spots.
* Measure average placement, top 4 rate, win rate, and sample size.
* Stratify by whether the augment led to the expected line.
* Follow up by checking whether the augment remains strong after excluding obvious highroll boards.

---

## Baselines Matter

Every conclusion should have a baseline.

Weak baseline:

* “This item averages 4.05, so it is good.”

Better baseline:

* “In this patch and rank bracket, all completed items on this unit average 4.32. This item averages 4.05 over a large sample, so it appears above average on this holder.”

Best baseline:

* “On this unit, after controlling for two-star copies and the same board family, this item averages 4.05 compared with 4.28 for other third-item options. Its top 4 rate improves, but its win rate is neutral, suggesting it is a consistency item rather than a cap-increasing item.”

Useful baselines:

* Whole population baseline.
* Same patch baseline.
* Same rank bracket baseline.
* Same comp family baseline.
* Same item holder baseline.
* Same augment stage/tier baseline.
* Same level/stage baseline.
* Same star-level baseline.
* Same HP/economy bracket baseline.
* Same contesting level baseline.

---

## Avoiding Common TFT Data Traps

### Survivorship Bias

Final-board stats only include players who survived long enough to make those boards.

A capped board with excellent stats may not be a good line to force because failed attempts are missing or undercounted.

To reduce survivorship bias:

* Include games that attempted the line earlier.
* Track key unit holds, item commitments, trait commitments, or augment commitments before the final board.
* Compare outcomes from the moment of commitment, not only from final board state.

### Selection Bias

Players choose options when they already fit their spot.

An augment, item, or unit may look strong because good players take it only when conditions are favorable.

To reduce selection bias:

* Compare within similar starting contexts.
* Use offered-but-not-taken data if available.
* Compare taken options among the same offered set if available.
* Stratify by items, opener, HP, gold, and stage.

### Confounding

A variable may appear strong because it is correlated with another stronger variable.

Examples:

* A trait breakpoint looks strong because it usually includes a strong upgraded carry.
* An item looks weak because players build it when desperate.
* A late-game unit looks strong because only healthy players reach it.
* A comp looks weak because it is often forced by contested players.

To reduce confounding:

* Control for obvious related variables.
* Compare within comp families.
* Use matched contexts where possible.
* Report uncertainty when controls are unavailable.

### Patch Drift

TFT changes frequently. Mixing patches can destroy the meaning of a result.

Always filter by patch unless the question is explicitly about historical trends.

For recent patches, consider time buckets within a patch if the meta is evolving quickly.

### Rank Effects

Stats vary by rank.

Low-rank data may overvalue simple or forgiving lines. High-rank data may overvalue lines that require precise execution but are stronger when played well.

When possible, analyze by rank bracket:

* All ranks for broad popularity.
* Emerald/Diamond+ for general competitive signal.
* Master+ or GM/Challenger for optimized play, if sample size permits.

### Contestedness

A line's strength depends on how many players are competing for the same units and items.

Analyze:

* Performance when uncontested.
* Performance with one contesting player.
* Performance with multiple contesting players.
* Whether contesting affects the carry, tank, low-cost reroll targets, or only splash traits.

### Item Timing

An item made on Stage 2 is not the same as an item made on Stage 5.

Early slams affect HP, streaks, and direction. Late items often appear on already successful boards.

If item completion timing exists, use it.

### Augment Stage

The same augment can have different meaning on different stages.

Stage 2 augments often define direction. Stage 3 augments often reinforce or pivot. Stage 4 augments often cap or stabilize.

Never mix augment stages unless intentionally measuring global performance.

### Star-Level Effects

Items, traits, and augments can look different depending on unit star level.

A carry item on a one-star unit may look weak because the unit is not upgraded. A trait breakpoint may look strong because it correlates with upgraded units.

Control for star level when evaluating units and item holders.

### Conditional Availability

Some outcomes require conditions that may not be visible in the database.

Examples:

* Shop luck.
* Carousel priority.
* Component drops.
* Encounter/portal/set mechanic outcomes.
* Opponent fight order.
* Player skill.

When the database lacks a variable, mention the limitation rather than pretending it was controlled.

---

## Interpreting Multiplicative and Additive Scaling in Data

TFT power is often multiplicative. Raw stats should be interpreted through synergy layers.

### Additive Pattern in Data

A board may be adding more of something it already has:

* More raw damage.
* More AP/AD.
* More attack speed.
* More resistances.
* More trait levels of the same type.

This can show diminishing returns.

Data signs of additive overstacking:

* Third damage item underperforms utility/sustain/tempo items.
* Higher trait breakpoint adds little placement lift over a lower breakpoint.
* Extra carry investment does not improve win rate because frontline collapses.
* Combat augment overlaps with existing item stats and underperforms more complementary options.

### Multiplicative Pattern in Data

A board may become strong when different power sources interact:

* Carry damage plus attack speed/mana generation.
* Frontline durability plus carry uptime.
* Shred/sunder plus matching damage type.
* Healing/shielding plus resistances.
* Trait amplification plus correct itemization.
* Secondary carry plus AoE/cleanup utility.
* Economy augment plus fast-level cap.

Data signs of multiplicative scaling:

* Two individually average components become strong together.
* An item is mediocre globally but excellent in a specific trait shell.
* A trait breakpoint improves mostly when a specific unit is upgraded or itemized.
* An augment's lift is much larger in certain board families.
* Win rate improves more than top 4 rate, implying increased cap.

### Practical Analysis Rule

When a statistic changes sharply after adding a unit, item, trait, or augment, ask whether the change came from:

* Raw additive power.
* A missing multiplier being unlocked.
* A proxy for player highroll/economy.
* Survivorship bias.
* A real interaction.

---

## Line Selection Through Data

Line selection is the process of choosing a realistic path from the player's current spot.

A good line is not merely the best average placement comp. It is the line with the best expected outcome given:

* Current items/components.
* Current units/pairs/upgrades.
* Current augments.
* HP.
* Gold.
* Level.
* Stage.
* Lobby contesting.
* Player's ability to transition.
* Meta speed.

### Query Strategy for Line Selection

1. Identify possible lines from current components/items.
2. Identify possible lines from current units/traits.
3. Intersect those with current augments.
4. Filter by patch and rank.
5. Compare expected placement from similar spots.
6. Check contesting and play rate.
7. Check required cap conditions.
8. Return a ranked set of options with reasons.

### Output Format for Line Selection

For each recommended line, include:

* **Why it fits the spot**.
* **What evidence supports it**.
* **What must be hit**.
* **What can go wrong**.
* **When to abandon it**.
* **What alternative line uses similar resources**.

Example conclusion style:

> This line appears to be the best fit because your completed items match its primary carry, its average placement is above the same-item baseline, and it remains playable when one other player contests it. Confidence is moderate because the sample drops sharply when controlling for the exact augment combination.

---

## Economy and Tempo Through Data

Economy decisions should be analyzed as timing decisions, not moral rules.

### Useful Economy Queries

* Average placement by gold at start of each stage.
* Average placement by HP/gold combinations.
* Outcomes for players who leveled on specific rounds.
* Outcomes for players who rolled below 30/20/10 gold at specific stages.
* Stabilization success after rolldowns.
* Placement by streak status entering Stage 3 or Stage 4.
* Damage taken by stage for different strategies.

### Interpreting Economy Data

High gold with low HP can be fake strength. Low gold with high HP can be correct tempo. The correct question is whether the player converted resources into placement equity.

Important patterns:

* If rich players with low HP perform poorly after greeding, the meta may punish slow stabilization.
* If early levelers preserve streak and convert to high average placement, tempo is valuable.
* If rolldowns at a certain stage have poor outcomes, players may be rolling too late, rolling at bad odds, or rolling from too weak a spot.
* If loss streakers perform well only when they stabilize by a specific round, identify that round as a critical timing.

### Do Not Overgeneralize

A database may show that leveling on a round is strong, but that does not mean every player should level on that round. It may mean strong players and strong boards are more likely to level then.

Control for board strength, streak, HP, and economy when possible.

---

## Meta Understanding Through Data

A meta is not just a tier list. It is the interaction of strength, popularity, availability, execution difficulty, and punishment.

### Meta Dimensions

Analyze the meta using several dimensions:

* **Power**: average placement, top 4, win rate.
* **Popularity**: play rate and contesting frequency.
* **Accessibility**: how often the line is reachable from common openers/items.
* **Flexibility**: number of viable item/unit/augment paths.
* **Cap**: ability to win lobbies.
* **Floor**: ability to avoid bot 4.
* **Tempo requirement**: how early the line must stabilize.
* **Risk**: failure rate when contested or missing upgrades.
* **Meta adaptation**: whether performance changes as more players adopt it.

### Identifying Meta Shapes

Possible macro reads:

* **Tempo meta**: Early HP and Stage 3 stability correlate strongly with placement.
* **Greed meta**: Rich players can regularly survive to cap boards.
* **Reroll meta**: Low-cost 3-stars have high success and reasonable hit rates.
* **Fast-level meta**: Level 8/9 boards dominate win rates.
* **Item-flex meta**: Flexible item slams outperform greeding narrow best-in-slot.
* **Augment-driven meta**: Certain augment families dramatically reshape line viability.
* **Contested meta**: Popular lines collapse when shared; scouting and pivots matter more.

### Trend Detection

When detecting trends:

* Use same-patch time buckets.
* Compare early-patch versus recent performance.
* Track play rate and performance together.
* Separate high-rank adoption from broad-rank adoption.
* Check if performance remains after popularity increases.

Interpretation examples:

* Rising play rate + stable placement = likely real meta adoption.
* Rising play rate + falling placement = likely over-contesting or low-skill adoption.
* Low play rate + strong placement + high-rank concentration = possible underplayed tech.
* High win rate + low top 4 rate = high-cap but risky.
* High top 4 rate + low win rate = stable but capped.

---

## Recommended Analysis Workflow

Use this workflow for most TFT database tasks.

### Step 1: Restate the Decision

Convert the user's request into a decision.

Examples:

* “Best comp?” becomes “Which lines have strong outcomes, sufficient sample size, and realistic accessibility in the current patch/rank?”
* “Is this item good?” becomes “Does this item improve outcomes on this holder in this board context compared with alternative items?”
* “Should I reroll?” becomes “Does committing gold at this level/stage produce better expected placement than leveling or delaying?”

### Step 2: Identify Required Filters

Usually include:

* Patch.
* Rank bracket.
* Queue type.
* Stage/round if relevant.
* Unit/trait/item/augment context.
* Level.
* Star level.
* Final placement or not, depending on question.

### Step 3: Start Broad

Run a broad query first to understand the landscape.

Examples:

* Top comp families by play rate and placement.
* Item holders by frequency and performance.
* Augment performance by stage.
* Line outcomes by rank bracket.

### Step 4: Narrow Context

Then filter to the actual decision context.

Examples:

* Same components.
* Same opener.
* Same augment stage.
* Same carry star level.
* Same board family.
* Similar HP/gold/level.

### Step 5: Compare Against Baselines

Do not report raw stats alone.

Compare to:

* Overall baseline.
* Similar decision baseline.
* Alternatives available from the same spot.

### Step 6: Stress-Test the Finding

Ask:

* Does it hold at higher rank?
* Does it hold after removing low samples?
* Does it hold when contested?
* Does it hold in recent data only?
* Does it hold after controlling for star level/items/augments?
* Does it improve top 4, win rate, or both?

### Step 7: State Confidence

Use calibrated language:

* **High confidence**: large sample, clear baseline advantage, controls pass, robust across rank/time.
* **Moderate confidence**: good signal but some missing controls or narrower sample.
* **Low confidence**: low sample, noisy result, likely confounding, or exploratory finding.

### Step 8: Recommend Action

Translate the analysis into a practical TFT decision.

A good recommendation says:

* What to do.
* Why.
* Under what conditions.
* What risks remain.
* What to scout or query next.

---

## Database Query Heuristics

The exact schema may vary. Adapt these concepts to the available tables and columns.

### Likely Useful Tables

A TFT statistics database may include:

* `matches`: match metadata, patch, region, queue, timestamp.
* `players`: one row per player per match, placement, rank, HP, level, gold.
* `boards`: board snapshots by round/stage.
* `units`: units on board or bench, star level, items held.
* `traits`: active traits and breakpoints.
* `items`: completed items/components, holder, creation round.
* `augments`: augment choices, stage, tier, offered alternatives if available.
* `rounds`: combat outcomes, damage dealt/taken, opponent.
* `shops`: shop offerings if available.
* `rolls`: roll events and gold spent if available.
* `lobbies`: lobby-level contesting and composition distribution.
* `stat_caches`: precomputed aggregates for common queries.

### Choose the Right Grain

* Use **match** grain for global patch volume or lobby context.
* Use **player-game** grain for placement outcomes.
* Use **round/board snapshot** grain for stage-specific decisions.
* Use **unit-item-holder** grain for itemization.
* Use **augment-choice** grain for augment analysis.
* Use **lobby** grain for contesting.

Avoid mixing grains accidentally. For example, joining units and items can multiply rows and distort counts unless grouped correctly.

### Count the Right Thing

Be explicit about denominators:

* Number of player-games.
* Number of matches.
* Number of boards.
* Number of augment choices.
* Number of item-holder instances.
* Number of line attempts.

For placement metrics, the denominator is usually player-games, not rows after joins.

### Deduplicate Carefully

When joining board, unit, item, trait, and augment tables, use distinct player-game identifiers when computing placement metrics.

Bad pattern:

* Counting each item row as if it were a separate game.

Good pattern:

* First identify matching player-game IDs, then aggregate placement over those unique IDs.

### Prefer Cohort Queries

For decision analysis, define a cohort of comparable player-games.

Examples:

* Players with a specific opener by 2-1.
* Players with a specific augment at 2-1.
* Players with a specific item holder by 3-2.
* Players who had 6+ copies of a reroll unit by 3-5.
* Players who reached level 8 by 4-2 with at least a certain HP threshold.

Then compare outcomes within that cohort.

---

## Common Analysis Templates

### Template: Is a Comp Strong?

Query:

* Same patch/rank.
* Define comp family by core units/traits, not exact final board only.
* Include attempts if possible, not just completed final boards.
* Compute play rate, average placement, top 4, win rate, bot 4, sample size.
* Stratify by contest count.
* Stratify by item/augment dependency.
* Compare to meta baseline.

Conclusion should include:

* Strength.
* Consistency.
* Ceiling.
* Contest sensitivity.
* Required conditions.
* Whether to force, angle, or avoid.

### Template: Best Item on a Carry

Query:

* Same patch/rank.
* Same holder.
* Same star level if possible.
* Same board family if possible.
* Compare item combinations, not only single items.
* Control for number of completed items.
* Check placement, top 4, win rate, sample size.

Conclusion should include:

* Best general item.
* Best third item after common pairs.
* Flexible alternatives.
* Whether item improves floor or cap.
* Whether sample is large enough.

### Template: Best Augment Choice

Query:

* Same patch/rank.
* Same augment stage and tier.
* Same existing board/item context.
* Include offered alternatives if available.
* Compare average placement, top 4, win rate, play rate.
* Stratify by resulting line.

Conclusion should include:

* Which augment is best from this spot.
* Whether it is generally strong or context-specific.
* Whether it locks direction.
* Whether it is floor, cap, or economy oriented.

### Template: Reroll Viability

Query:

* Identify target unit and cost.
* Track commitment before final 3-star outcome.
* Include failed attempts.
* Analyze outcomes by roll timing, level, copies held, HP, gold, and contest count.
* Compare to alternative non-reroll transitions from similar starts.

Conclusion should include:

* When the reroll is correct.
* Minimum copies/items/augment support needed.
* When to abandon.
* How contested it can tolerate.

### Template: Fast-Level / Capped Board Viability

Query:

* Filter to players reaching high levels by specific rounds.
* Control for HP and gold at level-up timing.
* Identify final board families.
* Compare outcomes by stabilization timing.
* Include failure cases where possible: players who greeded but died or bot 4'd.

Conclusion should include:

* Whether fast-leveling is a meta-wide plan or only a highroll conversion.
* Required HP/economy thresholds.
* What boards stabilize along the way.
* Whether the line plays for first or merely top 4.

### Template: Is Something Underplayed?

Query:

* Low-to-moderate play rate.
* Strong placement relative to baseline.
* Sufficient sample size.
* Performance by rank bracket.
* Performance after play rate increases.
* Item/augment dependency.
* Contest sensitivity.

Conclusion should include:

* Whether it is likely underplayed or just conditional.
* What spot enables it.
* What makes it fail.
* Confidence level.

---

## Interpreting Output for Gameplay

Statistics should be translated into practical advice.

### Good Output

> The data suggests this is a strong line from AD-heavy starts, but not a line to hard force. Its average placement is above baseline when the carry is upgraded by Stage 4, and its top 4 rate remains strong with one contesting player. However, the eighth-rate rises sharply when two or more players contest it. The practical recommendation is to angle it when you have early components and an upgraded opener, but pivot if another player is already holding the same carry and you do not have a copy advantage.

### Bad Output

> This comp has a 3.92 average placement, so it is S-tier.

The good output explains context, causality risk, practical conditions, and failure modes.

---

## Confidence and Language Discipline

Use grounded language.

Prefer:

* “The data suggests...”
* “Within this filtered population...”
* “Compared with similar spots...”
* “This appears to improve top 4 rate more than win rate...”
* “The sample is too small for a firm conclusion, but it is worth exploring...”
* “This may be selection bias because...”

Avoid:

* “Always.”
* “Never.”
* “Best” without context.
* “Broken” without baseline and sample size.
* “Unplayable” when the issue is contesting, execution, or narrow conditions.
* “BiS” without holder, board, and item-combination context.

---

## Handling Missing Data

If the database lacks a useful variable, say what cannot be controlled.

Examples:

* If offered augments are unavailable, augment analysis is based only on taken augments and is selection-biased.
* If item creation timing is unavailable, item stats may mix early slams and late completions.
* If board snapshots are unavailable, final comp stats may suffer from survivorship bias.
* If rank is unavailable, results may combine very different skill environments.
* If contesting data is unavailable, line risk may be understated.

Then propose the best available proxy.

Example:

> The database does not expose offered augments, so I cannot directly compare what players passed on. I will compare taken augments in similar opener/item contexts and treat the result as suggestive rather than causal.

---

## Agent Query Decision Tree

Use this decision tree before analysis:

1. **Is the question patch-dependent?**

   * Usually yes. Filter to current/relevant patch.

2. **Is the question about a player decision at a specific time?**

   * Use stage/round/level context, not final board only.

3. **Is the question about an object's general strength?**

   * Start broad, then stratify by context.

4. **Could selection bias explain the result?**

   * Compare within similar contexts or use offered data.

5. **Could survivorship bias explain the result?**

   * Include attempts, commitments, or earlier board states.

6. **Could contesting change the answer?**

   * Query contest count or proxy via lobby copies.

7. **Does the result improve floor or ceiling?**

   * Compare top 4 rate and win rate separately.

8. **Is sample size sufficient?**

   * If not, lower confidence and suggest more data or broader filters.

9. **Does the finding survive controls?**

   * If yes, present stronger conclusion.
   * If no, explain the narrowed condition.

10. **What should the player do differently?**

* End with an actionable recommendation.

---

## Example Agent Behavior

### User asks: “What are the best comps?”

Agent should not only query final boards by average placement.

Better process:

1. Query comp families by play rate, average placement, top 4, win rate, and sample size for the current patch/rank.
2. Exclude or flag very low-sample boards.
3. Separate common stable lines from rare capped boards.
4. Check contesting sensitivity.
5. Check item/augment dependency.
6. Return categories:

   * Best stable lines.
   * Best high-cap lines.
   * Underplayed lines.
   * Risky/overcontested lines.

### User asks: “Is this augment good?”

Better process:

1. Filter by augment stage and patch.
2. Compare to other augments of same tier/stage.
3. Filter to similar board/item context.
4. Check top 4 and win rate separately.
5. Identify which lines use it successfully.
6. Warn about selection bias if offered data is unavailable.

### User asks: “Should I slam this item?”

Better process:

1. Identify possible holders and future lines.
2. Compare early-item outcomes if timing exists.
3. Compare item flexibility across multiple lines.
4. Check whether the item improves streak/HP preservation, not just final placement.
5. Recommend based on current board strength and component opportunity cost.

### User asks: “Why is this comp bad for me but good in stats?”

Better process:

1. Check if stats are final-board-only.
2. Check required star levels/items/augments.
3. Check average HP/economy at commitment.
4. Check contesting sensitivity.
5. Check rank/execution effects.
6. Explain the gap between theoretical strength and practical accessibility.

---

## Minimum Standard for a Grounded TFT Stat Answer

A good answer should include:

* The exact population analyzed.
* The core metric results.
* The comparison baseline.
* The sample size.
* The main caveat.
* The practical recommendation.
* The confidence level.

Example structure:

> I filtered to Patch X, Diamond+, player-games where the board had [condition] by [round]. Within that population, [option A] averaged [metric] over [sample], compared with [baseline]. The signal is strongest in [condition] and weakens when [condition]. This suggests [interpretation]. Confidence is [level] because [reason]. Practical recommendation: [action].

---

## Final Philosophy

TFT statistics are most useful when they help answer: **What should I do from this spot?**

Do not use data to replace strategic reasoning. Use data to discipline it.

A strong TFT analysis agent should combine:

* Game knowledge.
* Query discipline.
* Statistical caution.
* Contextual baselines.
* Awareness of bias.
* Practical actionability.

The best output is not the most confident-sounding answer. The best output is the answer that most accurately reflects what the data can and cannot prove, then turns that evidence into a better in-game decision.
