/** Shared local entity imagery, currently consumed by the composition workspace. */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { createAssetLoader, imageKey, uniqueImages } from "./utils.js";
import "./images.css";

const Images = createContext({ results: new Map(), reportBroken: () => {} });

/** Load a view's images without blocking its data or applying stale responses. */
export function EntityAssetProvider({ context, entities, children }) {
  const { patch, set_number: setNumber } = context;
  const load = useMemo(() => createAssetLoader(patch, setNumber), [patch, setNumber]);
  const signature = JSON.stringify(uniqueImages(entities));
  const [state, setState] = useState(null);
  const [brokenSources, setBrokenSources] = useState(new Set());
  const reportBroken = useCallback((src) => {
    setBrokenSources((previous) => previous.has(src) ? previous : new Set([...previous, src]));
  }, []);
  useEffect(() => {
    let alive = true;
    load(JSON.parse(signature)).then((results) => {
      if (alive) setState({ load, signature, results });
    });
    return () => { alive = false; };
  }, [load, signature]);
  const current = state?.load === load && state?.signature === signature;
  const results = state?.load === load ? state.results : new Map();
  const unavailable = [...results.values()].filter((value) => value.status === "missing" || brokenSources.has(value.src)).length;
  const patches = [...new Set([...results.values()].filter((value) => value.fallback)
    .map((value) => value.asset_patch))];
  return <Images.Provider value={{ results, reportBroken }}>
    {children}
    {current && (unavailable > 0 || patches.length > 0) && <p className="entity-asset-status" role="status">
      {patches.length > 0 && `Images use same-set patch ${patches.join(", ")}. `}
      {unavailable > 0 && `${unavailable} entity image${unavailable === 1 ? " is" : "s are"} unavailable; names remain visible.`}
    </p>}
  </Images.Provider>;
}

/** Render a decorative image beside a readable entity label with a stable footprint. */
export function EntityIcon({ kind, entity, size = 24 }) {
  const { results: images, reportBroken } = useContext(Images);
  const key = imageKey({ kind, name_or_id: entity.key, role: kind === "unit" ? "portrait" : "icon" });
  const src = images.get(key)?.src;
  const [failedSource, setFailedSource] = useState(null);
  if (!src || src === failedSource) return <span
    className="entity-icon entity-icon-placeholder" aria-hidden="true"
    style={{ width: size, height: size }} />;
  return <img className={`entity-icon entity-icon-${kind}`} src={src} alt=""
    width={size} height={size} loading="lazy" decoding="async"
    onError={() => { setFailedSource(src); reportBroken(src); }} />;
}

/** Keep entity names readable and searchable even when local images are absent. */
export function EntityLabel({ kind, entity, size = 24 }) {
  return <span className="entity-label">
    <EntityIcon kind={kind} entity={entity} size={size} />
    <span>{entity.name}</span>
  </span>;
}
