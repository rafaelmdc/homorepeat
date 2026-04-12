# Browser Optimization Phases For `rehaul`

## Purpose

This document turns [optimize.md](/home/rafael/Documents/GitHub/homorepeat/docs/optimize/optimize.md)
into an execution sequence for the real `rehaul` branch.

Sequencing rules:

- optimize raw/run-mode browser behavior first
- keep merged mode out of raw-browser completion criteria
- use the existing cursor and virtual-scroll layer rather than replacing it
- remove giant branch dropdowns instead of optimizing them
- fix hot query shape and indexes before broader caching
- persist only small, low-cardinality browse metadata
- validate against the large real Docker/Postgres import, not only small tests

## Current Baseline

Verified branch facts:

- `rehaul` already includes `CursorPaginatedListView` and `VirtualScrollListView`
- raw proteins and repeat calls already enable cursor mode in run mode
- fragments are already served through `fragment=virtual-scroll`
- browser home and run summaries now read metadata-backed counts
- raw branch filters now use `branch_q` instead of live taxon dropdowns
- raw protein and repeat-call facet choices now resolve from browser metadata
- run-detail method and residue inventory now resolves from browser metadata
- raw sequence, protein, and repeat-call fragments can omit exact `count`
- merged-mode pages still materialize large repeat-call sets in Python

Current baseline artifact:

- `docs/optimize/baseline-2026-04-11.md`

Current next slice:

- `3.2` add composite browse indexes for hot raw pages

## Phase 1: Baseline And Metadata Contract

### Slice 1.1: Measure the real `rehaul` baseline

Goal:

- lock in the current raw-browser and fragment bottlenecks on this branch

Scope:

- measure first-page and follow-up fragment timings for:
  - `/browser/`
  - `/browser/runs/`
  - `/browser/proteins/`
  - `/browser/calls/`
  - `/browser/sequences/`
- capture dominant query shapes for:
  - browser home and run summaries
  - protein raw browse
  - repeat-call raw browse
  - sequence raw browse
- record whether branch dropdown generation and raw facet generation are visible
  contributors on the large dataset

Out of scope:

- no schema changes
- no browser behavior changes

Exit criteria:

- the repo has a baseline artifact with measured timings or clearly marked
  pending measurements
- follow-up slices can prove improvement against the same paths

Status:

- skipped

### Slice 1.2: Add persisted `PipelineRun.browser_metadata`

Goal:

- define the metadata contract that raw browser pages will use at request time

Scope:

- add `PipelineRun.browser_metadata = models.JSONField(default=dict, blank=True)`
- store:
  - `raw_counts`
  - `facets.methods`
  - `facets.residues`
- add a single builder in the import service layer
- populate metadata during successful import completion
- ensure replace-existing imports overwrite the cached metadata

Required behavior:

- `raw_counts` matches the imported counts already written into
  `ImportBatch.row_counts`
- `facets.methods` comes from imported `RunParameter`
- `facets.residues` comes from imported `RunParameter` and
  `AccessionCallCount`
- metadata stays small and deterministic

Exit criteria:

- migrations apply cleanly
- new imports persist browser metadata
- focused import tests cover the stored shape

Status:

- implemented

### Slice 1.3: Backfill and fallback path for existing runs

Goal:

- keep already imported runs useful immediately after the metadata contract lands

Scope:

- add a metadata access helper that reads, in order:
  - `PipelineRun.browser_metadata`
  - latest completed `ImportBatch.row_counts`
  - small-table metadata rebuild only when needed
- add a management command to backfill metadata for existing runs

Exit criteria:

- existing imported runs can use metadata-backed raw summaries without
  re-importing
- focused tests cover fallback behavior and backfill

Status:

- implemented

## Phase 2: Remove Hot Page-Chrome Work

### Slice 2.1: Move browser home and run summaries to metadata

Goal:

- stop doing live correlated count work on the hottest summary pages

Scope:

- replace `_annotated_runs()` for browser home recent runs and run list row
  counts with metadata-backed values
- use latest completed `ImportBatch.row_counts` as fallback
- leave values blank rather than reintroducing live count queries

Out of scope:

- no merged-mode summaries
- no high-cardinality per-run caches

Exit criteria:

- browser home recent runs and run list no longer depend on fact-table count
  subqueries
- tests verify metadata-backed run counts and fallback behavior

Status:

- implemented

### Slice 2.2: Replace branch dropdowns with `branch_q`

Goal:

- remove giant taxon dropdown work from the raw list pages

Scope:

- add `branch_q` support to raw taxa, genomes, sequences, proteins, repeat
  calls, and accessions
- keep legacy `branch=<pk>` support
- replace branch dropdown controls with a text input labeled `Branch taxon`
- show the active branch search in the page scope summary

Exit criteria:

- hot raw pages no longer render live branch dropdowns
- `branch_q` supports numeric taxon-id and prefix name matching
- tests cover `branch_q` behavior and legacy `branch=<pk>`

Status:

- implemented

### Slice 2.3: Move raw method and residue facets to metadata

Goal:

- stop building raw protein and repeat-call filter choices by scanning
  `RepeatCall`

Scope:

- for selected run views, use that run's metadata facets
- for all-run raw views, use the union of run metadata facets
- keep the run dropdown live from `PipelineRun`
- move run-detail method and residue inventories onto the same metadata helper

Out of scope:

- no merged-mode facet caching
- no persisted branch/taxon options

Exit criteria:

- raw proteins and repeat calls do not query `RepeatCall` just to populate
  method and residue choices
- run detail method and residue inventory no longer scans `RepeatCall`
- tests cover metadata-backed facet resolution

Status:

- implemented

### Slice 2.4: Make fragment `count` optional and keep fragments row-only

Goal:

- remove unnecessary exact totals from the virtual-scroll hot path

Scope:

- update `VirtualScrollListView` fragment payloads so raw fragments may omit
  `count`
- update templates and `static/js/site.js` to tolerate missing fragment counts
- ensure fragment requests do not rebuild expensive page chrome

Exit criteria:

- raw fragment responses contain rows and navigation state without requiring
  exact totals
- tests cover missing fragment counts and continued client behavior

Status:

- implemented

## Phase 3: Cursor Contract And Raw Query Path

### Slice 3.1: Align default raw orders to fast browse paths

Goal:

- make the default raw orders match the order we actually want to optimize

Scope:

- repeat calls default to `pipeline_run_id, accession, protein_name, start, id`
- proteins default to `pipeline_run_id, accession, protein_name, id`
- sequences default to `pipeline_run_id, assembly_accession, sequence_name, id`
- retain stable tie-breaking on primary key

Exit criteria:

- raw default orders use base-table fields that can be backed by dedicated
  composite indexes
- tests assert the default order contract

Status:

- implemented

### Slice 3.2: Add composite browse indexes for hot raw pages

Goal:

- support the new raw default orders directly in the database

Scope:

- add composite indexes for repeat calls, proteins, and sequences matching the
  default raw browse orders
- verify query plans with live `EXPLAIN` on the large Postgres dataset

Exit criteria:

- migrations apply cleanly
- live Postgres plans show the intended indexes being used for the hot raw list
  queries

Status:

- pending

### Slice 3.3: Restrict cursor virtual scroll to fast default orders only

Goal:

- keep cursor mode honest instead of pretending every sort is equally cheap

Scope:

- keep cursor pagination enabled for raw proteins, repeat calls, and sequences
  only when the request uses the fast default order
- preserve alternate sorts, but serve them through regular page-number
  pagination

Exit criteria:

- raw default-order pages use cursor mode
- alternate sorts fall back cleanly
- tests cover both paths

Status:

- pending

### Slice 3.4: Trim the repeat-call raw query shape

Goal:

- reduce join and row-width overhead on the hottest raw fact-table browser

Scope:

- keep repeat-call list projection narrow
- rely on existing denormalized `RepeatCall` display fields where possible
- avoid loading heavy sequence/protein payload columns on the list view
- keep related joins only where they are needed for visible fields or filters

Exit criteria:

- the repeat-call raw browse query is narrower and uses the new browse index
- tests assert the intended queryset shape at a coarse level

Status:

- pending

### Slice 3.5: Trim the protein and sequence raw query shapes

Goal:

- apply the same raw-browse discipline to proteins and sequences

Scope:

- keep list projections narrow with `only()` and `defer()`
- avoid unnecessary related-object loading on list views
- ensure sequence and protein filter paths stay compatible with the default
  browse indexes

Exit criteria:

- raw protein and sequence list queries stay narrow
- tests cover the intended queryset shape and cursor fallback behavior

Status:

- pending

## Phase 4: Large-Run Acceptance

### Slice 4.1: Re-profile the large imported dataset

Goal:

- confirm that the raw-browser slices improved the real large dataset

Scope:

- rerun first-page and fragment timings for the measured raw pages
- capture fresh Postgres plans for the hottest raw queries
- verify that branch dropdown removal and metadata-backed facets landed as
  intended

Exit criteria:

- the baseline artifact is updated with before-and-after results
- `/browser/`, `/browser/proteins/`, `/browser/calls/`, and `/browser/sequences/`
  are materially faster on the large dataset

Status:

- pending

## Separate Track: Merged Redesign

Merged mode is intentionally not part of the raw-browser completion path.

Current issue:

- merged accessions, proteins, and repeat calls still materialize large
  repeat-call sets in Python and group them in memory

Required future direction:

- database-first aggregation, or
- persisted merged summary tables built at import time

Reference note:

- `docs/optimize/merged-fix-2026-04-11.md`
