/** One unit, item, or augment rendered as an image tile with a readable text fallback. */
import React, { useState } from "react";

/**
 * Show a catalog entity's image, or its name when no image is downloaded.
 *
 * Args:
 *   entity: `EntityRef` with category and api_name.
 *   entry: Matching catalog entry (name, src, cost) or undefined for unknown names.
 *   size: Square pixel size of the tile.
 */
export default function EntityTile({ entity, entry, size = 40 }) {
  const [failed, setFailed] = useState(false);
  const name = entry?.name ?? entity.api_name;
  const cost = entity.category === "unit" ? entry?.cost : undefined;
  return (
    <span
      className="flowchart-tile"
      data-category={entity.category}
      data-cost={cost}
      title={name}
      style={{ width: size, height: size }}
    >
      {entry?.src && !failed
        ? <img src={entry.src} alt={name} width={size} height={size} draggable={false} onError={() => setFailed(true)} />
        : <span className="flowchart-tile-text">{name}</span>}
    </span>
  );
}
