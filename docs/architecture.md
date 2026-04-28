# Architecture

HomoRepeat is split into three Django apps:

- `apps/core`: home page, site shell, and healthcheck.
- `apps/browser`: read-only canonical biology browser and statistical views.
- `apps/imports`: staff-facing import queue and published-run ingestion.

## Data Layers

The browser stores two related data layers.

Raw import layer:

- `Genome`, `Sequence`, `Protein`, `RepeatCall`, `RepeatCallCodonUsage`,
  `RepeatCallContext`
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

The primary row-level scientific browser surfaces are built from the canonical
repeat-call catalog:

- **Homorepeats**: compact repeat observations with organism, assembly,
  protein/gene, repeat class, repeat architecture pattern, length, purity,
  position, and method.
- **Codon Usage**: one row-level profile per repeat call's target residue,
  using canonical codon-usage rows to show coverage, count-derived codon
  percentages, codon counts, and dominant codon.

The older accession, genome, sequence, protein, and repeat-call list pages
remain supporting catalog/provenance views rather than the main scientific
entry point.

Taxonomy:

- `Taxon`: NCBI-style taxonomy node.
- `TaxonClosure`: materialized ancestor/descendant closure table.

Statistical browser views group repeat calls through `TaxonClosure`, which lets
the same query summarize at phylum, class, order, family, genus, or species.

## Import Flow

The import path is:

1. Published pipeline artifacts are validated by
   `apps/imports/services/published_run/`. The supported public contract is
   publish contract v2, identified by `publish_contract_version: 2` in
   `metadata/run_manifest.json`.
2. `apps/imports/services/import_run/` writes the raw per-run tables. The v2
   PostgreSQL path streams run-level TSVs through temporary tables and `COPY`,
   then inserts raw rows with SQL joins.
3. `apps/browser/catalog/sync.py` rebuilds the current canonical catalog from
   the raw import.
4. Codon composition rollups are rebuilt from canonical codon-usage rows.
5. Normal browser requests read PostgreSQL/SQLite tables, not pipeline files.

The import boundary is intentionally file-based. Pipeline code owns computation;
the web app owns validation, provenance, canonicalization, browsing, and
statistical summaries.

The v2 public contract is table-first. It imports `calls/repeat_calls.tsv`,
`calls/run_params.tsv`, run-level tables under `tables/`, summaries under
`summaries/`, and `metadata/run_manifest.json`. The web app no longer depends on
older public batch directories, finalized codon-usage fragments, or public FASTA
files for v2 imports. Full matched sequence and protein bodies come from
`matched_sequences.tsv.nucleotide_sequence` and
`matched_proteins.tsv.amino_acid_sequence`.

`tables/repeat_context.tsv` is stored in the raw layer as
`RepeatCallContext`. It is per-run provenance data linked one-to-one to the raw
`RepeatCall`; there is no canonical context table unless a future browser
surface requires current-serving flank context independent of run provenance.

## View Structure

List browsers are built on reusable class-based views:

- `BrowserListView`
- `CursorPaginatedListView`
- `VirtualScrollListView`

They support search, sorting, cursor pagination, and AJAX row fragments.

`HomorepeatListView` and `CodonUsageListView` reuse the canonical repeat-call
filtering, virtual-scroll pagination, and TSV export infrastructure. Their
default table columns are biology-first; fuller sequences and provenance fields
are exposed through row details and downloads.

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
