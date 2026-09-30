import { Disclosure, DisclosureSummary } from "@/components/shared/disclosure";
import { Card as UiCard } from "@/components/ui/card";
import { Input as UiInput } from "@/components/ui/input";
import { Button as UiButton } from "@/components/ui/button";
import { useState } from "react";
import {
  apiPost,
  AutoTextarea,
  Collapsible,
  Icon,
  Json,
  Spinner,
} from "../app.jsx";

/** Render one JSON diagnostic panel only when its value is available. */
function DebugPanel({ title, subtitle, value, defaultOpen = false }) {
  if (value == null) return null;
  return (
    <Collapsible title={title} subtitle={subtitle} defaultOpen={defaultOpen}>
      <Json value={value} />
    </Collapsible>
  );
}

/** Provide a local UI for branching a stored OpenAI Responses API response. */
function ResponseTuningTab() {
  const [responseId, setResponseId] = useState("");
  const [message, setMessage] = useState("");
  const [model, setModel] = useState("");
  const [instructions, setInstructions] = useState("");
  const [temperature, setTemperature] = useState("");
  const [maxOutputTokens, setMaxOutputTokens] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setResult(null);
    try {
      const response = await apiPost("/api/response-tuning/continue", {
        response_id: responseId,
        message,
        model: model || null,
        instructions: instructions || null,
        temperature: temperature === "" ? null : Number(temperature),
        max_output_tokens: maxOutputTokens === "" ? null : Number(maxOutputTokens),
      });
      setResult(response);
    } catch (error) {
      setResult({
        ok: false,
        latency_ms: 0,
        error: { stage: "request", type: "BrowserError", message: error.message },
      });
    } finally {
      setBusy(false);
    }
  }

  const canRun = responseId.trim() && message.trim() && !busy;
  return (
    <div className="explorer-pane response-tuning-view">
      <h3>Response continuation tuner</h3>
      <p className="lead">
        Fork a stored OpenAI response with a new user turn and inspect the
        exact state, request, output, tools, usage, and latency.
      </p>
      <div className="response-tuning-layout">
        <UiCard as="section" className="card response-tuning-controls block gap-0 p-6 shadow-xs">
          <p className="lead">
            The parent is retrieved for inspection, but the run itself uses
            <code> previous_response_id </code> so OpenAI retains the original
            conversation state. Your API key never leaves the server.
          </p>
          <label className="response-tuning-field">
            <span>Previous response ID</span>
            <UiInput
              type="text"
              placeholder="resp_..."
              value={responseId}
              onChange={(event) => setResponseId(event.target.value)}
            />
          </label>
          <label className="response-tuning-field">
            <span>Next user message</span>
            <AutoTextarea
              minRows={7}
              placeholder="Append a candidate follow-up prompt…"
              value={message}
              onChange={(event) => setMessage(event.target.value)}
            />
          </label>
          <Disclosure className="response-tuning-options">
            <DisclosureSummary>Optional runtime overrides</DisclosureSummary>
            <p className="muted small">
              Leaving model empty reuses the parent model. Supplying instructions
              replaces—not extends—the parent response instructions.
            </p>
            <label className="response-tuning-field">
              <span>Model</span>
              <UiInput
                type="text"
                placeholder="Reuse parent model"
                value={model}
                onChange={(event) => setModel(event.target.value)}
              />
            </label>
            <label className="response-tuning-field">
              <span>Instructions</span>
              <AutoTextarea
                minRows={4}
                placeholder="Optional replacement developer/system instructions"
                value={instructions}
                onChange={(event) => setInstructions(event.target.value)}
              />
            </label>
            <div className="response-tuning-number-row">
              <label className="response-tuning-field">
                <span>Temperature</span>
                <UiInput
                  type="number"
                  min="0"
                  max="2"
                  step="0.1"
                  placeholder="API default"
                  value={temperature}
                  onChange={(event) => setTemperature(event.target.value)}
                />
              </label>
              <label className="response-tuning-field">
                <span>Max output tokens</span>
                <UiInput
                  type="number"
                  min="1"
                  placeholder="API default"
                  value={maxOutputTokens}
                  onChange={(event) => setMaxOutputTokens(event.target.value)}
                />
              </label>
            </div>
          </Disclosure>
          <UiButton variant="default" className="run" disabled={!canRun} onClick={run}>
            {busy ? <Spinner label="Running…" /> : <><Icon name="play" size={14} /> Run continuation</>}
          </UiButton>
        </UiCard>
        <section className="response-tuning-results">
          {!result ? (
            <UiCard as="div" className="card empty-state block gap-0 p-6 shadow-xs">
              <Icon name="bolt" size={26} />
              <strong>Ready for a prompt branch</strong>
              <p>Run a continuation to reveal the response and debugging data.</p>
            </UiCard>
          ) : (
            <>
              <div className={"card response-tuning-summary " + (result.ok ? "ok" : "bad")}>
                <div>
                  <span className="response-tuning-status">{result.ok ? "Completed" : "Failed"}</span>
                  <span className="muted small">{result.latency_ms} ms</span>
                </div>
                {result.response_id ? <code>{result.response_id}</code> : null}
              </div>
              {result.assistant_output ? (
                <UiCard as="div" className="card response-tuning-output block gap-0 p-6 shadow-xs">
                  <h3>Assistant output</h3>
                  <pre>{result.assistant_output}</pre>
                </UiCard>
              ) : null}
              {result.error ? (
                <UiCard as="div" className="card response-tuning-error block gap-0 p-6 shadow-xs">
                  <h3>Error</h3>
                  <Json value={result.error} />
                </UiCard>
              ) : null}
              {result.prior_input_items_error ? (
                <div className="statusline warn">
                  Parent input-item inspection unavailable: {result.prior_input_items_error}
                </div>
              ) : null}
              <DebugPanel title="Exact request" subtitle="sent to Responses API" value={result.request} defaultOpen />
              <DebugPanel title="Output items / tool calls" value={result.output_items} defaultOpen />
              <DebugPanel title="Token usage" value={result.usage} defaultOpen />
              <DebugPanel title="Prior response metadata" value={result.prior_response} />
              <DebugPanel title="Prior input items" value={result.prior_input_items} />
              <DebugPanel title="Full returned response" value={result.response} />
            </>
          )}
        </section>
      </div>
    </div>
  );
}

export default ResponseTuningTab;
