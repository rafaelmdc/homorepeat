# Development Guide

## Local Workflow

Start the Compose stack (handles migrations automatically):

```bash
docker compose up --build   # first run
docker compose up           # subsequent runs
```

Run tests inside the stack:

```bash
docker compose exec web python manage.py test web_tests
```

SQLite works for most unit and view tests but does not exercise the PostgreSQL-specific `COPY` staging path or raw SQL rollup rebuilds. Use the Compose stack for import, rollup, or PostgreSQL SQL work.

## Code Organisation

| Concern | Location |
|---------|----------|
| Data model | `apps/browser/models/` |
| Import validation | `apps/imports/services/published_run/` |
| Import write path | `apps/imports/services/import_run/` |
| Canonical sync | `apps/browser/catalog/sync.py` |
| Stats filters and query bundles | `apps/browser/stats/filters.py`, `apps/browser/stats/queries.py` |
| Pure summary math | `apps/browser/stats/summaries.py` |
| Chart payloads | `apps/browser/stats/payloads.py` |
| Stats views | `apps/browser/views/stats/` |
| Templates | `templates/browser/` |
| Chart JavaScript | `static/js/` |

Keep query building, scientific reductions, payload serialisation, and rendering separate. This allows statistical calculations to be tested without a browser and chart behaviour to change without touching biological definitions.

## Data Model Rules

Raw models are per-run historical observations. Canonical models are current-serving rows.

When changing imports:

- write raw rows first
- sync canonical rows from raw rows
- refresh derived rollups after canonical codon usage is replaced
- keep `latest_pipeline_run`, `latest_import_batch`, and `last_seen_at` meaningful

When changing taxonomy behaviour:

- keep `TaxonClosure` as the source of ancestor grouping
- ensure branch filters use descendant IDs from the closure table
- keep grouped result rows lineage-ordered for chart readability

## Stats Development

All stats views must start from `StatsFilterState`. Do not parse query parameters ad hoc in a view or payload builder.

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
- test branch-scoped and unscoped behaviour if both paths exist
- check whether a precomputed rollup path and a live path must stay equivalent

## Rollup Safety

Rollups exist for common unfiltered views and must match live aggregation semantics.

When editing rollups:

- update PostgreSQL and Python rebuild paths together
- verify denominators count repeat calls, not incidental joined rows
- rebuild the table in the Compose PostgreSQL database
- compare at least one rollup row against live canonical codon usage

```bash
docker compose exec web python manage.py backfill_codon_composition_summaries
docker compose exec web python manage.py backfill_codon_composition_length_summaries
```

## Frontend Development

The frontend is plain JavaScript plus ECharts with no bundler.

Before editing chart code, identify which file owns the change:

- `stats-chart-shell.js` — shared zoom/wheel/gutter helpers
- `pairwise-overview.js` — reusable pairwise matrix behaviour
- `taxonomy-gutter.js` — SVG taxonomy overlay
- page-specific file — page mounting, local tooltips, local chart options

Keep chart axes stable. Taxonomy gutter alignment depends on category axis values matching taxon IDs from the gutter payload. Use formatters to display taxon names rather than making names the axis values.

After frontend edits:

```bash
node --check static/js/<changed-file>.js
```

Automated tests catch payload contracts. Manual browser checks are required for SVG/ECharts alignment.

## Testing Strategy

Use the narrowest meaningful test first:

| Change | Test module |
|--------|------------|
| Model / import | `web_tests.test_models`, `web_tests.test_import_published_run`, `web_tests.test_canonical_catalog` |
| Stats math and payloads | `web_tests.test_browser_stats` |
| Length page | `web_tests.test_browser_lengths` |
| Codon composition page | `web_tests.test_browser_codon_ratios` |
| Codon composition by length | `web_tests.test_browser_codon_composition_lengths` |

Run broader tests when changing shared filters, canonical sync, rollups, or shared frontend contracts.

## Documentation

When a change alters scientific semantics, update `docs/statistics.md`.

When a change alters commands, operations, caches, or backfills, update `docs/operations.md`.

When a change alters module boundaries, update `docs/architecture.md`.

For temporary working notes, add a dated entry in `docs/journal/` rather than creating a new long-lived planning folder.
