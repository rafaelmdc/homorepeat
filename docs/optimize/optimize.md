# Rehaul Browser Optimization Plan

## Summary

This plan targets the actual browser architecture on the `rehaul` branch.

Unlike the deleted `optimize-rehaul` branch, this branch already has:

- the full browser surface for runs, taxa, genomes, sequences, proteins, repeat
  calls, accessions, accession status, accession call counts, download manifest,
  and normalization warnings
- cursor pagination support in the list-view layer
- virtual-scroll fragment requests served by `VirtualScrollListView`
- a client-side virtual-scroll implementation in `static/js/site.js`

The optimization work therefore starts from a richer and more expensive browser
surface. The raw/run-mode pass should optimize the existing list and fragment
behavior rather than invent a new browser architecture.

## Scope And Defaults

This pass is intentionally scoped to raw/run-mode browser behavior.

Defaults:

- optimize raw/run-mode pages first
- keep merged mode as a separate redesign track
- remove giant branch dropdowns rather than trying to optimize them
- persist only small, low-cardinality browse metadata
- make fragment payloads row-focused and count-optional
- keep cursor mode only where the default order is actually index-backed
- favor narrower queryset shape before broader caching

Out of scope for this pass:

- merged-mode performance fixes
- persisted high-cardinality accession, protein, or call rollups
- replacing the existing virtual-scroll client
- redesigning detail pages unless they show up in profiling as major bottlenecks

## Current Branch Reality

The current hot-path problems on `rehaul` split into three categories.

### 1. Repeated page-chrome work

The browser still rebuilds stable request-time state too often:

- `_annotated_runs()` uses correlated subqueries for many run counts
- browser home directory cards still hit live table counts
- raw branch filters still build live taxon dropdowns
- raw protein and repeat-call filters still derive method and residue choices by
  scanning `RepeatCall`
- fragment payloads still include exact `count`, which forces count work to stay
  on the virtual-scroll path

### 2. Hot raw ordered fetches are not yet index-backed end to end

The raw default list orders for proteins, repeat calls, and sequences are
reasonable from a UX perspective, but they are not matched by dedicated
composite indexes. The current query path still depends on expensive sort and
join behavior on the largest raw tables.

### 3. Merged mode is a separate memory-bound problem

`apps/browser/merged.py` still materializes large repeat-call datasets into
Python lists and groups them in memory. That is not a continuation of the raw
browser tuning work. It is a separate redesign problem.

## Planned Changes

### 1. Add persisted browse metadata per run

Add `PipelineRun.browser_metadata` as a small JSON cache for request-time raw
browser summaries and facets.

Stored shape:

```json
{
  "raw_counts": {
    "genomes": 0,
    "sequences": 0,
    "proteins": 0,
    "repeat_calls": 0,
    "accession_status_rows": 0,
    "accession_call_count_rows": 0,
    "download_manifest_entries": 0,
    "normalization_warnings": 0
  },
  "facets": {
    "methods": [],
    "residues": []
  }
}
```

Population rules:

- `raw_counts` mirrors the imported counts already persisted in
  `ImportBatch.row_counts`
- `facets.methods` comes from imported `RunParameter.method`
- `facets.residues` comes from the union of non-empty
  `RunParameter.repeat_residue` and `AccessionCallCount.repeat_residue`
- arrays are sorted and deduplicated before saving
- metadata is written during successful import completion
- a backfill path is required for already imported runs

Deliberately excluded from persisted metadata:

- branch/taxon option lists
- merged analytics
- high-cardinality accession, genome, protein, or repeat-call inventories

### 2. Move stable summaries off the hot request path

Use metadata-backed summaries for the browser home and run list instead of live
correlated count annotations.

Fallback order:

1. `PipelineRun.browser_metadata.raw_counts`
2. latest completed `ImportBatch.row_counts`
3. `None` or `-`

For this pass, run-detail method and residue inventories should also come from
the per-run metadata cache. The heavier per-run grouped summaries can remain
live unless baseline measurements show they dominate request time.

### 3. Replace branch dropdowns with branch search

All raw list pages currently build live `branch_choices` querysets. On a large
dataset that is the wrong UI contract.

Replace those dropdowns with `branch_q` text search:

- numeric input matches `Taxon.taxon_id`
- text input matches `Taxon.taxon_name__istartswith`
- matched ancestors expand through `TaxonClosure`
- results are filtered to descendants of any matched ancestor
- no matches means an empty result set

Compatibility rule:

- keep legacy `branch=<pk>` support for existing links and back-links

### 4. Keep virtual-scroll fragments row-only and cheap

The fragment layer already exists on this branch. The work here is to make it
honest and lightweight.

Rules:

- fragment responses return row HTML and navigation state only
- fragment `count` is optional and should be omitted on hot raw pages
- templates and `static/js/site.js` must tolerate missing fragment `count`
- fragment requests must not rebuild giant dropdown context

### 5. Restrict cursor mode to fast default orders

Cursor pagination is already implemented. It should only stay enabled when the
requested ordering is the fast default raw order.

Rules:

- proteins, repeat calls, and sequences use cursor mode only on the
  index-backed default order
- alternate sorts fall back to normal page-number pagination
- the final ordering field must remain a stable unique tiebreaker

### 6. Fix the hottest raw query paths

Optimize the large raw fact-table browsers in this order:

- repeat calls
- proteins
- sequences

Default raw order targets:

- repeat calls: `pipeline_run_id, accession, protein_name, start, id`
- proteins: `pipeline_run_id, accession, protein_name, id`
- sequences: `pipeline_run_id, assembly_accession, sequence_name, id`

Required supporting indexes:

- `RepeatCall(pipeline_run, accession, protein_name, start, id)`
- `Protein(pipeline_run, accession, protein_name, id)`
- `Sequence(pipeline_run, assembly_accession, sequence_name, id)`

Query-shape rules:

- keep row projection narrow with `only()` and `defer()` where it materially
  reduces row width
- use existing denormalized raw display fields on `Protein` and `RepeatCall`
- avoid unnecessary related-object joins on hot list pages
- keep detail-link construction on local ids and already selected fields

## Current Measured Outcome

The post-migration large-run profile for `chr_all3_raw_2026_04_09` is recorded
in [reprofile-2026-04-12.md](/home/rafael/Documents/GitHub/homorepeat/docs/optimize/reprofile-2026-04-12.md).

Current measured state:

- the default raw row fetch plans for proteins, repeat calls, and sequences now
  use the intended composite browse indexes
- the trimmed raw list views keep the hot row path narrow and avoid the removed
  eager joins
- branch dropdown generation and live `RepeatCall` facet scans are no longer
  visible in the measured hot raw requests
- the remaining dominant hot cost is exact `COUNT(*)`, including on cursor
  follow-up fragments
- `/browser/` is still dominated by live directory-card counts

## Acceptance Criteria

The raw optimization pass is complete when all of the following are true on the
large Docker/Postgres dataset:

- `/browser/` and `/browser/runs/` no longer spend most of their time building
  live cross-table counts
- `/browser/proteins/`, `/browser/calls/`, and `/browser/sequences/` use
  index-backed default orders
- cursor mode is active only on the fast default order for the hot raw pages
- alternate sorts fall back cleanly to regular pagination
- raw fragment requests stay row-focused and do not require exact counts
- branch dropdowns are gone from the hot raw pages
- raw method and residue choices no longer depend on live `RepeatCall` scans

## Assumptions

- `ImportBatch.row_counts` remains the audit/history record and is not removed
- a small JSON cache on `PipelineRun` is acceptable
- exact totals are optional on hot pages when they are not already available
- the existing virtual-scroll client remains in place for this pass
- merged mode will need a separate database-first or persisted-summary design
