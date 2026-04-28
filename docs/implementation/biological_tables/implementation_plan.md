# Biological Tables Implementation Plan

## Summary

Add two primary scientific browser surfaces in a future implementation pass:

- `/browser/homorepeats/`
- `/browser/codon-usage/`

This document is planning-only. It describes how to implement the tables using
the current codebase while keeping the browser biology-first and avoiding new
source-of-truth data models for the MVP.

The implementation should build presentation/query layers on top of the
canonical catalog:

- `CanonicalRepeatCall`
- `CanonicalRepeatCallCodonUsage`
- `CanonicalProtein`
- `CanonicalSequence`
- `CanonicalGenome`
- `Taxon`

The existing SQL-shaped catalog and provenance views should remain available as
secondary surfaces.

## Reuse Points

Use the existing browser infrastructure instead of building a parallel table
stack:

- `VirtualScrollListView` and cursor pagination for large result sets.
- `BrowserTSVExportMixin` and `TSVColumn` for table downloads.
- Current repeat-call filters for run, branch, genome, sequence, protein,
  method, residue, length, and purity.
- `scoped_canonical_repeat_calls()` as the starting queryset pattern.
- Existing browser facets from `resolve_browser_facets()`.
- Existing sort-header, pagination, download, and row-include templates.
- Existing test fixtures in `web_tests/support.py`, especially
  `create_imported_run_fixture()` and codon-usage setup patterns.

Keep large text fields deferred in default list querysets. Full repeat
sequence, codon sequence, sequence bodies, protein bodies, and flank context
belong in detail views or downloads.

## Homorepeats Table

Implement as a canonical repeat-call list with biology-first labels and derived
display fields.

Default route and view:

- route name: `browser:homorepeat-list`
- URL: `/browser/homorepeats/`
- model/query base: `CanonicalRepeatCall`

Default columns:

- organism: `taxon.taxon_name` or available species name
- genome / assembly: `genome.accession` or repeat-call `accession`
- protein / gene: compact protein name/accession plus `gene_symbol`
- repeat class: `repeat_residue`
- length: `length`
- pattern: derived from `aa_sequence`
- purity: existing `purity`, formatted compactly
- position: derived from `start`, `end`, and `protein_length`
- method: `method`

Implementation details:

- Add a small reusable presentation helper for repeat pattern formatting.
  Input is an amino-acid string; output is consecutive run-length groups such
  as `18Q1A12Q`.
- Add a small reusable helper for protein position display. It should tolerate
  missing or zero `protein_length` and fall back to coordinates.
- Use the same filter semantics as `RepeatCallListView`; avoid inventing a
  second filter grammar.
- Link rows to the existing repeat-call detail page for MVP, or to a renamed
  Homorepeat detail page if that rename is included in the implementation
  scope.
- Do not show latest run or source call ID by default, but keep provenance links
  available from details and downloads.

Download columns should include the visible columns plus:

- source call ID
- protein start and end
- repeat count and non-repeat count
- full repeat sequence
- full codon sequence
- latest run

## Codon Usage Table

Implement as one biology-first profile row per canonical repeat call and target
repeat class, backed by the repeat call's canonical codon-usage rows.

Default route and view:

- route name: `browser:codon-usage-list`
- URL: `/browser/codon-usage/`
- model/query base: `CanonicalRepeatCall` with prefetched or aggregated
  `CanonicalRepeatCallCodonUsage`

Default columns:

- organism
- genome / assembly
- protein / gene
- repeat class
- length
- pattern
- codon coverage
- codon profile
- codon counts
- dominant codon
- method

Implementation details:

- Filter to codon usage rows where `amino_acid` matches the repeat call's
  `repeat_residue` for the default profile.
- For interrupted repeats, derive pattern and length from the full repeat
  region, but compute codon profile only from target-residue codon-usage rows.
- Calculate codon coverage as summed target codon counts over
  `repeat_count`, displayed as `covered/target`.
- Calculate codon profile from codon counts or fractions and format compactly,
  sorted by descending count then codon.
- Dominant codon is the codon with the largest count; break ties
  deterministically by codon text.
- Avoid one SQL result row per codon in the default table. If SQL aggregation is
  awkward across SQLite/PostgreSQL, start with queryset prefetching plus
  per-page/profile reduction, and keep TSV export streaming in bounded chunks.

Download columns should include the visible columns plus:

- full repeat sequence
- full codon sequence
- parseable codon counts, for example `CAG=20;CAA=10`
- parseable codon fractions, for example `CAG=0.667;CAA=0.333`
- target residue count
- latest run

## Navigation And User Experience

Update the browser directory so these become the primary scientific entry
points:

- Homorepeats
- Codon Usage

Move or describe the existing accession, genome, sequence, protein, repeat-call,
run, and operational pages as supporting catalog/provenance views. Do not remove
them.

The table copy should avoid database language. Prefer `Homorepeats`,
`Repeat class`, `Pattern`, `Organism`, and `Codon profile` over internal model
terms.

## Expected Implementation Issues

- `Pattern` requires full `aa_sequence`, but list querysets currently try to
  stay narrow. The implementation should compute it only for the visible page
  and downloads, not for unrelated catalog pages.
- Codon Usage rows need profile aggregation. The implementation should avoid
  N+1 queries by using `prefetch_related()` for visible pages and chunked
  iteration for downloads.
- Existing codon composition explorers are taxon-level statistical summaries.
  The new Codon Usage table is row-level repeat biology and should not change
  existing stats semantics.
- Full flanks are raw provenance data on `RepeatCallContext`, not canonical
  fields. Keep them out of default canonical table querysets unless a dedicated
  detail surface needs them.
- Downloads should be richer than visible tables, but still stable and
  human-readable.

## Test Plan

Add focused tests for the future implementation:

- Homorepeats list renders biology-first headers and does not show run/import
  provenance as default columns.
- Homorepeats filters preserve existing repeat-call semantics for run, branch,
  search, method, residue, length, purity, genome, sequence, and protein.
- Pattern helper formats pure and interrupted repeats:
  `42Q`, `18Q1A12Q`, `10A1G9A`, `7P1A8P1S5P`.
- Position helper handles normal coordinates and missing/zero protein length.
- Codon Usage list combines multiple codon rows into one profile row.
- Interrupted repeat example `18Q1A12Q` counts only Q codons for a Q profile.
- Dominant codon tie-breaking is deterministic.
- TSV downloads include full repeat and codon sequences while default tables do
  not.
- Virtual-scroll/cursor and TSV export behavior match existing browser list
  contracts.
- Browser home/navigation promotes Homorepeats and Codon Usage as primary
  scientific surfaces while keeping provenance views accessible.

## Acceptance Criteria

- The planning/design contract in `context.md` is reflected in the implemented
  table labels, defaults, details, and downloads.
- The implementation reuses existing list, filter, pagination, and export
  infrastructure.
- Default views are compact and biological, not provenance- or schema-first.
- Existing canonical, provenance, operational, and statistical views continue
  to work unchanged.
