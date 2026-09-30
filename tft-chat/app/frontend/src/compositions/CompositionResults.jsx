import React, { useState } from "react";
import { Search, Star } from "lucide-react";
import { Disclosure, DisclosureSummary } from "@/components/shared/disclosure";
import { NativeSelect as UiNativeSelect } from "@/components/ui/native-select";
import { Button as UiButton } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Spinner } from "../app.jsx";
import { EntityIcon, EntityLabel } from "../assets/EntityImages.jsx";
import ParameterLabel from "./ParameterLabel.jsx";
import { percent } from "./utils.js";

// Riot trait styles: 0 inactive, then bronze, silver, gold, and prismatic tiers.
const traitStyles = ["inactive", "bronze", "silver", "gold", "prismatic"];

/** Format unknown data without implying zero or inactivity. */
export function known(value) {
  return value === null || value === undefined ? "Unknown" : String(value);
}
/** Format a possibly missing count with thousands separators. */
function count(value) {
  return value == null ? "Unknown" : value.toLocaleString();
}
/**
 * Render a representative board's structure as chips without merging alternatives.
 *
 * The chips restate one real board (the family's representative): its units, whether
 * each held completed items, and its active trait tiers. They describe that board and
 * do not decide family membership, which comes from distance to the frozen references.
 */
export function PatternRequirements({ pattern }) {
  const requirements = [
    ...pattern.units.map((u, i) => <span key={`unit-${i}`} className="composition-req" data-kind="unit">
      {u.min_copies > 1 && <span className="composition-req-count">{u.min_copies}×</span>}
      <EntityLabel kind="unit" entity={u.unit} size={22} />
      {u.itemized === true && <span className="composition-req-tag">itemized</span>}
      {u.itemized === false && <span className="composition-req-tag">no completed items</span>}
    </span>),
    ...pattern.traits.map((t, i) => <span key={`trait-${i}`} className="composition-req" data-kind="trait">
      <EntityLabel kind="trait" entity={t.trait} size={18} /> ≥ {t.min_tier_current}
    </span>),
  ];
  return requirements.length ? <span className="composition-reqs">{requirements.map((node, i) =>
    <React.Fragment key={node.key}>{i > 0 && <span className="composition-req-join">+</span>}{node}</React.Fragment>,
  )}</span> : <span className="composition-muted">No units or traits on the representative board</span>;
}
/** Render the measured conjunction without combining marginal frequencies. */
export function Pattern({ pattern, children }) {
  return <li className="composition-pattern">
    <span className="composition-pattern-label">{pattern.label}</span>
    <PatternRequirements pattern={pattern} />
    {children}
  </li>;
}
/** Preview one representative structure while retaining the list's original label. */
export function FamilyPreview({ family }) {
  if (!family.preview) return null;
  const { pattern, omitted_requirements: omitted, alternative_patterns: alternatives } = family.preview;
  return <span className="composition-family-preview" title={pattern.label}>
    <PatternRequirements pattern={pattern} />
    {(omitted > 0 || alternatives > 0) && <small>
      {omitted > 0 && `${omitted} more units and traits. `}
      {alternatives > 0 && `${alternatives} other representative structure${alternatives === 1 ? "" : "s"}.`}
    </small>}
  </span>;
}
/** Show a star level as filled glyphs with a spoken count. */
function Stars({ level }) {
  const count = Math.min(level, 5);
  return <span className="composition-stars">
    {Array.from({ length: count }, (_, i) => <Star key={i} aria-hidden="true" />)}
    <span className="sr-only">{level} stars</span>
  </span>;
}
/** Placement badge whose tone separates wins, top-four, and bottom-four finishes. */
function PlacementBadge({ placement }) {
  const tone = placement == null ? "unknown" : placement === 1 ? "win" : placement <= 4 ? "top" : "bottom";
  return <span className="composition-place" data-tone={tone}>Placement {known(placement)}</span>;
}
/** Render one observed occurrence roster; no positions are inferred. */
export function BoardCard({ example, compact = false, onInspect }) {
  const { board, outcome, assignment } = example;
  const items = board.units.reduce((total, u) => total + u.items.length, 0);
  return (
    <article className="composition-board composition-card">
      <header className="composition-board-head">
        <div>
          <h3>
            {example.is_representative ? "Representative board" : "Observed board"}{" "}
            · <code>{board.observation_id}</code>
          </h3>
          <p className="composition-muted composition-caption">
            Level {known(board.level)} · {board.units.length} units · {items} completed items
          </p>
        </div>
        <div className="composition-actions">
          <PlacementBadge placement={outcome?.placement} />
          {onInspect && (
            <UiButton variant="secondary" size="sm" onClick={() => onInspect(example)}>
              Inspect board →
            </UiButton>
          )}
        </div>
      </header>
      <div className="composition-roster">
        {board.units.map((u) => (
          <div key={u.occurrence_index} className="composition-unit">
            <div className="composition-unit-head">
              <EntityIcon kind="unit" entity={u.unit} size={48} />
              <div>
                <strong>{u.unit.name}</strong>
                <Stars level={u.star_level} />
              </div>
            </div>
            {u.items.length ? (
              <ul>
                {u.items.map((i) => (
                  <li key={i.slot}>
                    <EntityIcon kind="item" entity={i.item} size={20} />
                    <span>{i.item.name}</span>
                    <span className="sr-only"> slot {i.slot + 1}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <small>No completed items</small>
            )}
          </div>
        ))}
      </div>
      {board.traits.length > 0 && (
        <div className="composition-traits">
          <span className="composition-muted composition-caption">Traits</span>
          {board.traits.map((t, index) => (
            <span key={`${t.trait.key}-${index}`} className="composition-trait"
              data-style={t.style == null ? "unknown" : traitStyles[Math.min(t.style, 4)]}>
              <EntityLabel kind="trait" entity={t.trait} size={16} />
              <strong>{t.num_units ?? "?"}</strong>
              <span className="sr-only">{` · units ${known(t.num_units)} · tier ${known(t.tier_current)} · style ${known(t.style)}`}</span>
            </span>
          ))}
        </div>
      )}
      {!compact && assignment && (
        <section className="composition-evidence">
          <div className="composition-actions">
            <h4>Assignment evidence</h4>
            <Badge variant="outline">{assignment.status}</Badge>
          </div>
          <p>{assignment.explanation}</p>
          {assignment.candidates.length > 0 && (
            <table className="composition-table">
              <thead>
                <tr><th scope="col">Candidate family</th><th scope="col">Score</th><th scope="col">Evidence</th></tr>
              </thead>
              <tbody>
                {assignment.candidates.map((c, i) => (
                  <tr key={`${c.family_id}-${i}`}>
                    <td>{c.family_id}</td>
                    <td>
                      <span className="composition-number">{c.score.value.toFixed(3)}</span>{" "}
                      <span className="composition-muted composition-caption">
                        {c.score.name} · {c.score.kind}; {c.score.higher_is_better ? "higher" : "lower"} is better
                      </span>
                    </td>
                    <td>{c.evidence.join("; ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}
      <p className="composition-muted composition-caption">
        Observed roster; positioning is unavailable.
      </p>
    </article>
  );
}
/** Pick an example from compact roster thumbnails instead of a bare ID list. */
function ExampleThumbnails({ examples, selectedId, onSelect }) {
  return (
    <div role="group" aria-label="Examples" className="composition-thumbs">
      {examples.map((e) => (
        <button
          key={e.board.observation_id}
          type="button"
          className="composition-thumb"
          aria-pressed={e.board.observation_id === selectedId}
          onClick={() => onSelect(e.board.observation_id)}
        >
          <span className="composition-thumb-top">
            <code>{e.board.observation_id}</code>
            <PlacementBadge placement={e.outcome?.placement} />
          </span>
          <span className="composition-thumb-roster" aria-hidden="true">
            {e.board.units.slice(0, 10).map((u) => (
              <EntityIcon key={u.occurrence_index} kind="unit" entity={u.unit} size={22} />
            ))}
          </span>
          <span className="composition-muted composition-caption">
            {e.is_representative ? "Representative · " : ""}Level {known(e.board.level)}
          </span>
        </button>
      ))}
    </div>
  );
}
/** Explore a selected family with explicit outcome denominators and observed examples. */
export function FamilyDetail({ detail, onInspect }) {
  const [exampleId, setExampleId] = useState(null);
  const examples = detail.examples;
  const example =
    examples.find((e) => e.board.observation_id === exampleId) || examples[0];
  const outcomes = detail.profile?.outcomes;
  const available = outcomes?.state === "available";
  const stats = [
    ["Avg. placement", available ? outcomes.avg_placement.toFixed(2) : "Unavailable", "lower is better"],
    ["Top 4", available ? percent(outcomes.top4_rate) : "Unavailable",
      available ? `${count(outcomes.placement_counts.slice(0, 4).reduce((a, b) => a + b, 0))} boards` : ""],
    ["Win rate", available ? percent(outcomes.win_rate) : "Unavailable",
      available ? `${count(outcomes.placement_counts[0])} firsts` : ""],
    ["Play share", percent(detail.profile?.play_share),
      `${count(detail.profile?.assigned_boards)} / ${count(detail.profile?.eligible_population_boards)} boards`],
  ];
  return (
    <section className="composition-family-detail">
      <header className="composition-detail-head">
        <h2>{detail.family.label}</h2>
        <p className="composition-muted">{detail.family.description}</p>
        {detail.warnings.map((w) => (
          <p key={w.code} className="composition-callout">{w.message}</p>
        ))}
      </header>
      <div className="composition-overview">
        <div>
          <dl className="composition-stats">
            {stats.map(([label, value, sub]) => (
              <div key={label} className="composition-card">
                <dt>{label}</dt>
                <dd>{value}</dd>
                {sub && <dd className="composition-muted composition-caption">{sub}</dd>}
              </div>
            ))}
          </dl>
          <p className="composition-muted composition-caption">
            Outcomes: {outcomes?.state ?? "unavailable"}
            {available && ` · ${count(outcomes.observed_boards)} known placements`} ·{" "}
            {count(detail.profile?.assigned_boards)} assigned boards
          </p>
        </div>
        {outcomes?.placement_counts ? (
          <PlacementDistribution counts={outcomes.placement_counts} />
        ) : (
          <div className="composition-card composition-empty">
            <p className="composition-muted">No placement distribution for these outcomes.</p>
          </div>
        )}
      </div>
      <section className="composition-card composition-section">
        <div className="composition-card-head">
          <h3>Representative structure</h3>
          <span className="composition-muted composition-caption">
            {count(detail.profile?.assigned_boards)} assigned / {count(detail.profile?.eligible_population_boards)} eligible boards
          </span>
        </div>
        <ul className="composition-patterns">
          {detail.family.defining_patterns.map((p) => (
            <Pattern key={p.pattern_id} pattern={p} />
          ))}
        </ul>
        <Disclosure open>
          <DisclosureSummary>Boards matching the representative structure</DisclosureSummary>
          <p className="composition-muted composition-caption">
            How many assigned boards also contain every unit, item state, and trait tier of the representative board. Membership itself comes from distance to the family's reference boards.
          </p>
          <ul className="composition-patterns">
            {detail.profile?.joint_patterns.map((p) => (
              <Pattern key={p.pattern.pattern_id} pattern={p.pattern}>
                <span className="composition-support">
                  <span className="composition-meter" aria-hidden="true">
                    <span style={{ width: `${p.eligible_boards ? (100 * p.matching_boards) / p.eligible_boards : 0}%` }} />
                  </span>
                  <span className="composition-number">{count(p.matching_boards)} / {count(p.eligible_boards)}</span>
                </span>
              </Pattern>
            ))}
          </ul>
        </Disclosure>
        <Disclosure>
          <DisclosureSummary>
            Variations ({detail.family.variations.length})
          </DisclosureSummary>
          {detail.family.variations.map((v) => (
            <section key={v.variation_id} className="composition-variation">
              <h4>{v.label}</h4>
              <p className="composition-muted">{v.description}</p>
              <ul className="composition-patterns">
                {v.patterns.map((p) => (
                  <Pattern key={p.pattern_id} pattern={p} />
                ))}
              </ul>
            </section>
          ))}
          {!detail.family.variations.length && (
            <p className="composition-muted">No variations in this family.</p>
          )}
        </Disclosure>
      </section>
      <section className="composition-card composition-section">
        <div className="composition-card-head">
          <h3>
            <ParameterLabel help="Choose an observed board illustrating this family. Representative examples are marked; positions are not available.">
              Examples
            </ParameterLabel>
          </h3>
          {onInspect && example && (
            <UiButton variant="secondary" size="sm" onClick={() => onInspect(example)}>
              Inspect board →
            </UiButton>
          )}
        </div>
        {example ? (
          <>
            {examples.length > 1 && (
              <ExampleThumbnails examples={examples} selectedId={example.board.observation_id} onSelect={setExampleId} />
            )}
            <BoardCard example={example} compact={!!onInspect} />
          </>
        ) : (
          <p className="composition-muted">
            No observed examples are available.
          </p>
        )}
      </section>
    </section>
  );
}

/** Show all eight observed placement counts without inferring missing outcomes. */
export function PlacementDistribution({ counts }) {
  const maximum = Math.max(1, ...counts);
  return (
    <figure className="composition-card composition-placement">
      <figcaption>
        <span>
          Placement distribution{" "}
          <span className="composition-muted composition-caption">· observed boards</span>
        </span>
        <span className="composition-legend" aria-hidden="true">
          <span data-tone="top">Top 4</span>
          <span data-tone="bottom">Bottom 4</span>
        </span>
      </figcaption>
      <div
        className="composition-distribution"
        role="img"
        aria-label={counts
          .map((count, index) => `Placement ${index + 1}: ${count} boards`)
          .join("; ")}
      >
        {counts.map((count, index) => (
          <div key={index} className="composition-bin" aria-hidden="true">
            <span>{count.toLocaleString()}</span>
            <div className="composition-bar-space">
              <div
                className="composition-bar"
                data-tone={index < 4 ? "top" : "bottom"}
                style={{ height: `${(100 * count) / maximum}%` }}
              />
            </div>
            <span>#{index + 1}</span>
          </div>
        ))}
      </div>
    </figure>
  );
}

/** Present family navigation beside details, with a native selector on small screens. */
export function FamilyBrowser({
  families,
  detail,
  label,
  busy,
  onSelect,
  onInspect,
}) {
  const [query, setQuery] = useState("");
  if (!families)
    return (
      <div role="status">
        <Spinner label="Loading families…" />
      </div>
    );
  if (!families.length)
    return (
      <p className="composition-muted">
        No families were discovered for this population.
      </p>
    );
  const maxShare = Math.max(0, ...families.map((f) => f.play_share ?? 0));
  const needle = query.trim().toLowerCase();
  // Match labels and previewed requirement names so a unit or trait finds its families.
  const visible = needle ? families.filter((family) => [
    family.label,
    ...(family.preview?.pattern.units.map((u) => u.unit.name) ?? []),
    ...(family.preview?.pattern.traits.map((t) => t.trait.name) ?? []),
  ].some((text) => text.toLowerCase().includes(needle))) : families;
  return (
    <div className="composition-layout">
      <aside className="composition-card composition-list-panel composition-family-navigation">
        <div className="composition-list-head">
          <h3>
            Families <span className="composition-muted">({families.length})</span>
          </h3>
          <label className="composition-search">
            <Search aria-hidden="true" />
            <input type="search" aria-label="Filter families" placeholder="Filter by family, unit or trait"
              value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
        </div>
        <div className="composition-mobile-family [&_[data-slot=native-select-wrapper]]:w-full">
          <UiNativeSelect
            aria-label={label}
            value={detail?.family.family_id || ""}
            disabled={busy}
            onChange={(event) => onSelect(event.target.value)}
          >
            <option value="" disabled>
              Choose a family
            </option>
            {families.map((family) => (
              <option key={family.family_id} value={family.family_id}>
                {family.label} · {family.assigned_boards.toLocaleString()} boards
              </option>
            ))}
          </UiNativeSelect>
        </div>
        <nav aria-label={label} className="composition-list composition-family-list">
          {visible.map((family) => (
            <button
              key={family.family_id}
              type="button"
              className="composition-list-row composition-family-row"
              aria-pressed={detail?.family.family_id === family.family_id}
              disabled={busy}
              onClick={() => onSelect(family.family_id)}
            >
              <span className="composition-family-row-top">
                <strong>{family.label}</strong>
                {family.variation_count > 0 && (
                  <span className="composition-muted composition-caption">
                    {family.variation_count} variation{family.variation_count === 1 ? "" : "s"}
                  </span>
                )}
              </span>
              <FamilyPreview family={family} />
              <span className="composition-share">
                <span className="composition-meter" aria-hidden="true">
                  <span style={{ width: `${maxShare && family.play_share != null ? (100 * family.play_share) / maxShare : 0}%` }} />
                </span>
                <span className="composition-number composition-caption">
                  {family.play_share == null ? "Share unavailable" : `${percent(family.play_share)} play share`}
                  {" · "}{family.assigned_boards.toLocaleString()} boards
                </span>
              </span>
            </button>
          ))}
          {!visible.length && <p className="composition-muted composition-caption">No families match “{query}”.</p>}
        </nav>
      </aside>
      <div className="composition-detail-column">
        {detail ? (
          <FamilyDetail
            key={detail.family.family_id}
            detail={detail}
            onInspect={onInspect}
          />
        ) : (
          <div className="composition-card composition-empty">
            <p className="composition-muted">
              Choose a family to explore its representative structure and observed boards.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
