# Table Downloads Overview

## Purpose

The MVP needs reusable TSV downloads for every table-like surface in the
browser. Filters are part of the export contract when a table has them, but the
scope is not limited to tables that expose filters:

- database-backed list tables, such as accessions, genomes, proteins, repeat
  calls, taxa, runs, warnings, accession status, accession call counts, and
  download manifest rows
- contextual detail-page tables, such as related sequences, proteins, repeat
  calls, warnings, batches, source calls, and provenance rows
- higher-level statistical views, such as repeat lengths, codon composition,
  and codon composition by length

The export must represent the table's **current data scope**, not just the rows
that are visible on the current page. For filterable tables, current data scope
means the active filter state. For contextual detail-page tables, current data
scope means the object or section the visible table belongs to. Pagination,
cursor state, and virtual-scroll windowing are display concerns and must not
limit downloads.

## User Contract

Users should be able to click `Download TSV` from any browser table section and
receive a tab-separated file containing the rows in that table's current data
scope.

Downloads should:

- preserve search, sort, run, branch, rank, residue, method, length, purity,
  minimum-count, and top-N filters where those filters exist
- preserve detail-page context for embedded tables that do not have independent
  filters
- ignore pagination parameters: `page`, `after`, `before`, and `fragment`
- include a header row
- use stable, human-readable column names
- use UTF-8 text
- avoid metadata/comment rows so files open cleanly in spreadsheet software, R,
  Python, and command-line tools

## Endpoint Shape

Use the existing page URLs with a query parameter:

```text
/browser/genomes/?run=run-123&q=actin&download=tsv
/browser/proteins/123/?download=repeat_calls
/browser/lengths/?rank=phylum&min_count=5&download=summary
/browser/codon-ratios/?residue=Q&rank=class&download=overview
/browser/codon-composition-length/?residue=Q&rank=phylum&download=browse
```

For ordinary list pages, `download=tsv` is sufficient because each page has one
primary table.

For detail pages with multiple embedded tables, `download=<table-key>`
identifies which table section to export. Table keys should be stable,
lowercase, snake_case names matching the section meaning, such as
`sequences`, `proteins`, `repeat_calls`, `warnings`, or `source_calls`.

For statistical pages, `download=<dataset-key>` identifies which server-side
dataset to export. Dataset keys must be explicit and documented in the
implementation plan.

## Why Server-Side Export

The browser already has pagination, virtual scroll, hidden rows, ECharts
payloads, and section-specific tables. Exporting from the DOM would only capture
what is currently rendered and would miss off-page or virtualized rows.

Server-side export is the correct MVP design because it can:

- reuse the exact filtered querysets and summary bundles
- export all matching rows
- keep biological/statistical calculations authoritative
- avoid JavaScript-only failure modes
- support no-JS and automated uses naturally

## File Format

MVP format is TSV only.

Response headers:

```text
Content-Type: text/tab-separated-values; charset=utf-8
Content-Disposition: attachment; filename="homorepeat_<view>_<dataset>.tsv"
```

Cell formatting:

- `None` becomes an empty cell
- booleans become `true`/`false`
- numbers use plain string formatting from Python values
- tabs, carriage returns, and newlines inside values are replaced with spaces
- rows end with `\n`

No quoting is required after tab/newline normalization.

## Main Implementation Surfaces

Reusable backend pieces:

- TSV formatting helper
- streaming TSV response helper
- export column definitions
- list-view export mixin
- detail-table export dispatcher
- statistical-view export dispatcher

Reusable frontend/template pieces:

- link helper or template context value that preserves current filters while
  replacing `download`
- `Download TSV` buttons in section headers

Existing architecture to reuse:

- `BrowserListView.get_queryset()` for filtered database list pages
- existing detail view query/context methods for contextual embedded tables
- `StatsFilterState` and stats bundle builders for statistical pages
- existing `summary_rows`, inspect rows, and chart payload source bundles

## Scope Boundaries

In scope for MVP:

- all top-level browser list pages
- all browser detail-page table sections
- repeat length statistical page
- codon composition statistical page
- codon composition by length statistical page
- section-level exports for views with multiple tables or datasets

Out of scope for MVP:

- asynchronous export jobs
- ZIP bundles
- XLSX/CSV/JSON export formats
- client-side chart image export

## Scientific Accuracy Requirements

Exports from statistical pages must use the same server-side bundles that feed
the visible tables and charts. Do not recompute related statistics in templates
or JavaScript.

For codon composition exports:

- keep species-weighted codon shares
- preserve selected-residue semantics
- keep codon shares normalized to the selected residue's synonymous codon set
- include support fields where available: observations and species

For codon composition by length exports:

- retain length-bin labels and starts
- retain taxon identifiers and ranks
- include codon shares, dominant codon, dominance margin, and support
- export pairwise/trajectory metrics in long form when exporting matrices

## Success Criteria

- Every browser table section has a `Download TSV` action.
- Downloaded list pages contain all filtered rows, not only the visible page.
- Downloaded detail-page tables contain all rows in that table's context.
- Statistical downloads match the currently displayed filtered analysis.
- TSV files have stable headers and parse correctly with standard TSV readers.
- Tests cover filters, pagination independence, empty results, and stat dataset
  exports.
