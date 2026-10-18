# Reference resources and progressive disclosure

Static facts live under `app/backend/src/domain/resources/content/references`. Assistants see
only root directory descriptions in their instructions. `read_resource("set18")`
returns a set overview and permitted topic IDs; reading a topic reveals its
children. A leaf read returns the complete source body. Any known ID may be read
directly, but every read requires membership in the repository library and
permission from the active assistant's spec.
Descriptions and index listings guide discovery; they are not factual evidence.

`domain.resources` owns resource schemas, metadata validation, storage, caching,
and complete content loading. Runtime loads the repository-wide library directly
into `AssistantRunContext.resources` for every invocation, regardless of the
assistant graph. Assistants never construct their own libraries. Their renderers
filter metadata with `self.spec.allows_resource(id)` and compose their own
instruction directories. `domain.tools.context` uses the active assistant's spec
to check reads and filter child listings and links from the same shared library.
Successful reads are recorded in invocation activity. The resources package has
no assistant or invocation dependencies. There is no provider or selector
execution path.

## Authoring and parsing

See [resource layout and schema](resource-layout.md) for the complete contract.
Reference Markdown has strict YAML frontmatter: stable `id`, `title`,
`description`, `kind`, and `parent`; optional `patches`,
`requires`, `related`, and `provenance` describe applicability and relationships.
Identity is independent of physical paths. Unknown fields, duplicate keys/IDs,
broken links and cyclic required dependencies fail
validation rather than silently removing facts from discovery.
The library assumes all resources belong to the consistent current set. Resource
metadata, tool responses, invocation context, and execution receipts carry no set
number; patch provenance remains available.

Indexes are authored Markdown documents. Their child lists derive from parent
IDs and are filtered for the active assistant. Leaf references preserve complete
explanations, conditions, and tables. The champion roster remains a complete
population reference rather than an arbitrary token-sized slice. Source patch
coverage is explicit where known; an empty patch list does not claim currentness.

## Structured Wisp populations

Seven record collections each have a Markdown descriptor and exactly one typed
JSON backing file. These JSON files are authoritative records, not prose copies
of independently maintained Markdown. They retain all 365 original variants,
exact source wording, stable variant IDs, structured inclusive stage/round
windows, modes, conditions, and augment exclusions. The full wording preserves
restrictions beyond the normalized fields; absent normalized fields are not
proof that a restriction is absent.

`read_resource("set18/wisps/offers-goldxp")` returns the full category and its
stage view IDs. `set18/wisps/offers-goldxp/stage-2` returns every variant whose
window intersects Stage 2. Cross-stage variants appear in each matching view,
with identical variant IDs. `stage-all` retains explicitly unrestricted offers;
it does not make prismatic variants ordinary offers. Stage views link to required
general rules and their applicable all-stage view. Count unions by variant ID.
Other references, including patch 18.2 offer ledgers, retain their own source
revision rather than silently superseding the baseline. Consult the source
conflict reference when claims disagree.

## Loading, caching, and provenance

Preparation scans metadata headers and reuses a validated index keyed by source
modification time and size. It does not consume document bodies or record JSON.
Reads perform filesystem work off the async event loop and cache complete bodies
under that library revision. Old invocations retain their snapshot. A source
changed before its first read returns an error asking for a fresh invocation;
an already cached read retains the original content. Symlinks and arbitrary
filesystem paths cannot become read targets.

`AssistantRunContext.activity.resource_reads` records actual read IDs, source paths,
source SHA-256 hashes, complete returned content, and variant IDs. Captured
execution receipts additionally record content hashes, including reads preceding
a failed generation. Receipts keep those summaries under `resources.reads`;
activity exports contain tool and handoff records without duplicating resource
bodies. Index reads count as reads too. Source paths identify
provenance but are never resource identities. Body caches do not grant access:
the read tool checks library membership and the active assistant's spec before
consulting the shared cache. Prompt directories use the same spec predicate. Handoffs and clones apply their own specs to the shared
materials; neither a reused name nor a cached body grants additional access.

## Migration and validation

The [migration receipt](resource-migration.json) maps 75 original Markdown
sources to stable IDs and records original hashes. All 75 bodies were checked
against Git source bytes after normalizing line endings and removing display-only
variant labels. Ten prose-only JSON companions were consolidated into Markdown;
claims not matching an existing entry were explicitly retained in an appendix.
Seven Wisp JSON companions became typed canonical backing records. Selector
suites, scoring hooks, legacy metadata aliases, and provider tests have been
removed. Current assistant snapshots use the current run schema; archived bytes
are records only and are not given a compatibility execution path.

```bash
.venv/bin/python -m domain.resources
.venv/bin/python -m pytest -q tests/test_resource_library.py tests/test_assistant_runtime.py
```

Validation loads all bodies and structured views offline. Normal preparation
remains metadata-only. It makes no model calls or database changes.

Offline corpus validation checks 141 resources and derived views. Global
`evals validate` checks 11 assistant suites and 142 cases; no selector corpus
preflight remains. No paid-model evaluations or hosted content edits are needed.
