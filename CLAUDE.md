# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Migrate database (SQLite by default, no env vars needed)
python3 manage.py migrate

# Run all tests
python3 manage.py test web_tests

# Run a single test module
python3 manage.py test web_tests.test_browser_lengths

# Start dev server
python3 manage.py runserver 0.0.0.0:8000

# Import a published pipeline run
python3 manage.py import_run --publish-root /absolute/path/to/<run>/publish
```

Docker Compose stack (PostgreSQL-backed):
```bash
docker compose up web worker postgres
docker compose exec web python manage.py import_run --next-pending
```

Set `HOMOREPEAT_RUNS_ROOT` to a directory of run folders for the import UI to auto-detect them. Without database env vars, Django falls back to `db.sqlite3`.

## Architecture

**Django apps:**
- `apps/core/` — home page, site shell, healthcheck
- `apps/browser/` — read-only biology browser; the main product surface
- `apps/imports/` — staff-facing run ingestion (queue + worker)

**Data model (two layers):**

Raw import layer: `Genome`, `Sequence`, `Protein`, `RepeatCall`, `RepeatCallCodonUsage` — per-run historical observations linked to `PipelineRun`.

Canonical layer: `CanonicalGenome`, `CanonicalSequence`, `CanonicalProtein`, `CanonicalRepeatCall`, `CanonicalRepeatCallCodonUsage` — current-serving catalog that survives across runs. Each canonical record carries `latest_pipeline_run` and `latest_import_batch` FK pointers.

Taxonomy: `Taxon` (NCBI taxon tree) + `TaxonClosure` (materialised closure table for ancestor queries at arbitrary depth). Explorer views join against this closure to group repeat calls by rank.

**Browser view hierarchy (`apps/browser/views/`):**

```
BrowserListView (base.py)
  └─ CursorPaginatedListView (pagination.py)  — cursor-based pagination
       └─ VirtualScrollListView (pagination.py) — AJAX fragment loading
```

List views expose `?order_by=`, `?q=`, `?after=`/`?before=` (cursor tokens), `?page=`, and `?fragment=virtual-scroll` (XHR row reload). Cursor tokens are base64-encoded JSON position values.

Explorer views (`views/stats/`) are `TemplateView` subclasses — not list views. They compute aggregated payloads via `apps/browser/stats/` and pass them as JSON blobs to the template for the client-side charts.

**Stats pipeline (`apps/browser/stats/`):**

- `filters.py` / `params.py` — parse and validate URL query params into a `StatsFilterState` dataclass (rank, residue, method, length range, min_count, top_n, branch scope)
- `queries.py` — build filtered `CanonicalRepeatCall` querysets and aggregate by taxonomy rank
- `summaries.py` — reduce group rows to summary dicts
- `payloads.py` — serialise summaries to JSON-ready chart payload dicts
- `taxonomy_gutter.py` — build the cladogram payload (cached) for the side-gutter canvas widget
- `aggregates.py` / `bins.py` / `ordering.py` — helpers

**Frontend (`static/js/`):**

- `repeat-length-explorer.js` — D3-based heatmap for the length explorer
- `repeat-codon-ratio-explorer.js` — D3-based heatmap for the codon-ratio explorer
- `taxonomy-gutter.js` — canvas-based cladogram rendered left of both heatmaps; reads a JSON payload embedded in the page by id and draws a labelled phylogenetic tree with optional bottom-tree mode
- `site.js` — shared site utilities

The JS files are plain vanilla bundles (no build step). Edit and reload.

**Import flow (`apps/imports/`):**

The `import_run` management command reads a published pipeline run directory (`publish/`) and writes into both the raw and canonical layers inside a transaction. `apps/imports/services/published_run/` and `apps/imports/services/import_run/` contain the ingestion logic.

## Key conventions

- All canonical models have `last_seen_at` (not auto-updated — set explicitly on import) and point back to the `PipelineRun` and `ImportBatch` that last touched them.
- Explorer view filter params are validated/clamped server-side before reaching the DB; invalid values fall back to defaults, never raise.
- Taxonomy gutter payloads are cached by a hash of the visible taxon ID list + filter state; cache version is a constant in `taxonomy_gutter.py` — bump it when the payload shape changes.
- `TaxonClosure` must be rebuilt whenever the taxon tree changes (the import command handles this).
