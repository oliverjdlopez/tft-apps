/** Validate the small read-only image API before rendering any returned URL. */
import { z } from "zod";

const imageResult = z.object({
  status: z.enum(["resolved", "missing"]),
  api_name: z.string().nullable(),
  src: z.string().regex(/^\/media\/tft\/[A-Za-z0-9_./%\-]+$/).nullable(),
  asset_patch: z.string().nullable(),
  fallback: z.boolean(),
}).strict().refine((value) => value.status === "resolved"
  ? value.src !== null && value.api_name !== null && value.asset_patch !== null
  : value.src === null && value.asset_patch === null && !value.fallback,
"Invalid image availability result");
export const AssetResolveResponseSchema = z.object({ results: z.array(imageResult) }).strict();
