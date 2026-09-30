/** Collect entity imagery from loaded composition data without changing identities. */

// ============================================================================
// Composition image presentation
//
// Collect once at the view boundary so every occurrence retains its holder and
// slot while the shared loader deduplicates the image transfers underneath.
// ============================================================================

/** Gather images for family previews, definitions, examples, and board inspection. */
export function compositionImageRequests({ families = [], detail = null, board = null }) {
  const entities = [];
  /** Retain the API's identity key instead of inventing frontend name aliases. */
  function add(kind, entity) {
    entities.push({ kind, name_or_id: entity.key, role: kind === "unit" ? "portrait" : "icon" });
  }
  /** Preserve requirement identity independently of pattern labels or prose. */
  function pattern(value) {
    value.units.forEach((u) => add("unit", u.unit));
    value.traits.forEach((t) => add("trait", t.trait));
  }
  /** Include every observed occurrence; deduplication happens only in asset lookup. */
  function example(value) {
    value.board.units.forEach((u) => {
      add("unit", u.unit);
      u.items.forEach((i) => add("item", i.item));
    });
    value.board.traits.forEach((t) => add("trait", t.trait));
  }
  families.forEach((family) => { if (family.preview) pattern(family.preview.pattern); });
  if (detail) {
    detail.family.defining_patterns.forEach(pattern);
    detail.family.variations.forEach((variation) => variation.patterns.forEach(pattern));
    detail.profile?.joint_patterns.forEach((support) => pattern(support.pattern));
    detail.examples.forEach(example);
  }
  if (board) example(board);
  return entities;
}

// ============================================================================
// Composition workspace formatting
//
// Shared by the run rail, setup form, run header, and result panels so a run's
// algorithm, rates, and placements read identically wherever they appear.
// ============================================================================

const algorithmNames = {
  hdbscan: "HDBSCAN",
};

/** Label the sole supported algorithm consistently across workspace views. */
export function algorithmLabel(id) {
  return algorithmNames[id] ?? id;
}

/** Format a rate as a percentage while keeping missing values distinct from zero. */
export function percent(value) {
  return value == null ? "Unavailable" : `${(value * 100).toFixed(1)}%`;
}

/** Name a statistics population. */
export function populationLabel(kind) {
  if (kind === "discovery_sample")
    return "Discovery sample";
  return "Full population";
}

/** Map a run status to the tone used by rail dots and header badges. */
export function statusTone(status) {
  if (status === "completed") return "success";
  if (status === "queued" || status === "running") return "active";
  if (status === "failed" || status === "interrupted") return "danger";
  return "muted";
}

/** Confirm costly discovery runs before either a new submission or saved rerun. */
export async function confirmSampleRun(sampleSize, confirm) {
  return (
    sampleSize <= 20000 ||
    confirm(
      `Start a high-sample run with ${sampleSize.toLocaleString()} boards? Runs over 20,000 boards can use substantial memory and take a long time. Continue?`,
    )
  );
}
