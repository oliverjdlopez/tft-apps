/** Standalone, opt-in composition workspace with parsed display models. */
import React, { useEffect, useState } from "react";
import { api, EmptyState, Spinner, ViewHeader } from "../app.jsx";
import { compositionRequest } from "./api.js";
import {
  CompositionListResponseSchema,
  CompositionDetailResponseSchema,
} from "./models.js";
import "./compositions.css";
import Experiments from "./Experiments.jsx";
import { EntityAssetProvider } from "../assets/EntityImages.jsx";
import { compositionImageRequests } from "./utils.js";
import { ParameterHelpProvider } from "./ParameterLabel.jsx";

import { FamilyBrowser } from "./CompositionResults.jsx";
export { BoardCard, FamilyDetail, FamilyPreview } from "./CompositionResults.jsx";

/** Gate fixture and experiment UI on the same explicit backend configuration. */
export default function Compositions() {
  const [state, setState] = useState("loading"),
    [error, setError] = useState(""),
    [list, setList] = useState(null),
    [detail, setDetail] = useState(null);
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const config = await api("/api/config");
        if (!config.composition_workbench)
          throw new Error(
            "Composition workbench is disabled. Enable [chat] composition_workbench in the application settings.",
          );
        const value = await compositionRequest(
          "/fixtures",
          CompositionListResponseSchema,
        );
        if (alive) {
          setList(value);
          setState("ready");
        }
      } catch (e) {
        if (alive) {
          setError(e.message);
          setState("error");
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, []);
  /** Load one fixture definition and its separately identified examples. */
  async function selectFamily(id) {
    try {
      setState("loading");
      setDetail(
        await compositionRequest(
          `/fixtures/${encodeURIComponent(id)}`,
          CompositionDetailResponseSchema,
        ),
      );
      setState("ready");
    } catch (e) {
      setError(e.message);
      setState("error");
    }
  }
  return (
    <ParameterHelpProvider>
      <div className="view compositions-view" data-ready={list ? "true" : undefined}>
        {!list && (
          <ViewHeader
            icon="data"
            title="Compositions"
            subtitle="Discover structures and compare reproducible experiments."
          />
        )}
        {state === "error" && (
          <div role="alert">
            <EmptyState icon="alert" title="Compositions unavailable">
              {error}
            </EmptyState>
          </div>
        )}
        {state === "loading" && (
          <div role="status">
            <Spinner label="Loading compositions…" />
          </div>
        )}
        {list && (
          <Experiments
            fixtures={
              <EntityAssetProvider context={list.context}
                entities={compositionImageRequests({ families: list.families, detail })}>
              <section aria-label="Display fixtures">
                <div className="composition-page-head">
                  <h2 tabIndex={-1}>Display fixtures</h2>
                  <p className="composition-muted">
                    Illustrative families · {list.context.population_kind.replaceAll("_", " ")}{" "}
                    · {list.context.snapshot_revision}
                  </p>
                </div>
                {list.warnings.map((w) => (
                  <p key={w.code} className="composition-callout">{w.message}</p>
                ))}
                <FamilyBrowser
                  families={list.families}
                  detail={detail}
                  label="Fixture families"
                  busy={state === "loading"}
                  onSelect={selectFamily}
                />
              </section>
              </EntityAssetProvider>
            }
          />
        )}
      </div>
    </ParameterHelpProvider>
  );
}
