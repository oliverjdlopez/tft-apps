/** Flowchart workspace, saved-group, and entity catalog requests, parsed before reaching components. */
import { api, apiDelete, apiPatch, apiPost, apiPut } from "../app.jsx";
import {
  EntityCatalogSchema,
  GroupListSchema,
  GroupRecordSchema,
  WorkspaceExportSchema,
  WorkspaceListSchema,
  WorkspaceRecordSchema,
} from "./models.js";

const root = "/api/flowchart/workspaces";

/** Validate a response so contract drift fails loudly instead of corrupting the canvas. */
function parse(schema, raw) {
  const result = schema.safeParse(raw);
  if (!result.success)
    throw new Error(
      `Flowchart contract error: ${result.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; ")}`,
    );
  return result.data;
}

const withSource = (path, source) => `${path}?source=${encodeURIComponent(source)}`;
const workspacePath = (id) => `${root}/${encodeURIComponent(id)}`;

export const listWorkspaces = async (source) =>
  parse(WorkspaceListSchema, await api(withSource(root, source)));
export const getWorkspace = async (id, source) =>
  parse(WorkspaceRecordSchema, await api(withSource(workspacePath(id), source)));
export const createWorkspace = async (body) =>
  parse(WorkspaceRecordSchema, await apiPost(withSource(root, "database"), body));
export const saveWorkspace = async (id, revision, workspace) =>
  parse(WorkspaceRecordSchema, await apiPut(withSource(workspacePath(id), "database"), { revision, workspace }));
export const renameWorkspace = async (id, revision, name) =>
  parse(WorkspaceRecordSchema, await apiPatch(withSource(workspacePath(id), "database"), { revision, name }));
export const deleteWorkspace = (id) => apiDelete(withSource(workspacePath(id), "database"));
export const exportWorkspace = async (id, source) =>
  parse(WorkspaceExportSchema, await apiPost(withSource(`${workspacePath(id)}/export`, source), {}));
export const importWorkspace = async (workspace) =>
  parse(WorkspaceRecordSchema, await apiPost(`${root}/import`, { workspace }));

// The saved-group library always lives in the database, so it takes no source.
const groupsRoot = "/api/flowchart/groups";
const groupPath = (id) => `${groupsRoot}/${encodeURIComponent(id)}`;

export const listGroups = async () => parse(GroupListSchema, await api(groupsRoot)).groups;
export const createGroup = async (body) => parse(GroupRecordSchema, await apiPost(groupsRoot, body));
export const renameGroup = async (id, name) => parse(GroupRecordSchema, await apiPatch(groupPath(id), { name }));
export const deleteGroup = (id) => apiDelete(groupPath(id));

/** Load the sidebar roster for a workspace's patch and set, or the configured default. */
export async function loadCatalog(patch, setNumber) {
  const query = new URLSearchParams();
  if (patch) query.set("patch", patch);
  if (setNumber) query.set("set_number", String(setNumber));
  const suffix = query.toString() ? `?${query}` : "";
  return parse(EntityCatalogSchema, await api(`/api/assets/catalog${suffix}`));
}
