/** New-experiment form beside a live summary of what Start will capture and run. */
import React from "react";
import { Play } from "lucide-react";
import { Input as UiInput } from "@/components/ui/input";
import { NativeSelect as UiNativeSelect } from "@/components/ui/native-select";
import { Checkbox as UiCheckbox } from "@/components/ui/checkbox";
import { Button as UiButton } from "@/components/ui/button";
import ParameterLabel from "./ParameterLabel.jsx";
import { parameterHelp } from "./parameterHelp.js";
import { algorithmLabel } from "./utils.js";

const presetSizes = [2000, 20000];

/** Offer direct parameter fields derived from each adapter's Pydantic JSON schema. */
function Parameters({ algorithmId, schema, values, onChange }) {
  return Object.entries(schema?.properties || {}).map(([key, spec]) => (
    <label key={key}>
      <ParameterLabel
        help={
          parameterHelp[algorithmId]?.[key] ||
          spec.description ||
          "No explanation is available for this parameter in this algorithm version."
        }
      >
        {spec.title || key}
      </ParameterLabel>
      {spec.type === "boolean" ? (
        <UiCheckbox
          aria-label={key}
          checked={Boolean(values[key] ?? spec.default)}
          onCheckedChange={(checked) =>
            onChange({ ...values, [key]: checked === true })
          }
        />
      ) : (
        <UiInput
          aria-label={key}
          aria-description={
            parameterHelp[algorithmId]?.[key] || spec.description
          }
          type={["number", "integer"].includes(spec.type) ? "number" : "text"}
          min={spec.minimum ?? spec.exclusiveMinimum}
          max={spec.maximum}
          step={spec.type === "integer" ? 1 : "any"}
          value={values[key] ?? spec.default ?? ""}
          onChange={(event) =>
            onChange({
              ...values,
              [key]: ["number", "integer"].includes(spec.type)
                ? Number(event.target.value)
                : event.target.value,
            })
          }
        />
      )}
    </label>
  ));
}

/**
 * Edit a draft experiment and show its frozen source, sampling plan, and Start action.
 *
 * Draft state lives in Experiments so it survives navigation to results and back.
 *
 * Args:
 *   form, setForm: The draft request and its setter.
 *   algorithms: Adapters offered by the backend, with parameter schemas.
 *   sourceSummary: Live source readiness for a fresh capture.
 *   savedSource: Frozen counts when the draft duplicates a saved snapshot.
 *   sampleLimit, sampleCount: Eligible ceiling and effective discovery size.
 *   busy, error: Request state that gates submission.
 *   onSubmit: Form submit handler that confirms and enqueues the run.
 */
export default function ExperimentSetup({
  form, setForm, algorithms, sourceSummary, sampleLimit, sampleCount, busy, error, onSubmit,
}) {
  const algorithm = algorithms.find((a) => a.algorithm_id === "hdbscan");
  const frozen = !!form.snapshot_id;
  const sizeLabel = "Sample size";
  // Presets never exceed the eligible population; "All" always equals it.
  const presets = sampleLimit
    ? [...presetSizes.filter((size) => size < sampleLimit), sampleLimit]
    : [];

  return (
    <form onSubmit={onSubmit} className="composition-setup">
      <div className="composition-page-head">
        <h2 tabIndex={-1}>New experiment</h2>
        <p className="composition-muted">Freeze a source snapshot, configure HDBSCAN, and start a reproducible run.</p>
      </div>
      <div className="composition-setup-grid">
        <div className="composition-setup-fields">
          <fieldset className="composition-card composition-fieldset">
            <legend>Source &amp; sampling</legend>
            <div className="composition-form composition-form-3 [&_[data-slot=native-select-wrapper]]:w-full">
              <label>
                <ParameterLabel help="Use the configured eligible boards: the checked-in population in offline development mode, or the active ready analysis scope otherwise. The illustrative fixture is also available. Saved snapshots retain their original source until you refresh it.">
                  Source
                </ParameterLabel>
                <UiNativeSelect
                  aria-label="Source"
                  value={form.source_kind}
                  disabled={frozen}
                  onChange={(e) => setForm({ ...form, source_kind: e.target.value })}
                >
                  <option value="active">Configured eligible boards</option>
                  <option value="fixture">Immutable fixture</option>
                </UiNativeSelect>
              </label>
              <label>
                <ParameterLabel help="Controls reproducible sampling and algorithm randomness. To change sampling for a saved snapshot, refresh the source before starting.">
                  Seed
                </ParameterLabel>
                <UiInput
                  aria-label="Seed"
                  type="number"
                  min="0"
                  max="2147483647"
                  disabled={frozen}
                  value={form.seed}
                  onChange={(e) => setForm({ ...form, seed: Number(e.target.value) })}
                />
              </label>
              <label>
                <ParameterLabel help="Number of boards used to discover families, up to the full eligible source population. Runs sampling more than 20,000 boards require confirmation because they can take substantial memory and time. Refresh the source to change a saved sample.">
                  {sizeLabel}
                </ParameterLabel>
                <UiInput
                  aria-label={sizeLabel}
                  type="number"
                  min="1"
                  max={sampleLimit ?? undefined}
                  disabled={frozen}
                  value={form.sample_size}
                  onChange={(e) => setForm({ ...form, sample_size: Number(e.target.value) })}
                />
              </label>
            </div>
            <div className="composition-setup-row">
              {!frozen && presets.length > 0 && (
                <div role="group" aria-label="Sample presets" className="composition-chips">
                  <span className="composition-muted composition-caption">Presets</span>
                  {presets.map((size) => (
                    <button
                      key={size}
                      type="button"
                      className="composition-chip"
                      aria-pressed={form.sample_size === size}
                      onClick={() => setForm({ ...form, sample_size: size })}
                    >
                      {size === sampleLimit ? `All ${size.toLocaleString()}` : size.toLocaleString()}
                    </button>
                  ))}
                </div>
              )}
              <label className="composition-inline-check">
                <UiCheckbox
                  aria-label="Classify full eligible population"
                  checked={form.full_population}
                  onCheckedChange={(checked) => setForm({ ...form, full_population: checked === true })}
                />
                <ParameterLabel help="Also classify every eligible source board using the discovered families. Discovery still uses the sample; full classification can take longer and requires a snapshot containing the full population.">
                  Classify full eligible population
                </ParameterLabel>
              </label>
            </div>
          </fieldset>

          <fieldset className="composition-card composition-fieldset">
            <legend>HDBSCAN</legend>
            {algorithm && Object.keys(algorithm.parameter_schema?.properties || {}).length > 0 && (
              <>
                <h3 className="composition-subhead">{algorithmLabel(form.algorithm_id)} parameters</h3>
                <div className="composition-form composition-form-4">
                  <Parameters
                    algorithmId={form.algorithm_id}
                    schema={algorithm.parameter_schema}
                    values={form.parameters}
                    onChange={(parameters) => setForm({ ...form, parameters })}
                  />
                </div>
              </>
            )}
          </fieldset>

        </div>

        <aside className="composition-summary" aria-label="Run summary">
          <div className="composition-summary-head">
            <h3>Run summary</h3>
            {frozen ? (
              <span className="composition-status" data-tone="active">Saved snapshot</span>
            ) : sourceSummary && (
              <span className="composition-status" data-tone={sourceSummary.ready ? "success" : "danger"}>
                {sourceSummary.ready ? "Source ready" : "Source unavailable"}
              </span>
            )}
          </div>
          <dl className="composition-summary-list">
            {!frozen && sourceSummary && (
              <>
                <dt>Patch</dt><dd>{sourceSummary.patch ?? "Unknown"}</dd>
                <dt>Set · Queue</dt><dd>{sourceSummary.set_number ?? "Unknown"} · {sourceSummary.queue_id ?? "Unknown"}</dd>
              </>
            )}
            <dt>Eligible boards</dt><dd>{sampleLimit?.toLocaleString() ?? "Unknown"}</dd>
            <dt>Sample</dt><dd><strong>{sampleCount ? sampleCount.toLocaleString() : "—"}</strong></dd>
            <dt>Full classification</dt><dd>{form.full_population ? "On" : "Off"}</dd>
          </dl>
          <div className="composition-summary-plan">
            <strong>{algorithmLabel(form.algorithm_id)}</strong>
            <span>
              {`One fit over ${(sampleCount ?? 0).toLocaleString()} sampled boards${form.full_population ? ", then classify every eligible board" : ""}.`}
            </span>
          </div>
          {sampleCount > 20000 && (
            <p className="composition-callout">
              Runs over 20,000 boards can use substantial memory and take a long time. You will be asked to confirm.
            </p>
          )}
          {sourceSummary?.warning && !frozen && <p className="composition-callout">{sourceSummary.warning}</p>}
          <p className="composition-muted composition-caption">
            {frozen
              ? `Saved source ${form.snapshot_id.slice(0, 12)} · original sampling retained`
              : `Capture configured eligible boards at Start; sample up to ${sampleLimit?.toLocaleString() ?? "the full population of"} eligible boards.`}
          </p>
          <UiButton
            type="submit"
            size="lg"
            className="w-full"
            disabled={
              busy ||
              !sampleCount ||
              !algorithms.length ||
              !!error ||
              (!frozen && !sourceSummary?.ready)
            }
          >
            <Play aria-hidden="true" /> Start experiment
          </UiButton>
          <UiButton
            variant="ghost"
            type="button"
            className="w-full"
            onClick={() => setForm({ ...form, snapshot_id: null })}
          >
            Refresh source on next start
          </UiButton>
        </aside>
      </div>
    </form>
  );
}
