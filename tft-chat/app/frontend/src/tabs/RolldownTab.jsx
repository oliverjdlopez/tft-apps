import { Card as UiCard } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button as UiButton } from "@/components/ui/button";
import { NativeSelect as UiNativeSelect } from "@/components/ui/native-select";
import { Input as UiInput } from "@/components/ui/input";
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { apiGet, apiPost, EmptyState, Icon, Spinner, ViewHeader } from "../app.jsx";

// Rolldown lab — prepare target-free Monte Carlo runs, then analyze them.
//
const RD_PALETTE = ["#4f46e5", "#15803d", "#926500", "#be185d", "#0369a1", "#7e22ce"];
const RD_COST_TONE = ["#626262", "#15803d", "#0369a1", "#7e22ce", "#926500"];

function rdPct(value, digits) {
  return `${(Number(value || 0) * 100).toFixed(digits == null ? 1 : digits)}%`;
}

function rdRunLabel(parameters) {
  const budget = parameters.budget_type === "gold"
    ? `${parameters.budget}g`
    : `${parameters.budget} rolls`;
  return `L${parameters.level} · ${budget} · ${Math.round(parameters.pool_pressure * 100)}% contested`;
}

function rdParseSweepValues(raw) {
  return String(raw || "")
    .split(/[,\s]+/)
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value));
}

function rdDefaultSweepValues(dimension, budgetType) {
  if (dimension === "level") return "5, 6, 7, 8, 9, 10";
  if (dimension === "pressure") return "0, 20, 40, 60";
  return budgetType === "rolls"
    ? "5, 10, 15, 20, 25, 30"
    : "10, 20, 30, 40, 50, 60";
}

function rdDimensionLabel(dimension) {
  return {
    budget: "Budget",
    level: "Player level",
    pressure: "Pool pressure",
  }[dimension] || dimension;
}

function rdCoordinateLabel(dimension, value, budgetType) {
  if (dimension === "pressure") return `${value}%`;
  if (dimension === "budget") return budgetType === "rolls" ? `${value} rolls` : `${value}g`;
  return `L${value}`;
}

function rdHeatColor(probability, alpha) {
  const value = Math.max(0, Math.min(1, Number(probability || 0)));
  const hue = 230 - value * 86;
  const lightness = 24 + value * 35;
  return `hsla(${hue}, 72%, ${lightness}%, ${alpha == null ? 1 : alpha})`;
}

function rdProbability(result) {
  return Number(result?.probability_hit ?? result?.probability_find_all_targets ?? 0);
}

function RdProbabilityChart({ series, focusId, xMode, showBand }) {
  const [hover, setHover] = useState(null);
  const W = 900, H = 330, L = 54, R = 882, T = 18, B = 284;
  const available = series.filter((item) => item.result?.hit_all_by_shop);
  if (!available.length) {
    return <EmptyState icon="data" title="Choose a target">The selected runs will update here automatically.</EmptyState>;
  }
  const domain = Math.max(1, ...available.map((item) => {
    const result = item.result;
    return xMode === "gold"
      ? (result.spend_by_shop || [])[result.max_shops] || 1
      : result.max_shops;
  }));
  let yMax = 0;
  available.forEach((item) => {
    const bounds = item.result.hit_all_by_shop_confidence_95 || [];
    const maximumUpperBound = Math.max(
      rdProbability(item.result),
      ...bounds.map((interval) => Number(interval.upper || 0)),
    );
    yMax = Math.max(yMax, maximumUpperBound);
  });
  yMax = [0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 1].find((value) => value >= yMax * 1.08) || 1;
  const px = (value) => L + (value / domain) * (R - L);
  const py = (value) => T + (1 - Math.min(1, value / yMax)) * (B - T);
  const points = (item) => {
    const result = item.result;
    return result.hit_all_by_shop.map((probability, shop) => ({
      shop,
      probability,
      lower: result.hit_all_by_shop_confidence_95?.[shop]?.lower ?? probability,
      upper: result.hit_all_by_shop_confidence_95?.[shop]?.upper ?? probability,
      x: px(xMode === "gold" ? (result.spend_by_shop || [])[shop] || 0 : shop),
      y: py(probability),
    }));
  };
  const focused = available.find((item) => item.id === focusId) || available[0];
  const grid = [0, 0.25, 0.5, 0.75, 1].map((fraction) => ({
    value: fraction * yMax,
    y: py(fraction * yMax),
  }));
  const tickCount = Math.min(6, Math.max(1, Math.floor(domain)));
  const ticks = Array.from({ length: tickCount + 1 }, (_, index) => {
    const value = (domain / tickCount) * index;
    return { value, x: px(value) };
  });
  const hoverX = hover == null ? null : px(hover);
  const hoverItems = hoverX == null ? [] : available.map((item) => {
    let nearest = points(item)[0];
    points(item).forEach((point) => {
      if (Math.abs(point.x - hoverX) < Math.abs(nearest.x - hoverX)) nearest = point;
    });
    return { ...nearest, color: item.color, label: item.label };
  });
  return (
    <div className="rd-chart-frame" style={{ position: "relative" }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ display: "block", width: "100%", height: "auto", overflow: "visible" }}>
        <text x="15" y="151" transform="rotate(-90 15 151)" textAnchor="middle" fill="var(--text-muted)" fontSize="13" fontWeight="700">Chance to satisfy target</text>
        <text x="468" y="328" textAnchor="middle" fill="var(--text-muted)" fontSize="13" fontWeight="700">{xMode === "gold" ? "Gold spent  →" : "Shops rolled  →"}</text>
        {grid.map((line, index) => (
          <g key={index}>
            <line x1={L} y1={line.y} x2={R} y2={line.y} stroke="var(--border)" />
            <text x="45" y={line.y + 4} textAnchor="end" fill="var(--text-muted)" fontSize="11.5">{Math.round(line.value * 100)}%</text>
          </g>
        ))}
        {ticks.map((tick, index) => (
          <g key={index}>
            <line x1={tick.x} y1={T} x2={tick.x} y2={B} stroke="var(--border)" />
            <text x={tick.x} y="307" textAnchor="middle" fill="var(--text-muted)" fontSize="11.5">{xMode === "gold" ? `${Math.round(tick.value)}g` : Math.round(tick.value)}</text>
          </g>
        ))}
        {showBand && focused ? (() => {
          const curve = points(focused);
          const upper = curve.map((point) => `${point.x.toFixed(1)} ${py(point.upper).toFixed(1)}`);
          const lower = curve.slice().reverse().map((point) => `${point.x.toFixed(1)} ${py(point.lower).toFixed(1)}`);
          return <path d={`M${upper.join(" L")} L${lower.join(" L")} Z`} fill={`${focused.color}22`} />;
        })() : null}
        {available.map((item) => {
          const path = points(item).map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ");
          return <path key={item.id} d={path} fill="none" stroke={item.color} strokeWidth={item.id === focusId ? 2.8 : 1.8} strokeLinecap="round" strokeLinejoin="round" />;
        })}
        {hoverX == null ? null : (
          <g>
            <line x1={hoverX} y1={T} x2={hoverX} y2={B} stroke="var(--input)" strokeDasharray="3 3" />
            {hoverItems.map((item, index) => <circle key={index} cx={item.x} cy={item.y} r="4" fill="var(--card)" stroke={item.color} strokeWidth="2.5" />)}
          </g>
        )}
        <rect x={L} y={T} width={R - L} height={B - T} fill="transparent" style={{ cursor: "crosshair" }}
          onMouseMove={(event) => {
            const rect = event.currentTarget.ownerSVGElement.getBoundingClientRect();
            const position = ((event.clientX - rect.left) / rect.width) * W;
            setHover(Math.max(0, Math.min(domain, ((position - L) / (R - L)) * domain)));
          }}
          onMouseLeave={() => setHover(null)} />
      </svg>
      {hoverX == null ? null : (
        <div style={{ position: "absolute", top: 8, left: `${(hoverX / W) * 100}%`, transform: hoverX > 620 ? "translateX(-104%)" : "translateX(12px)", minWidth: 195, padding: "10px 11px", pointerEvents: "none", border: "1px solid var(--border)", borderRadius: 11, background: "var(--popover)", boxShadow: "var(--shadow)" }}>
          {hoverItems.map((item) => (
            <div key={item.label} style={{ display: "grid", gridTemplateColumns: "9px minmax(0,1fr) auto", gap: 7, alignItems: "center", marginBottom: 5 }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: item.color }} />
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--text-dim)", fontSize: 11 }}>{item.label}</span>
              <strong style={{ fontSize: 11.5, fontVariantNumeric: "tabular-nums" }}>{rdPct(item.probability)}</strong>
              <small style={{ gridColumn: "2 / 4", color: "var(--muted-foreground)", fontSize: 9.5 }}>95% CI {rdPct(item.lower)}–{rdPct(item.upper)}</small>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function RdOutcomeHistogram({ result, metric }) {
  const trials = result?.trials || [];
  if (!trials.length) {
    return <EmptyState icon="data" title="No sampled outcomes">This target query did not return trial samples.</EmptyState>;
  }
  const misses = trials.filter((trial) => (
    trial.hit == null ? !trial.hit_shop : !trial.hit
  )).length;
  const hits = trials.length - misses;
  const plottedTrials = metric === "shops"
    ? trials.filter((trial) => trial.hit_shop > 0)
    : trials;
  const values = plottedTrials.map((trial) => metric === "copies"
    ? trial.copies.reduce((total, value) => total + value, 0)
    : metric === "gold"
      ? trial.gold_spent
      : trial.hit_shop);
  const minimum = values.length ? Math.min(...values) : 0;
  const maximum = values.length ? Math.max(...values) : 0;
  const binWidth = Math.max(1, Math.ceil((maximum - minimum + 1) / 16));
  const binCount = values.length ? Math.floor((maximum - minimum) / binWidth) + 1 : 0;
  const bins = Array.from({ length: binCount }, (_, index) => ({
    start: minimum + index * binWidth,
    end: Math.min(maximum, minimum + ((index + 1) * binWidth) - 1),
    count: 0,
  }));
  values.forEach((value) => {
    const index = Math.min(bins.length - 1, Math.max(0, Math.floor((value - minimum) / binWidth)));
    bins[index].count += 1;
  });
  const shares = bins.map((bin) => bin.count / Math.max(1, plottedTrials.length));
  const rawMaximumShare = Math.max(0, ...shares);
  const yMaximum = [0.1, 0.2, 0.4, 0.6, 0.8, 1]
    .find((value) => value >= rawMaximumShare * 1.05) || 1;
  const W = 900, H = 310, L = 70, R = 884, T = 20, B = 240;
  const plotWidth = R - L;
  const barSlot = bins.length ? plotWidth / bins.length : plotWidth;
  const barWidth = Math.max(2, barSlot - Math.min(5, barSlot * 0.18));
  const py = (value) => T + (1 - (value / yMaximum)) * (B - T);
  const yTicks = [0, yMaximum / 2, yMaximum];
  const xTickEvery = Math.max(1, Math.ceil(bins.length / 8));
  const xAxisLabel = metric === "shops"
    ? "Shop where target was hit · successful trials only"
    : metric === "gold"
      ? "Gold spent during the rolldown"
      : "Total target copies found";
  const binLabel = (bin) => bin.start === bin.end ? String(bin.start) : `${bin.start}–${bin.end}`;
  return (
    <div className="rd-outcome-histogram">
      <div className="rd-outcome-summary" aria-label={`${hits.toLocaleString()} hits and ${misses.toLocaleString()} misses`}>
        <div>
          <span className="rd-outcome-dot hit" />
          <span>Hit target</span>
          <strong>{rdPct(hits / trials.length)}</strong>
          <small>{hits.toLocaleString()} trials</small>
        </div>
        <div>
          <span className="rd-outcome-dot miss" />
          <span>Missed target</span>
          <strong>{rdPct(misses / trials.length)}</strong>
          <small>{misses.toLocaleString()} trials</small>
        </div>
      </div>
      {bins.length ? (
        <div className="rd-histogram" style={{ position: "relative" }}>
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${xAxisLabel}. Vertical axis shows share of plotted trials.`}>
            <text x="16" y={(T + B) / 2} transform={`rotate(-90 16 ${(T + B) / 2})`} textAnchor="middle" fill="var(--text-muted)" fontSize="12.5" fontWeight="700">Share of plotted trials</text>
            <text x={(L + R) / 2} y="304" textAnchor="middle" fill="var(--text-muted)" fontSize="12.5" fontWeight="700">{xAxisLabel}</text>
            {yTicks.map((tick) => (
              <g key={tick}>
                <line x1={L} y1={py(tick)} x2={R} y2={py(tick)} stroke="var(--border)" />
                <text x={L - 9} y={py(tick) + 4} textAnchor="end" fill="var(--text-muted)" fontSize="11">{rdPct(tick, 0)}</text>
              </g>
            ))}
            {bins.map((bin, index) => {
              const x = L + index * barSlot + (barSlot - barWidth) / 2;
              const y = py(shares[index]);
              const showTick = index % xTickEvery === 0 || index === bins.length - 1;
              return (
                <g key={bin.start}>
                  <title>{`${binLabel(bin)}: ${bin.count.toLocaleString()} trials (${rdPct(shares[index])})`}</title>
                  <rect x={x} y={y} width={barWidth} height={Math.max(bin.count ? 2 : 0, B - y)} rx="3" fill="#4f46e5" />
                  {showTick ? <text x={x + barWidth / 2} y="260" textAnchor="middle" fill="var(--text-muted)" fontSize="10.5">{binLabel(bin)}</text> : null}
                </g>
              );
            })}
            <line x1={L} y1={B} x2={R} y2={B} stroke="var(--input)" />
          </svg>
          <p className="rd-histogram-note">
            {metric === "shops"
              ? `Misses are summarized above and excluded from these ${hits.toLocaleString()} successful trials so the hit timing remains readable.`
              : `Each bar shows its share of all ${trials.length.toLocaleString()} recorded trials. Hover a bar for its count and range.`}
          </p>
        </div>
      ) : (
        <div className="rd-histogram-empty">
          <strong>No successful trials to plot</strong>
          <span>Every sampled rolldown missed this target. The miss rate is shown above.</span>
        </div>
      )}
    </div>
  );
}

export default RolldownTab;

function RdSweepSurface({ series, sweeps, focusId, onFocus }) {
  const [mode, setMode] = useState("heatmap");
  const [rotation, setRotation] = useState({ yaw: -38, pitch: 55 });
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef(null);
  const suppressSurfaceClick = useRef(false);
  if (sweeps.length !== 2) return null;

  const [xSweep, ySweep] = sweeps;
  const xValues = xSweep.values || [];
  const yValues = ySweep.values || [];
  const budgetType = series[0]?.parameters?.budget_type || "gold";
  const byCoordinate = new Map(series.map((item) => [
    `${item.coordinates?.[xSweep.dimension]}|${item.coordinates?.[ySweep.dimension]}`,
    item,
  ]));
  const grid = yValues.map((yValue) => xValues.map((xValue) => (
    byCoordinate.get(`${xValue}|${yValue}`) || null
  )));
  const W = 860, H = 430, L = 100, R = 838, T = 24, B = 340;
  const cellWidth = (R - L) / Math.max(1, xValues.length);
  const cellHeight = (B - T) / Math.max(1, yValues.length);
  const contourLevels = [0.2, 0.4, 0.6, 0.8];
  const contourSegments = [];
  const interpolate = (a, b, pointA, pointB, level) => {
    const ratio = a === b ? 0.5 : (level - a) / (b - a);
    return {
      x: pointA.x + (pointB.x - pointA.x) * ratio,
      y: pointA.y + (pointB.y - pointA.y) * ratio,
    };
  };
  contourLevels.forEach((level) => {
    for (let y = 0; y < yValues.length - 1; y += 1) {
      for (let x = 0; x < xValues.length - 1; x += 1) {
        const corners = [grid[y][x], grid[y][x + 1], grid[y + 1][x + 1], grid[y + 1][x]];
        if (corners.some((item) => !item)) continue;
        const values = corners.map((item) => rdProbability(item.result));
        const points = [
          { x: L + (x + 0.5) * cellWidth, y: T + (y + 0.5) * cellHeight },
          { x: L + (x + 1.5) * cellWidth, y: T + (y + 0.5) * cellHeight },
          { x: L + (x + 1.5) * cellWidth, y: T + (y + 1.5) * cellHeight },
          { x: L + (x + 0.5) * cellWidth, y: T + (y + 1.5) * cellHeight },
        ];
        const crossings = [];
        [[0, 1], [1, 2], [2, 3], [3, 0]].forEach(([start, end]) => {
          if ((values[start] < level && values[end] >= level)
            || (values[end] < level && values[start] >= level)) {
            crossings.push(interpolate(values[start], values[end], points[start], points[end], level));
          }
        });
        for (let index = 0; index + 1 < crossings.length; index += 2) {
          contourSegments.push({ level, start: crossings[index], end: crossings[index + 1] });
        }
      }
    }
  });

  const yaw = rotation.yaw * Math.PI / 180;
  const pitch = rotation.pitch * Math.PI / 180;
  const project = (xIndex, yIndex, probability) => {
    const x = xValues.length === 1 ? 0 : (xIndex / (xValues.length - 1)) * 2 - 1;
    const y = yValues.length === 1 ? 0 : (yIndex / (yValues.length - 1)) * 2 - 1;
    const z = Number(probability || 0) * 1.35;
    const rotatedX = x * Math.cos(yaw) - y * Math.sin(yaw);
    const rotatedY = x * Math.sin(yaw) + y * Math.cos(yaw);
    const screenPlaneY = rotatedY * Math.cos(pitch) - z * Math.sin(pitch);
    const depth = rotatedY * Math.sin(pitch) + z * Math.cos(pitch);
    return { x: 430 + rotatedX * 235, y: 270 + screenPlaneY * 155, depth };
  };
  const projected = grid.map((row, y) => row.map((item, x) => (
    item ? project(x, y, rdProbability(item.result)) : null
  )));
  const axisOrigin = project(0, 0, 0);
  const xAxisEnd = project(Math.max(0, xValues.length - 1), 0, 0);
  const yAxisEnd = project(0, Math.max(0, yValues.length - 1), 0);
  const zAxisEnd = project(0, 0, 1);
  const surfaceFaces = [];
  for (let y = 0; y < yValues.length - 1; y += 1) {
    for (let x = 0; x < xValues.length - 1; x += 1) {
      const items = [grid[y][x], grid[y][x + 1], grid[y + 1][x + 1], grid[y + 1][x]];
      const points = [projected[y][x], projected[y][x + 1], projected[y + 1][x + 1], projected[y + 1][x]];
      if (items.some((item) => !item) || points.some((point) => !point)) continue;
      const probability = items.reduce((sum, item) => sum + rdProbability(item.result), 0) / 4;
      surfaceFaces.push({
        key: `${x}-${y}`,
        points,
        probability,
        depth: points.reduce((sum, point) => sum + point.depth, 0) / 4,
      });
    }
  }
  surfaceFaces.sort((a, b) => a.depth - b.depth);

  const handlePointerDown = (event) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    suppressSurfaceClick.current = false;
    dragRef.current = { x: event.clientX, y: event.clientY, moved: false, ...rotation };
    setDragging(true);
  };
  const handlePointerMove = (event) => {
    if (!dragRef.current) return;
    if (Math.abs(event.clientX - dragRef.current.x) > 3 || Math.abs(event.clientY - dragRef.current.y) > 3) {
      dragRef.current.moved = true;
    }
    const nextYaw = dragRef.current.yaw + (event.clientX - dragRef.current.x) * 0.55;
    const nextPitch = Math.max(15, Math.min(82, dragRef.current.pitch - (event.clientY - dragRef.current.y) * 0.4));
    setRotation({ yaw: nextYaw, pitch: nextPitch });
  };
  const finishPointer = (event) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    suppressSurfaceClick.current = Boolean(dragRef.current?.moved);
    dragRef.current = null;
    setDragging(false);
  };

  return (
    <div className="rd-sweep-surface">
      <div className="rd-surface-toolbar">
        <div>
          <strong>Dimension comparison</strong>
          <small>Dimension 1 (x-axis): {rdDimensionLabel(xSweep.dimension)} · Dimension 2 (y-axis): {rdDimensionLabel(ySweep.dimension)} · Dimension 3 (z-axis): target-hit probability (height/color)</small>
        </div>
        <Tabs value={mode} onValueChange={setMode}>
          <TabsList aria-label="Dimension visualization" className="h-auto flex-wrap">
            <TabsTrigger id="dimension-heatmap" aria-controls="dimension-panel" value="heatmap">Heatmap + contours</TabsTrigger>
            <TabsTrigger id="dimension-surface" aria-controls="dimension-panel" value="surface">3D surface</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>
      <div role="tabpanel" id="dimension-panel" aria-labelledby={`dimension-${mode}`} tabIndex={0}>
      {mode === "heatmap" ? (
        <div className="rd-surface-canvas">
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Heatmap of target-hit probability by ${rdDimensionLabel(xSweep.dimension)} and ${rdDimensionLabel(ySweep.dimension)}`}>
            <text x={(L + R) / 2} y="414" textAnchor="middle" className="rd-axis-label">{rdDimensionLabel(xSweep.dimension)}</text>
            <text x="18" y={(T + B) / 2} transform={`rotate(-90 18 ${(T + B) / 2})`} textAnchor="middle" className="rd-axis-label">{rdDimensionLabel(ySweep.dimension)}</text>
            {yValues.map((value, y) => <text key={value} x={L - 10} y={T + (y + 0.5) * cellHeight + 4} textAnchor="end" className="rd-axis-tick">{rdCoordinateLabel(ySweep.dimension, value, budgetType)}</text>)}
            {xValues.map((value, x) => <text key={value} x={L + (x + 0.5) * cellWidth} y={B + 24} textAnchor="middle" className="rd-axis-tick">{rdCoordinateLabel(xSweep.dimension, value, budgetType)}</text>)}
            {grid.map((row, y) => row.map((item, x) => {
              const probability = item ? rdProbability(item.result) : null;
              return (
                <g key={`${x}-${y}`} onClick={() => item && onFocus(item.id)} style={{ cursor: item ? "pointer" : "default" }}>
                  <rect x={L + x * cellWidth + 1} y={T + y * cellHeight + 1} width={Math.max(0, cellWidth - 2)} height={Math.max(0, cellHeight - 2)} rx="4" fill={item ? rdHeatColor(probability) : "var(--secondary)"} stroke={item?.id === focusId ? "#ffffff" : "var(--border)"} strokeWidth={item?.id === focusId ? 2.5 : 1} />
                  <text x={L + (x + 0.5) * cellWidth} y={T + (y + 0.5) * cellHeight + 4} textAnchor="middle" fill={probability == null ? "var(--foreground)" : probability > 0.5 ? "#07101b" : "#ffffff"} fontSize="12" fontWeight="800">{probability == null ? "—" : rdPct(probability)}</text>
                  {item ? <title>{`${item.label}: ${rdPct(probability)}`}</title> : null}
                </g>
              );
            }))}
            {contourSegments.map((segment, index) => <line key={`${segment.level}-${index}`} x1={segment.start.x} y1={segment.start.y} x2={segment.end.x} y2={segment.end.y} stroke="rgba(255,255,255,0.78)" strokeWidth="1.6" strokeDasharray="4 3"><title>{`${rdPct(segment.level, 0)} probability contour`}</title></line>)}
          </svg>
          <div className="rd-heat-legend"><span>0%</span><i /><span>100%</span><small>White dashed lines mark the 20%, 40%, 60%, and 80% contours.</small></div>
        </div>
      ) : (
        <div className="rd-surface-canvas rd-surface-3d">
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Rotatable three-dimensional target-hit probability surface" style={{ cursor: dragging ? "grabbing" : "grab", touchAction: "none" }} onPointerDown={handlePointerDown} onPointerMove={handlePointerMove} onPointerUp={finishPointer} onPointerCancel={finishPointer}>
            <rect width={W} height={H} rx="9" fill="var(--secondary)" />
            <g className="rd-surface-axes">
              <line x1={axisOrigin.x} y1={axisOrigin.y} x2={xAxisEnd.x} y2={xAxisEnd.y} />
              <line x1={axisOrigin.x} y1={axisOrigin.y} x2={yAxisEnd.x} y2={yAxisEnd.y} />
              <line x1={axisOrigin.x} y1={axisOrigin.y} x2={zAxisEnd.x} y2={zAxisEnd.y} />
              <text x={xAxisEnd.x + 7} y={xAxisEnd.y + 4}>{rdDimensionLabel(xSweep.dimension)}</text>
              <text x={yAxisEnd.x + 7} y={yAxisEnd.y + 4}>{rdDimensionLabel(ySweep.dimension)}</text>
              <text x={zAxisEnd.x + 7} y={zAxisEnd.y + 4}>100% hit</text>
            </g>
            {surfaceFaces.map((face) => <polygon key={face.key} points={face.points.map((point) => `${point.x},${point.y}`).join(" ")} fill={rdHeatColor(face.probability, 0.9)} stroke="rgba(255,255,255,0.18)" strokeWidth="1"><title>{`Average hit chance ${rdPct(face.probability)}`}</title></polygon>)}
            {grid.map((row, y) => row.map((item, x) => item ? <circle key={item.id} cx={projected[y][x].x} cy={projected[y][x].y} r={item.id === focusId ? 5 : 2.8} fill={item.id === focusId ? "#ffffff" : rdHeatColor(rdProbability(item.result))} stroke="#111827" strokeWidth="1.5" style={{ cursor: "pointer" }} onClick={(event) => { event.stopPropagation(); if (!suppressSurfaceClick.current) onFocus(item.id); }}><title>{`${item.label}: ${rdPct(rdProbability(item.result))}`}</title></circle> : null))}
            <text x="430" y="412" textAnchor="middle" className="rd-axis-label">Drag anywhere to rotate · {rdDimensionLabel(xSweep.dimension)} × {rdDimensionLabel(ySweep.dimension)} × hit chance</text>
          </svg>
          <UiButton variant="outline" type="button" className="rd-surface-reset" onClick={() => setRotation({ yaw: -38, pitch: 55 })}>Reset view</UiButton>
        </div>
      )}
      </div>
    </div>
  );
}

function RdConditionalExplorer({ series, purchases, focusId, onFocus }) {
  const selected = series.find((item) => item.id === focusId) || series[0];
  const [operator, setOperator] = useState("all");
  const [filters, setFilters] = useState([{ unit: purchases[0]?.unit || "", copies_at_least: 1 }]);
  useEffect(() => {
    const available = new Set(purchases.map((purchase) => purchase.unit));
    setFilters((current) => current.map((filter) => available.has(filter.unit) ? filter : { ...filter, unit: purchases[0]?.unit || "" }));
  }, [purchases.map((purchase) => purchase.unit).join("|")]);
  const trials = selected?.result?.trials || [];
  const purchaseIndex = new Map(purchases.map((purchase, index) => [purchase.unit, index]));
  const activeFilters = filters.filter((filter) => purchaseIndex.has(filter.unit));
  const matching = trials.filter((trial) => {
    if (!activeFilters.length) return true;
    const checks = activeFilters.map((filter) => Number(trial.copies?.[purchaseIndex.get(filter.unit)] || 0) >= filter.copies_at_least);
    return operator === "all" ? checks.every(Boolean) : checks.some(Boolean);
  });
  const average = (key) => matching.length
    ? matching.reduce((total, trial) => total + Number(trial[key] || 0), 0) / matching.length
    : 0;
  const distributions = purchases.map((purchase, unitIndex) => {
    const counts = Array.from({ length: 10 }, () => 0);
    matching.forEach((trial) => {
      const copies = Math.max(0, Math.min(9, Number(trial.copies?.[unitIndex] || 0)));
      counts[copies] += 1;
    });
    return { purchase, counts };
  });
  const setFilter = (index, patch) => setFilters((current) => current.map((filter, filterIndex) => filterIndex === index ? { ...filter, ...patch } : filter));

  if (!selected) return null;
  return (
    <div className="rd-explorer-layout">
      <section className="rd-explorer-query">
        <div className="rd-query-heading">
          <div><strong>Conditional outcome search</strong><small>Filter the recorded Monte Carlo samples without rerunning the simulation.</small></div>
        </div>
        <label className="rd-explorer-field"><span>Run</span><UiNativeSelect value={selected.id} onChange={(event) => onFocus(event.target.value)}>{series.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</UiNativeSelect></label>
        <div className="rd-boolean-toggle rd-explorer-operator">
          <span>Match</span>
          {[["all", "ALL filters"], ["any", "ANY filter"]].map(([value, label]) => <UiButton aria-pressed={operator === value} variant={operator === value ? "secondary" : "outline"} type="button" key={value} className={operator === value ? "active" : ""} onClick={() => setOperator(value)}>{label}</UiButton>)}
        </div>
        <div className="rd-explorer-filters">
          {filters.map((filter, index) => (
            <div key={index} className="rd-condition-row">
              <UiNativeSelect aria-label="Filter unit" value={filter.unit} onChange={(event) => setFilter(index, { unit: event.target.value })}>
                <option value="">Choose unit</option>
                {purchases.map((purchase) => <option key={purchase.unit} value={purchase.unit}>{purchase.unit}</option>)}
              </UiNativeSelect>
              <div className="rd-target-slider">
                <label><span>Copies at least</span><strong>{filter.copies_at_least}</strong></label>
                <input aria-label={`Minimum copies of ${filter.unit || "unit"}`} type="range" min="0" max="9" value={filter.copies_at_least} onChange={(event) => setFilter(index, { copies_at_least: Number(event.target.value) })} />
                <div className="rd-slider-scale"><span>0</span><span>9</span></div>
              </div>
              <UiButton variant="ghost" size="icon-sm" type="button" aria-label="Remove filter" disabled={filters.length === 1} onClick={() => filters.length > 1 && setFilters((current) => current.filter((_, filterIndex) => filterIndex !== index))} className="rd-icon-button"><Icon name="close" size={11} /></UiButton>
            </div>
          ))}
        </div>
        <UiButton variant="outline" type="button" onClick={() => setFilters((current) => [...current, { unit: purchases[0]?.unit || "", copies_at_least: 1 }])} className="rd-add-button">+ Add filter</UiButton>
        <p className="rd-sample-note">Based on {trials.length.toLocaleString()} retained samples. This view is exploratory; the headline query above uses every simulation.</p>
      </section>
      <div className="rd-explorer-results">
        <div className="rd-explorer-stats">
          <div><span>Matching samples</span><strong>{matching.length.toLocaleString()}</strong><small>{rdPct(matching.length / Math.max(1, trials.length))} of this run</small></div>
          <div><span>Average shops</span><strong>{average("shops_seen").toFixed(1)}</strong><small>among matches</small></div>
          <div><span>Average spend</span><strong>{average("gold_spent").toFixed(1)}g</strong><small>among matches</small></div>
        </div>
        <section className="rd-conditional-distributions">
          <div className="rd-query-heading"><div><strong>Copies found within this subset</strong><small>Each row is normalized independently across matching samples.</small></div></div>
          {matching.length ? distributions.map(({ purchase, counts }, unitIndex) => {
            const maximum = Math.max(1, ...counts);
            return (
              <div key={purchase.unit} className="rd-copy-distribution">
                <strong>{purchase.unit}</strong>
                <div className="rd-copy-bars">{counts.map((count, copies) => <div key={copies}><span style={{ height: `${(count / maximum) * 100}%`, background: RD_PALETTE[unitIndex % RD_PALETTE.length] }} title={`${copies === 9 ? "9+" : copies} copies: ${count} samples`} /><small>{copies === 9 ? "9+" : copies}</small></div>)}</div>
              </div>
            );
          }) : <EmptyState icon="search" title="No samples match">Loosen or remove a filter to inspect this run.</EmptyState>}
        </section>
      </div>
    </div>
  );
}

function RolldownTab() {
  const [units, setUnits] = useState([]);
  const [catalogError, setCatalogError] = useState("");
  const [level, setLevel] = useState(8);
  const [budgetType, setBudgetType] = useState("gold");
  const [budget, setBudget] = useState(30);
  const [pressure, setPressure] = useState(20);
  const [simulations, setSimulations] = useState(2000);
  const [sweepDimension, setSweepDimension] = useState("budget");
  const [sweepRaw, setSweepRaw] = useState("20, 30, 40, 50");
  const [secondSweepDimension, setSecondSweepDimension] = useState("none");
  const [secondSweepRaw, setSecondSweepRaw] = useState("0, 20, 40, 60");
  const [prepared, setPrepared] = useState(null);
  const [preparedFingerprint, setPreparedFingerprint] = useState("");
  const [selectedRunIds, setSelectedRunIds] = useState([]);
  const [purchases, setPurchases] = useState([{ unit: "", copies_out: 0 }]);
  const [outcomeOperator, setOutcomeOperator] = useState("any");
  const [conditionGroups, setConditionGroups] = useState([
    { operator: "all", conditions: [{ unit: "", copies_at_least: 3 }] },
  ]);
  const [series, setSeries] = useState([]);
  const [focusId, setFocusId] = useState(null);
  const [view, setView] = useState("insights");
  const [xMode, setXMode] = useState("shops");
  const [showBand, setShowBand] = useState(true);
  const [distributionMetric, setDistributionMetric] = useState("shops");
  const [runBusy, setRunBusy] = useState(false);
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [error, setError] = useState("");
  const analysisSequence = useRef(0);
  const pendingViewScroll = useRef(null);

  useLayoutEffect(() => {
    const pending = pendingViewScroll.current;
    if (!pending) return;
    pending.container.scrollTop = pending.scrollTop;
    pendingViewScroll.current = null;
  }, [view]);

  useEffect(() => {
    apiGet("/api/rolldown/units")
      .then((data) => setUnits(data.units || []))
      .catch((requestError) => setCatalogError(requestError.message));
  }, []);

  const F = {
    card: { minWidth: 0 },
    label: { display: "block", color: "var(--muted-foreground)", fontSize: 12, fontWeight: 500, textTransform: "uppercase", letterSpacing: "0.06em" },
  };

  const parameters = {
    level,
    budget,
    budget_type: budgetType,
    pool_pressure: pressure / 100,
    simulations,
  };
  const sweepValues = rdParseSweepValues(sweepRaw);
  const secondSweepValues = rdParseSweepValues(secondSweepRaw);
  const sweepDefinitions = [
    { dimension: sweepDimension, values: sweepValues },
    ...(secondSweepDimension === "none" ? [] : [{ dimension: secondSweepDimension, values: secondSweepValues }]),
  ];
  const sweptDimensions = new Set(sweepDefinitions.map((sweep) => sweep.dimension));
  const currentFingerprint = JSON.stringify({ parameters, sweeps: sweepDefinitions });
  const runsDirty = !!prepared && currentFingerprint !== preparedFingerprint;
  const exactPurchases = purchases.map((purchase) => units.find((unit) => unit.name === purchase.unit.trim()));
  const purchaseNames = new Set(purchases.map((purchase) => purchase.unit.trim().toLowerCase()));
  const duplicatePurchases = purchaseNames.size !== purchases.length;
  const purchasesValid = purchases.length > 0 && exactPurchases.every(Boolean) && !duplicatePurchases;
  const groupsValid = conditionGroups.length > 0 && conditionGroups.every((group) => (
    group.conditions.length > 0
    && group.conditions.every((condition) => purchaseNames.has(condition.unit.trim().toLowerCase()))
    && new Set(group.conditions.map((condition) => `${condition.unit.trim().toLowerCase()}|${condition.copies_at_least}`)).size === group.conditions.length
  ));
  const canAnalyze = !!prepared && selectedRunIds.length > 0 && purchasesValid && groupsValid;
  const focus = series.find((item) => item.id === focusId) || series[0] || null;
  const focusedResult = focus?.result || null;
  const targetRuleLabel = `${outcomeOperator === "any" ? "Any" : "Every"} outcome group`;
  const focusedFinalConfidence = focusedResult
    ? focusedResult.hit_all_by_shop_confidence_95?.[focusedResult.max_shops]
    : null;

  async function prepareRunSet() {
    if (!sweepValues.length) {
      setError("Add at least one numeric value for Dimension 1 (x-axis).");
      return;
    }
    if (secondSweepDimension !== "none" && !secondSweepValues.length) {
      setError("Add at least one numeric value for Dimension 2 (y-axis).");
      return;
    }
    setRunBusy(true);
    setError("");
    try {
      const sweepPayload = sweepDefinitions.length === 1
        ? { sweep: sweepDefinitions[0] }
        : { sweeps: sweepDefinitions };
      const result = await apiPost("/api/rolldown/runs", {
        parameters,
        ...sweepPayload,
      });
      setPrepared(result);
      setPreparedFingerprint(currentFingerprint);
      setSelectedRunIds((result.runs || []).map((run) => run.id));
      setSeries([]);
      setFocusId(null);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setRunBusy(false);
    }
  }

  useEffect(() => {
    const sequence = ++analysisSequence.current;
    if (!canAnalyze) {
      setSeries([]);
      setAnalysisBusy(false);
      return undefined;
    }
    setAnalysisBusy(true);
    const timer = window.setTimeout(() => {
      apiPost("/api/rolldown/runs/analyze", {
        run_set_id: prepared.run_set_id,
        run_ids: selectedRunIds,
        target: {
          purchases: purchases.map((purchase) => ({
            unit: purchase.unit.trim(),
            copies_out: Number(purchase.copies_out) || 0,
          })),
          groups: conditionGroups.map((group) => ({
            operator: group.operator,
            conditions: group.conditions.map((condition) => ({
              unit: condition.unit.trim(),
              copies_at_least: Math.max(0, Math.min(9, Number(condition.copies_at_least) || 0)),
            })),
          })),
          outcome_operator: outcomeOperator,
          include_trials: true,
          trials_sample_cap: 2000,
        },
      }).then((result) => {
        if (sequence !== analysisSequence.current) return;
        const nextSeries = (result.runs || []).map((run, index) => ({
          ...run,
          label: run.label === "Baseline" ? `Baseline · ${rdRunLabel(run.parameters)}` : run.label,
          color: RD_PALETTE[index % RD_PALETTE.length],
        }));
        setSeries(nextSeries);
        setFocusId((current) => nextSeries.some((item) => item.id === current) ? current : nextSeries[0]?.id || null);
        setError("");
      }).catch((requestError) => {
        if (sequence === analysisSequence.current) setError(requestError.message);
      }).finally(() => {
        if (sequence === analysisSequence.current) setAnalysisBusy(false);
      });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [
    prepared?.run_set_id,
    selectedRunIds.join("|"),
    JSON.stringify(purchases),
    JSON.stringify(conditionGroups),
    outcomeOperator,
    units.length,
  ]);

  function setPurchase(index, patch) {
    setPurchases((current) => current.map((purchase, purchaseIndex) => purchaseIndex === index ? { ...purchase, ...patch } : purchase));
  }

  function setGroup(groupIndex, patch) {
    setConditionGroups((current) => current.map((group, index) => index === groupIndex ? { ...group, ...patch } : group));
  }

  function setCondition(groupIndex, conditionIndex, patch) {
    setConditionGroups((current) => current.map((group, index) => index !== groupIndex ? group : {
      ...group,
      conditions: group.conditions.map((condition, innerIndex) => innerIndex === conditionIndex ? { ...condition, ...patch } : condition),
    }));
  }

  function toggleRun(runId) {
    setSelectedRunIds((current) => current.includes(runId)
      ? current.filter((id) => id !== runId)
      : [...current, runId]);
  }

  /** Switch analysis panels without moving the surrounding scroll container. */
  function selectAnalysisView(event, nextView) {
    if (nextView === view) return;
    const scrollContainer = event.currentTarget.closest(".content");
    if (scrollContainer) {
      pendingViewScroll.current = {
        container: scrollContainer,
        scrollTop: scrollContainer.scrollTop,
      };
    }
    setView(nextView);
  }

  const stats = focusedResult ? [
    { label: targetRuleLabel, value: rdPct(rdProbability(focusedResult)), note: focusedFinalConfidence ? `95% CI ${rdPct(focusedFinalConfidence.lower)}–${rdPct(focusedFinalConfidence.upper)} · ${Number(focusedResult.simulations).toLocaleString()} samples` : `±${rdPct(focusedResult.confidence_95_half_width, 1)} · ${Number(focusedResult.simulations).toLocaleString()} samples`, color: "#15803d" },
    { label: "Expected shops", value: Number(focusedResult.expected_shops_seen).toFixed(2), note: "full purchase-plan rolldown", color: "var(--foreground)" },
    { label: "Expected spend", value: `${Number(focusedResult.expected_gold_spent || 0).toFixed(1)}g`, note: "refreshes + purchases", color: "#926500" },
    { label: "Runs compared", value: String(series.length), note: "same prepared samples", color: "#4f46e5" },
  ] : [];

  return (
    <div className="view rolldown-view">
      <datalist id="rolldown-unit-options">
        {units.map((unit) => <option key={unit.name} value={unit.name}>{`${unit.cost}-cost`}</option>)}
      </datalist>

      <div className="rd-page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 14, marginBottom: 12 }}>
        <ViewHeader icon="refresh" eyebrow="Probability lab" title="Rolldown analysis"
          subtitle="Prepare the runs, define what you buy, then explore flexible Boolean questions and conditional outcomes." />
        <div style={{ display: "flex", gap: 6, padding: 5, border: "1px solid var(--border)", borderRadius: 11, background: "var(--card)" }}>
          {[
            ["1", "Define runs", true],
            ["2", "Explore", !!prepared],
          ].map(([number, label, active]) => (
            <span key={number} style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 8px", color: active ? "var(--foreground)" : "var(--muted-foreground)", fontSize: 10.5, fontWeight: 700 }}>
              <span style={{ display: "grid", placeItems: "center", width: 18, height: 18, borderRadius: 99, background: active ? "var(--accent-soft)" : "var(--secondary)", color: active ? "var(--primary)" : "var(--muted-foreground)" }}>{number}</span>{label}
            </span>
          ))}
        </div>
      </div>

      <UiCard as="section" className="block gap-0 p-4 sm:p-6 shadow-xs rd-setup-panel" style={{ ...F.card, marginBottom: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 14 }}>
          <div>
            <span style={{ fontSize: 13.5, fontWeight: 800 }}>1. Define the runs</span>
            <p style={{ margin: "4px 0 0", color: "var(--muted-foreground)", fontSize: 11.5 }}>Choose values for Dimension 1 (x-axis) and optionally Dimension 2 (y-axis). Two dimensions produce every pair in the comparison grid. Dimension 3 (z-axis) shows target-hit probability.</p>
          </div>
          <UiButton variant="default" type="button" onClick={prepareRunSet} disabled={runBusy} className="shrink-0">
            {runBusy ? <Spinner /> : <Icon name="bolt" size={14} />}{prepared ? "Run again" : "Run simulation"}
          </UiButton>
        </div>
        <div className="rd-run-definition-grid">
          <div>
            <label style={{ ...F.label, marginBottom: 7 }}>Dimension 1 (x-axis)</label>
            <UiNativeSelect aria-label="Dimension 1 (x-axis)" value={sweepDimension} onChange={(event) => {
              const dimension = event.target.value;
              setSweepDimension(dimension);
              setSweepRaw(rdDefaultSweepValues(dimension, budgetType));
              if (dimension === secondSweepDimension) setSecondSweepDimension("none");
            }} style={{ marginBottom: 9 }}>
              <option value="budget">Budget</option>
              <option value="level">Player level</option>
              <option value="pressure">Pool pressure</option>
            </UiNativeSelect>
            <label style={{ ...F.label, marginBottom: 6 }}>{sweepDimension === "pressure" ? "Percent values" : `${sweepDimension} values`}</label>
            <UiInput value={sweepRaw} onChange={(event) => setSweepRaw(event.target.value)} placeholder="20, 30, 40, 50"  />
            <div className="rd-second-sweep">
              <label style={{ ...F.label, marginBottom: 6 }}>Dimension 2 (y-axis) <span style={{ color: "var(--muted-foreground)", textTransform: "none", letterSpacing: 0 }}>· optional</span></label>
              <UiNativeSelect aria-label="Dimension 2 (y-axis)" value={secondSweepDimension} onChange={(event) => {
                const dimension = event.target.value;
                setSecondSweepDimension(dimension);
                if (dimension !== "none") setSecondSweepRaw(rdDefaultSweepValues(dimension, budgetType));
              }} style={{ marginBottom: secondSweepDimension === "none" ? 0 : 7 }}>
                <option value="none">No Dimension 2 (y-axis)</option>
                {[["budget", "Budget"], ["level", "Player level"], ["pressure", "Pool pressure"]].filter(([value]) => value !== sweepDimension).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </UiNativeSelect>
              {secondSweepDimension === "none" ? null : <UiInput aria-label={`${rdDimensionLabel(secondSweepDimension)} values`} value={secondSweepRaw} onChange={(event) => setSecondSweepRaw(event.target.value)} placeholder="0, 20, 40, 60"  />}
            </div>
            <p style={{ margin: "7px 0 0", color: "var(--muted-foreground)", fontSize: 10.5, lineHeight: 1.45 }}>Comma-separated values. No extra baseline is added.{secondSweepDimension === "none" ? "" : ` This grid prepares ${(sweepValues.length * secondSweepValues.length).toLocaleString()} runs.`}</p>
          </div>

          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <label style={F.label}>Budget type</label>
              <div style={{ display: "flex", gap: 2, padding: 2, border: "1px solid var(--border)", borderRadius: 7, background: "var(--secondary)" }}>
                <UiButton variant={budgetType === "gold" ? "secondary" : "ghost"} type="button" onClick={() => { setBudgetType("gold"); setBudget(30); if (sweepDimension === "budget") setSweepRaw(rdDefaultSweepValues("budget", "gold")); if (secondSweepDimension === "budget") setSecondSweepRaw(rdDefaultSweepValues("budget", "gold")); }} aria-pressed={budgetType === "gold"}>Gold</UiButton>
                <UiButton variant={budgetType === "rolls" ? "secondary" : "ghost"} type="button" onClick={() => { setBudgetType("rolls"); setBudget(15); if (sweepDimension === "budget") setSweepRaw(rdDefaultSweepValues("budget", "rolls")); if (secondSweepDimension === "budget") setSecondSweepRaw(rdDefaultSweepValues("budget", "rolls")); }} aria-pressed={budgetType === "rolls"}>Rolls</UiButton>
              </div>
            </div>
            <div className="rd-fixed-parameter-grid">
              {!sweptDimensions.has("level") ? <div><label style={{ ...F.label, marginBottom: 6 }}>Fixed level</label><UiNativeSelect aria-label="Fixed level" value={level} onChange={(event) => setLevel(Number(event.target.value))} >{[5, 6, 7, 8, 9, 10].map((value) => <option key={value} value={value}>Level {value}</option>)}</UiNativeSelect></div> : null}
              {!sweptDimensions.has("budget") ? <div><label style={{ ...F.label, marginBottom: 6 }}>{budgetType === "gold" ? "Fixed gold" : "Fixed rolls"}</label><UiInput aria-label={budgetType === "gold" ? "Fixed gold" : "Fixed rolls"} type="number" min="1" max={budgetType === "gold" ? 200 : 100} value={budget} onChange={(event) => setBudget(Math.max(1, Number(event.target.value) || 1))}  /></div> : null}
              {!sweptDimensions.has("pressure") ? <div><label style={{ ...F.label, marginBottom: 6 }}>Fixed pool pressure %</label><UiInput aria-label="Fixed pool pressure percent" type="number" min="0" max="100" value={pressure} onChange={(event) => setPressure(Math.max(0, Math.min(100, Number(event.target.value) || 0)))}  /></div> : null}
            </div>
          </div>

          <div>
            <label style={{ ...F.label, marginBottom: 7 }}>Monte Carlo samples per run</label>
            <UiNativeSelect aria-label="Monte Carlo samples per run" value={simulations} onChange={(event) => setSimulations(Number(event.target.value))} >
              <option value="800">800 · fast</option>
              <option value="2000">2,000 · balanced</option>
              <option value="6000">6,000 · precise</option>
              <option value="20000">20,000 · max</option>
            </UiNativeSelect>
            <p style={{ margin: "8px 0 0", color: "var(--muted-foreground)", fontSize: 10.5, lineHeight: 1.5 }}>Every run in a comparison reuses the same prepared random samples.</p>
          </div>
        </div>
        {runsDirty ? <div style={{ marginTop: 12, padding: "8px 10px", border: "1px solid rgba(245,185,66,0.3)", borderRadius: 8, background: "rgba(245,185,66,0.08)", color: "var(--warning)", fontSize: 11.5 }}>Run conditions changed. The current analysis still uses the last prepared samples until you run again.</div> : null}
        {catalogError ? <p className="statusline warn" style={{ marginTop: 10 }}>Champion autocomplete unavailable: {catalogError}</p> : null}
      </UiCard>

      {!prepared && error ? <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 10, padding: "9px 11px", border: "1px solid rgba(255,107,107,0.28)", borderRadius: 9, background: "rgba(255,107,107,0.08)", color: "var(--bad)", fontSize: 11.5 }}><Icon name="alert" size={14} />{error}</div> : null}

      {!prepared ? (
        <UiCard as="section" className="block gap-0 p-4 sm:p-6 shadow-xs rd-empty-panel" style={F.card}>
          <EmptyState icon="data" title="No runs prepared yet">Choose the dimension values and fixed conditions, then run the simulation. The analysis workspace unlocks afterward.</EmptyState>
        </UiCard>
      ) : (
        <UiCard as="section"  style={{ ...F.card, marginBottom: 10 }} className="block gap-0 p-4 sm:p-6 shadow-xs rd-visualization-workspace">
          <div className="rd-workspace-header">
            <div>
              <span style={{ fontSize: 14, fontWeight: 800 }}>2. Explore the prepared runs</span>
              <p style={{ margin: "4px 0 0", color: "var(--muted-foreground)", fontSize: 11.5 }}>Select runs, define what gets bought, then ask flexible Boolean questions about the outcomes.</p>
            </div>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 8px", border: "1px solid var(--border)", borderRadius: 99, color: analysisBusy ? "#926500" : canAnalyze ? "#15803d" : "var(--muted-foreground)", fontSize: 10.5, fontWeight: 700 }}>
              <span className={`status-dot ${analysisBusy ? "loading" : canAnalyze ? "ready" : ""}`} />{analysisBusy ? "Updating analysis" : canAnalyze ? "Analysis live" : "Complete purchase plan and query"}
            </span>
          </div>
          <div className="rd-workspace-body">
          <aside className="rd-analysis-builder" aria-label="Visualization controls">
          <UiCard as="section"  style={{ ...F.card, background: "var(--card)" }} className="block gap-0 p-4 sm:p-6 shadow-xs rd-analysis-control-panel">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8, marginBottom: 10 }}>
              <div>
                <span style={{ fontSize: 13.5, fontWeight: 800 }}>Selected runs</span>
                <p style={{ margin: "4px 0 0", color: "var(--muted-foreground)", fontSize: 11 }}>Compare only the runs relevant to this question.</p>
              </div>
              <UiButton variant="ghost" type="button" onClick={() => setSelectedRunIds(selectedRunIds.length === prepared.runs.length ? [] : prepared.runs.map((run) => run.id))} >{selectedRunIds.length === prepared.runs.length ? "Clear" : "Select all"}</UiButton>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {prepared.runs.map((run, index) => {
                const selected = selectedRunIds.includes(run.id);
                return (
                  <UiButton variant={selected ? "secondary" : "outline"} type="button" key={run.id} onClick={() => toggleRun(run.id)} aria-pressed={selected} className="grid h-auto w-full grid-cols-[18px_minmax(0,1fr)_auto] gap-2 whitespace-normal text-left">
                    <span style={{ display: "grid", placeItems: "center", width: 17, height: 17, borderRadius: 5, border: `1px solid ${selected ? RD_PALETTE[index % RD_PALETTE.length] : "#515d73"}`, background: selected ? RD_PALETTE[index % RD_PALETTE.length] : "transparent", color: "#ffffff" }}>{selected ? <Icon name="check" size={11} /> : null}</span>
                    <span style={{ minWidth: 0 }}>
                      <strong style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 11.5 }}>{run.label === "Baseline" ? "Baseline" : run.label}</strong>
                      <small style={{ display: "block", marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--muted-foreground)", fontSize: 10 }}>{rdRunLabel(run.parameters)}</small>
                    </span>
                    <span style={{ color: "var(--muted-foreground)", fontSize: 9.5 }}>{Number(run.prepared_samples).toLocaleString()}</span>
                  </UiButton>
                );
              })}
            </div>
            <p style={{ margin: "9px 0 0", color: "var(--muted-foreground)", fontSize: 10.5 }}>Prepared samples are kept for 30 minutes in this server process.</p>
          </UiCard>

          <UiCard as="section"  style={{ ...F.card, background: "var(--card)" }} className="block gap-0 p-4 sm:p-6 shadow-xs rd-analysis-control-panel">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10, marginBottom: 12 }}>
              <div>
                <span style={{ fontSize: 13.5, fontWeight: 800 }}>Purchase plan</span>
                <p style={{ margin: "4px 0 0", color: "var(--muted-foreground)", fontSize: 11 }}>Every listed unit is bought whenever it appears. The full budget is always played out.</p>
              </div>
            </div>
            <div className="rd-purchase-list">
              {purchases.map((purchase, index) => {
                const unit = exactPurchases[index];
                const bagSize = Number(unit?.bag_size || 0);
                return (
                  <div key={index} className="rd-purchase-card">
                    <div style={{ display: "flex", gap: 7, alignItems: "center" }}>
                      <span style={{ display: "grid", placeItems: "center", width: 21, height: 21, borderRadius: 6, background: "var(--secondary)", color: RD_COST_TONE[Math.max(0, Number(unit?.cost || 1) - 1)], fontSize: 10, fontWeight: 800 }}>{unit?.cost || "–"}</span>
                      <UiInput list="rolldown-unit-options" value={purchase.unit} onChange={(event) => {
                        const unitName = event.target.value;
                        const selectedUnit = units.find((candidate) => candidate.name === unitName.trim());
                        const oldName = purchase.unit;
                        setPurchase(index, {
                          unit: unitName,
                          copies_out: selectedUnit
                            ? Math.min(Number(purchase.copies_out) || 0, selectedUnit.bag_size)
                            : purchase.copies_out,
                        });
                        setConditionGroups((current) => current.map((group) => ({
                          ...group,
                          conditions: group.conditions.map((condition) => condition.unit === oldName ? { ...condition, unit: unitName } : condition),
                        })));
                      }} placeholder="Champion" style={{ flex: 1, minWidth: 0 }} />
                      <UiButton variant="ghost" size="icon-sm" type="button" aria-label="Remove purchased unit" onClick={() => purchases.length > 1 && setPurchases((current) => current.filter((_, purchaseIndex) => purchaseIndex !== index))} disabled={purchases.length === 1} className="rd-icon-button"><Icon name="close" size={11} /></UiButton>
                    </div>
                    <div className="rd-target-slider">
                      <label htmlFor={`rd-purchase-out-${index}`}><span>Already out of the pool</span><strong>{bagSize ? `${purchase.copies_out} / ${bagSize}` : "Choose unit"}</strong></label>
                      <input id={`rd-purchase-out-${index}`} type="range" min="0" max={bagSize || 30} step="1" value={Math.min(Number(purchase.copies_out) || 0, bagSize || 30)} disabled={!bagSize} onChange={(event) => setPurchase(index, { copies_out: Number(event.target.value) })} />
                      <div className="rd-slider-scale"><span>0</span><span>{bagSize || "—"}</span></div>
                    </div>
                  </div>
                );
              })}
            </div>
            {purchases.length < 12 ? <UiButton variant="outline" type="button" onClick={() => setPurchases((current) => [...current, { unit: "", copies_out: 0 }])} className="rd-add-button">+ Add unit to purchase plan</UiButton> : null}

            <div className="rd-query-divider" />
            <div className="rd-query-heading">
              <div><strong>Outcome query</strong><small>Build groups of conditions, then choose how the groups combine.</small></div>
              <div className="rd-boolean-toggle">
                <span>Match</span>
                {[["any", "ANY group"], ["all", "ALL groups"]].map(([value, label]) => <UiButton aria-pressed={outcomeOperator === value} variant={outcomeOperator === value ? "secondary" : "outline"} type="button" key={value} className={outcomeOperator === value ? "active" : ""} onClick={() => setOutcomeOperator(value)}>{label}</UiButton>)}
              </div>
            </div>
            <div className="rd-condition-groups">
              {conditionGroups.map((group, groupIndex) => (
                <div key={groupIndex} className="rd-condition-group">
                  <header>
                    <strong>Group {groupIndex + 1}</strong>
                    <div className="rd-boolean-toggle">
                      {[["all", "ALL conditions"], ["any", "ANY condition"]].map(([value, label]) => <UiButton aria-pressed={group.operator === value} variant={group.operator === value ? "secondary" : "outline"} type="button" key={value} className={group.operator === value ? "active" : ""} onClick={() => setGroup(groupIndex, { operator: value })}>{label}</UiButton>)}
                    </div>
                    <UiButton variant="ghost" size="icon-sm" type="button" aria-label="Remove condition group" disabled={conditionGroups.length === 1} onClick={() => conditionGroups.length > 1 && setConditionGroups((current) => current.filter((_, index) => index !== groupIndex))} className="rd-icon-button"><Icon name="close" size={11} /></UiButton>
                  </header>
                  {group.conditions.map((condition, conditionIndex) => (
                    <div key={conditionIndex} className="rd-condition-row">
                      <UiNativeSelect aria-label="Condition unit" value={condition.unit} onChange={(event) => setCondition(groupIndex, conditionIndex, { unit: event.target.value })} >
                        <option value="">Choose purchased unit</option>
                        {purchases.filter((purchase) => purchase.unit.trim()).map((purchase) => <option key={purchase.unit} value={purchase.unit}>{purchase.unit}</option>)}
                      </UiNativeSelect>
                      <div className="rd-target-slider">
                        <label htmlFor={`rd-condition-copies-${groupIndex}-${conditionIndex}`}><span>Copies at least</span><strong>{condition.copies_at_least}</strong></label>
                        <input id={`rd-condition-copies-${groupIndex}-${conditionIndex}`} type="range" min="0" max="9" step="1" value={condition.copies_at_least} onChange={(event) => setCondition(groupIndex, conditionIndex, { copies_at_least: Number(event.target.value) })} />
                        <div className="rd-slider-scale"><span>0</span><span>9</span></div>
                      </div>
                      <UiButton variant="ghost" size="icon-sm" type="button" aria-label="Remove condition" disabled={group.conditions.length === 1} onClick={() => group.conditions.length > 1 && setGroup(groupIndex, { conditions: group.conditions.filter((_, index) => index !== conditionIndex) })} className="rd-icon-button"><Icon name="close" size={11} /></UiButton>
                    </div>
                  ))}
                  {group.conditions.length < 12 ? <UiButton variant="outline" type="button" onClick={() => setGroup(groupIndex, { conditions: [...group.conditions, { unit: purchases[0]?.unit || "", copies_at_least: 1 }] })} className="rd-inline-add">+ Add condition</UiButton> : null}
                </div>
              ))}
            </div>
            {conditionGroups.length < 12 ? <UiButton variant="outline" type="button" onClick={() => setConditionGroups((current) => [...current, { operator: "all", conditions: [{ unit: purchases[0]?.unit || "", copies_at_least: 1 }] }])} className="rd-add-button">+ Add outcome group</UiButton> : null}
            <p className="rd-query-preview">{targetRuleLabel} · edits recalculate the selected runs automatically</p>
          </UiCard>
          </aside>
          <div className="rd-visualization-panel">

          {error ? <div style={{ display: "flex", alignItems: "center", gap: 7, margin: "10px 0", padding: "9px 11px", border: "1px solid rgba(255,107,107,0.28)", borderRadius: 9, background: "rgba(255,107,107,0.08)", color: "var(--bad)", fontSize: 11.5 }}><Icon name="alert" size={14} />{error}</div> : null}

          {series.length ? (
        <div>
          <div className="rd-view-tabs" style={{ display: "flex", gap: 4, padding: 4, marginBottom: 10, border: "1px solid var(--border)", borderRadius: 10, background: "var(--card)" }}>
            {[["insights", "Insights", "Compare the selected runs"], ["distribution", "Distributions", "Inspect simulated outcomes"], ["explorer", "Run explorer", "Search conditional outcomes"]].map(([value, label, note]) => (
              <UiButton variant={view === value ? "secondary" : "ghost"} type="button" key={value} onClick={(event) => selectAnalysisView(event, value)} aria-pressed={view === value} className="h-auto min-h-9 flex-1 flex-col items-start whitespace-normal text-left"><strong style={{ display: "block", fontSize: 11.5 }}>{label}</strong><small style={{ display: "block", marginTop: 2, color: "var(--muted-foreground)", fontSize: 9.5 }}>{note}</small></UiButton>
            ))}
          </div>

          <div className="rd-view-content">
            {view === "insights" ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 9 }}>
                {stats.map((stat) => <UiCard as="div" className="block gap-0 p-4 sm:p-6 shadow-xs" key={stat.label} style={{ ...F.card, padding: "11px 12px" }}><span style={{ ...F.label, marginBottom: 6 }}>{stat.label}</span><strong style={{ display: "block", color: stat.color, fontSize: 21 }}>{stat.value}</strong><small style={{ display: "block", marginTop: 4, color: "var(--muted-foreground)", fontSize: 10.5 }}>{stat.note}</small></UiCard>)}
              </div>
              {(prepared.sweeps || []).length === 2 ? (
                <UiCard as="section" className="block gap-0 p-4 sm:p-6 shadow-xs" style={F.card}>
                  <RdSweepSurface
                    series={series}
                    sweeps={prepared.sweeps}
                    focusId={focusId}
                    onFocus={setFocusId}
                  />
                </UiCard>
              ) : null}
              <UiCard as="section" className="block gap-0 p-4 sm:p-6 shadow-xs" style={F.card}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
                  <div><span style={{ fontSize: 13, fontWeight: 800 }}>How the selected runs compare</span><small style={{ display: "block", marginTop: 3, color: "var(--muted-foreground)", fontSize: 11 }}>One Boolean outcome query evaluated across the selected runs.</small></div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4, padding: 2, border: "1px solid var(--border)", borderRadius: 8, background: "var(--secondary)" }}><UiButton variant={xMode === "shops" ? "secondary" : "ghost"} type="button" onClick={() => setXMode("shops")} aria-pressed={xMode === "shops"}>By shop</UiButton><UiButton variant={xMode === "gold" ? "secondary" : "ghost"} type="button" onClick={() => setXMode("gold")} aria-pressed={xMode === "gold"}>By spend</UiButton><UiButton variant={showBand ? "secondary" : "ghost"} type="button" onClick={() => setShowBand((value) => !value)} title="Pointwise Wilson intervals for the focused run" aria-pressed={showBand}>95% pointwise band</UiButton></div>
                </div>
                <RdProbabilityChart series={series} focusId={focusId} xMode={xMode} showBand={showBand} />
              </UiCard>
              <UiCard as="section" className="block gap-0 p-4 sm:p-6 shadow-xs" style={F.card}>
                <span style={{ display: "block", marginBottom: 9, fontSize: 13, fontWeight: 800 }}>Run outcomes</span>
                <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
                  {series.map((item) => {
                    const probability = rdProbability(item.result);
                    return <UiButton variant={item.id === focusId ? "secondary" : "outline"} key={item.id} onClick={() => setFocusId(item.id)} aria-pressed={item.id === focusId} className="grid h-auto w-full grid-cols-[12px_minmax(0,1fr)_minmax(0,1fr)_58px] gap-2 whitespace-normal text-left"><span style={{ width: 9, height: 9, borderRadius: 3, background: item.color }} /><span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 11.5, fontWeight: 700 }}>{item.label}</span><span style={{ height: 7, borderRadius: 99, overflow: "hidden", background: "var(--surface-3)" }}><span style={{ display: "block", width: `${probability * 100}%`, height: "100%", background: item.color }} /></span><strong style={{ textAlign: "right", fontSize: 11.5 }}>{rdPct(probability)}</strong></UiButton>;
                  })}
                </div>
              </UiCard>
              </div>
            ) : null}

            {view === "distribution" && focusedResult ? (
              <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.5fr) minmax(260px,0.8fr)", gap: 10 }} className="rd-distribution-grid">
              <UiCard as="section" className="block gap-0 p-4 sm:p-6 shadow-xs" style={F.card}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
                  <div><span style={{ fontSize: 13, fontWeight: 800 }}>Sampled outcomes</span><small style={{ display: "block", marginTop: 3, color: "var(--muted-foreground)", fontSize: 11 }}>{focus.label} · {(focusedResult.trials || []).length.toLocaleString()} recorded trials</small></div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4, padding: 2, border: "1px solid var(--border)", borderRadius: 8, background: "var(--secondary)" }}>{[["shops", "Shops to hit"], ["gold", "Gold spent"], ["copies", "Copies found"]].map(([value, label]) => <UiButton variant={distributionMetric === value ? "secondary" : "ghost"} type="button" key={value} onClick={() => setDistributionMetric(value)} aria-pressed={distributionMetric === value}>{label}</UiButton>)}</div>
                </div>
                <RdOutcomeHistogram result={focusedResult} metric={distributionMetric} />
              </UiCard>
              <UiCard as="section" className="block gap-0 p-4 sm:p-6 shadow-xs" style={F.card}>
                <span style={{ display: "block", marginBottom: 10, fontSize: 13, fontWeight: 800 }}>Purchased unit reach</span>
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {(focusedResult.targets || []).map((target, index) => {
                    const probability = Number(target.probability_find_all || 0);
                    return <div key={target.unit}><div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 6 }}><span style={{ color: "var(--foreground)", fontSize: 11.5, fontWeight: 700 }}>{target.unit} · at least {target.copies_needed}</span><strong style={{ color: RD_PALETTE[index % RD_PALETTE.length], fontSize: 11.5 }}>{rdPct(probability)}</strong></div><div style={{ height: 7, overflow: "hidden", borderRadius: 99, background: "var(--surface-3)" }}><div style={{ width: `${probability * 100}%`, height: "100%", background: RD_PALETTE[index % RD_PALETTE.length] }} /></div></div>;
                  })}
                </div>
                <div style={{ marginTop: 16, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
                  <span style={{ ...F.label, marginBottom: 7 }}>Reading this result</span>
                  <p style={{ margin: 0, color: "var(--muted-foreground)", fontSize: 10.5, lineHeight: 1.55 }}>Every listed unit is bought in purchase-plan order when affordable. The threshold shown is the highest copy count used for that unit in the Boolean query.</p>
                </div>
              </UiCard>
              </div>
            ) : null}

            {view === "explorer" ? <RdConditionalExplorer series={series} purchases={purchases} focusId={focusId} onFocus={setFocusId} /> : null}
          </div>
        </div>
          ) : (
        <UiCard as="section" className="block gap-0 p-4 sm:p-6 shadow-xs" style={{ ...F.card, marginTop: 10, background: "var(--card)" }}>
          <EmptyState icon="search" title="Define a purchase plan and query">Select a prepared run, choose the units to buy, and add at least one valid outcome condition.</EmptyState>
        </UiCard>
          )}
          </div>
          </div>
        </UiCard>
      )}
    </div>
  );
}
