# Shared application UI

ChatTFT, Compositions, and Rolldown use a light shadcn/ui interface with subtle
distinct pastel surfaces and iris actions.
VOD Review, Wisps, Langfuse, and CloudBeaver retain their independently managed themes.
The Electron shell uses matching plain CSS and retains its 48px navigation bar.

## Canonical sources and generation

ChatTFT's `app/frontend/src/theme.css` is the canonical theme. The local independent
`vod-review` and `vod-review-wt2` checkouts currently use their own `styles.css`
and do not contain the shared `frontend/src/theme.css` previously described here.
There is no shared runtime package or monorepo; updating ChatTFT does not restyle
those applications.
ChatTFT stays JavaScript/JSX; both video frontends stay TypeScript/TSX.

The initial component sources were generated with **shadcn CLI 4.21.0**:
**New York**, **neutral**, **Radix**, **Lucide**, CSS variables enabled, RSC off.
`components.json` records the preset, aliases, theme path, and language choice.
The CLI's online registry can change independently of its version; the checked-in
component sources and lockfiles are the reproducible artifact.

- Tailwind CSS / Vite plugin: 4.3.3
- Radix unified primitives: 1.6.7
- Lucide React: 1.47.0
- CVA: 0.7.1; clsx: 2.1.1; tailwind-merge: 3.7.0; tw-animate-css: 1.4.0

`src/components/ui/` contains Button, Input, Textarea, Native Select, Checkbox,
Switch, Tabs, Sidebar, Card, Badge, Alert, Dialog, Alert Dialog, Popover, Tooltip,
Collapsible, Separator, Progress, Skeleton, Table, and Sidebar's Sheet dependency.
`src/lib/utils` supplies `cn`; `src/hooks/use-mobile` supports responsive Sidebar.
Vite resolves `@` to `src`; the video Vitest configurations resolve the same alias.
Video dev/build commands explicitly select `vite.config.ts` so previously emitted
ignored JavaScript configs cannot shadow the canonical configuration.

Local adaptations to preserve during regeneration:

- Card accepts an `as` tag so section/aside semantics survive replacement.
- Tabs lists and triggers use automatic height (36px/32px minimums) so wrapped
  lists fit. Existing conditional panels have explicit accessible tab relationships.
- Sidebar state belongs to the existing application local-storage contract.
  The generated Sidebar cookie write is removed in all three copies.
- Shared component imports use the local `@/lib/utils`, not an npm `cn` package.
- `components/shared` owns application adapters, rather than editing Radix behavior
  at individual call sites: retained-content disclosures, asynchronous confirmations,
  video conditional dialogs, keyboard-accessible file uploads, and A2UI selection
  controls. Single-choice selection keeps native radio semantics with shared tokens;
  multiple-choice selection uses shadcn Checkbox.

## Visual and interaction conventions

Use semantic tokens: background `#fafafa`, card/popover `#ffffff`, secondary
`#e7def7`, foreground `#292733`, muted foreground `#626262`, primary `#6350ac`,
primary foreground `#ffffff`, border `#dedce3`. The base radius is 10px. Use system
sans-serif, 36px standard controls, 32px compact controls, and 4px spacing steps.
Keep meaningful chart, rarity, TFT item, warning, and canvas-overlay hues, with
darker chart strokes and status text for contrast on light surfaces. Chart axes,
tooltips, Markdown/code, warnings, and legacy panels use the semantic palette.
The HTML entry and CSS request `color-scheme: light`; no dark class or theme
switcher is applied, regardless of the operating system preference.

Decorative colors are limited to selected surfaces: lilac chat starters,
chat headers and secondary actions, mint activity headers and experiment setup
panels, blue Compositions/Rolldown page headers, and sand header icons.
Both standalone workspaces use a lightly tinted canvas, and the Compositions
form expands to 1120px to use the available width. Family navigation is lavender;
placement, top-four, and win-rate metrics use blue, mint, and sand cards.
Dense results, chart plots, and field interiors stay white. Repeated unit cards
and empty states use a quieter sand tint so they do not dominate the workspace.
Dialogs use light lilac (`--dialog-surface`) and a translucent muted
scrim (`--dialog-overlay`), also shared by mobile sheets. Outline buttons use
separate surface, border, and ink tokens. Keep these washes distinct from success,
warning, destructive-action, rarity, and chart colors; avoid multicolor borders,
gradients, and decorative color cycling across dense lists.

Use shared controls for application-owned interactions. Keep native video
controls, range-slider pointer semantics, canvas drawing, SVG charts, Markdown
sanitization, and A2UI processing with their existing renderers. File inputs behind
UploadButton and the video timestamp compatibility inputs are intentionally native.
Basic Table only wraps existing sorting/filtering/pagination; no table engine or
form framework is installed.

Theme, base, legacy, components, and utilities have explicit CSS layer order.
Domain layout lives in `styles.css` and `compositions/compositions.css` under the
legacy layer; shared component utilities win. Avoid new global button/input/table
skins. Neutral aliases keep domain renderers consistent while semantic status and
TFT colors remain meaningful. Panels and toolbars wrap; table containers own
horizontal scrolling. Video and canvas retain their shared aspect-ratio parent.

Controlled Radix checkboxes use `onCheckedChange` and boolean adapters. Native
Select retains DOM change events and the existing unset/default coercion rules.
Workflow category changes still remount their runner. Desktop views and saved
navigation retain their existing lifecycle. Confirmation cancellation performs no
operation; Escape returns focus to the invoking control. Annotation shortcuts
ignore an open confirmation. A2UI local controls retain local behavior and existing
allowlisted investigation requests.

## Updating the three independent builds

1. Make the component/theme change in ChatTFT. Review upstream diffs before
   replacing local sources. For additions, use the pinned command from the frontend:

   ```bash
   npx shadcn@4.21.0 add <component>
   ```

2. When a change also targets video frontends, first verify their current component
   and theme setup. Checkouts using the shared theme should receive an exact copy;
   older checkouts need a separate migration. Do not copy App, annotation, API, or
   upload logic between the video branches: their feature sets differ.
3. Mirror changed palette/typography values in `desktop/workspace.css` and
   `desktop/status.css`. Both are already included in immutable Windows staging;
   CSS changes produce a new shell hash. No shell React build is needed.
4. In each frontend run `npm ci`, `npm test`, and `npm run build`. Run
   `npm --prefix desktop test` after shell changes. Inspect component event payloads,
   keyboard navigation, focus return, disabled/loading states, and retained mounts.
5. Capture the same fixture states at 1440, 1024, and 390px. Inspect internal table
   scrolling, toolbar wrapping, and video/canvas rectangles at each width. Separately
   validate native Windows tab switching, shortcuts, recovery, and staged assets.

See [web runtime](../architecture/web-runtime.md), [desktop validation](../apps/desktop.md#validation),
and [migration validation](shared-ui-validation.md). Upstream setup references:
[existing Vite app](https://ui.shadcn.com/docs/installation/vite) and
[JavaScript generation](https://ui.shadcn.com/docs/javascript).

## Light theme validation

The light theme passes all 85 frontend tests, all 50 desktop Node tests, and
the production Vite build. Browser inspection used the production assets with
read-only fixture responses: ChatTFT chat, Compositions family details and mobile
layout, Rolldown setup, and the desktop navigation/loading HTML. No live model,
database, or experiment requests were needed. Native desktop window behavior and
the independent video applications were not part of this visual check.
Restart Desktop to reload its shell CSS; normal startup rebuilds the web assets.

The pastel refinement was reviewed in two visual passes, including the real
high-sample confirmation dialog with synthetic source counts and cancellation.
The second pass reduced repeated card tint and restored white form fields to
keep the setup surfaces quiet and the controls distinct.
The subsequent stronger palette was also reviewed on desktop and mobile,
including fixture family details and Rolldown setup. A second pass retained the
more distinct blue/mint headers and forms while reducing the emphasis on large
empty states and repeated unit cards. Selected Rolldown budget controls use white
against the lavender control group to remain distinguishable.

## Compositions workspace layout

`src/compositions/Compositions.jsx` retains the configuration gate and validated display
fixtures. `Experiments.jsx` owns the selected run, draft setup, request state,
run header, result tabs, and comparison. It composes `RunRail.jsx` (new
experiment entry, saved run history, fixtures entry), `ExperimentSetup.jsx`
(the new-experiment form and run summary), and `BoardInspector.jsx` (the Boards
tab). `CompositionResults.jsx` supplies the shared family browser, family
details, requirement chips, observed board roster, and placement distribution.
Shared labels and formatting (`algorithmLabel`, `percent`, `populationLabel`,
`statusTone`, `confirmSampleRun`) live in `compositions/utils.js`. All workspace
styling is in `compositions/compositions.css` under the `components` layer; the
global `styles.css` no longer carries composition overrides.

The page is a two-column workspace. A sticky 280px rail lists every saved run
with its algorithm, status, short ID, elapsed time, patch, and sample/eligible
counts. Selecting the already open run returns to it with its selections intact;
selecting another run loads it and clears evidence from the previous run. There is
no separate history page. **New experiment** opens a form grouped into Source &
sampling (with sample-size presets capped at the eligible population) and HDBSCAN
parameters. A sticky **Run summary** beside the form
shows source readiness, patch, set, queue, eligible and sampled boards, the
sampling plan, large-run warnings, and **Start experiment**. Draft inputs survive
navigation. Display fixtures have their own view and remain explicitly labeled as
illustrative data.

A selected run shows a header with algorithm, status, source context, and
Cancel/Rerun/Duplicate actions, then a metrics strip (families, coverage,
ambiguity, sample, elapsed). Completed runs expose **Families**,
**Boards**, **Diagnostics**, and **Compare** as line-style shadcn Tabs, with a
segmented **Statistics population** control beside them. Panels remain mounted
while hidden so example selections, diagnostic disclosures, and pagination
survive tab switches. Opening another run or changing statistics population
clears evidence and comparisons belonging to the previous context. The first
family loads automatically.

The Families tab pairs a sticky, filterable family list with the detail column.
Each row shows the family label, variation count, requirement chips with entity
images, and a play-share bar. Below 960px a native selector replaces the list.
Family details show average placement, top-four rate, win rate, and play share as
stat tiles with their denominators, beside a placement distribution that colors
top-four and bottom-four bins separately. All eight observed counts are shown;
unavailable and suppressed outcomes remain distinct from zero. The representative
structure, the boards matching it (with support bars), and variations remain separate from
representative observations. Examples appear as roster thumbnails above the
selected compact board. Rosters preserve champion occurrences, star levels, and
holder-bound item slots (announced to screen readers) without inferring
positioning. Trait chips are toned by style tier. **Inspect board** opens the
Boards panel, which lists the population's observations with assignment-status
filters and pagination beside the full board and its assignment evidence, and
transfers keyboard focus to its tab. Navigation also moves focus when an action
hides its own trigger.

Validation for this layout includes frontend behavior tests and a production
build, plus Chromium screenshots against contract-valid mocked API responses
with local Community Dragon images. Mocked responses exercise layout and
navigation without launching database-backed experiments. They do not establish
native Windows Electron or live-source behavior.

The rail-and-workspace redesign passed all **94 frontend tests** (`npm test`)
and `npm run build`; the existing bundle-size advisory remains. Screenshots
covered setup, families, boards, both statistics populations, diagnostics, a
failed run, and fixtures at 1440px, plus families at 820px and setup at 390px,
with no horizontal page overflow at 390px. Tests that previously used the history
table, the population select, and the example and board
selectors now drive the rail, HDBSCAN settings, segmented population control,
example thumbnails, and observation list. No automated WCAG audit or Python
suite was rerun for this change, and no backend behavior changed.
