# Codon Ratio Viewer Slices

## Goal

Build the codon-ratio viewer by reusing the existing browser stats stack,
starting with the codon data contract and then landing the page in small,
reviewable slices.

## Phase 1: Codon data contract

### `C1` Add numeric codon storage

Goal:

- make codon viewer queries numeric and predictable

Scope:

- add `codon_ratio_value` to `RepeatCall`
- add `codon_ratio_value` to `CanonicalRepeatCall`
- keep `codon_metric_name` and `codon_metric_value` unchanged

Tests:

- schema-level coverage for nullable numeric storage
- no regressions to import or canonical-sync tests

Exit criteria:

- codon ratio has a stable numeric home in both raw and canonical models

### `C2` Populate the numeric field during import and canonical sync

Goal:

- eliminate viewer-time text parsing

Scope:

- parse numeric codon values during repeat-call import
- preserve the parsed value during canonical sync
- leave invalid or blank values as null

Tests:

- numeric import success
- blank value becomes null
- invalid value becomes null without import failure

Exit criteria:

- canonical repeat calls already contain the numeric codon value needed by the
  viewer

### `C3` Extend fixtures and test helpers with real codon values

Goal:

- make codon viewer tests realistic from the first UI slice

Scope:

- update browser test fixtures and helper builders to set representative codon
  metric names and numeric values
- keep residue-specific coverage explicit

Exit criteria:

- codon viewer tests do not depend on ad hoc data setup inside each test

## Phase 2: Shared stats support for codon pages

### `C4` Extend normalized stats filters for codon use

Goal:

- reuse the shared filter contract instead of hand-parsing codon pages

Scope:

- residue stays first-class
- add optional `codon_metric_name` handling
- keep branch, rank, run, `min_count`, and `top_n` semantics aligned with
  length view

Tests:

- default residue-specific behavior
- selector behavior when multiple metric names exist
- null-codon rows excluded correctly

Exit criteria:

- codon pages can use the same normalized stats state pattern as length

### `C5` Add codon summary queries and summary builders

Goal:

- support grouped taxon codon summaries before any chart work

Scope:

- grouped summaries by display taxon over `codon_ratio_value`
- count, min, q1, median, q3, and max or equivalent bounded interval summary
- reuse the same rank roll-up behavior as length

Tests:

- grouped codon summaries at broad and branch scopes
- filters by residue, method, and run

Exit criteria:

- the backend can produce one bounded codon summary row per visible taxon

## Phase 3: Ship the browse layer first

### `C6` Add the codon-ratio route and server-rendered page

Goal:

- land a useful codon page before adding JS charting

Scope:

- route: `/browser/codon-ratios/`
- URL-facing view under `apps/browser/views/stats/`
- grouped HTML summary table
- current-scope summary and explicit empty states

Tests:

- route resolution
- default render
- empty-state messaging
- grouped summary output

Exit criteria:

- codon ratio is browseable without JavaScript

### `C7` Add the ranked codon browse chart

Goal:

- match the existing length-view interaction model

Scope:

- page-local chart payload for codon interval summaries
- branch drill-down links
- taxon detail links
- chart and table represent the same visible set

Tests:

- payload shape
- branch link preservation
- page-local asset loading

Exit criteria:

- codon ratio has a real Tier 2 browse layer

## Phase 4: Add overview and inspect tiers

### `C8` Add codon heatmap queries and payloads

Goal:

- support the overview tier without inventing a second query stack

Scope:

- reuse shared length-bin helpers
- summarize `codon_ratio_value` per taxon and length bin
- keep the output bounded and lineage-orderable

Tests:

- bin payload shape
- branch-scoped heatmap summaries

Exit criteria:

- backend support exists for the codon overview tier

### `C9` Add the Tier 1 codon heatmap

Goal:

- deliver the scalable overview page for codon behavior

Scope:

- `Taxon x Length-bin Codon Heatmap`
- lineage-aware taxon order
- tooltip with taxon, length bin, count, and codon summary
- hex-bin heatmap

Exit criteria:

- codon ratio has a real overview tier

### `C10` Add Tier 3 inspect charts

Goal:

- support taxon- or branch-level codon inspection

Scope:

- histogram-style codon distribution
- boxplot-style codon summary
- selected taxon, clade, or filtered subset only

Tests:

- inspect-state render
- inspect payload shape

Exit criteria:

- codon ratio spans all three viewer tiers

### `C11` Add discoverability and handoffs

Goal:

- make the codon viewer part of the browser, not an orphan route

Scope:

- browser home entry
- branch handoff from taxon detail
- optional handoffs from protein and repeat-call detail when context is valid

Exit criteria:

- codon ratio is reachable through the same browser pathways as length
