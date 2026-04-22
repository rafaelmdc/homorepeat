# Table Downloads Implementation Plan

## Summary

Add reusable server-side TSV downloads for every browser table surface,
including list pages, detail-page embedded tables, and statistical browser
datasets. Use existing page URLs with `download` query parameters, preserve
current filters where they exist, preserve table context where filters do not
exist, and ignore pagination/virtual-scroll state. Keep the MVP synchronous and
TSV-only.

## Phase 1: Reusable TSV Core

Add a small backend export module under `apps/browser/exports.py` or
`apps/browser/views/exports.py`.

Required helpers:

- `clean_tsv_value(value) -> str`
  - `None` -> `""`
  - booleans -> `"true"` / `"false"`
  - all other values -> `str(value)`
  - replace `\t`, `\r`, and `\n` with a single space
- `iter_tsv_rows(headers, rows)`
  - yields UTF-8 text rows
  - first row is headers
  - every row has the same number of cells as headers
- `stream_tsv_response(filename, headers, rows)`
  - returns `StreamingHttpResponse`
  - content type `text/tab-separated-values; charset=utf-8`
  - sets attachment `Content-Disposition`

Testing:

- header-only export for empty rows
- tab/newline normalization
- `None` and boolean formatting
- response headers and filename

## Phase 2: List Page Exports

Add `BrowserTSVExportMixin` for `BrowserListView` descendants.

Mixin behavior:

- if `request.GET["download"] != "tsv"`, fall through to normal page rendering
- if `download=tsv`, call `get_queryset()` and export the full filtered,
  searched, ordered queryset
- do not paginate
- ignore `page`, `after`, `before`, and `fragment` in generated download links
- use explicit per-view column definitions

Suggested mixin interface:

```python
class BrowserTSVExportMixin:
    tsv_filename_slug = ""
    tsv_columns = ()

    def get_tsv_columns(self):
        return self.tsv_columns

    def get_tsv_filename(self):
        return f"homorepeat_{self.tsv_filename_slug}.tsv"

    def get_tsv_queryset(self):
        return self.get_queryset()
```

Column definition shape:

```python
("Column header", lambda obj: obj.field)
```

or a tiny dataclass if preferred:

```python
TSVColumn("Column header", "field.path")
```

The implementation must support callables because several list pages expose
linked/provenance fields that are easier to flatten explicitly.

List pages to wire:

- `RunListView`
- `AccessionsListView`
- `GenomeListView`
- `SequenceListView`
- `ProteinListView`
- `RepeatCallListView`
- `TaxonListView`
- `NormalizationWarningListView`
- `AccessionStatusListView`
- `AccessionCallCountListView`
- `DownloadManifestEntryListView`

Minimum columns:

- include stable IDs/accessions/names shown in the table
- include run/batch/provenance fields where already visible
- include counts and statuses already visible
- avoid HTML-only action columns

Testing:

- each representative list type exports TSV
- filters/search are honored
- ordering is honored
- pagination does not restrict export rows
- virtual-scroll `fragment` is ignored for export

## Phase 3: Download Link Generation

Add a reusable context helper for download links.

For list pages:

- `download_tsv_url` should be current path plus current query params
- set `download=tsv`
- remove `page`, `after`, `before`, and `fragment`

Add a `Download TSV` button near each primary table heading.

Suggested template placement:

- in the section header area beside filter summary/count text
- use `btn btn-outline-secondary`
- no JavaScript required

Testing:

- rendered list pages contain a download link
- link preserves current filters
- link excludes pagination/cursor params

## Phase 4: Detail and Embedded Table Exports

Add a small dispatcher for detail views with embedded table sections.

Behavior:

- if `download` is absent, render normally
- if `download=<table-key>` is present, export the matching table section
- use the same object context as the visible detail page
- preserve any section-specific filters if a detail table already has them
- do not paginate embedded table exports
- unknown table keys return the same HTTP 404 or 400 used by stat exports

Suggested interface:

```python
class DetailTableTSVExportMixin:
    tsv_table_exporters = {}

    def dispatch(self, request, *args, **kwargs):
        table_key = request.GET.get("download", "").strip()
        if table_key:
            return self.render_table_tsv_export(table_key)
        return super().dispatch(request, *args, **kwargs)
```

Table-key naming:

- use stable lowercase snake_case names
- match the section meaning, not the model class when that would be less clear
- examples: `sequences`, `proteins`, `repeat_calls`, `warnings`, `batches`,
  `source_calls`, `provenance`

Detail pages to inspect and wire where table sections exist:

- accession detail
- genome detail
- sequence detail
- protein detail
- repeat-call detail
- taxon detail
- run detail

Minimum columns:

- include the stable identifiers and names shown in the table
- include relationship/provenance columns needed to understand why the row
  appears in that detail context
- avoid HTML-only action columns

Testing:

- each wired detail table exports TSV
- exports are scoped to the current detail object
- empty related tables return headers only
- generated links use explicit table keys

## Phase 5: Statistical View Export Dispatcher

Add a reusable pattern for stats `TemplateView` classes.

Behavior:

- if `download` is absent, render normally
- if `download` is present, dispatch to a dataset-specific export method
- unknown dataset keys return HTTP 404 or 400; choose one and use consistently
- export methods reuse the same bundles already used for visible tables/charts

Suggested interface:

```python
class StatsTSVExportMixin:
    tsv_exporters = {}

    def dispatch(self, request, *args, **kwargs):
        dataset = request.GET.get("download", "").strip()
        if dataset:
            return self.render_tsv_export(dataset)
        return super().dispatch(request, *args, **kwargs)
```

Use explicit exporter methods instead of introspecting JSON payloads. Payloads
are optimized for charting; exports should be stable analysis tables.

## Phase 6: Repeat Length Exports

Add dataset keys:

- `summary`
- `overview_typical`
- `overview_tail`
- `inspect`

`summary` columns:

- taxon_id
- taxon_name
- rank
- observations
- species
- min_length
- q1
- median
- q3
- max_length

`overview_typical` columns:

- row_taxon_id
- row_taxon_name
- column_taxon_id
- column_taxon_name
- wasserstein1_distance

`overview_tail` columns:

- row_taxon_id
- row_taxon_name
- column_taxon_id
- column_taxon_name
- tail_burden_distance

`inspect` columns:

- scope_label
- observations
- median
- q90
- q95
- max
- ccdf_length
- ccdf_survival_fraction

If inspect scope is inactive or empty, export headers only.

## Phase 7: Codon Composition Exports

Add dataset keys:

- `summary`
- `overview`
- `browse`
- `inspect`

`summary` columns:

- taxon_id
- taxon_name
- rank
- observations
- species
- one column per visible codon share

`overview` columns:

- row_taxon_id
- row_taxon_name
- column_taxon_id
- column_taxon_name
- metric
- value
- row_observations
- row_species
- column_observations
- column_species

For two-codon signed preference, `metric` should be
`signed_preference_difference`. For multi-codon overview, `metric` should be
`jensen_shannon_divergence` or `similarity`, matching the view's displayed
metric.

`browse` can export the same content as `summary` for this page unless the
visible browse chart diverges later. Keep the separate key so the UI can expose
section-specific buttons consistently.

`inspect` columns:

- scope_label
- observations
- codon
- share

If inspect scope is inactive or empty, export headers only.

## Phase 8: Codon Composition by Length Exports

Add dataset keys:

- `summary`
- `preference`
- `dominance`
- `shift`
- `similarity`
- `browse`
- `inspect`
- `comparison`

`summary` and `browse` columns:

- taxon_id
- taxon_name
- rank
- length_bin_start
- length_bin_label
- observations
- species
- dominant_codon
- dominance_margin
- codon
- codon_share

Use one row per taxon/bin/codon. This is easier to analyze than one wide column
per codon and remains stable for residues with different codon counts.

`preference` columns:

- taxon_id
- taxon_name
- rank
- length_bin_start
- length_bin_label
- metric_label
- preference_value
- codon_a
- codon_a_share
- codon_b
- codon_b_share
- observations
- species

Return headers only when preference mode is unavailable.

`dominance` columns:

- taxon_id
- taxon_name
- rank
- length_bin_start
- length_bin_label
- dominant_codon
- dominance_margin
- observations
- species
- codon
- codon_share

Return headers only when dominance mode is unavailable.

`shift` columns:

- taxon_id
- taxon_name
- rank
- previous_bin_start
- previous_bin_label
- next_bin_start
- next_bin_label
- shift_value
- previous_observations
- previous_species
- next_observations
- next_species

`similarity` columns:

- row_taxon_id
- row_taxon_name
- column_taxon_id
- column_taxon_name
- trajectory_jensen_shannon_divergence

`inspect` columns:

- scope_label
- length_bin_start
- length_bin_label
- observations
- species
- dominant_codon
- dominance_margin
- codon
- codon_share
- shift_from_previous

`comparison` uses the same columns as `inspect` but with the comparison scope
label. Return headers only if no comparison is available.

## Phase 9: UI Integration for Stat Views

Add section-level buttons:

- Repeat lengths:
  - Overview: `overview_typical`, `overview_tail`
  - Browse/grouped taxa: `summary`
  - Inspect: `inspect`
- Codon composition:
  - Overview: `overview`
  - Browse/grouped taxa: `summary` or `browse`
  - Inspect: `inspect`
- Codon composition by length:
  - Overview mode buttons can share one download dropdown or individual buttons
    for available datasets
  - Browse: `browse`
  - Inspect: `inspect`
  - Comparison: `comparison`
  - Grouped taxa fallback: `summary`

Keep MVP UI simple. A single `Download TSV` link per table section is enough;
for overview modes with several datasets, use clearly labeled links such as
`Download Preference TSV` and `Download Similarity TSV`.

## Phase 10: Tests and Acceptance Criteria

Backend tests:

- TSV helper escaping and response headers
- list exports honor filters and ordering
- list exports ignore pagination/cursor/fragment
- list exports include all matching rows
- detail table exports are scoped to the current detail object
- stat exports return headers for unavailable datasets
- stat exports match source summary bundles
- codon-by-length summary export emits one row per taxon/bin/codon
- pairwise exports are long-form and symmetric if the underlying matrix is
  symmetric

Manual checks:

- download from a paginated list while on page 2 and confirm page 1 rows are
  still included
- download from detail-page embedded tables and confirm unrelated objects are
  excluded
- download from virtual-scroll pages after scrolling and confirm export is not
  limited to mounted rows
- download from each stats view with filters active
- open files in a spreadsheet and with `python csv.reader(..., delimiter="\t")`

Acceptance criteria:

- every browser table section has a working TSV download
- all current filters are preserved where filters exist
- contextual tables export the rows belonging to their current detail object or
  section
- exported rows are not limited by pagination
- statistical exports use server-side biological/statistical calculations
- no JavaScript is required for downloading
