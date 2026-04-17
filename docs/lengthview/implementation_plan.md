# Length View Implementation Plan

## Purpose

This document turns:

- [pre-refactor-plan.md](/home/gibli/Documents/GitHub/homorepeat/docs/lengthview/pre-refactor-plan.md)
- [plan.md](/home/gibli/Documents/GitHub/homorepeat/docs/lengthview/plan.md)

into an execution sequence for implementing the first lineage-aware repeat
length explorer.

It is intentionally implementation-focused. It is not a product brainstorm.
It is also explicitly performance-focused: the finished view must remain fast
when summarizing millions of repeat-call matches.

## Sequencing Rules

- keep one Django app: `apps.browser`
- do the explorer-vs-stats structural split before adding the first stats page
- preserve `apps.browser.views` as the stable import surface throughout
- keep `apps/browser/views/filters.py` limited to browser-wide shared scope
  helpers
- introduce reusable stats filters once and reuse them across stats views
- prove the server-rendered summary/table view before adding ECharts
- add navigation and discoverability after the page semantics are correct
- do not introduce import-time summary tables or new browser models in this
  track
- treat performance as part of the implementation, not a later cleanup pass
- never ship or render unbounded raw match sets; only bounded aggregates should
  reach the page
- keep `q` and `branch_q` index-friendly in v1
- clamp visible-row controls like `top_n` to safe maximums
- validate hot grouped queries with real query plans before closing the work
- allow targeted indexes and short-TTL cache entries if real validation shows
  they materially improve the hot path

## Current Baseline

Verified branch facts:

- the project still has three Django apps at the framework boundary:
  - `apps.core`
  - `apps.browser`
  - `apps.imports`
- `apps.browser` is already internally modularized into packages for:
  - `models/`
  - `views/`
  - `catalog/`
- `apps/browser/urls.py` still imports URL-facing views from
  `apps.browser.views`
- browser-wide scope helpers already exist in `apps/browser/views/filters.py`
- explorer-domain canonical query/detail helpers still live under
  `apps/browser/views/` instead of a dedicated explorer-domain service package
- there is no `apps/browser/stats/` package yet
- there is no `apps/browser/views/stats/` package yet
- there is no chart integration yet
- the first length-view plan assumes a new route at `/browser/lengths/`

Current next slice:

- `1.1` create explorer-vs-stats view packages while preserving the current
  `apps.browser.views` import surface

## Performance Baseline

This feature is expected to operate over million-scale `CanonicalRepeatCall`
tables.

That means:

- the browser presents aggregates over large datasets, not raw result streams
- streaming is not the primary optimization for the interactive page
- the hot path is:
  - candidate taxon selection
  - bounded grouped summary computation
  - rendering only visible rows
- any feature choice that forces full-table substring scans or Python-side
  materialization of all matching lengths is out of bounds for v1

## Phase 1: Pre-Refactor Browser Ownership

### Slice 1.1: Split URL-facing views into explorer vs stats packages

Goal:

- create a stable internal ownership boundary before the first stats page lands

Scope:

- add `apps/browser/views/explorer/`
- add `apps/browser/views/stats/`
- move current explorer pages into `views/explorer/`
- keep `apps/browser/views/__init__.py` as the stable re-export surface
- keep `apps/browser/urls.py` importing from `apps.browser.views`

Required behavior:

- no route names change
- no existing browser page changes behavior
- outside callers do not need to import from nested packages directly

Exit criteria:

- current explorer views live under `views/explorer/`
- `apps.browser.views` still exports the same explorer classes as before
- current browser routes keep working unchanged

### Slice 1.2: Move explorer-domain query helpers out of generic view modules

Goal:

- stop treating explorer-specific canonical query assembly as generic browser
  infrastructure

Scope:

- create `apps/browser/explorer/`
- move canonical entity and genome helper logic into:
  - `apps/browser/explorer/canonical.py`
  - `apps/browser/explorer/accessions.py`
- keep only URL-facing view logic in the explorer view modules

Required behavior:

- explorer views import explorer-domain helpers from `apps.browser.explorer`
- shared browser infrastructure modules remain generic
- no explorer list/detail semantics change

Exit criteria:

- explorer-domain helper code no longer sits in generic `views/`
- current explorer tests still pass

### Slice 1.3: Add the reusable stats service layer

Goal:

- create the internal package that future stats views will build on

Scope:

- add `apps/browser/stats/`
- introduce:
  - `filters.py`
  - `queries.py`
  - `summaries.py`
  - `payloads.py`
  - `params.py`
- define a normalized filter contract such as `StatsFilterState`

Required behavior:

- browser-wide scope helpers stay in `apps/browser/views/filters.py`
- reusable stats-family filters live in `apps/browser/stats/filters.py`
- stats queries take normalized filter state, not raw request params
- normalized stats filters clamp visible-row bounds and expose stable cache-key
  serialization
- stats-layer search semantics stay index-friendly by default

Exit criteria:

- stats package exists and is importable
- shared stats filters are defined once
- the first stats page can be implemented without adding chart/query logic to
  generic explorer modules

## Phase 2: Build The Server-Rendered Length Explorer

### Slice 2.1: Add route, view shell, and normalized filter handling

Goal:

- put the first stats page on the new structure with a stable request contract

Scope:

- add `/browser/lengths/` to `apps/browser/urls.py`
- add the URL-facing class in `apps/browser/views/stats/lengths.py`
- re-export it from `apps/browser/views/__init__.py`
- implement normalized filter parsing through `apps/browser/stats/filters.py`

Required query params:

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

Required behavior:

- branch and `branch_q` semantics match the current browser model
- defaults are applied consistently through the normalized stats filter state
- invalid numeric inputs fail soft through empty/ignored parsing, matching the
  current browser style
- `q` stays exact-or-prefix in v1 rather than broad substring search
- `top_n` is clamped to a safe maximum such as `100`

Exit criteria:

- the route resolves
- the page renders with normalized stats filter state in context
- the filter contract is reusable by later stats views

### Slice 2.2: Add grouped taxon summary queries and HTML output

Goal:

- deliver the first useful length explorer without any chart dependency

Scope:

- grouped aggregation over `CanonicalRepeatCall`
- roll up repeat calls by ancestor taxon at the selected rank using
  `TaxonClosure`
- apply normalized stats filters before grouping
- render a plain HTML summary table
- render empty states and current-scope summary text

Required output per visible taxon row:

- taxon pk
- taxon name
- rank
- observation count
- min length
- q1
- median
- q3
- max length

Required behavior:

- broad default rank remains bounded and readable
- branch-scoped drill-down behaves correctly
- `top_n` and `min_count` bound the visible result set
- the page works meaningfully with JS disabled
- the template only receives aggregated visible rows, never raw repeat-call
  result sets

Exit criteria:

- table output is correct for broad and branch-scoped views
- empty states are explicit
- the page is already useful before chart wiring exists

### Slice 2.3: Harden the grouped query shape, indexes, and caching

Goal:

- make the first server-rendered explorer fast enough for million-scale data

Scope:

- keep grouped candidate selection bounded
- add query-plan review on representative broad and branch-scoped requests
- add targeted indexes where `EXPLAIN` shows the current index set is
  insufficient
- add short-TTL caching for repeated grouped summaries or chart payloads if the
  hot path is repeatedly reused
- compute quartiles only for visible taxa, using:
  - database-side percentile aggregates on PostgreSQL when visible groups are
    large
  - Python fallback for SQLite/tests and bounded small-group cases
- verify sorting and visible-row shaping
- ensure later stats views can reuse the same normalized filter flow

Required behavior:

- no query depends on giant live taxonomy dropdowns
- no broad `icontains` scans across large text fields
- broad unscoped requests remain bounded by defaults
- broad unscoped requests remain bounded by a hard `top_n` max
- no broad request materializes all matching lengths into Python
- queries do not parse raw request params directly in the lower layers

Exit criteria:

- grouped summaries stay correct under filter combinations
- hot query plans are explain-reviewed
- any necessary indexes or caches land before chart work proceeds
- query shape is acceptable for the first real validation pass

## Phase 3: Add ECharts To The Length Explorer

### Slice 3.1: Add page-level asset support and chart payload shaping

Goal:

- add chart integration without changing the server-rendered page model

Scope:

- add page asset blocks to `templates/base.html`
- add `static/js/repeat-length-explorer.js`
- add chart payload shaping in `apps/browser/stats/payloads.py`
- deliver payload through `json_script`

Required behavior:

- ECharts loads only on the length explorer page
- the chart uses the same server-side data as the HTML summary table
- no SPA-style fetch loop is required for v1
- only bounded visible-row payloads are sent to the client

Exit criteria:

- the page renders server-side and then enhances with ECharts
- chart payload and HTML table stay aligned

### Slice 3.2: Implement the ranked horizontal length chart

Goal:

- deliver the first actual visual browse surface for length exploration

Scope:

- one ranked horizontal chart
- one row per visible taxon
- row encoding:
  - min
  - q1
  - median
  - q3
  - max
- row labels include taxon and observation count

Required behavior:

- the chart remains readable at the default visible set
- broad views do not try to render hundreds of taxa at once
- visible rows match the summary table exactly

Exit criteria:

- chart renders correctly for broad and branch-scoped views
- chart is readable at the intended default bounds

### Slice 3.3: Add chart-driven drill-down and polish

Goal:

- make the chart an actual explorer surface rather than a passive graphic

Scope:

- clicking a chart row reloads the explorer with the clicked taxon as branch
- preserve relevant filter state across drill-down
- add visible result summary copy such as “showing 25 of 143 taxa”

Required behavior:

- drill-down semantics match the current taxon browser mental model
- the chart does not introduce hidden state beyond the querystring

Exit criteria:

- chart click drill-down works
- the page remains comprehensible without learning chart-specific controls

## Phase 4: Integrate The Explorer Into The Browser

### Slice 4.1: Add browser-home discoverability

Goal:

- make the first stats page reachable from the current catalog entry flow

Scope:

- add a new current-catalog navigation item on browser home
- describe the page as current-catalog exploration, not provenance reporting

Required behavior:

- the explorer is discoverable without knowing the route
- browser home copy stays consistent with the canonical-first architecture

Exit criteria:

- browser home links to the length explorer clearly

### Slice 4.2: Add branch-scoped handoff from taxon detail

Goal:

- make lineage browsing flow directly into the new stats page

Scope:

- add a branch-scoped CTA from taxon detail
- preserve `run` scope if present
- preserve taxon-driven lineage context

Required behavior:

- taxon detail -> length explorer feels like a natural branch continuation
- handoff uses the same branch semantics as the rest of the browser

Exit criteria:

- branch-scoped entry from taxon detail works and is clear

### Slice 4.3: Optional explorer handoffs

Goal:

- add small convenience links only if they improve real browsing flow

Scope:

- optionally add handoff links from repeat-call or protein explorer pages when
  the current scope already maps naturally into the length explorer

Out of scope:

- do not add broad cross-link sprawl just because a route exists

Exit criteria:

- any added handoff is clearly useful and semantically aligned

## Phase 5: Validate And Close Out

### Slice 5.1: Structural regression pass

Goal:

- confirm the pre-refactor did not break the current browser

Scope:

- run the focused browser suites
- verify import surfaces and current route wiring

Required checks:

- `apps.browser.views` still exports the current explorer classes
- current browser routes still resolve
- current explorer pages still behave the same

Exit criteria:

- the refactor is structurally safe

### Slice 5.2: Length-view functional test pass

Goal:

- confirm the new page behaves correctly on test fixtures

Scope:

- add `web_tests/test_browser_lengths.py`
- cover:
  - branch scope
  - `branch_q`
  - rank roll-up
  - method filter
  - residue filter
  - length range
  - `min_count`
  - `top_n`
  - empty states
  - chart payload to summary-table alignment

Exit criteria:

- the first stats page is covered enough to evolve safely

### Slice 5.3: Real-data validation

Goal:

- confirm the view is usable on actual imported data volume

Scope:

- validate one broad unscoped view
- validate one branch-scoped view
- validate one deeper drill-down path
- verify that visible row bounds and defaults keep the page readable

Required checks:

- broad taxonomy scope remains bounded and understandable
- branch-scoped drill-down is biologically meaningful
- chart and table stay aligned
- the page remains useful with hundreds or thousands of taxa in the database
- million-scale repeat-call volumes still produce an interactive bounded view
- hot queries use the intended indexes or cached grouped summaries where added
- no part of the page depends on streaming raw match sets to the browser

Exit criteria:

- the first length explorer is acceptable as the first serious stats view

## Explicit Non-Goals

Do not include these in this track:

- a separate Django app for stats
- new stats models or import-time summary tables
- raw vs merged mode split
- longest-repeat-per-protein toggles
- taxonomy ambiguity handling
- multi-panel stats dashboards
- beeswarm/scatter/histogram companion views in the initial track
- advanced provenance or batch analytics
- client-side fetch-driven filtering architecture
- streaming raw repeat-call rows to the interactive browser view
