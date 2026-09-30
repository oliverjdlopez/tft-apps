# ChatTFT eval brainstorm — orchestrator prompt

## Your role

You coordinate a research effort. You are not a coding agent and you do not write eval cases yourself: you dispatch and brief subagents, keep the process on track, check what they deliver, and document everything. The goal is a large pool of high-quality **candidate** eval cases for ChatTFT, a Teamfight Tactics assistant, covering what real players ask about **items, units, compositions, and traits**.

ChatTFT in brief: it answers TFT questions from current-set game knowledge (units, traits, items, mechanics) and aggregate statistics from recent high-elo ranked games (end-of-game boards: placement, level, units with star levels and items, active traits). The eval suite will measure whether its answers are correct, grounded, and genuinely useful to a player. This phase is brainstorming only — nothing gets formatted for or wired into an eval harness (Langfuse or otherwise).

## Ground rules (for you and every subagent)

1. **Write scope.** Create `eval-brainstormings/` at the repo root. All writes go inside it, and only as `.md` or `.json` files. Do not create, modify, or delete anything else in the repository, including `docs/**`, `evals/**`, and agent configuration. This task overrides the documentation-sync rule in `AGENTS.md`: do not update docs.
2. **No code.** No scripts, notebooks, or package installs. Fetching pages with web tools (or a plain command-line fetch where your environment allows it) is fine. Save only curated `.md`/`.json` output, never raw dumps.
3. **Implementation-agnostic deliverables.** Subagents do not need this repository. Do not point them at app code, tool definitions, or the existing eval datasets — this effort is deliberately independent of all three. No deliverable may name ChatTFT's tools, functions, tables, or APIs. Data needs are written in plain language:
   - Good: "Reference data should include the most common 3-item builds on this unit and their average placement, filtered to 2-star copies on patch 18.3b in Emerald+ ranked games, with sample sizes."
   - Bad: "The agent should call `rank_items` with holder=…"
4. **No fabrication.** Every quote, link, and number must come from a source that was actually read. When unsure, say so.
5. **Models and harness.** Every subagent (the 4 scouts and all 40 lane researchers) runs **gpt-6-astra with medium reasoning effort**, has web search, and may write into its assigned directory. If you cannot provide all three, stop and tell the user before dispatching anything. Never substitute silently.
6. **Current game state.** As of 2026-09-28 the live set is **Set 18, "Enchanted Wilds"** (live since late August 2026; set mechanic: Wisps). The live patch is **18.3b**: 18.3 shipped Sept 23 and its b-patch Sept 24. Verify this against Riot's patch notes when you start, and use whatever patch is current throughout.

## Phases

### Phase 0 — Set up (you)

- Create the directory skeleton below.
- Start `PROCESS.md`: a dated, append-only log of every dispatch (including the model settings used), decision, retry, and deviation.
- Verify the set and patch. Fill the placeholders in Appendices A–C and save them as `_shared/brief.md`, `_shared/scout-brief.md`, and `_shared/lane-brief.md`. These are the exact text subagents receive.
- For your own grounding you may skim `README.md` and `docs/content_providers/set18-context.md`. Do not do the research yourself.

### Phase 1 — Scouting (4 scouts, in parallel)

Dispatch one scout per subject. Each receives Appendix A plus Appendix B, verbatim and with placeholders filled.

| Subject | Lanes | Ranked alternates |
| --- | --- | --- |
| units | 16 | 4 |
| compositions | 16 | 4 |
| items | 4 | 2 |
| traits | 4 | 2 |

Scouts write to `<subject>/_scoping/`.

### Phase 2 — Finalize lanes (you)

- Read the four scouting reports. Pick exactly 16 / 16 / 4 / 4 lanes. You may merge, split, rescope, or promote alternates.
- Drop any lane that does not have at least 3 verbatim real-player seed questions — it is probably invented.
- Prefer lanes defined by a player need (a decision or a confusion) over lanes defined by a single entity or a single stats view.
- Some overlap is fine. Near-duplicate lanes are not, so give them distinct angles.
- **Coverage sanity check.** Confirm that the needs seen most often in real threads are covered somewhere. For example:
  - best items, and item-vs-item comparisons, for a carry
  - "is X good / fake?"
  - how a unit's or a trait's mechanic actually works
  - what to play given an early item, emblem, or artifact
  - how to play a specific comp: levels, rolls, early units, item priority, positioning
  - pivots and contested lobbies
  - reroll vs fast 8/9
  - capping the endgame
  - slam vs hold
  - what to do with artifacts, radiants, and support items
  - which trait breakpoints are worth hitting
  - emblem value
- Merge the scouts' access notes into `_shared/research-playbook.md`. Include:
  - which sources were readable
  - which access routes and query patterns worked
  - links or IDs for the best threads, such as every Set 18 Daily Discussion thread and "What's Working? What's Not?" megathread
  - pitfalls
- Log the final lanes and your rationale in `PROCESS.md`, including dropped and merged lanes. Create the `<subject>/lane-NN-<slug>/` directories.

### Phase 3 — Lane research (40 researchers)

- Paste the following in full into each researcher's prompt:
  - Appendix A and Appendix C
  - its finalized lane entry from `lanes.json`
  - the one-line titles of all 40 lanes, so it can stay in its own lane
  - the research playbook
- Dispatch in waves if concurrency is capped. About ten at a time is polite to the sources everyone shares.
- Researchers write their own files. Do not route deliverable content through your context. Ask each researcher to reply with only a short completion note.

### Phase 4 — Check and synthesize (you)

- **Completeness.** For every lane, confirm that `report.md` and `triplets.json` exist, that the JSON is well-formed, and that the required fields are present. A read-only check such as `python -m json.tool` is fine.
- **Spot checks.** Check at least 2 cases per lane against the quality bar in Appendix A. Look for:
  - tool names
  - unverifiable quotes or links
  - generic, "AI-sounding" questions
  - entities that are not in Set 18
  - invented numbers
- **Revisions.** If a lane is materially deficient, send one targeted revision request (or re-dispatch with your feedback) and log it. Do not rewrite subagent content yourself.
- **`README.md`.** Write it with:
  - what was done
  - case counts per subject and lane
  - how to navigate the directory
  - cross-lane themes
  - probable duplicates to merge later (flag them; do not merge)
  - coverage gaps
  - recurring data needs that standard end-of-game match data cannot satisfy
  - open questions for the human

## Directory layout

```
eval-brainstormings/
  README.md                 # final synthesis (Phase 4)
  PROCESS.md                # your log
  _shared/
    brief.md                # Appendix A as sent
    scout-brief.md          # Appendix B as sent
    lane-brief.md           # Appendix C as sent
    research-playbook.md    # merged access notes (Phase 2)
  units/  compositions/  items/  traits/
    _scoping/
      report.md
      lanes.json
    lane-01-<slug>/
      report.md
      triplets.json
    ...
```

---

## Appendix A — Shared brief (every subagent, verbatim)

### Why this matters

You are helping build the eval suite for ChatTFT, an assistant that answers Teamfight Tactics questions using current-set game knowledge and statistics from recent high-elo ranked games. These cases decide what the assistant gets optimized for. If they are questions real players don't actually ask, we will build an assistant that sounds smart and helps nobody.

### Game state and scope

- **Game state.** Set 18, "Enchanted Wilds". Live patch {PATCH}; research date {DATE}.
- **Set 18 only.** Set 18 is the only valid game state. Older-set material may suggest question *shapes*, but every case must be rebuilt in Set 18 terms and verified against current sources.
- **In scope:** standard ranked games only.
- **Out of scope:** Double Up, Hyper Roll, and other modes; bugs, client performance, cosmetics, LP/MMR, and esports.
- **Context only:** augments, Wisps, encounters, and econ may appear as context in a case, but never as its subject.

### Subjects

- **Items.** An item is the subject. This covers craftable items, components, artifacts, radiants, emblems, support items, and set-mechanic items. Typical questions: what it does, who should hold it, slam vs hold, priority, comparisons, interactions.
- **Units.** A champion is the subject. Typical questions: strength, itemization, star-up value, role and positioning, how the ability works, which comps it fits, counters.
- **Compositions.** The board or game plan is the subject. Typical questions: what to play, and how to play it (levels, rolls, early units, transitions); openers; pivots; contested lobbies; capping; counters; the current meta.
- **Traits.** A trait or breakpoint is the subject. Typical questions: how it works, which breakpoints are worth it, vertical vs splash, emblems, trait-specific choices, interactions.

When a question spans subjects, it belongs to the one whose noun is central to it.

### What makes a great case

1. **A real player would type it.** It reads like a comment in r/CompetitiveTFT's Daily Discussion thread or a post on r/TeamfightTactics.
   - Real players are terse. They bring context from their own game and ask about decisions.
   - They use slang naturally and sparingly: BIS, slam, 2*/3*, fast 8, reroll, spat, cap, "is X fake". Do not caricature it.
   - Most real questions are one line, some include game context, and few are essays. Mirror that mix, and mix newer and high-elo voices.
2. **It matters to a decision or to understanding.** What should I build, itemize, play, level, or pivot to? Why did I lose? How does this actually work?
3. **It discriminates.** A confident, generic LLM answer should fail or be clearly worse than a good one. A good answer needs evidence: current-set facts, current-patch statistics, or precise mechanics.
4. **It has a defensible good answer.** Either the answer can be verified, or experts agree on it. Where opinion is contested, the grading notes say what counts as acceptable.
5. **It is representative.** Weight toward the needs players raise most often. Include the long tail only when it is genuinely asked.

**Calibration only.** These are real Set 18 posts. Do not reuse them verbatim.

- "Which one is better for ashe. Shojin vs Guinso?"
- "When / How to Gromp? Today I natty'd a 2* gromp on 2-1 and realized I have absolutely no idea what to do with this unit."
- "typically do you link Taric w/ your tank or carry DPS?"
- "Why is Nidalee with EoN, rageblade and HoJ AP form?"
- "i struggle with how to prio items for strongest board … should I be prio 3 items carry/tank even at the cost of making a weaker item?"

**Reject** questions like these:

- "Analyze the synergistic implications of combining Spellweaver and Invoker on team performance." No player talks like this.
- "Provide a comprehensive ranking of all 3-cost units with statistical significance." This is a report request, not a question.
- "Which 3-cost has the highest base armor?" Trivia, with no decision attached.
- "How can I optimize my itemization strategy?" Too generic to grade.
- Anything that names an entity outside Set 18, or that mentions ChatTFT's internals.

Players often ask about a screenshot. Turn it into text by describing the board the way a player would type it, e.g. "2* Kog with Guinsoo + Nashor, 4 Invoker, 3-5, 40g".

### Research: external sources are the job, not a nice-to-have

Your questions must come from what real players actually say, and your answers must rest on current, citable facts. Cases that can't show real players care about the need will be discarded.

**Where players talk** (primary for questions):

- **r/CompetitiveTFT**
  - The daily "Daily Discussion Thread" is mostly questions.
  - The per-patch "[18.x] What's Working? What's Not?" megathreads collect meta opinions.
  - Discussion and Guide posts are also useful.
  - Read the replies too: they show what the community considers a good answer, and where it disagrees.
- **r/TeamfightTactics** is larger and more casual, and has more lower-elo voices.
- **Requests for tools and features** reveal unmet needs. Look for "is there a site that…" questions and "I built a tool…" posts.
- **X/Twitter and YouTube** yield little for automated research (see the access notes below). Use them opportunistically.

**What tools expose** (primary for "what players want from a tool"). Treat their views, filters, and metrics as evidence of demand:

- **MetaTFT:** comps; units; items (craftable, artifact, radiant, emblem, support); traits; augments; the explorer; team builder; early comps; pro comps; trends; set-mechanic tables.
- **tactics.tools:** per-unit pages with star-level and item-count distributions; items, item pairs, and item trios with raw and adjusted placement; synergies; strong-against and weak-against lists; the explorer; perfect synergies; trends.
- **LittleBuddyBot:** datamined odds and trait tables.
- **TFT Academy:** comp guides covering playstyle, early units, item priority, augments, positioning, stage-by-stage plans, and alternative builds.
- **TFT Flow:** line selection from the components, anvils, and items you hold.
- **Others:** lolchess.gg, tftactics.gg, Blitz, Mobalytics, BunnyMuffins.

**Ground truth** (for sample answers):

- Riot's patch notes (teamfighttactics.leagueoflegends.com)
- readable stat pages (tactics.tools)
- datamined tables (LittleBuddyBot)
- consensus across guides

**Access notes.** These were verified on 2026-09-28 from one environment; yours may differ. Check the research playbook for updates.

- **Reddit.** reddit.com and old.reddit.com refused automated fetches.
  - Try your web search tool first, e.g. `site:reddit.com/r/CompetitiveTFT <unit> items`.
  - For full threads, the Arctic Shift Reddit archive returned JSON reliably:
    - List threads and their IDs: `https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=CompetitiveTFT&title=Daily%20Discussion&after=2026-08-25&limit=100`
    - Get every comment in a thread, with replies: `https://arctic-shift.photon-reddit.com/api/comments/tree?link_id=<post id>&limit=500`
    - Keyword search in comments: `https://arctic-shift.photon-reddit.com/api/comments/search?subreddit=TeamfightTactics&body=<keyword>&after=2026-08-25&limit=100`
    - For posts, search with `title=`. The full-text `query=` parameter timed out.
  - Be polite: send one request at a time, pause between calls, and back off on HTTP 429 or on "Timeout. Maybe slow down".
- **MetaTFT** is client-rendered, so plain fetches return an empty shell. List its views from `https://www.metatft.com/sitemap.xml`, and use search snippets and its guides. Do not sink many calls into it.
- **Readable HTML:** tactics.tools (e.g. `/units/da_18_ashe`), TFT Academy, TFT Flow, tftactics.gg, lolchess.gg, and LittleBuddyBot all served readable pages.
- **Mobalytics** returned a bot check.
- **X/Twitter.** Search requires a login, and the Nitter mirrors are down. Only individual post URLs surfaced by web search are readable. Limit yourself to a few attempts.

**Search craft.**

- Combine Set 18 entity names and nicknames with question phrasing: "how do you play", "is X good", "X or Y", "BIS", "when to", "why did", "what do I do with".
- Filter to posts after 2026-08-25 to get current-set voices.
- Mine older sets only for recurring question shapes.
- Record every query and source in your trace, including dead ends.
- Stop when new sources stop surfacing new needs.

### Triplet specification

Each case has three parts:

1. **Question** — written in the player's voice.
2. **Sample answer** — what an excellent coach with good data would reply.
3. **Reference requirements** — the data and references needed to answer it properly.

Each case also carries light metadata for curation; the schema is in your role brief.

**Sample answers**

- **Structure.** Lead with the direct answer. Then give the why (data and mechanics), then conditions and caveats (patch, rank, sample size, contested units), then what to do next.
- **Length.** Usually 80–250 words. Go longer only when the question asks for a plan.
- **Missing context.** If key context is missing, state your assumption or ask one sharp clarifying question — and still give value.
- **Numbers.** Every number comes from a named public source and is labeled, e.g. "(tactics.tools, Diamond+, 18.3b, retrieved {DATE})". Otherwise use a bracketed placeholder such as `[avg placement ≈ ?]`. Never invent a statistic.
- **Stats literacy.** Keep these biases in mind:
  - Item and emblem numbers are confounded by who holds them and by strong comps.
  - 3-star and 5-cost numbers carry survivorship and highroll bias.
  - A low play rate with a great placement usually means niche or highroll, not "best".
  - End-of-game boards say nothing about the early game.

**Reference requirements**

Write in plain language, one entry per piece of evidence. Each entry names:

- the entity
- the population: patch, rank band, and region if relevant
- the conditions: star level, item count, trait tier, units on the same board
- the metric and its baseline
- why it is needed

Tag each entry with one evidence type:

- **`game-reference`:** costs, traits and breakpoints, abilities, item effects and recipes, odds tables, rules.
- **`match-statistics`:** aggregates over end-of-game ranked boards.
- **`in-game-timeline`:** stage-by-stage boards, roll and level timing, streaks, augment picks, positioning, per-unit damage. Standard end-of-game match data usually lacks these; say so.
- **`patch-history`:** what changed, and when.
- **`expert-consensus`:** guides, and pro or coach opinion.
- **`player-context`:** what the asker must supply, such as their board, items, stage, gold, HP, and contested units.

Do not limit yourself to what you think any particular tool can answer today. Label the needs precisely instead.

### Integrity and scope

- Quote sources verbatim and link every one.
- Keep usernames out of files.
- Never fabricate.
- Write only inside your assigned directory, and only `.md` and `.json` files.
- No code or scripts.
- Do not read the repository outside `eval-brainstormings/`, and do not mention the ChatTFT codebase.
- Do not format anything for an eval platform.

---

## Appendix B — Scout brief (fill `{SUBJECT}`, `{N}`, `{A}`)

You are the **{SUBJECT} scout**. Your job:

- Map the space of real player needs about {SUBJECT} in Set 18.
- Propose **{N} lanes** plus **{A} ranked alternates**.

Each lane goes to one parallel researcher, who will write about 12 eval triplets for it. Size each lane to support that many distinct cases while staying narrow enough to research deeply. You write no triplets yourself.

1. **Demand map.**
   - Harvest at least 40 real player questions or statements about {SUBJECT}, mostly from Set 18. Draw on the daily threads, the "What's Working?" megathreads, and both subreddits.
   - Record each one with a verbatim quote, a link, and a date.
   - Cluster them into needs, and note which needs recur most often.
2. **Tool survey.** For each major tool, list its views, filters, and metrics related to {SUBJECT}, and the player question each one answers.
3. **Lanes.** Partition the needs into {N} lanes that make the best use of {N} researchers.
   - Useful axes:
     - player intent: decide, itemize, evaluate, compare, diagnose, learn a mechanic, plan, adapt, counter
     - game phase
     - entity class: carries, tanks, or utility; cost tier; reroll units vs fast-8/9 units; units or traits with unusual mechanics
     - player level
     - evidence type
   - Define lanes by need. A single-entity lane is justified only if that entity generates genuinely distinct questions.
   - Every lane, including alternates, needs at least 3 verbatim real-player seed questions with links. If you cannot find 3, it is not a lane.
4. **Coverage map.** Show how the lanes cover the needs, where they overlap (including with other subjects), and what you deliberately left out, and why.
5. **Access notes.** Record what worked and what failed: sites, endpoints, query patterns, and the IDs or links of the best threads (e.g. every Set 18 Daily Discussion thread). These notes feed the shared playbook.

**Outputs** go in `eval-brainstormings/{SUBJECT}/_scoping/`.

`report.md` has these sections, in order:

1. A summary of no more than 150 words
2. Method and research trace: queries, sources, dead ends
3. Demand map, with quotes
4. Tool survey
5. Lanes, with rationale
6. Coverage map
7. Access notes
8. Open questions

`lanes.json`:

```json
{
  "subject": "...",
  "budget": {N},
  "lanes": [{
    "rank": 1,
    "slug": "kebab-case",
    "title": "...",
    "player_need": "one sentence",
    "scope": "what's in",
    "out_of_scope": "what's not, and which neighbor owns it",
    "seed_questions": [{"quote": "verbatim", "url": "...", "date": "YYYY-MM-DD"}],
    "starter_sources": ["url — why it's useful"],
    "tool_views": ["site: view — the player question it answers"],
    "likely_evidence_types": ["match-statistics", "game-reference"],
    "overlap_notes": "..."
  }],
  "alternates": ["same shape as lanes"]
}
```

Reply to the orchestrator with only: your lane titles, your counts, and any problems.

---

## Appendix C — Lane researcher brief (fill `{LANE_ID}`, `{TITLE}`, `{SUBJECT}`, `{LANE_DIR}`)

You are the researcher for **lane {LANE_ID}: {TITLE}** ({SUBJECT}). Your lane entry follows this brief. Stay inside it; the list of all 40 lanes shows what your neighbors cover. For more context you may read your scout's full demand map in `eval-brainstormings/{SUBJECT}/_scoping/report.md`.

Deliver **8–15 triplets, aiming for about 12**. A few excellent cases beat many mediocre ones, so never pad.

1. **Harvest.**
   - Collect 20+ real player questions or statements for your lane, each with a verbatim quote, a link, and a date.
   - Note what repliers answered, and where they disagreed.
   - Use Set 18 sources first. Use older sets only for question shapes.
   - If your lane is niche and you fall short of 20, say so.
2. **Tool check.** Note how the major tools serve this lane: views, filters, metrics. This tells you what players expect to be answerable.
3. **Cluster and select.**
   - Group the harvest into needs.
   - Pick cases that cover the most frequent and most important needs.
   - Vary the cases along these axes:
     - persona: new, climbing, high-elo
     - phrasing: terse and slangy vs detailed
     - answer type: lookup, comparison, conditional, diagnosis, explanation, plan
     - time sensitivity: evergreen shape, set-specific, patch-specific
4. **Write.** Follow the triplet specification in the shared brief.
5. **Verify.**
   - Check every entity, mechanic, and number against a current external source.
   - Re-open every quote and link.
   - Run the self-check below and cut any case that fails it.

**Self-check (every case)**

- Would a player post this without it looking out of place?
- Does it inform a decision or resolve a confusion?
- Is it valid for Set 18 and the current patch?
- Would a generic answer fail?
- Are the reference requirements plain-language and specific, with no tool names?
- Is every number sourced or a placeholder?
- Is the provenance real?
- Is the case distinct from your other cases?

**Outputs** go in `eval-brainstormings/{SUBJECT}/{LANE_DIR}/`.

`report.md` has these sections, in order:

1. A summary of no more than 150 words
2. The lane scope, as you interpreted it
3. Method and research trace: queries, sources, dead ends
4. The question bank, with quotes and links
5. Clustering and selection rationale
6. An index table of your triplets: id and question
7. Conclusions: what players in this lane really want, and which data needs recur or are hard to satisfy
8. Gaps and limitations
9. Suggestions for other lanes

`triplets.json`:

```json
{
  "subject": "...",
  "lane_id": "...",
  "lane_title": "...",
  "set": "18",
  "patch_at_research": "...",
  "researched_on": "YYYY-MM-DD",
  "triplets": [{
    "id": "units-07-03",
    "question": "player-voiced text",
    "player_context": "optional: who is asking, and the game situation implied",
    "intent": "itemize | compare | evaluate | decide | plan | adapt | diagnose | explain | counter",
    "sample_answer": "...",
    "reference_requirements": [
      {"need": "plain language: entity, population, conditions, metric, baseline",
       "evidence_type": "match-statistics",
       "why": "..."}
    ],
    "grading_notes": {
      "must_include": ["points any good answer must make"],
      "red_flags": ["wrong, outdated, or misleading claims to penalize"]
    },
    "provenance": [
      {"kind": "player-question | player-discussion | tool-view",
       "url": "...", "quote": "verbatim, for player sources", "date": "YYYY-MM-DD"}
    ],
    "answer_sources": [{"url": "...", "supports": "which claim in the sample answer", "retrieved": "YYYY-MM-DD"}],
    "time_sensitivity": "evergreen | set-specific | patch-specific",
    "evergreen_pattern": "optional: the set-agnostic shape of the question"
  }]
}
```

Rules for the fields:

- **`id`** takes the form `<subject>-<lane NN>-<case nn>`.
- **`provenance`** must include at least one entry per case showing that real players care about this need. That entry is either a player post or comment, or a tool view with the inferred need explained.
- **`provenance` and `answer_sources` are different things.** `provenance` shows why players ask the question. `answer_sources` shows what backs the sample answer.

Reply to the orchestrator with only: your triplet count, 3 notable findings, and any problems.
