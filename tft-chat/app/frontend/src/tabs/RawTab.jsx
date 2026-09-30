import { Disclosure, DisclosureSummary } from "@/components/shared/disclosure";
import { NativeSelect as UiNativeSelect } from "@/components/ui/native-select";
import { Input as UiInput } from "@/components/ui/input";
import { Button as UiButton } from "@/components/ui/button";
import { useEffect, useId, useState } from "react";
import { apiGet, apiPost, Icon, Json, Pill, Spinner } from "../app.jsx";

// Data explorer — Raw API
// --------------------------------------------------------------------------
function PayloadView({ payload }) {
  if (!payload) return null;
  if (payload.truncated) {
    return (
      <div>
        <div className="statusline warn">
          truncated — {payload.total_chars.toLocaleString()} chars total
          {payload.length != null ? `, ${payload.length} entries` : ""}
          {payload.top_level_keys
            ? ` · top-level keys: ${payload.top_level_keys.join(", ")}`
            : ""}
        </div>
        <Json value={payload.preview} />
      </div>
    );
  }
  if ("json" in payload) return <Json value={payload.json} />;
  if ("text" in payload) return <Json value={payload.text} />;
  return <Json value={payload} />;
}

function RawResult({ res }) {
  if (!res) return null;
  if (!res.ok && res.error)
    return (
      <div>
        <div className="statusline bad">error</div>
        {res.request ? (
          <Disclosure open>
            <DisclosureSummary>request</DisclosureSummary>
            <Json value={res.request} />
          </Disclosure>
        ) : null}
        <Json value={res.error} />
      </div>
    );
  return (
    <div>
      <div className={"statusline " + (res.ok ? "ok" : "bad")}>
        HTTP {res.response.status} · {res.response.elapsed_ms} ms ·{" "}
        {res.response.bytes.toLocaleString()} bytes
      </div>
      <h4>request (exactly what hit the network)</h4>
      <Json value={res.request} />
      <h4>response body</h4>
      <PayloadView payload={res.response} />
    </div>
  );
}

function RawCard({ entry }) {
  const formId = useId();
  const [open, setOpen] = useState(false);
  const initial = {};
  entry.params.forEach((p) => (initial[p.name] = p.default ?? ""));
  const [values, setValues] = useState(initial);
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setRes(null);
    try {
      const r = await apiPost("/api/raw/call", { id: entry.id, params: values });
      setRes(r);
    } catch (e) {
      setRes({ ok: false, error: e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="list-item">
      <UiButton variant="ghost" type="button" aria-expanded={open} className="head h-auto w-full justify-start whitespace-normal text-left" onClick={() => setOpen(!open)}>
        <Icon name="chevron" size={13} className={"chev " + (open ? "down" : "")} />
        <Pill kind="cat">{entry.source}</Pill>
        <span className="name">{entry.label}</span>
        {entry.needs_key ? <Pill kind="req">key</Pill> : null}
        <span className="desc" />
      </UiButton>
      {open ? (
        <div className="body">
          <div className="muted small mb">{entry.notes}</div>
          <div className="kv">
            <span className="k">template</span>
            <code>{entry.url_template}</code>
          </div>
          {entry.host_kind ? (
            <div className="kv">
              <span className="k">routing</span>
              <span>{entry.host_kind}</span>
            </div>
          ) : null}
          <h4>parameters</h4>
          {entry.params.length === 0 ? (
            <div className="muted small">none</div>
          ) : (
            <div className="arg-form">{entry.params.map((p) => (
              <div className="form-row" key={p.name}>
                <label htmlFor={`${formId}-${p.name}`}>
                  <code>{p.name}</code>
                  {p.query ? <Pill kind="opt">query</Pill> : null}
                  {p.required ? <Pill kind="req">req</Pill> : null}
                </label>
                {p.enum ? (
                  <UiNativeSelect id={`${formId}-${p.name}`}
                    value={values[p.name] ?? ""}
                    onChange={(e) =>
                      setValues({ ...values, [p.name]: e.target.value })
                    }
                  >
                    <option value="">(unset)</option>
                    {p.enum.map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                  </UiNativeSelect>
                ) : (
                  <UiInput id={`${formId}-${p.name}`}
                    type="text"
                    value={values[p.name] ?? ""}
                    onChange={(e) =>
                      setValues({ ...values, [p.name]: e.target.value })
                    }
                  />
                )}
                {p.help ? <span className="hint">{p.help}</span> : null}
              </div>
            ))}</div>
          )}
          <div className="run-row">
            <UiButton variant="default" className="run" disabled={busy} onClick={run}>
              {busy ? <Spinner /> : <><Icon name="bolt" size={14} /> fetch</>}
            </UiButton>
          </div>
          <RawResult res={res} />
        </div>
      ) : null}
    </div>
  );
}

function RawTab() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    apiGet("/api/raw/catalog").then(setData).catch((e) => setErr(e.message));
  }, []);
  if (err) return <div className="statusline bad">Failed to load: {err}</div>;
  if (!data) return <Spinner label="Loading…" />;
  return (
    <div className="explorer-pane">
      <p className="lead">
        The unprocessed requests the backend's clients make. The response shows
        the <b>exact URL</b> hit and raw JSON — before any model validation.
        (Riot keys redacted; large blobs truncated.)
      </p>
      <div className="section-note">
        <b>Routing:</b> platform hosts are per-shard (
        <code>na1.api.riotgames.com</code>); regional hosts aggregate (
        <code>americas.api.riotgames.com</code>). Match-V1 / Account-V1 are
        regional; League / Summoner / Status are platform.
      </div>
      {data.endpoints.map((e) => (
        <RawCard key={e.id} entry={e} />
      ))}
    </div>
  );
}

export default RawTab;
