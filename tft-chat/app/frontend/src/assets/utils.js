/** Batch local image requests and retain results for one view's catalog context. */
import { apiPost } from "../app.jsx";
import { AssetResolveResponseSchema } from "./models.js";

/** Preserve exact input identity; backend TFTNameResolver owns normalization. */
export function imageKey(entity) {
  return JSON.stringify([entity.kind, entity.name_or_id, entity.role]);
}

/** Deduplicate and consistently order requests so unrelated renders do not reload. */
export function uniqueImages(entities) {
  return [...new Map(entities.map((entity) => [imageKey(entity), entity])).entries()]
    .sort(([a], [b]) => a.localeCompare(b)).map(([, entity]) => entity);
}

/** Create a cache shared by list/detail requests for the same patch and TFT set. */
export function createAssetLoader(patch, setNumber) {
  const cache = new Map();
  return async (entities) => {
    const unique = uniqueImages(entities);
    const missing = unique.filter((entity) => !cache.has(imageKey(entity)));
    for (let offset = 0; offset < missing.length; offset += 256) {
      const chunk = missing.slice(offset, offset + 256);
      const batch = apiPost("/api/assets/resolve", {
        patch, set_number: setNumber, entities: chunk,
      }).then((raw) => {
        const { results } = AssetResolveResponseSchema.parse(raw);
        if (results.length !== chunk.length) throw new Error("Asset response length mismatch");
        return results;
      });
      chunk.forEach((entity, index) => {
        const key = imageKey(entity);
        const pending = batch.then((results) => results[index]).catch(() => {
          // Transport failures do not prevent the next view change from retrying.
          cache.delete(key);
          return { status: "missing", src: null, asset_patch: null, fallback: false, api_name: null };
        });
        cache.set(key, pending);
      });
    }
    return new Map(await Promise.all(unique.map(async (entity) => {
      const key = imageKey(entity);
      return [key, await cache.get(key)];
    })));
  };
}
