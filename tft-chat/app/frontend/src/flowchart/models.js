/** Zod mirrors of `services.flowchart.models` (workspaces and saved groups) and the entity catalog response. */
import { z } from "zod";

const elementId = z.string().regex(/^[A-Za-z0-9_-]{1,64}$/);
const handleSide = z.enum(["top", "right", "bottom", "left"]).nullable();

export const EntityRefSchema = z.object({
  category: z.enum(["unit", "item", "augment"]),
  api_name: z.string().min(1).max(120),
}).strict();

const coordinate = z.number().finite().min(-1_000_000).max(1_000_000);
export const PositionSchema = z.object({ x: coordinate, y: coordinate }).strict();
export const FlowchartElementSchema = z.object({
  id: elementId,
  kind: z.enum(["plan", "action", "decision", "fork", "start", "end", "entity", "note", "group"]),
  position: PositionSchema,
  size: z.object({ width: z.number().finite().positive().max(4000), height: z.number().finite().positive().max(4000) }).strict().nullable().default(null),
  parent_id: elementId.nullable().default(null),
  locked: z.boolean().default(false),
  tint: z.string().regex(/^#[0-9A-Fa-f]{6}$/).nullable().default(null),
  title: z.string().max(120).default(""),
  stage_hint: z.string().max(40).nullable().default(null),
  entities: z.array(EntityRefSchema).max(40).default([]),
  text: z.string().max(4000).default(""),
}).strict().superRefine((element, ctx) => {
  if (element.kind === "entity" ? element.entities.length !== 1 : !["plan", "action"].includes(element.kind) && element.entities.length)
    ctx.addIssue({ code: "custom", message: "Invalid entities for node kind" });
  if (element.tint !== null && element.kind !== "group") ctx.addIssue({ code: "custom", message: "Only groups have a tint" });
});
export const FlowchartConnectionSchema = z.object({
  id: elementId, source: elementId, target: elementId,
  kind: z.enum(["transition", "annotation"]).default("transition"),
  condition: z.string().max(200).default(""), notes: z.string().max(2000).default(""),
  source_handle: handleSide.default(null), target_handle: handleSide.default(null),
  waypoints: z.array(PositionSchema).max(64).default([]),
  label_offset: PositionSchema.nullable().default(null),
}).strict();
const fragmentShape = {
  elements: z.array(FlowchartElementSchema).max(400).default([]),
  connections: z.array(FlowchartConnectionSchema).max(800).default([]),
};
/** Validate containment and links before accepting files, clipboard, or API data. */
function validateGraph(graph, ctx) {
  const elements = new Map(graph.elements.map((e) => [e.id, e]));
  const fail = (message) => ctx.addIssue({ code: "custom", message });
  if (elements.size !== graph.elements.length || new Set(graph.connections.map((e) => e.id)).size !== graph.connections.length)
    fail("Ids must be unique");
  for (const element of graph.elements) {
    const seen = new Set([element.id]);
    let parent = element.parent_id;
    while (parent) {
      if (seen.has(parent)) { fail("Cyclic containment"); break; }
      seen.add(parent);
      if (elements.get(parent)?.kind !== "group") { fail("Parent must be an existing group"); break; }
      parent = elements.get(parent).parent_id;
    }
  }
  for (const edge of graph.connections) {
    const a = elements.get(edge.source), b = elements.get(edge.target);
    if (!a || !b || a.id === b.id || a.kind === "group" || b.kind === "group") { fail("Invalid endpoints"); continue; }
    if (edge.kind === "annotation" ? a.kind !== "note" && b.kind !== "note" :
      a.kind === "note" || b.kind === "note" || a.kind === "end" || b.kind === "start") fail("Invalid connection kind");
  }
}
export const FlowchartFragmentSchema = z.object(fragmentShape).strict().superRefine(validateGraph);
export const ViewportSchema = z.object({ x: coordinate, y: coordinate, zoom: z.number().finite().positive().max(10) }).strict();
export const FlowchartSchema = z.object({
  ...fragmentShape, viewport: ViewportSchema.default({ x: 0, y: 0, zoom: 1 }),
}).strict().superRefine(validateGraph);
export const PatchWorkspaceSchema = z.object({
  schema_version: z.enum(["flowchart.v1", "flowchart.v2"]).default("flowchart.v2"),
  name: z.string().min(1).max(120), patch: z.string().min(1).max(40).nullable().default(null),
  set_number: z.number().int().min(1).max(99).nullable().default(null),
  gameplan: z.object({ flowchart: FlowchartSchema }).strict(),
}).strict().transform((value) => ({ ...value, schema_version: "flowchart.v2" }));
/** Clipboard events carry a versioned, strictly validated portable fragment. */
export const ClipboardSchema = z.object({
  type: z.literal("tft.flowchart.fragment"), version: z.literal(2), fragment: FlowchartFragmentSchema,
}).strict();

const source = z.enum(["database", "json"]);

export const WorkspaceRecordSchema = z.object({
  id: z.string(),
  revision: z.number().int(),
  created_at: z.string().nullable(),
  updated_at: z.string().nullable(),
  source,
  workspace: PatchWorkspaceSchema,
}).strict();

export const WorkspaceListSchema = z.object({
  source,
  workspaces: z.array(z.object({
    id: z.string(),
    name: z.string(),
    patch: z.string().nullable(),
    set_number: z.number().int().nullable(),
    revision: z.number().int(),
    updated_at: z.string().nullable(),
    source,
  }).strict()),
}).strict();

export const WorkspaceExportSchema = z.object({
  path: z.string(),
  workspace: PatchWorkspaceSchema,
}).strict();

const imageSrc = z.string().regex(/^\/media\/tft\/[A-Za-z0-9_./%\-]+$/).nullable();

export const EntityCatalogSchema = z.object({
  patch: z.string().nullable(),
  set_number: z.number().int().nullable(),
  units: z.array(z.object({ api_name: z.string(), name: z.string(), cost: z.number().int(), src: imageSrc }).strict()),
  items: z.array(z.object({ api_name: z.string(), name: z.string(), type: z.string(), src: imageSrc }).strict()),
  augments: z.array(z.object({ api_name: z.string(), name: z.string(), src: imageSrc }).strict()),
}).strict();

export const GroupRecordSchema = z.object({
  id: z.string(),
  name: z.string(),
  set_number: z.number().int().nullable(),
  created_at: z.string().nullable(),
  updated_at: z.string().nullable(),
  fragment: FlowchartFragmentSchema,
}).strict();

export const GroupListSchema = z.object({ groups: z.array(GroupRecordSchema) }).strict();
