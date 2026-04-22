# Table Downloads Implementation Plan

## Summary

Add synchronous, server-side TSV downloads for every browser table surface:
list pages, virtual-scroll tables, detail-page embedded tables, and statistical
view tables. Filters must be preserved where tables have filters. Tables
without independent filters must export their current detail-object or section
context. Pagination, cursors, virtual-scroll windows, and frontend-only row
sections must never limit the downloaded rows.

Implement this in small slices. Each slice should land with focused tests before
moving to the next slice.

## Delivery Rules

- Use existing page URLs with a `download` query parameter.
- Export from server-side querysets or stats bundles, never from DOM rows.
- Preserve semantic query params: search, sort, run, branch, accession, genome,
  sequence, protein, method, residue, length, purity, rank, min-count, top-N.
- Strip display-only params in generated links: `page`, `after`, `before`,
  `fragment`, and any virtual-scroll-only section cursor.
- Stream rows so large exports do not load the whole result into memory.
- Keep MVP format TSV-only.
- Add one visible `Download TSV` action per table section.

## Phase 1: Export Foundation

Build reusable backend and template primitives. This phase should not wire every
view; it creates the pattern and proves it on one small list table.

### Slice 1.1: TSV Helpers

Files:

- `apps/browser/exports.py`
- focused tests in `web_tests`

Work:

- add `clean_tsv_value(value) -> str`
- add `iter_tsv_rows(headers, rows)`
- add `stream_tsv_response(filename, headers, rows)`
- normalize tabs, carriage returns, and newlines inside values to spaces
- format `None` as an empty cell and booleans as `true`/`false`
- set `Content-Type: text/tab-separated-values; charset=utf-8`
- set attachment `Content-Disposition`

Validation:

- helper tests for empty rows, normalization, booleans, `None`, and headers
- response-header test

### Slice 1.2: List Export Mixin

Files:

- `apps/browser/exports.py`
- `apps/browser/views/base.py` or `apps/browser/views/pagination.py`

Work:

- add `BrowserTSVExportMixin`
- when `download=tsv`, call the view's full `get_queryset()`
- do not call pagination or virtual-scroll fragment rendering
- iterate querysets with `.iterator(chunk_size=...)`
- support explicit per-view column definitions
- support callable column accessors for flattened relationship/provenance fields

Validation:

- prove that `download=tsv&page=2`, `download=tsv&after=...`, and
  `download=tsv&fragment=virtual-scroll` export the full filtered queryset

### Slice 1.3: Download URL Helper

Files:

- `apps/browser/exports.py` or a browser view utility module
- `apps/browser/views/base.py`
- one shared template include under `templates/browser/includes/`

Work:

- generate `download_tsv_url` from the current path and current query params
- set `download=tsv`
- strip `page`, `after`, `before`, and `fragment`
- add a reusable button/include for table section headers

Validation:

- rendered link preserves filters and ordering
- rendered link removes pagination/cursor/fragment params

### Slice 1.4: First End-to-End Table

Files:

- `apps/browser/views/explorer/runs.py`
- `templates/browser/run_list.html`

Work:

- add run-list TSV columns
- add the `Download TSV` action to the run table header
- keep the existing virtual-scroll behavior unchanged

Validation:

- `RunListView` exports all filtered rows
- export honors search, status filter, and ordering
- export is not limited by page/cursor/fragment
- existing virtual-scroll tests still pass

## Phase 2: Top-Level Browser List Tables

Wire the reusable list-export pattern across every primary browser list table.
Each slice should add columns, a button, and tests for that group.

### Slice 2.1: Canonical Catalog Lists

Views:

- `AccessionsListView`
- `GenomeListView`
- `SequenceListView`

Templates:

- `accession_list.html`
- `genome_list.html`
- `sequence_list.html`

Columns:

- stable accession/genome/sequence identifiers and names
- taxon name/id where visible
- latest run where visible
- visible counts such as source runs, genomes, proteins, and repeat calls

Validation:

- run, branch, accession, genome, gene, search, and ordering filters are
  preserved where applicable
- cursor/virtual-scroll state does not limit rows

### Slice 2.2: Protein and Repeat-Call Lists

Views:

- `ProteinListView`
- `RepeatCallListView`

Templates:

- `protein_list.html`
- `repeatcall_list.html`

Columns:

- stable protein/call identifiers
- accession, genome/sequence/protein identifiers where visible
- gene symbol, taxon, run, method, residue, length, purity
- repeat-call coordinates and support fields already shown in the table

Validation:

- method, residue, length, purity, branch, run, genome, sequence, protein, and
  search filters are preserved
- exports stream the full queryset even for virtual-scroll pages without counts

### Slice 2.3: Taxonomy List

Views:

- `TaxonListView`

Templates:

- `taxon_list.html`

Columns:

- taxon id
- taxon name
- rank
- parent taxon id/name

Validation:

- run, branch, rank, search, and ordering filters are preserved
- export remains distinct when lineage joins are active

### Slice 2.4: Operational Lists

Views:

- `NormalizationWarningListView`
- `AccessionStatusListView`
- `AccessionCallCountListView`
- `DownloadManifestEntryListView`

Templates:

- `normalizationwarning_list.html`
- `accessionstatus_list.html`
- `accessioncallcount_list.html`
- `downloadmanifest_list.html`

Columns:

- visible run and batch provenance
- accession/source identifiers
- statuses, warning codes/scopes/messages, counts, paths, checksums, and sizes
  already visible in each table

Validation:

- run, batch, accession, status, method, residue, warning, package, search, and
  ordering filters are preserved where applicable

## Phase 3: Detail-Page Embedded Tables

Add exports for contextual tables that do not necessarily have independent
filters. These exports use the current detail object as their data scope.

### Slice 3.1: Detail Export Dispatcher

Files:

- `apps/browser/exports.py`
- shared detail-view mixin or local helper in browser views

Work:

- add a dispatcher for `download=<table-key>`
- use stable lowercase snake_case table keys
- return a consistent 404 or 400 for unknown table keys
- support header-only exports for empty contextual tables

Validation:

- unknown keys fail consistently
- valid keys export only rows belonging to the current detail object

### Slice 3.2: Genome and Accession Detail Tables

Pages:

- accession detail
- genome detail

Likely keys:

- `source_genomes`
- `source_sequences`
- `source_proteins`
- `source_repeat_calls`
- `warnings`

Validation:

- exports are scoped to the accession/genome being viewed
- current visible context and provenance columns are included

### Slice 3.3: Sequence, Protein, and Repeat-Call Detail Tables

Pages:

- sequence detail
- protein detail
- repeat-call detail

Likely keys:

- `source_sequences`
- `source_proteins`
- `source_repeat_calls`
- `repeat_calls`
- `codon_usage`
- `observations`

Validation:

- exports are scoped to the sequence/protein/repeat call being viewed
- source observation tables include enough provenance to trace rows back to
  run, accession, sequence, protein, method, residue, and coordinates

### Slice 3.4: Taxon and Run Detail Tables

Pages:

- taxon detail
- run detail

Likely keys:

- `linked_genomes`
- `method_residue_summary`
- `terminal_status_summary`
- `warning_summary`
- `batch_preview`
- `recent_import_batches`

Validation:

- taxon exports honor optional run context
- run exports are scoped to the selected run

## Phase 4: Statistical View Export Infrastructure

Add export dispatch for stats pages. This phase wires reusable infrastructure
and then each analysis view as its own slice.

### Slice 4.1: Stats Export Dispatcher

Files:

- `apps/browser/exports.py`
- `apps/browser/views/stats/*.py`

Work:

- add `StatsTSVExportMixin`
- dispatch on `download=<dataset-key>`
- reuse the same server-side bundles that feed visible charts and tables
- do not export chart JSON directly
- return headers only for valid but currently unavailable datasets

Validation:

- unknown dataset keys fail consistently
- active filters are preserved
- unavailable datasets return valid header-only TSV

### Slice 4.2: Repeat Length Exports

View:

- repeat length explorer

Dataset keys:

- `summary`
- `overview_typical`
- `overview_tail`
- `inspect`

Columns:

- `summary`: taxon id/name, rank, observations, species, min, q1, median, q3,
  max
- `overview_typical`: row taxon, column taxon, Wasserstein-1 distance
- `overview_tail`: row taxon, column taxon, tail-burden distance
- `inspect`: scope label, observations, median, q90, q95, max, CCDF length,
  CCDF survival fraction

Validation:

- exports match visible grouped taxa, overview, and inspect values
- inspect exports headers only when inspect scope is inactive

### Slice 4.3: Codon Composition Exports

View:

- codon composition explorer

Dataset keys:

- `summary`
- `overview`
- `browse`
- `inspect`

Columns:

- `summary`: taxon id/name, rank, observations, species, one column per visible
  synonymous codon share
- `overview`: row taxon, column taxon, metric, value, row support, column
  support
- `browse`: same content as `summary` unless the browse table diverges later
- `inspect`: scope label, observations, codon, share

Validation:

- species-weighted codon shares are preserved
- selected-residue semantics are preserved
- codon shares remain normalized to the selected residue's synonymous codon set

### Slice 4.4: Codon Composition by Length Exports

View:

- codon composition by length explorer

Dataset keys:

- `summary`
- `preference`
- `dominance`
- `shift`
- `similarity`
- `browse`
- `inspect`
- `comparison`

Columns:

- `summary` and `browse`: one row per taxon, length bin, and codon; include
  taxon, rank, length bin, observations, species, dominant codon, dominance
  margin, codon, and codon share
- `preference`: taxon, length bin, preference value, codon A/B shares, support
- `dominance`: taxon, length bin, dominant codon, dominance margin, codon share,
  support
- `shift`: taxon, previous/next length bins, shift value, previous/next support
- `similarity`: row taxon, column taxon, trajectory Jensen-Shannon divergence
- `inspect` and `comparison`: scope label, length bin, support, dominant codon,
  codon share, shift from previous

Validation:

- long-form codon-by-length rows parse cleanly
- unavailable modes return headers only
- pairwise matrices are long-form and symmetric where the underlying matrix is
  symmetric

## Phase 5: UI Integration and Consistency Pass

Bring the table actions together after backend exports exist.

### Slice 5.1: Shared Button Placement

Work:

- use one shared `Download TSV` include where possible
- place actions in table/section headers, not inside table rows
- keep no-JS behavior
- ensure buttons preserve filters and strip display-only state

Validation:

- every browser table section has a visible action
- labels are clear when a section has multiple datasets

### Slice 5.2: Stats Section Actions

Work:

- add section-level buttons for repeat lengths, codon composition, and codon
  composition by length
- for overview modes with multiple datasets, use explicit labels such as
  `Download Preference TSV` and `Download Similarity TSV`

Validation:

- each visible statistical table or matrix has the correct dataset key
- unavailable modes do not show awkward or broken actions

### Slice 5.3: Final Coverage Audit

Work:

- scan `templates/browser/` for every `<table`
- confirm each table is either wired to TSV or deliberately non-data/static
- document any intentionally excluded static table in the plan or follow-up

Validation:

- no browser data table is missed

## Phase 6: Final Test and Release Checks

### Slice 6.1: Automated Test Pass

Run focused browser tests after each slice, then run the broader browser suite
after phase completion.

Required automated coverage:

- TSV helper escaping and response headers
- list exports honor filters, ordering, and full-row export
- list exports ignore pagination, cursor, fragment, and virtual-scroll state
- detail table exports are scoped to current detail objects
- stat exports match source server-side bundles
- unavailable stat datasets return headers only

### Slice 6.2: Manual Export Checks

Manual checks:

- download from a paginated list while on page 2 and confirm page 1 rows are
  included
- download from a virtual-scroll table after scrolling and confirm export is not
  limited to mounted rows
- download from detail-page embedded tables and confirm unrelated objects are
  excluded
- download from each stats view with filters active
- open files in a spreadsheet and with
  `python csv.reader(..., delimiter="\t")`

## Acceptance Criteria

- every browser table section has a working TSV download
- current filters are preserved where filters exist
- contextual tables export rows belonging to their current detail object or
  section
- exported rows are not limited by pagination, cursor state, virtual-scroll
  section state, or frontend rendering
- statistical exports use the same server-side biological/statistical
  calculations as the visible analysis
- no JavaScript is required for downloading
