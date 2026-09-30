/** Zod mirrors of `services.flowchart.models` (workspaces and saved groups) and the entity catalog response. */
import { z } from "zod";

const elementId = z.string().regex(/^[A-Za-z0-9_-]{1,64}$/);
const handleSide = z.enum(["top", "right", "bottom", "left"]).nullable();

export const EntityRefSchema = z.object({
  category: z.enum(["unit", "item", "augment"]),
  api_name: z.string().min(1).max(120),
}).strict();

export const FlowchartElementSchema = z.object({
  id: elementId,
  kind: z.enum(["plan", "action", "decision", "fork", "start", "end", "entity", "note"]),
  position: z.object({ x: z.number(), y: z.number() }).strict(),
  size: z.object({ width: z.number().positive(), height: z.number().positive() }).strict().nullable(),
  title: z.string().max(120),
  stage_hint: z.string().max(40).nullable(),
  entities: z.array(EntityRefSchema).max(40),
  text: z.string().max(4000),
}).strict();

export const FlowchartConnectionSchema = z.object({
  id: elementId,
  source: elementId,
  target: elementId,
  kind: z.enum(["transition", "annotation"]),
  condition: z.string().max(200),
  notes: z.string().max(2000),
  source_handle: handleSide,
  target_handle: handleSide,
}).strict();

const fragmentShape = {
  elements: z.array(FlowchartElementSchema).max(400),
  connections: z.array(FlowchartConnectionSchema).max(800),
};

/** A saved library group: elements and the links between them, positioned from the origin. */
export const FlowchartFragmentSchema = z.object(fragmentShape).strict();

export const FlowchartSchema = z.object({
  ...fragmentShape,
  viewport: z.object({ x: z.number(), y: z.number(), zoom: z.number().positive() }).strict(),
}).strict();

export const PatchWorkspaceSchema = z.object({
  schema_version: z.literal("flowchart.v1"),
  name: z.string().min(1).max(120),
  patch: z.string().nullable(),
  set_number: z.number().int().nullable(),
  gameplan: z.object({ flowchart: FlowchartSchema }).strict(),
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
