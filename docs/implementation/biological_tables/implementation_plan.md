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

---

## Reuse Points

Use the existing browser infrastructure instead of building a parallel table
stack:

- `VirtualScrollListView` and cursor pagination for large result sets.
- `BrowserTSVExportMixin` and `TSVColumn` for table downloads.
- Current repeat-call filters for run, branch, genome, sequence, protein,
  method, residue, length, and purity.
- `scoped_canonical_repeat_calls()` as the starting queryset pattern — see
  **Queryset Gaps** below for what must be added on top.
- Existing browser facets from `resolve_browser_facets()`.
- Existing sort-header, pagination, download, and row-include templates.
- Existing test fixtures in `web_tests/support.py`, especially
  `create_imported_run_fixture()` — see **Test Fixture Gap** below.

Keep large text fields deferred in default list querysets. Full repeat
sequence, codon sequence, sequence bodies, protein bodies, and flank context
belong in detail views or downloads.

---

## Codebase Findings — Explicit Issues And Gaps

These were found by auditing the codebase before writing the implementation
plan. They are listed explicitly so the implementer does not rediscover them.

### 1. `repeat_count` Is Not In The `scoped_canonical_repeat_calls()` Projection

`scoped_canonical_repeat_calls()` calls `.only(...)` and the list does **not**
include `repeat_count` or `non_repeat_count`. These fields exist on
`CanonicalRepeatCall` but accessing them on queryset results will trigger a
lazy SQL fetch per row (N+1).

Codon Usage needs `repeat_count` to calculate `codon_coverage`
(`covered / target`). The Homorepeats TSV download also lists it.

**Fix:** Do not use `scoped_canonical_repeat_calls()` unmodified for these
views. Build a dedicated queryset helper for these views that calls
`scoped_canonical_repeat_calls()` and then chains `.only(...)` again with the
full desired field list — including `repeat_count` and `non_repeat_count`.
Django's `.only()` replaces the existing immediate-load set when chained, so
this is the correct way to expand the projection. Do not try to chain
`.defer()` to add fields: Django's ORM cannot use `.defer()` to un-defer a
field that was excluded by a prior `.only()` — it can only remove fields from
the loaded set.

### 2. `aa_sequence` Is Deferred By Default

`scoped_canonical_repeat_calls()` includes `"aa_sequence"` in its `.defer()`
call. The `Pattern` column requires the full `aa_sequence` string.

Accessing `obj.aa_sequence` on a result row without explicit loading will
trigger one extra SQL query per row.

**Fix:** For the visible page in both Homorepeats and Codon Usage views,
override `get_queryset()` to chain `.only(...)` again with the full desired
field list including `aa_sequence`. Django's `.only()` when chained replaces
the immediate-load set, so this correctly expands the projection. For TSV
downloads, override `prepare_tsv_queryset()` to do the same including
`codon_sequence`. Do not use `.defer()` to try to add fields — chaining
`.defer()` after `.only()` can only remove fields from the loaded set.

### 3. Derive Display Percentages From `codon_count`, Not From Stored `codon_fraction`

Per `docs/statistics.md`, `codon_fraction` is residue-scoped: for a given
`amino_acid`, the fractions across all codons for that amino acid sum to 1 per
repeat call. The stored value is not full-region; it is already scoped to the
selected residue.

However, for the row-level Codon Usage table, display percentages should still
be recomputed from `codon_count` after filtering to `amino_acid ==
repeat_residue`. This makes the display count-derived, avoids relying on
stored fraction precision, and keeps the pipeline contract assumptions out of
the presentation layer. Sum the filtered codon counts, then compute per-codon
`count / total_target_count` for display.

### 4. Codon Usage Prefetch Must Filter In Python, Not In The Prefetch Queryset

A `prefetch_related("codon_usages")` call with a queryset filtered to a
specific `amino_acid` value would require the same `amino_acid` for all rows
on the page. Since `repeat_residue` differs per row, a single filtered
`Prefetch` object cannot be used.

**Fix:** Prefetch all codon-usage rows with
`prefetch_related("codon_usages")`, then filter to `amino_acid ==
obj.repeat_residue` in Python when building the profile for each row. The
`codon_usages` related manager has a compound index on `(amino_acid,
repeat_call)` so the DB fetch is efficient; the Python-side filter is O(small).

### 5. Test Fixture Gap — `create_imported_run_fixture()` Creates No Codon-Usage Records

`create_imported_run_fixture()` (web_tests/support.py) does not create any
`RepeatCallCodonUsage` or `CanonicalRepeatCallCodonUsage` rows. After calling
it, there will be zero codon-usage records for those canonical repeat calls.

**Fix:** Tests for the Codon Usage table must use the `_set_repeat_call_codon_usages`
pattern established in `test_browser_stats.py:147`. This pattern:

1. Creates `RepeatCallCodonUsage` rows on the raw `RepeatCall`.
2. Calls `sync_canonical_catalog_for_run()` again to propagate them to
   `CanonicalRepeatCallCodonUsage`.

This helper is not in `support.py`; it will need to be either extracted into
`support.py` or duplicated in the new test module.

### 6. `protein_length` Has `default=0`, Not `null=True`

`CanonicalRepeatCall.protein_length` is a `PositiveIntegerField(default=0)`.
A value of `0` means "unknown", not "zero-length protein". The position helper
must treat `0` as a missing value and fall back to displaying raw coordinates
rather than percentages.

**Fix:** In the position helper, check `if protein_length > 0` before computing
percentage. Display `start–end` as a fallback.

### 7. `source_call_id` Display Pattern

In `RepeatCallListView`, the TSV column for "Call" uses:

```python
lambda obj: obj.source_call_id or (
    obj.latest_repeat_call.call_id if obj.latest_repeat_call else ""
)
```

`source_call_id` is the canonical denormalized ID. `latest_repeat_call.call_id`
is a fallback via the FK. The Homorepeats TSV download should use this same
pattern rather than assuming `source_call_id` is always populated.

### 8. `use_cursor_pagination()` Must Guard On Default Ordering

`RepeatCallListView` returns `True` from `use_cursor_pagination()` only when
the active ordering is the default ordering. Cursor pagination requires a
stable, unique ordering; ad-hoc `order_by` values that are not covered by a
compound unique index will produce incorrect page boundaries.

**Fix:** Both new views must override `use_cursor_pagination()` with the same
guard as `RepeatCallListView`: return `True` only when `self.current_order_by`
matches the default ordering.

### 9. Virtual Scroll `colspan` Values

- Homorepeats table has 9 default columns → `virtual_scroll_colspan = 9`
- Codon Usage table has 10 default columns → `virtual_scroll_colspan = 10`

These must be set explicitly on the view class. The template does not compute
this automatically.

### 10. `__init__.py` `__all__` Export

`apps/browser/views/__init__.py` has an `__all__` list. New view classes must
be added to this list and imported there, or Django's URL resolver will not
find them via the views module.

Verify the import path used in `apps/browser/urls.py` before wiring up new
routes.

### 11. Route Names Must Not Collide With Existing Stats Routes

The following `browser:` names are already taken and relate to codon topics:

- `browser:codon-ratios`
- `browser:codon-composition-length`

New route names per the plan are `browser:homorepeat-list` and
`browser:codon-usage-list`. These do not collide. Use them as-is.

### 12. `ordering_map` Entries Must Include A Unique Tiebreaker

`CursorPaginatedListView.get_cursor_ordering()` appends `pk` as a tiebreaker
automatically, so the cursor is always unique. However `ordering_map` entries
still need to be defined with stable secondary fields to produce deterministic
page ordering under all sort conditions.

Follow the pattern in `RepeatCallListView.ordering_map` where secondary fields
such as `latest_pipeline_run_id` and `id` are appended.

---

## Homorepeats Table

Implement as a canonical repeat-call list with biology-first labels and derived
display fields.

Default route and view:

- route name: `browser:homorepeat-list`
- URL: `/browser/homorepeats/`
- view class: `HomorepeatListView(BrowserTSVExportMixin, VirtualScrollListView)`
- model/query base: `CanonicalRepeatCall`
- `virtual_scroll_colspan = 9`

Default columns:

- organism: `taxon.taxon_name` or available species name (already in
  `scoped_canonical_repeat_calls()` projection via `select_related("taxon")`)
- genome / assembly: `accession` field on `CanonicalRepeatCall` (already in
  projection)
- protein / gene: `protein_name` plus `gene_symbol` (both already in
  projection)
- repeat class: `repeat_residue` (already in projection)
- length: `length` (already in projection)
- pattern: derived from `aa_sequence` — **must be undeferred for visible page**
- purity: `purity` (already in projection), formatted compactly
- position: derived from `start`, `end`, and `protein_length` — all already
  in projection; treat `protein_length == 0` as unknown
- method: `method` (already in projection)

Implementation details:

- Add a small reusable presentation helper for repeat pattern formatting.
  Input is an amino-acid string; output is consecutive run-length groups such
  as `18Q1A12Q`. Place in `apps/browser/presentation.py` or similar. The plan
  test cases are `42Q`, `18Q1A12Q`, `10A1G9A`, `7P1A8P1S5P`.
- Add a small reusable helper for protein position display. Treat
  `protein_length == 0` as missing and fall back to `start–end` coordinates.
- Override `get_queryset()` to call `scoped_canonical_repeat_calls(...)` then
  chain a step that un-defers `aa_sequence` for the visible page only.
- Override `prepare_tsv_queryset()` to un-defer both `aa_sequence` and
  `codon_sequence` for full TSV rows.
- Use the same filter semantics as `RepeatCallListView`; copy `_load_filter_state()`
  and `get_context_data()` facet injection pattern directly.
- Link rows to the existing `browser:repeatcall-detail` for MVP.
- Override `use_cursor_pagination()` to guard on default ordering.

Download columns should include the visible columns plus:

- source call ID (use the `source_call_id or latest_repeat_call.call_id` pattern)
- protein start and end
- repeat count and non-repeat count (**must add to queryset projection —
  not in default `scoped_canonical_repeat_calls()` output**)
- full repeat sequence (`aa_sequence` — must be un-deferred in
  `prepare_tsv_queryset()`)
- full codon sequence (`codon_sequence` — must be un-deferred in
  `prepare_tsv_queryset()`)
- latest run (`latest_pipeline_run__run_id`)

---

## Codon Usage Table

Implement as one biology-first profile row per canonical repeat call and target
repeat class, backed by the repeat call's canonical codon-usage rows.

Default route and view:

- route name: `browser:codon-usage-list`
- URL: `/browser/codon-usage/`
- view class: `CodonUsageListView(BrowserTSVExportMixin, VirtualScrollListView)`
- model/query base: `CanonicalRepeatCall` with `prefetch_related("codon_usages")`
- `virtual_scroll_colspan = 10`

Default columns:

- organism
- genome / assembly
- protein / gene
- repeat class
- length
- pattern (**requires `aa_sequence` un-deferred**)
- codon coverage (**requires `repeat_count` added to queryset projection**)
- codon profile
- codon counts
- dominant codon
- method

Implementation details:

- Filter the queryset to only rows that have at least one `CanonicalRepeatCallCodonUsage`
  row for the call's own `repeat_residue`. Use `.filter(codon_usages__amino_acid=F("repeat_residue")).distinct()`
  or a subquery existence check to avoid showing blank profiles.
- Use `prefetch_related("codon_usages")` and filter to `amino_acid ==
  obj.repeat_residue` in Python when computing the profile. Do not use a
  filtered `Prefetch` queryset because `repeat_residue` differs per row.
- Compute display percentages from `codon_count` after filtering to
  `amino_acid == repeat_residue`: `fraction = codon_count / sum(all
  target-residue codon_counts)`. Do not display stored `codon_fraction` values
  directly; they are residue-scoped but recomputing from counts is more
  explicit and avoids stored-precision assumptions.
- Compute `codon_coverage` as `sum(codon_count) / repeat_count`. **`repeat_count`
  is not in the default projection and must be added** (see finding #1 above).
- Dominant codon is the codon with the largest recomputed count; break ties
  alphabetically by codon string.
- Codon profile format: `CAG 86%, CAA 14%` (sorted by descending count then
  codon, rounded to nearest integer percent).
- Codon counts format: `CAG 20 / CAA 10` (sorted by descending count then
  codon).
- Override `get_queryset()` to un-defer `aa_sequence` and add `repeat_count`
  to the queryset projection on top of `scoped_canonical_repeat_calls()`.
- For TSV downloads, override `prepare_tsv_queryset()` to also un-defer
  `codon_sequence`.
- Avoid one SQL result row per codon in the default table. The prefetch
  approach keeps one queryset execution per page load (one for repeat calls,
  one for all their codon-usage rows). Codon aggregation happens in Python.
- For TSV streaming, iterate in bounded chunks using `tsv_chunk_size`. Each
  chunk loads repeat calls and their codon-usage rows in two queries (main
  queryset + prefetch).

Download columns should include the visible columns plus:

- full repeat sequence (`aa_sequence`)
- full codon sequence (`codon_sequence`)
- parseable codon counts, for example `CAG=20;CAA=10`
- parseable codon fractions recomputed from target-residue counts, for example
  `CAG=0.667;CAA=0.333`
- target residue count (`repeat_count` — same as codon coverage denominator)
- latest run

---

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

---

## Expected Implementation Issues

- `Pattern` requires full `aa_sequence`, but list querysets currently stay
  narrow. The implementation should un-defer `aa_sequence` only for the visible
  page and downloads, not globally.
- Codon Usage rows need profile aggregation. Use `prefetch_related("codon_usages")`
  for visible pages and chunked iteration for downloads to avoid N+1.
- `repeat_count` is absent from `scoped_canonical_repeat_calls()` `.only()`
  projection. It must be added explicitly wherever codon coverage or the TSV
  download needs it.
- Stored `codon_fraction` is residue-scoped, but row-level Codon Usage display
  percentages should be recomputed from filtered `codon_count` values for
  precision and explicitness.
- Existing codon composition explorers are taxon-level statistical summaries.
  The new Codon Usage table is row-level repeat biology and must not change
  existing stats semantics.
- Full flanks are raw provenance data on `RepeatCallContext`, not canonical
  fields. Keep them out of default canonical table querysets unless a dedicated
  detail surface needs them.
- Downloads should be richer than visible tables, but still stable and
  human-readable.

---

## Test Plan

Add focused tests for the future implementation:

- Homorepeats list renders biology-first headers and does not show run/import
  provenance as default columns.
- Homorepeats filters preserve existing repeat-call semantics for run, branch,
  search, method, residue, length, purity, genome, sequence, and protein.
- Pattern helper formats pure and interrupted repeats:
  `42Q`, `18Q1A12Q`, `10A1G9A`, `7P1A8P1S5P`.
- Position helper handles normal coordinates and missing/zero `protein_length`
  (falls back to coordinate display when `protein_length == 0`).
- Codon Usage list combines multiple codon rows into one profile row.
- Interrupted repeat example `18Q1A12Q` counts only Q codons for a Q profile;
  display percentages are derived from `codon_count`, not stored `codon_fraction`.
- Dominant codon tie-breaking is deterministic (alphabetical by codon string).
- TSV downloads include full repeat and codon sequences while default tables do
  not.
- Virtual-scroll/cursor and TSV export behavior match existing browser list
  contracts.
- Browser home/navigation promotes Homorepeats and Codon Usage as primary
  scientific surfaces while keeping provenance views accessible.
- **Codon Usage test fixture** must use `RepeatCallCodonUsage.objects.bulk_create`
  + `sync_canonical_catalog_for_run()` pattern (from test_browser_stats.py:147)
  since `create_imported_run_fixture()` creates no codon-usage records.

---

## Acceptance Criteria

- The planning/design contract in `context.md` is reflected in the implemented
  table labels, defaults, details, and downloads.
- The implementation reuses existing list, filter, pagination, and export
  infrastructure.
- Default views are compact and biological, not provenance- or schema-first.
- Existing canonical, provenance, operational, and statistical views continue
  to work unchanged.
- No N+1 queries on visible-page loads or TSV streaming.
- Codon profile display percentages are computed from `codon_count` after
  filtering to `amino_acid == repeat_residue`, not from stored `codon_fraction`
  values (which are residue-scoped but should not be trusted for display
  precision).
