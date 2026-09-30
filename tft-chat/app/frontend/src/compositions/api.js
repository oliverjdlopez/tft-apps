/** Parse each composition response once before it reaches a component. */
import { api, apiPost } from "../app.jsx";
export const root = "/api/developer/compositions";
/** Fetch and validate a response, surfacing contract failures distinctly. */
export async function compositionRequest(path, schema, body) {
  const raw =
    body === undefined
      ? await api(root + path)
      : await apiPost(root + path, body);
  const result = schema.safeParse(raw);
  if (!result.success)
    throw new Error(
      `Composition contract error: ${result.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; ")}`,
    );
  return result.data;
}
