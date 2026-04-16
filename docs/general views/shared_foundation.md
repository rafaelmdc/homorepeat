# Shared Foundation For First-Wave Viewers

## Purpose

This document captures the implementation decisions that should be reused by
all first-wave viewers:

- `Length`
- `Codon Ratio`
- `Codon Ratio x Length`

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

## Shared codon contract

The current schema preserves codon metrics as:

- `codon_metric_name`
- `codon_metric_value`

That is useful provenance, but it is not a sufficient hot-path viewer contract.
The codon viewers should standardize around a normalized numeric field:

- `codon_ratio_value`

Rules for that field:

- populate it during import for `RepeatCall`
- preserve it during canonical sync for `CanonicalRepeatCall`
- leave it null when the upstream metric is blank or cannot be parsed safely
- exclude null values from codon summaries and codon heatmaps
- keep `codon_metric_name` and `codon_metric_value` for provenance and optional
  selector behavior

Residue behavior:

- the product should support all residues
- codon summaries stay residue-specific by default
- do not aggregate mixed residues into one codon-ratio summary in v1
- expose a `codon_metric_name` selector only when more than one metric exists
  in the current scope

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

### `F2` Extract shared view and template helpers only after the second viewer

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

- one helper for taxon ordering usable by ranked summaries and heatmaps
- a stable ordering contract that overview viewers can share

Exit criteria:

- overview pages do not each invent their own taxon-ordering logic

### `F4` Add reusable binning helpers

Goal:

- share the expensive logic for length-bin and heatmap payload shaping

Scope:

- length-bin definitions
- visible bin normalization
- heatmap payload shaping
- small-multiple input shaping where possible

Exit criteria:

- length and codon viewers reuse one binned-summary layer

### `F5` Add the codon numeric data contract

Goal:

- make codon viewers queryable without repeated text casting

Scope:

- schema additions
- import and canonical-sync population
- fixture updates
- unit tests for blank and invalid values

Exit criteria:

- codon viewer queries can use a numeric field directly

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
