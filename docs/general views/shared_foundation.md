# Shared Foundation For First-Wave Viewers

## Purpose

This document captures the implementation decisions that should be reused by
all first-wave viewers:

- `Length`
- `Codon Composition`
- `Codon Composition x Length`

Viewer-specific docs should point back here instead of repeating the same
architecture, filter, and performance rules.

## Reusable baseline that already exists

The current length explorer has already established the correct browser stats
shape:

- one Django app: `apps.browser`
- stable route exports through `apps.browser.views`
- normalized stats filters through `apps/browser/stats/filters.py`
- grouped canonical-repeat-call queries through `apps/browser/stats/queries.py`
- reusable summary shaping in `apps/browser/stats/summaries.py`
- chart payload shaping in `apps/browser/stats/payloads.py`
- a server-rendered page with a matching HTML summary table plus page-local JS

New viewers should reuse that pattern unless there is strong evidence that a
different shape is required.

## Cross-viewer rules

### 1. Shared ownership boundaries

- keep generic browser scope helpers in `apps/browser/views/filters.py`
- keep reusable stats-family parsing, aggregation, and payload code in
  `apps/browser/stats/`
- keep URL-facing viewer classes in `apps/browser/views/stats/`
- do not create a second stats app

### 2. Shared page contract

Every viewer page should follow the same base contract:

- normalized filter state is built once per request
- the template receives only bounded aggregate rows or bins
- the page is still meaningful with JavaScript disabled
- the summary table and chart describe the same visible set
- drill-down reloads the same viewer with a narrower branch scope when possible

### 3. Shared performance rules

- operate on `CanonicalRepeatCall`, not historical raw tables, unless a viewer
  explicitly needs provenance
- never render unbounded raw repeat-call matches into the page
- prefer branch scope, rank scope, bins, `min_count`, and `top_n` limits
- validate hot grouped queries with real query plans before closing a viewer
- only add indexes when a measured query path proves they are needed

### 4. Shared lineage rules

- overview pages must default to lineage-aware ordering
- browse pages may offer value-based sorts later, but must preserve a path back
  to biological order
- reuse the same lineage ordering helper across all viewers so adjacent rows
  remain biologically coherent
- for high-level Metazoa branches, reuse the curated sibling order in the
  shared helper so root-linked phyla do not sort arbitrarily
- when a chart needs a visible taxonomy axis, reuse the shared taxonomy gutter
  contract in `taxonomy_gutter_plan.md` rather than building a viewer-local
  tree widget

### 5. Shared `Tier 1 - Overview` shell

Every first-wave viewer should start from one recognizable overview pattern:

- taxonomy-first
- lineage-ordered
- bounded through rank, branch, `min_count`, and `top_n`
- hex-style cells for cross-viewer continuity

This does not force every viewer into the same metric. It only forces one
shared overview structure:

- y-axis: lineage-ordered taxa or lineage groups
- x-axis: viewer-specific domain
- cell encoding: viewer-specific metric, composition, or count
- interaction: shared branch drill-down and taxon handoff conventions

The taxonomy side is not a learned or embedded 2D space. It remains a stable,
ordered biological axis rendered through one consistent hex-overview shell.

Current codon-composition MVP exception:

- codon composition is currently frozen on a lineage-ordered pairwise
  `Taxon x Taxon` overview rather than the target `Taxon x Codon` shell
- that exception is deliberate MVP scope, not the long-term shared target

## Shared codon contract

The current repeat-call rows preserve these codon-adjacent fields:

- `codon_sequence`
- `codon_metric_name`
- `codon_metric_value`
- `codon_ratio_value`

Those fields are not the correct hot-path browser contract for composition
work. The codon viewers should standardize around normalized codon-usage rows.

The current source contract already exists in the published run layout:

- finalized codon-usage TSVs under
  `publish/calls/finalized/<method>/<residue>/<batch>/final_<method>_<residue>_<batch>_codon_usage.tsv`

Boundary rule:

- do not change `homorepeat_pipeline` as part of this viewer work unless the
  user explicitly approves pipeline changes
- assume the pipeline already emits the codon-composition rows the browser
  needs and import those existing finalized artifacts correctly

The imported browser contract should mirror the normalized codon-usage rows
already produced by codon slicing:

- one row per `call_id` plus `amino_acid` plus `codon`
- `codon_count`
- `codon_fraction`

The web browser should treat codon-usage rows as first-class imported and
canonical data rather than deriving its main analytics from one scalar value.

Role of the legacy fields:

- `codon_sequence` remains useful provenance and a source-side audit field
- `codon_metric_name`, `codon_metric_value`, and `codon_ratio_value` should not
  be the primary browser analytics contract
- if retained in the schema, those fields should be treated as legacy or
  provenance-only fields unless a later product decision reintroduces a
  secondary scalar companion view

Residue behavior:

- the product should support all residues
- codon composition stays residue-specific by default
- do not aggregate mixed residues into one codon-composition summary in v1
- require an explicit residue scope for composition-first views

Composition aggregation:

- aggregate grouped codon composition with equal call weight by default
- one longer tract should not dominate one shorter tract simply because it has
  more codons
- later viewers may add alternative weighting modes, but that should be treated
  as an explicit product choice rather than an implementation convenience

## Shared implementation slices

These slices should be treated as cross-viewer work rather than being
re-implemented inside each viewer plan.

### `F1` Keep the shared stats page shape

Goal:

- preserve one recognizable implementation pattern for stats pages

Scope:

- shared filter card conventions
- shared current-scope summary conventions
- shared grouped-summary table conventions
- shared branch drill-down and reset behavior

Exit criteria:

- the first three viewers feel like one family, not three unrelated pages

### `F2` Keep shared view and template helpers small

Goal:

- reuse code without premature abstraction

Scope:

- add a small shared base or mixin only for behavior used by both length and
  codon viewers
- move repeated summary-table or scope-card markup into template partials only
  when the duplication becomes real

Exit criteria:

- shared abstractions exist because at least two viewers need them

### `F3` Add lineage ordering helpers

Goal:

- make lineage-aware ordering reusable rather than page-local

Scope:

- one helper for taxon ordering usable by ranked summaries and taxonomy-first
  overview payloads
- a stable ordering contract that overview viewers can share

Exit criteria:

- overview pages do not each invent their own taxon-ordering logic

### `F4` Add reusable binning and composition helpers

Goal:

- share the expensive logic for length-bin and overview payload shaping

Scope:

- length-bin definitions
- visible bin normalization
- hex-overview payload shaping
- small-multiple input shaping where possible
- composition stack shaping for codon viewers

Exit criteria:

- length and codon viewers reuse one bounded overview layer

### `F5` Import existing finalized codon usage as first-class browser data

Goal:

- make codon viewers depend on real composition rows instead of ad hoc parsing
  or scalar fallbacks, without changing the pipeline boundary by default

Scope:

- published-run import support for existing finalized codon-usage TSVs
- finalized codon-usage artifact discovery across methods, residues, and
  batches
- import and canonical-sync support for codon-usage rows
- fixture and unit-test updates

Exit criteria:

- codon viewers query normalized codon usage directly

### `F6` Keep discoverability consistent

Goal:

- make new viewers feel native to the browser

Scope:

- browser home entry points
- branch-scoped handoffs from taxon detail
- optional handoffs from protein and repeat-call detail when semantically
  useful

Exit criteria:

- viewer entry points are consistent across the first-wave family

### `F7` Add a shared taxonomy gutter for cartesian charts

Goal:

- make taxonomy-grouped rows readable across chart views without replacing the
  shared chart shell

Scope:

- shared backend payload shaping for lineage connectors and terminal braces
- one reusable frontend overlay helper for ECharts cartesian charts
- scope-aware collapsed-descendant counts driven by the current stats filters

Reference:

- `taxonomy_gutter_plan.md`

Exit criteria:

- taxonomy-first charts can reuse one gutter/tree overlay contract across
  codon, length, and later taxon-based views
