# Pre-Refactor Plan For Explorer vs Stats Split

## Summary

Do **not** create a new Django app for stats views.

Instead, do a small structural refactor inside `apps.browser` before building
the first length explorer. The project now clearly has two product families:

- the current canonical/entity browser and provenance explorer
- upcoming stats/visualization views

That split is enough to justify internal packages now. The goal is to make the
next 5 to 6 stats views land cleanly without turning `apps/browser/views` into
another flat mixed layer.

The refactor should:

- keep one Django app: `apps.browser`
- preserve `apps.browser.views` as the stable import surface for URL wiring
- split URL-facing views into `explorer` and `stats`
- introduce a dedicated `apps/browser/stats/` service package
- make reusable stats filters a first-class internal layer rather than keeping
  them as ad hoc request parsing inside each stats view
- move explorer-specific non-view query helpers out of generic shared modules
  where that separation is already clear
- make stats performance ownership explicit, because these views will summarize
  million-scale repeat-call tables and must stay fast by design

## 1. Refactor Goal

The refactor is about ownership and growth, not about changing behavior.

We need to make these boundaries explicit:

- **shared browser infrastructure**
  - generic list/pagination/filter/navigation utilities
- **explorer views**
  - the current entity/provenance browser
- **stats views**
  - chart-driven aggregate views like repeat length exploration
- **stats service layer**
  - reusable filter parsing, aggregation, summary statistics, and chart payload
    shaping
  - bounded query shaping, cache integration, and backend-specific fast paths
    when needed

Success criteria:

- current routes, route names, and templates keep working
- `apps.browser.views` remains the only import surface required by
  `apps/browser/urls.py`
- existing tests keep passing without semantic changes
- the first stats view can be added without stuffing aggregation and chart logic
  into generic browser modules

## 2. Target Package Layout

### Keep as the stable public surface

- `apps/browser/views/__init__.py`

This file should continue to re-export every URL-facing view class and any
shared helpers that outside callers already use.

### Keep as generic shared browser infrastructure

These are still generic enough to remain higher-level shared modules:

- `apps/browser/views/base.py`
- `apps/browser/views/pagination.py`
- `apps/browser/views/cursor.py`
- `apps/browser/views/filters.py`
- `apps/browser/views/navigation.py`
- `apps/browser/views/formatting.py`

These modules already behave like shared browser foundations and should not be
buried under either explorer or stats.

`apps/browser/views/filters.py` should remain limited to browser-wide shared
scope helpers such as:

- `run`
- `branch`
- `branch_q`
- shared branch-scope context and entity filter resolution

It should not become the home for stats-family-specific filter parsing.

### New explorer view package

- `apps/browser/views/explorer/__init__.py`
- `apps/browser/views/explorer/home.py`
- `apps/browser/views/explorer/runs.py`
- `apps/browser/views/explorer/taxonomy.py`
- `apps/browser/views/explorer/genomes.py`
- `apps/browser/views/explorer/sequences.py`
- `apps/browser/views/explorer/proteins.py`
- `apps/browser/views/explorer/repeat_calls.py`
- `apps/browser/views/explorer/accessions.py`
- `apps/browser/views/explorer/operations.py`

These files should own the existing DB/entity explorer views only.

### New stats view package

- `apps/browser/views/stats/__init__.py`
- `apps/browser/views/stats/lengths.py`

Future stats views should also live here.

### New explorer service package

Create a non-view package for explorer-specific query and detail-context logic:

- `apps/browser/explorer/__init__.py`
- `apps/browser/explorer/canonical.py`
- `apps/browser/explorer/accessions.py`

Initial ownership:

- `canonical.py`
  - own canonical genome/sequence/protein/repeat-call list and detail query
    helpers
- `accessions.py`
  - own accession-specific grouping and summary helpers

The purpose is to stop treating explorer-domain query assembly as generic
browser infrastructure.

### New stats service package

- `apps/browser/stats/__init__.py`
- `apps/browser/stats/filters.py`
- `apps/browser/stats/queries.py`
- `apps/browser/stats/summaries.py`
- `apps/browser/stats/payloads.py`
- `apps/browser/stats/params.py`

Initial ownership:

- `filters.py`
  - reusable stats-family filter parsing and normalized filter-state assembly
  - shared stats filters such as:
    - method
    - residue
    - length range
    - optional run passthrough
    - target search
    - rank
    - `top_n`
    - `min_count`
  - enforce bounded defaults and hard caps, especially for visible row counts
  - keep search semantics index-friendly rather than allowing broad substring
    scans by default
- `queries.py`
  - grouped aggregate queries over canonical models for stats pages
  - take normalized stats filter state rather than raw request params
  - own performance-sensitive query shaping, optional cache use, and
    production-only fast paths where justified
- `summaries.py`
  - quartiles, range summaries, visible-row shaping
- `payloads.py`
  - ECharts payload generation for bounded visible rows only
- `params.py`
  - low-level parameter/default/max-clamp helpers used by stats filters where
    useful

Recommended contract:

- define a small normalized filter object such as `StatsFilterState`
- stats views build this once from the request
- stats queries and payload builders consume that object rather than raw
  querystring values
- include stable cache-key-safe serialization and clamped bounds in the filter
  contract so later stats views inherit the same performance guardrails

This package is the reusable base for the upcoming stats views and keeps
chart-specific logic out of `views/filters.py` and other shared explorer code.

## 3. Dependency Rules

These rules should hold after the refactor:

- `apps/browser/views/base.py`, `pagination.py`, `cursor.py`, `filters.py`,
  `navigation.py`, and `formatting.py` are shared infrastructure
- explorer view modules may depend on:
  - shared browser infrastructure
  - `apps.browser.explorer`
- stats view modules may depend on:
  - shared browser infrastructure
  - `apps.browser.stats`
- stats view modules should not hand-parse repeated stats filters directly once
  the shared stats filter layer exists
- performance-sensitive query shaping, cache use, and database-specific fast
  paths must live in `apps.browser.stats`, not be scattered across views
- stats views should only request bounded visible summaries, never raw
  million-row result sets
- `apps.browser.explorer` must not depend on stats packages
- `apps.browser.stats` must not depend on explorer view modules
- `apps.browser.urls` should continue importing from `apps.browser.views`
  rather than from nested packages directly

## 4. Migration Strategy

Do this as a compatibility-preserving internal move, not a behavioral rewrite.

### Phase 1: Create package shells and preserve imports

Implement:

- add `views/explorer/` and `views/stats/`
- move current URL-facing explorer views into `views/explorer/`
- update `views/__init__.py` to re-export from the new packages
- keep `apps/browser/urls.py` unchanged except for any new stats routes later

Exit criteria:

- all existing browser routes still import from `apps.browser.views`
- no route names or templates change

### Phase 2: Move explorer-specific support code out of generic view space

Implement:

- create `apps/browser/explorer/`
- move canonical entity and accession helper logic into
  `apps/browser/explorer/canonical.py` and
  `apps/browser/explorer/accessions.py`
- update explorer view imports to use `apps.browser.explorer.*`

Exit criteria:

- generic shared view helpers are actually generic
- explorer-specific query/detail logic no longer sits in `views/`

### Phase 3: Add stats service package

Implement:

- create `apps/browser/stats/`
- add filter, parameter, query, summary, and payload modules
- do not add broad generic abstractions yet; only add the pieces needed for
  the first stats view family

Exit criteria:

- the first length view can be implemented entirely in:
  - `views/stats/lengths.py`
  - `apps/browser/stats/*`
- shared stats filters are defined once and reused through a normalized filter
  contract
- no chart-specific logic leaks into explorer modules

### Phase 4: Add the first stats route on the new structure

After the refactor lands:

- add `/browser/lengths/`
- implement the length explorer on the stats package structure

## 5. What Should Not Move

Do **not** broaden the refactor into unrelated layers.

Keep these untouched for now:

- `apps/browser/models/`
- `apps/browser/catalog/`
- `apps/browser/management/`
- `apps/imports/`
- route names for current explorer pages
- current template hierarchy under `templates/browser/` except where the new
  stats pages are added

This refactor is only about browser feature structure, not models/import
architecture.

## 6. Compatibility Surface

Preserve these contracts during refactor:

- `apps.browser.views`
- current browser URL names
- existing templates for explorer pages
- existing web test module names

Do **not** require call sites to import from:

- `apps.browser.views.explorer.*`
- `apps.browser.views.stats.*`

Those are internal ownership boundaries, not public surfaces.

## 7. Testing Plan

Before adding the first stats page, validate the refactor with the current
browser suite:

- `web_tests.test_browser_home_runs`
- `web_tests.test_browser_taxa_genomes`
- `web_tests.test_browser_sequences`
- `web_tests.test_browser_proteins`
- `web_tests.test_browser_repeat_calls`
- `web_tests.test_browser_accessions`
- `web_tests.test_browser_operations`

Also add focused import-surface checks where useful:

- `apps.browser.views` still exports the expected explorer classes
- `apps.browser.urls` still resolves current route wiring correctly
- stats filter normalization can be unit-tested independently from the first
  chart page
- performance-critical grouped queries should be explain-reviewed on real data
  before the first stats page is considered done

## 8. Explicit Non-Goals

Do not do these as part of the pre-refactor:

- create a separate Django app for stats views
- move models into a new app
- create generic “chart framework” abstractions before real duplication exists
- redesign current explorer templates
- change query parameter contracts for existing explorer pages
- mix the length-view implementation into the refactor patch

The pre-refactor should be small, structural, and low-risk.

## 9. Recommended Immediate Next Step

The next coding step should be:

1. create `apps/browser/views/explorer/` and move the existing explorer views
   there
2. update `apps/browser/views/__init__.py` to re-export them
3. create empty `apps/browser/stats/` and `apps/browser/views/stats/`
   packages
4. move canonical entity and accession helper logic into the
   `apps/browser/explorer/` service package

Once that is done, the first length view can be added on a stable
explorer-versus-stats boundary instead of landing into another flat layer.

## Assumptions

- `apps.browser` remains the single Django app for all browser-facing product
  features
- current shared modules like `filters.py`, `pagination.py`, and
  `navigation.py` are still generic enough to stay at the higher shared level
- future stats views will share aggregation and chart-payload logic, so a
  dedicated `apps/browser/stats/` package will pay for itself quickly
- future stats views will also share most filter semantics, so
  `apps/browser/stats/filters.py` and a normalized stats filter-state contract
  are worth introducing from the first stats page
- future stats views will need the same performance guardrails, so keeping
  bounds, cache usage, and query-shape rules inside `apps/browser/stats/` is
  preferable to ad hoc tuning in individual views
