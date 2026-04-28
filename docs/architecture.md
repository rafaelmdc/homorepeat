# Architecture

PAARTA is a Django application split into three apps:

- `apps/core` — home page, site shell, and healthcheck
- `apps/browser` — read-only canonical biology browser and statistical views
- `apps/imports` — staff-facing import queue and published-run ingestion

## Data Model

The browser stores two related layers.

**Raw import layer** (`Genome`, `Sequence`, `Protein`, `RepeatCall`, `RepeatCallCodonUsage`, `RepeatCallContext`) — per-run historical observations linked to `PipelineRun`. Used for provenance and import history.

**Canonical layer** (`CanonicalGenome`, `CanonicalSequence`, `CanonicalProtein`, `CanonicalRepeatCall`, `CanonicalRepeatCallCodonUsage`, `CanonicalCodonCompositionSummary`, `CanonicalCodonCompositionLengthSummary`) — current-serving catalog. Each canonical record carries `latest_pipeline_run`, `latest_import_batch`, and `last_seen_at` pointers back to the import that last touched it.

The primary scientific browser surfaces are built from the canonical repeat-call catalog:

- **Homorepeats** — repeat observations with organism, assembly, protein/gene, repeat class, architecture pattern, length, purity, position, and method.
- **Codon Usage** — one row per repeat call's target residue, showing coverage, codon percentages, counts, and dominant codon.

**Taxonomy** — `Taxon` stores the NCBI-style taxonomy tree. `TaxonClosure` is a materialised ancestor/descendant table that lets statistical views group repeat calls at any rank (phylum through species) with a single join.

## Import Flow

PAARTA ingests PAASTA (Poly-Amino Acid Sequence Tract Analyzer) — PAASTA runs the pipeline; PAARTA imports what it publishes.

1. `apps/imports/services/published_run/` validates the published PAASTA artifacts. Supported format: publish contract v2 (`publish_contract_version: 2` in `metadata/run_manifest.json`).
2. `apps/imports/services/import_run/` writes raw per-run tables. The PostgreSQL path streams TSVs into temporary tables via `COPY`, then inserts raw rows with SQL joins.
3. `apps/browser/catalog/sync.py` rebuilds the canonical catalog from the raw import.
4. Codon composition rollups are rebuilt from canonical codon-usage rows.
5. Normal browser requests read from the database — not from pipeline files.

## View Structure

List browsers use a class-based view hierarchy:

- `BrowserListView` — base filtering and column config
- `CursorPaginatedListView` — cursor-based pagination
- `VirtualScrollListView` — AJAX fragment loading for virtual scroll

They support `?q=` search, `?order_by=`, cursor tokens (`?after=`/`?before=`), and `?fragment=virtual-scroll` for XHR row reload.

Statistical views are `TemplateView` subclasses under `apps/browser/views/stats/`. They parse URL params into `StatsFilterState`, build summary bundles via `apps/browser/stats/queries.py`, serialise chart payloads via `apps/browser/stats/payloads.py`, and pass JSON blobs to client-side chart renderers.

## Stats Modules

| Module | Role |
|--------|------|
| `filters.py` | Validates request params into `StatsFilterState` |
| `params.py` | Allowed ranks and param normalisation |
| `queries.py` | Filtered querysets and grouped aggregations |
| `summaries.py` | Pure Python reducers and statistical helpers |
| `payloads.py` | JSON-ready chart payload builders |
| `bins.py` | Shared 5-aa repeat-length bins |
| `ordering.py` | Lineage-aware row ordering |
| `taxonomy_gutter.py` | Cladogram payloads for chart side/bottom gutters |
| `codon_rollups.py` | Canonical codon composition rollup rebuild |
| `codon_length_rollups.py` | Canonical codon composition by length-bin rollup |

## Frontend

The frontend uses plain JavaScript and ECharts with no build step.

| File | Role |
|------|------|
| `stats-chart-shell.js` | Shared chart helpers, zoom, wheel handling, gutter attachment |
| `taxonomy-gutter.js` | SVG overlay cladogram aligned to ECharts category axes |
| `pairwise-overview.js` | Reusable pairwise heatmap renderer |
| `repeat-length-explorer.js` | Length overview, browse, and inspect charts |
| `repeat-codon-ratio-explorer.js` | Codon composition pairwise and browse charts |
| `codon-composition-length-explorer.js` | Codon composition by length-bin overview, browse, inspect, and pairwise trajectory |

Taxonomy gutters align by taxon ID axis values. Chart labels may show taxon names, but axis category values must match `taxonomy_gutter.py` leaf `axisValue` values.

## Celery Workers

Background work runs via Celery with Redis as the broker.

| Service | Queue | Purpose |
|---------|-------|---------|
| `celery-import-worker` | `imports` | Run ingestion jobs |
| `celery-graph-worker` | `payload_graph` | Stats bundle pre-warming after import |
| `celery-download-worker` | `downloads` | Download artifact generation |
| `celery-beat` | — | Periodic task scheduler |
