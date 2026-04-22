# Architecture

HomoRepeat is split into three Django apps:

- `apps/core`: home page, site shell, and healthcheck.
- `apps/browser`: read-only canonical biology browser and statistical views.
- `apps/imports`: staff-facing import queue and published-run ingestion.

## Data Layers

The browser stores two related data layers.

Raw import layer:

- `Genome`, `Sequence`, `Protein`, `RepeatCall`, `RepeatCallCodonUsage`
- per-run historical observations linked to `PipelineRun`
- used for provenance and import history

Canonical layer:

- `CanonicalGenome`, `CanonicalSequence`, `CanonicalProtein`
- `CanonicalRepeatCall`, `CanonicalRepeatCallCodonUsage`
- `CanonicalCodonCompositionSummary`
- `CanonicalCodonCompositionLengthSummary`

The canonical layer is the current-serving catalog. Canonical records keep
`latest_pipeline_run`, `latest_import_batch`, and `last_seen_at` so current
biology can be traced back to the import that last touched it.

Taxonomy:

- `Taxon`: NCBI-style taxonomy node.
- `TaxonClosure`: materialized ancestor/descendant closure table.

Statistical browser views group repeat calls through `TaxonClosure`, which lets
the same query summarize at phylum, class, order, family, genus, or species.

## Import Flow

The import path is:

1. Published pipeline artifacts are validated by
   `apps/imports/services/published_run/`.
2. `apps/imports/services/import_run/` writes the raw per-run tables.
3. `apps/browser/catalog/sync.py` rebuilds the current canonical catalog from
   the raw import.
4. Codon composition rollups are rebuilt from canonical codon-usage rows.
5. Normal browser requests read PostgreSQL/SQLite tables, not pipeline files.

The import boundary is intentionally file-based. Pipeline code owns computation;
the web app owns validation, provenance, canonicalization, browsing, and
statistical summaries.

## View Structure

List browsers are built on reusable class-based views:

- `BrowserListView`
- `CursorPaginatedListView`
- `VirtualScrollListView`

They support search, sorting, cursor pagination, and AJAX row fragments.

Statistical views are `TemplateView` subclasses under `apps/browser/views/stats/`.
They parse URL filters into `StatsFilterState`, build summary bundles through
`apps/browser/stats/queries.py`, serialize chart payloads through
`apps/browser/stats/payloads.py`, and render client-side charts.

## Stats Modules

- `filters.py`: validates request query parameters into `StatsFilterState`.
- `params.py`: allowed ranks and query parameter normalization.
- `queries.py`: filtered querysets, grouped aggregations, and bundle builders.
- `summaries.py`: pure Python reducers and statistical helper functions.
- `payloads.py`: JSON-ready chart payload builders.
- `bins.py`: shared 5-aa repeat-length bins.
- `ordering.py`: lineage-aware row ordering.
- `taxonomy_gutter.py`: cladogram payloads for chart side/bottom gutters.
- `codon_rollups.py`: current-catalog codon composition rollup rebuild.
- `codon_length_rollups.py`: current-catalog codon composition by length-bin
  rollup rebuild.

## Frontend Charts

The frontend uses plain JavaScript and ECharts; there is no build step.

- `static/js/stats-chart-shell.js`: shared chart helpers, zoom, wheel handling,
  taxonomy gutter attachment.
- `static/js/taxonomy-gutter.js`: SVG overlay cladogram aligned to ECharts
  category axes.
- `static/js/pairwise-overview.js`: reusable pairwise heatmap renderer,
  horizontal/vertical zoom, signed preference and distance scale controls.
- `static/js/repeat-length-explorer.js`: length overview, browse, and inspect
  charts.
- `static/js/repeat-codon-ratio-explorer.js`: codon composition pairwise and
  browse charts.
- `static/js/codon-composition-length-explorer.js`: codon composition by
  length-bin overview, browse panels, inspect layer, support traces, and
  pairwise trajectory similarity.

Taxonomy gutters align by taxon ID axis values. Chart labels may display taxon
names, but the axis category values must match `taxonomy_gutter.py` leaf
`axisValue` values.

## Production Boundary

The intended production split is:

- web repository: Django application, import UI, canonical browser, statistics
- pipeline repository: Nextflow workflow, scientific runtime, published artifact
  contract
- infrastructure repository: Kubernetes/PostgreSQL/object storage/secrets

Django is a control plane and browser. It should not implement Nextflow
scientific computation, require a Docker socket, or depend on workflow work
directories at request time.
