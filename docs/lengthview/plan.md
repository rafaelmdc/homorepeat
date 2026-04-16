# First Lineage-Aware Repeat Length Explorer

## Summary

Build a new standalone browser page for repeat length exploration that stays
inside the current Django + canonical browser architecture:

- route: `/browser/lengths/`
- source model: `CanonicalRepeatCall`
- lineage scope: existing `branch` / `branch_q` behavior backed by
  `TaxonClosure`
- structure: one `apps.browser` Django app, with stats views and stats service
  logic split into dedicated internal packages
- frontend: server-rendered page with one ECharts chart and a matching summary
  table
- product role: current-catalog exploration first, provenance secondary
- performance role: it must stay fast on datasets with millions of canonical
  repeat-call matches by presenting bounded aggregates, not raw rows

The first view should be simple, readable, and scalable. It should not try to
be a dashboard.

## 1. Current Architecture Fit

The repo already has the right backend substrate for this feature:

- canonical current-state entities are the primary browser model
- taxonomy is stored explicitly with `Taxon` and `TaxonClosure`
- branch scoping already works through `branch` and `branch_q`
- current browse pages are querystring-driven, server-rendered Django views
- canonical repeat-call filters already exist on the current browser path:
  method, residue, length, gene, accession, protein, and branch scope

The natural fit is:

- route kept in `apps/browser/urls.py`, still importing from
  `apps.browser.views`
- URL-facing view in `apps/browser/views/stats/lengths.py`, re-exported from
  `apps/browser/views/__init__.py`
- stats service modules under `apps/browser/stats/`, especially:
  - `filters.py`
  - `queries.py`
  - `summaries.py`
  - `payloads.py`
  - `params.py`
- new template: `templates/browser/repeat_length_explorer.html`
- new browser route: `/browser/lengths/`
- new navigation entry under current catalog, plus a branch-scoped entry from
  taxon detail

Current constraints to respect:

- the browser should be structurally split into explorer vs stats before the
  first stats page lands; see `docs/lengthview/pre-refactor-plan.md`
- browser-wide scope helpers should stay in `apps/browser/views/filters.py`,
  while reusable stats-family filters should live in `apps/browser/stats/`
- there is no chart stack yet
- frontend JS is intentionally light and page-scoped
- `base.html` does not currently expose page-specific asset blocks, so ECharts
  needs a small clean integration point
- browser metadata currently precomputes only raw counts plus method/residue
  facets, not length summaries
- the current canonical models already have useful single-column indexes on
  `CanonicalRepeatCall.method`, `repeat_residue`, `taxon`, and `length`, plus
  taxonomy-closure indexes; the stats path should start from those and only add
  evidence-backed composite indexes where real query plans require them

## 2. Recommended First View

### Primary chart for v1

Use a ranked horizontal taxon distribution chart:

- y-axis: taxa at a chosen display rank
- x-axis: repeat length
- one row per displayed taxon
- each row shows:
  - min
  - lower quartile
  - median
  - upper quartile
  - max
- row label also shows the observation count

This is conceptually boxplot-like, but it should be presented as a clean
ranked browse surface rather than a dense academic stats panel.

### Why this is the best first view

- works better than many-boxplot grids when there are many taxa
- preserves actual length-distribution shape instead of collapsing to one mean
- supports lineage drill-down naturally
- stays compatible with the project’s existing list-style browser language
- can be paired with a plain HTML summary table for no-JS fallback and easy
  testing

### Alternatives rejected for v1

- standard boxplot walls across hundreds of taxa: too dense and label-heavy
- per-taxon histograms: useful only for a few taxa, weak for broad comparison
- beeswarm/scatter views: visually noisy at biological scale
- small multiples: too space-hungry for the first view
- multi-panel dashboards: too much interface for the initial slice

## 3. Interaction Model

### Core browsing flow

1. Open the length explorer from browser home or a branch-scoped taxon page.
2. Set lineage scope using the existing branch search model.
3. Choose a display rank.
4. Apply a small set of biology filters.
5. Compare the visible taxa in the chart.
6. Click a taxon row to drill into that branch.

### Lineage-aware browsing

The view should reuse existing branch semantics:

- `branch=<taxon pk>` for exact selected branch
- `branch_q=<taxonomy id or name prefix>` for text-first branch discovery

Displayed rows should represent descendant repeat calls rolled up to the chosen
 ancestor rank within the active branch scope.

Examples:

- branch = Mammalia, rank = species
  - compare human, mouse, and other species under Mammalia
- branch = Mammalia, rank = order
  - compare Primates and other descendant orders

### Handling large taxon counts

Use all of these together:

- branch-first workflow
- explicit display-rank selector
- fixed `Top N` limit
- minimum observation count filter
- default sort by observation count descending
- vertical chart scrolling only for the already-limited visible set

### Drill-down behavior

- clicking a chart row should reload the same explorer with
  `branch=<clicked taxon pk>`
- the matching summary table row should also link to taxon detail
- do not add expansion panels or crossfilter brushing in v1

### Defaults

- without branch scope: default rank = `class`
- with branch scope: default rank = `species`
- default `top_n` = `25`

These defaults keep first render usable instead of dumping hundreds of species
rows into one page.

## 4. Filter Design

### Shared filter architecture

Filter reuse should be explicit from the first stats page:

- keep `apps/browser/views/filters.py` for browser-wide scope helpers only
  - `run`
  - `branch`
  - `branch_q`
  - shared branch-scope context
- add `apps/browser/stats/filters.py` for reusable stats-family filters
- define one normalized filter object such as `StatsFilterState`
- stats queries and payload builders should take normalized filter state, not
  raw request params

That separation lets future stats views share one filter contract without
polluting the explorer-side shared helpers.

### Must-have for v1

These should be visible in the main filter card:

- `branch_q`
- `rank`
- `q`
  - one target search field that matches:
    - `gene_symbol`
    - `protein_id`
    - `protein_name`
    - `accession`
  - keep this index-friendly in v1:
    - exact or prefix semantics only
    - no broad substring scans across multiple large text columns
- `method`
- `residue`
- `length_min`
- `length_max`
- `min_count`
- `top_n`
  - clamp to a safe hard maximum such as `100`

### Useful but secondary

- visible sort control beyond default count ordering
- optional `run`
- purity filters
- protein-length filters
- repeat-position filters

### Deferred

- multi-select taxon compare workflows
- companion histogram panel
- advanced provenance filters by batch/import batch
- saved views or pinned taxa
- taxonomy ambiguity handling
- longest-repeat-per-protein vs all-repeat toggles

The initial UX should remain one focused filter form, not an accordion-heavy
analytics surface.

## 5. Data Requirements

For each visible taxon row, the backend needs:

- taxon pk
- taxon name
- rank
- observation count
- min length
- q1
- median
- q3
- max length

Optional if cheap:

- mean length

### Query model

Use `CanonicalRepeatCall` as the base dataset.

Apply filters first:

- optional run scope if present
- branch scope
- `q`
- method
- residue
- length range

Then group repeat calls by ancestor taxon at the selected rank using
`TaxonClosure`.

The grouped query layer should consume normalized stats filter state from
`apps/browser/stats/filters.py`, not parse request params directly.

Candidate taxon selection should happen in the database and stay bounded before
quartile work begins.

### Performance requirement

This view is expected to summarize millions of `CanonicalRepeatCall` rows over
time. The browser must therefore present bounded aggregates, not raw matches.

Rules:

- never send raw repeat-call rows to the chart
- never build an unbounded Python-side list of all matching lengths
- keep visible taxa bounded with defaults and a hard `top_n` cap
- keep `q` and `branch_q` index-friendly:
  - exact taxon id or prefix search only
  - no broad `icontains` scans across large text fields in v1
- treat indexes, cache keys, and query-plan review as part of implementation,
  not later tuning

### Live query vs precomputed summaries

For v1, default to live aggregation. Do not add a new import-time summary table
yet.

Reasons:

- it fits the current architecture
- it avoids premature schema and import-pipeline work
- it keeps filtered semantics exact to the canonical repeat-call dataset
- the new `apps/browser/stats/` package can host stats-specific logic without
  requiring import-time materialization

But performance is still a feature requirement, so the first implementation is
allowed to add:

- short-TTL caching of grouped visible-row summaries or chart payloads keyed by
  normalized filter state for repeated hot scopes
- targeted database indexes if `EXPLAIN` on real queries shows the current
  single-column indexes are not enough

### Quartile strategy

Do this in two stages:

1. use DB aggregation to identify candidate display taxa and counts
2. compute quartiles only for the visible grouped taxa, using:
   - DB-side percentile aggregates on PostgreSQL in production when the visible
     groups are large
   - a Python fallback for SQLite, tests, and bounded small-group cases

This keeps the first implementation:

- portable across SQLite and PostgreSQL
- bounded by `Top N`
- fast enough to avoid pulling millions of lengths into Python on real data

### Performance concerns

Main risk:

- grouping by ancestor rank through `TaxonClosure` can get expensive on broad
  unscoped queries

Mitigations:

- broad default rank when unscoped
- explicit `Top N`
- explicit `min_count`
- only compute quartiles for visible taxa
- keep branch search text-first instead of giant dropdowns
- keep `q` search exact-or-prefix only in v1
- review query plans on representative broad and branch-scoped requests
- evaluate targeted composite indexes only after `EXPLAIN`; likely candidates
  are the hot stats predicate combinations on `CanonicalRepeatCall`, and a
  standalone `CanonicalProtein.protein_id` index if protein-id search is common
- cache repeated grouped summaries for common scopes if real validation shows
  repeated expensive broad requests

Streaming is not the primary optimization for the interactive page. If the page
is fast, there should be little to stream because only bounded summary rows
reach the client. Streaming is more relevant later for export endpoints, not
for the first browser view.

If real usage shows this is still too slow, revisit with a summary layer later.
Do not start there.

## 6. Frontend Integration

### ECharts integration approach

Use ECharts only on this page.

Implementation shape:

- add page asset blocks such as `extra_head` and `extra_scripts` to
  `templates/base.html`
- load ECharts only from the length explorer template
- add one page-specific JS file, e.g.
  `static/js/repeat-length-explorer.js`
- pass chart payload through `json_script`

This stays aligned with the current repo style:

- server-rendered first
- no SPA rewrite
- querystring remains the page-state contract
- JS enhances an already meaningful HTML page

### Page structure

1. landing band
   - title
   - current lineage scope summary
   - one short explanation of the row encoding
2. filter card
   - minimal, same styling language as current browser pages
3. chart card
   - ECharts visualization
   - visible result summary
   - empty state when no taxa match
4. summary table
   - same visible taxa rows
   - links for drill-down

### UI rules

- one chart only
- no side panel in v1
- no chart gallery
- keep labels short
- counts should live in row labels or row annotations, not a separate panel
- keep the chart payload small and bounded to the visible row set
- keep loading, empty, and overly narrow-filter states explicit and calm

## 7. Incremental Implementation Plan

### Phase 0: Pre-refactor for explorer vs stats ownership

Implement the structural split described in
`docs/lengthview/pre-refactor-plan.md`:

- create `apps/browser/views/explorer/` and move current explorer views there
- create `apps/browser/views/stats/`
- create `apps/browser/stats/`
- preserve `apps.browser.views` as the stable re-export surface
- move current explorer-specific canonical query helpers out of generic
  `views/` modules and into an explorer-domain service package

Acceptance:

- existing routes still work unchanged
- existing browser tests still pass
- the first stats page can land without adding chart logic to generic explorer
  modules

### Phase 1: Stats shell and server-rendered summaries

Implement:

- route `/browser/lengths/`
- new stats view and template
- reusable stats filter parsing plus normalized filter state in
  `apps/browser/stats/filters.py`
- stats parameter parsing, grouped repeat-length queries, and summary helpers in
  `apps/browser/stats/`
- query params:
  - `branch`
  - `branch_q`
  - `rank`
  - `q`
  - `method`
  - `residue`
  - `length_min`
  - `length_max`
  - `min_count`
  - `top_n`
  - optional `run`
- plain HTML summary table with grouped taxon statistics
- clear empty states

Acceptance:

- page works without JS
- branch scope and rank roll-up behave correctly
- summary rows and links are correct
- shared stats filters are defined once and can be reused by later stats views

### Phase 2: ECharts rendering and drill-down polish

Implement:

- base template asset blocks
- page-specific chart JS
- chart payload from the same server-side data as the summary table
- click-to-drill into selected taxon branch
- visible result summary such as “showing 25 of 143 taxa”

Acceptance:

- chart matches the table data exactly
- chart remains readable at 25 to 50 rows
- drill-down preserves relevant filter state

### Phase 3: Navigation integration and UX cleanup

Implement:

- browser home entry for the explorer
- taxon-detail CTA into branch-scoped length exploration
- optional handoff link from repeat-call list later
- small copy and empty-state refinements

Acceptance:

- the explorer is discoverable from current browser flows
- branch exploration feels like an extension of the existing taxon browser

## 8. Explicit Non-Goals

Do not do these in the first implementation:

- raw vs merged mode split
- longest-repeat vs all-repeats toggle
- taxonomy ambiguity or resolved-taxonomy handling
- multi-panel analytics dashboard
- beeswarm/scatter detail mode
- summary-table persistence or import-time analytics schema
- advanced provenance/batch analytics
- client-side async filtering architecture
- streaming raw repeat-call rows to the browser

## 9. Recommended Next Implementation Target

The next coding step should be:

Complete the explorer-vs-stats pre-refactor first, then add the standalone
`/browser/lengths/` explorer on that structure.

Concrete first slice:

- create `apps/browser/views/explorer/` and `apps/browser/views/stats/`
- preserve `apps.browser.views` re-exports
- create `apps/browser/stats/`
- move explorer-specific canonical query helpers out of generic `views/`
  modules

Then the first feature slice is:

- add the `/browser/lengths/` route and stats view
- add reusable stats filters and normalized filter-state handling
- support `branch_q`, `rank`, `q`, `method`, `residue`, `length_min`,
  `length_max`, `min_count`, and `top_n`
- render a grouped summary table with count and quartile statistics
- add links from browser home and taxon detail

Only after that should ECharts be layered on top of the same server-side data.

That order proves:

- the grouping semantics
- the filter contract
- the drill-down model
- the performance profile

before chart wiring adds another variable.
