# Development Guide

This guide is for contributors working on the HomoRepeat Django application.
It complements [Architecture](architecture.md), [Statistics](statistics.md), and
[Operations](operations.md).

## First Principles

- Preserve biological semantics before optimizing presentation.
- Keep raw import history separate from the canonical current-serving catalog.
- Prefer small, well-tested changes over broad rewrites.
- Treat chart payloads as contracts between Django and plain JavaScript.
- Keep old planning notes out of durable docs; add dated handoffs to
  `docs/journal/` when needed.

## Local Workflow

Install and migrate:

```bash
python3 manage.py migrate
```

Run tests:

```bash
python3 manage.py test web_tests
```

Start the local server:

```bash
python3 manage.py runserver 0.0.0.0:8000
```

Use the PostgreSQL-backed stack for import, rollup, or PostgreSQL SQL work:

```bash
docker compose up web worker postgres
docker compose exec web python manage.py test web_tests
```

SQLite is fine for many unit and view tests, but it does not exercise
PostgreSQL-specific raw SQL in the rollup rebuild paths.

## Code Organization

Use these entry points when changing behavior:

- data model: `apps/browser/models/`
- import validation: `apps/imports/services/published_run/`
- import write path: `apps/imports/services/import_run/`
- canonical sync: `apps/browser/catalog/sync.py`
- stats filters and query bundles: `apps/browser/stats/filters.py`,
  `apps/browser/stats/queries.py`
- pure summary math: `apps/browser/stats/summaries.py`
- chart payloads: `apps/browser/stats/payloads.py`
- stats views: `apps/browser/views/stats/`
- templates: `templates/browser/`
- browser chart JavaScript: `static/js/`

Keep query building, scientific reductions, payload serialization, and rendering
separate. That makes it possible to test statistical calculations without a
browser and to change chart behavior without changing biological definitions.

## Data Model Rules

Raw models are historical per-run observations. Canonical models are current
serving rows.

When changing imports:

- write raw rows first
- sync canonical rows from raw rows
- refresh derived rollups after canonical codon usage is replaced
- keep `latest_pipeline_run`, `latest_import_batch`, and `last_seen_at`
  meaningful

When changing taxonomy behavior:

- keep `TaxonClosure` as the source of ancestor grouping
- ensure branch filters use descendant IDs from the closure table
- keep grouped result rows lineage-ordered for chart readability

## Stats Development Rules

All public stats views should start from `StatsFilterState`. Do not parse query
parameters ad hoc in a view or payload builder.

Preferred flow:

```text
request
  -> build_stats_filter_state
  -> query/bundle builder in queries.py
  -> pure reducers in summaries.py, if needed
  -> payload builder in payloads.py
  -> TemplateView context
  -> json_script
  -> static/js renderer
```

When adding a statistic:

- document its biological meaning in `docs/statistics.md`
- add focused tests for the bundle or payload
- test empty data, one-taxon data, and multi-taxon data
- test branch-scoped and unscoped behavior if both paths exist
- check whether a precomputed rollup path and a live path must stay equivalent

## Rollup Safety

Rollups exist for common unfiltered views. They must match live aggregation
semantics.

When editing rollups:

- update PostgreSQL and Python rebuild paths together
- verify denominators count repeat calls, not incidental joined rows
- rebuild the table in the Compose PostgreSQL database
- compare at least one rollup row against live canonical codon usage
- run tests for both browser stats and the relevant page

Useful commands:

```bash
docker compose exec web python manage.py backfill_codon_composition_summaries
docker compose exec web python manage.py backfill_codon_composition_length_summaries
```

## Frontend Development Rules

The frontend is plain JavaScript plus ECharts. There is no bundler.

Before editing chart code, identify whether the change belongs in:

- `stats-chart-shell.js`: shared zoom/wheel/gutter helpers
- `pairwise-overview.js`: reusable pairwise matrix behavior
- `taxonomy-gutter.js`: SVG taxonomy overlay
- a page-specific file: page mounting, local tooltips, local chart options

Keep chart axes stable. Taxonomy gutter alignment depends on category axis
values matching taxon IDs from the gutter payload. Use formatters to show taxon
names rather than making names the axis values.

After frontend edits:

```bash
node --check static/js/<changed-file>.js
```

Manual browser checks matter for chart changes. Automated tests catch payload
contracts; they do not prove SVG/ECharts alignment.

## Testing Strategy

Use the narrowest meaningful test first:

- model/import changes: `web_tests.test_models`, `web_tests.test_import_published_run`,
  `web_tests.test_canonical_catalog`
- stats math and payloads: `web_tests.test_browser_stats`
- length page: `web_tests.test_browser_lengths`
- codon composition page: `web_tests.test_browser_codon_ratios`
- codon composition by length page:
  `web_tests.test_browser_codon_composition_lengths`

Run broader tests when changing shared filters, canonical sync, rollups, or
shared frontend contracts.

## Documentation Expectations

When a change alters scientific semantics, update `docs/statistics.md`.

When a change alters commands, operations, caches, or backfills, update
`docs/operations.md`.

When a change alters module boundaries, update `docs/architecture.md`.

For temporary implementation details, add a dated session note in
`docs/journal/` rather than creating a new long-lived planning folder.
