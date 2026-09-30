/** Graphics-first palette of units, items, augments, and saved groups that feeds the canvas by drag and drop. */
import React, { useMemo, useState } from "react";
import { Check, Pencil, Plus, Trash2, X } from "lucide-react";
import { Button as UiButton } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input as UiInput } from "@/components/ui/input";
import EntityTile from "./EntityTile.jsx";
import { catalogIndex, ENTITY_MIME, GROUP_MIME } from "./utils.js";

const ITEM_TYPE_LABELS = {
  component: "Components",
  craftable: "Craftable",
  emblem: "Emblems",
  uncraftable_emblem: "Uncraftable emblems",
  radiant: "Radiant",
  artifact: "Artifacts",
  support: "Support",
  anima: "Anima",
  psionic: "Psionic",
  fon: "Fon",
};

/** Singular and plural names for each element kind in a saved group's summary. */
const KIND_NAMES = {
  plan: ["state", "states"],
  action: ["action", "actions"],
  decision: ["decision", "decisions"],
  fork: ["fork", "forks"],
  start: ["start", "starts"],
  end: ["end", "ends"],
  entity: ["entity", "entities"],
  note: ["note", "notes"],
};
/** Entity thumbnails shown on a saved-group card before the rest are counted. */
const GROUP_PREVIEW_ENTITIES = 6;

/** Describe a group's contents, such as "2 states · 1 action · 1 link". */
function groupSummary(fragment) {
  const counts = new Map();
  for (const element of fragment.elements) counts.set(element.kind, (counts.get(element.kind) ?? 0) + 1);
  const parts = [...counts].map(([kind, count]) => `${count} ${KIND_NAMES[kind][count === 1 ? 0 : 1]}`);
  const links = fragment.connections.length;
  if (links) parts.push(`${links} ${links === 1 ? "link" : "links"}`);
  return parts.join(" · ");
}

/** Group entries under stable headings in first-seen order. */
function groupBy(entries, keyOf, labelOf) {
  const groups = new Map();
  for (const entry of entries) {
    const key = keyOf(entry);
    if (!groups.has(key)) groups.set(key, { key, label: labelOf(key), entries: [] });
    groups.get(key).entries.push(entry);
  }
  return [...groups.values()];
}

/** One draggable tile carrying its `EntityRef` in the drag payload. */
function DraggableTile({ category, entry }) {
  const entity = { category, api_name: entry.api_name };
  return (
    <li
      className="flowchart-palette-tile"
      draggable
      aria-label={entry.name}
      onDragStart={(event) => {
        event.dataTransfer.setData(ENTITY_MIME, JSON.stringify(entity));
        event.dataTransfer.setData("text/plain", entry.name);
        event.dataTransfer.effectAllowed = "copy";
      }}
    >
      <EntityTile entity={entity} entry={entry} size={44} />
      <span>{entry.name}</span>
    </li>
  );
}

/**
 * One saved group: draggable onto the canvas, with insert, rename, and delete.
 *
 * The drag payload carries the whole fragment, so the canvas can paste it
 * without another request.
 */
function GroupCard({ group, index, setNumber, canInsert, onInsert, onRename, onDelete }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(group.name);
  const entities = group.fragment.elements.flatMap((element) => element.entities);
  const commit = async (event) => {
    event.preventDefault();
    const next = name.trim();
    if (next && next !== group.name && !(await onRename(group, next))) return;
    setEditing(false);
  };
  return (
    <li
      className="flowchart-group"
      aria-label={group.name}
      draggable={canInsert && !editing}
      onDragStart={(event) => {
        event.dataTransfer.setData(GROUP_MIME, JSON.stringify(group.fragment));
        event.dataTransfer.setData("text/plain", group.name);
        event.dataTransfer.effectAllowed = "copy";
      }}
    >
      {editing
        ? <form className="flowchart-group-rename" onSubmit={commit}>
            <UiInput autoFocus aria-label="Group name" value={name} maxLength={120}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Escape") { setName(group.name); setEditing(false); } }} />
            <UiButton size="icon-sm" variant="ghost" type="submit" aria-label="Save name"><Check aria-hidden="true" /></UiButton>
            <UiButton size="icon-sm" variant="ghost" type="button" aria-label="Cancel rename"
              onClick={() => { setName(group.name); setEditing(false); }}><X aria-hidden="true" /></UiButton>
          </form>
        : <div className="flowchart-group-header">
            <strong>{group.name}</strong>
            {group.set_number && group.set_number !== setNumber && (
              <span className="flowchart-group-set" title="Built for a different set">Set {group.set_number}</span>
            )}
          </div>}
      <span className="flowchart-group-summary">{groupSummary(group.fragment)}</span>
      {entities.length > 0 && (
        <span className="flowchart-group-entities">
          {entities.slice(0, GROUP_PREVIEW_ENTITIES).map((entity, position) => (
            <EntityTile key={`${entity.category}:${entity.api_name}:${position}`} entity={entity}
              entry={index.get(`${entity.category}:${entity.api_name}`)} size={24} />
          ))}
          {entities.length > GROUP_PREVIEW_ENTITIES && <span>+{entities.length - GROUP_PREVIEW_ENTITIES}</span>}
        </span>
      )}
      {!editing && (
        <div className="flowchart-group-actions">
          <UiButton size="sm" variant="outline" disabled={!canInsert} onClick={() => onInsert(group)}>
            <Plus aria-hidden="true" /> Insert
          </UiButton>
          <span className="flowchart-toolbar-spacer" />
          <UiButton size="icon-sm" variant="ghost" aria-label={`Rename ${group.name}`} onClick={() => setEditing(true)}>
            <Pencil aria-hidden="true" />
          </UiButton>
          <UiButton size="icon-sm" variant="ghost" aria-label={`Delete ${group.name}`} onClick={() => onDelete(group)}>
            <Trash2 aria-hidden="true" />
          </UiButton>
        </div>
      )}
    </li>
  );
}

/**
 * Tabbed, searchable palette of entities and saved groups.
 *
 * Args:
 *   catalog: Parsed `/api/assets/catalog` response, or null while loading.
 *   error: Catalog load error message, if any.
 *   library: `{ groups, error, setNumber, canInsert, onInsert, onRename, onDelete }`
 *     for the Groups tab. `groups` is null while loading; `onRename` resolves
 *     to whether the rename succeeded.
 */
export default function EntitySidebar({ catalog, error, library }) {
  const [tab, setTab] = useState("units");
  const [query, setQuery] = useState("");
  const groups = useMemo(() => {
    if (!catalog) return { units: [], items: [], augments: [] };
    const needle = query.trim().toLowerCase();
    const match = (entry) => !needle || entry.name.toLowerCase().includes(needle);
    return {
      units: groupBy(catalog.units.filter(match), (u) => u.cost, (cost) => `${cost}-cost`),
      items: groupBy(catalog.items.filter(match), (i) => i.type, (type) => ITEM_TYPE_LABELS[type] ?? type),
      augments: [{ key: "all", label: null, entries: catalog.augments.filter(match) }],
    };
  }, [catalog, query]);
  const category = { units: "unit", items: "item", augments: "augment" };
  const index = useMemo(() => catalogIndex(catalog), [catalog]);
  const needle = query.trim().toLowerCase();
  const groupsShown = (library?.groups ?? []).filter((group) => !needle || group.name.toLowerCase().includes(needle));
  return (
    <aside className="flowchart-palette" aria-label="Entity palette">
      <UiInput
        type="search"
        aria-label="Search entities"
        placeholder="Search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      {error && <p role="alert" className="flowchart-muted">{error}</p>}
      {!catalog && !error && <p className="flowchart-muted">Loading entities…</p>}
      <Tabs value={tab} onValueChange={setTab} className="flowchart-palette-tabs">
        <TabsList>
          <TabsTrigger value="units">Units</TabsTrigger>
          <TabsTrigger value="items">Items</TabsTrigger>
          <TabsTrigger value="augments">Augments</TabsTrigger>
          {library && <TabsTrigger value="groups">Groups</TabsTrigger>}
        </TabsList>
        {Object.keys(category).map((name) => (
          <TabsContent key={name} value={name} className="flowchart-palette-panel">
            {groups[name].map((group) => (
              <section key={group.key} aria-label={group.label ?? name}>
                {group.label && <h3>{group.label}</h3>}
                <ul className="flowchart-palette-grid">
                  {group.entries.map((entry) => (
                    <DraggableTile key={entry.api_name} category={category[name]} entry={entry} />
                  ))}
                </ul>
              </section>
            ))}
            {catalog && !groups[name].some((group) => group.entries.length) && (
              <p className="flowchart-muted">
                {query ? "No matches." : "Nothing downloaded for this patch. See docs/apps/flowchart.md."}
              </p>
            )}
          </TabsContent>
        ))}
        {library && (
          <TabsContent value="groups" className="flowchart-palette-panel">
            {library.error && <p role="alert" className="flowchart-muted">{library.error}</p>}
            {!library.groups && !library.error && <p className="flowchart-muted">Loading groups…</p>}
            <ul className="flowchart-groups">
              {groupsShown.map((group) => (
                <GroupCard key={group.id} group={group} index={index} setNumber={library.setNumber}
                  canInsert={library.canInsert} onInsert={library.onInsert}
                  onRename={library.onRename} onDelete={library.onDelete} />
              ))}
            </ul>
            {library.groups && !groupsShown.length && (
              <p className="flowchart-muted">
                {query
                  ? "No matches."
                  : "No saved groups yet. Select elements on the canvas and choose Save group to reuse them."}
              </p>
            )}
          </TabsContent>
        )}
      </Tabs>
    </aside>
  );
}
