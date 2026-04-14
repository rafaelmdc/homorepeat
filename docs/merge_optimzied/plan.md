# Merged Browser Optimization Plan

## Summary

This plan targets merged browser performance on the real `rehaul` branch.

The original merged implementation was not blocked by the same issues as raw
mode. Raw mode was dominated by hot ordered queries and repeated page-chrome
work. The pre-redesign merged path was dominated by loading large `RepeatCall`
querysets into Python, grouping them in memory, sorting the resulting dict
records, and only then paginating and rendering them.

That meant the pre-redesign merged cost scaled with matching raw evidence, not
with the number of rows shown on screen. The current branch has now moved the
hot merged list and summary paths onto the serving layer; see
[reprofile-2026-04-13.md](/home/rafael/Documents/GitHub/homorepeat/docs/merge_optimzied/reprofile-2026-04-13.md)
for the post-change profile.

The recommended direction for this app is the usual database-backed serving
pattern:

- keep imported raw rows as the canonical fact layer
- keep merged semantics as a derived layer defined by
  [docs/django/merged.md](/home/rafael/Documents/GitHub/homorepeat/docs/django/merged.md)
- persist a merged serving layer during import or backfill
- read merged list and analytics pages from that serving layer
- read raw evidence only for drill-down and exact provenance

Current artifacts for this track:

- baseline:
  [baseline-2026-04-13.md](/home/rafael/Documents/GitHub/homorepeat/docs/merge_optimzied/baseline-2026-04-13.md)
- serving contract:
  [contract.md](/home/rafael/Documents/GitHub/homorepeat/docs/merge_optimzied/contract.md)
- reprofile:
  [reprofile-2026-04-13.md](/home/rafael/Documents/GitHub/homorepeat/docs/merge_optimzied/reprofile-2026-04-13.md)

## Scope And Defaults

This pass is intentionally scoped to merged browser behavior:

- `/browser/accessions/`
- `/browser/proteins/?mode=merged`
- `/browser/calls/?mode=merged`
- merged counts shown from taxon detail and accession detail

Defaults:

- preserve the existing merged semantics exactly
- do not change raw/run-mode behavior
- treat raw rows as the only authoritative stored truth
- optimize merged list and summary pages around precomputed summary rows
- keep exact evidence drill-down live against raw tables
- keep routine validation on the smaller sibling dataset and focused tests

Out of scope for the first merged optimization pass:

- changing merged biological identity rules
- changing the public merged URLs
- importing a second canonical `merged` publish format
- broad UI redesign unrelated to the merged hot path
- routine use of the `chr_all3_raw_2026_04_09` 90 GB import path

## Current Branch Reality

Current merged behavior still depends on Python-side materialization:

- `apps/browser/merged/repeat_calls.py`
  - merged list helpers now select scoped summary rows first and only fetch
    raw evidence for the active page or helper result set
- `apps/browser/merged/proteins.py`
  - merged protein list reads now follow the same summary-first path
- `apps/browser/merged/accessions.py`
  - accession analytics, accession detail counters, and taxon merged counts
    now read from summary and occurrence rows
  - accession detail still materializes raw evidence for its residue table
    because full provenance drill-down is still live
- `apps/browser/views/proteins.py` and `apps/browser/views/repeat_calls.py`
  - merged mode now paginates over summary querysets, then rematerializes
    exact display groups for just the current page
- merged list pages now render bounded provenance previews and drill-down links
  instead of expanding the full backlink set inline on the first page

Current implementation status:

- the summary schema slice already exists in
  `apps/browser/models/merged.py`
- migration
  `apps/browser/migrations/0012_mergedproteinsummary_mergedproteinoccurrence_and_more.py`
  adds the serving-layer tables and browse indexes
- import completion now rebuilds merged summary and occurrence rows for the
  imported run before the batch is marked completed
- `backfill_merged_summaries` now rebuilds serving rows for existing imported
  runs, with `--run-id` and `--force`
- merged protein and repeat-call list reads now use those tables
- accession analytics, accession detail counters, and taxon merged counts now
  use those tables
- exact evidence filters now preserve raw-evidence inclusion semantics
- first-page merged provenance payloads are now bounded in both rendered HTML
  and page-scoped view context
- the remaining small-dataset hotspot is accession detail, which still
  rematerializes accession-scoped raw evidence for its residue table because
  full provenance drill-down remains live

This architecture is useful for validating semantics, but it will not scale
well because:

- filtering large merged scopes still reads many raw rows
- sorting happens after grouping in process memory
- pagination applies after full grouping
- request cost grows with evidence volume rather than requested page size

## Target Architecture

### 1. Persisted merged serving layer

Add new browser-side models that serve merged browsing:

- `MergedProteinSummary`
  - one row per `(accession, protein_id, method)`
- `MergedResidueSummary`
  - one row per `(accession, protein_id, method, repeat_residue)`
- `MergedProteinOccurrence`
  - one row per `(summary, pipeline_run, taxon)` for scoped filtering and
    counts
- `MergedResidueOccurrence`
  - one row per `(summary, pipeline_run, taxon)` for scoped filtering and
    counts

The summary rows should store:

- identity fields
- deterministic representative raw backlinks
- stable display fields already needed by merged pages
- precomputed labels and counters used on list and detail pages

The occurrence rows should store:

- `pipeline_run`
- `taxon`
- summary foreign key
- scoped counts required for run and branch filters

This keeps merged list pages bounded by merged units rather than raw evidence.

### 2. Keep raw evidence authoritative

The new tables are serving tables, not new truth entities.

Rules:

- raw `Genome`, `Protein`, `RepeatCall`, and related rows stay unchanged
- merged summary rows are rebuildable from raw evidence
- merged provenance still points back to raw rows
- replace-existing imports must rebuild the affected merged serving rows

### 3. Build during import and backfill later

The import service already persists `PipelineRun.browser_metadata` after the raw
import succeeds. Merged optimization should follow the same operational
pattern:

- raw import completes first
- merged serving rows are rebuilt immediately after raw import
- import batch state gains a merged summary phase
- batch completion waits for merged summary success
- a dedicated backfill command rebuilds existing runs

### 4. Query merged pages from summary tables

Read-path rules:

- merged proteins list reads `MergedProteinSummary` plus filtered
  `MergedProteinOccurrence`
- merged repeat-call list reads `MergedResidueSummary` plus filtered
  `MergedResidueOccurrence`
- accession analytics and accession detail read precomputed summary rows and
  scoped occurrence counts
- taxon-detail merged counts read occurrence-backed counts instead of
  materializing merged groups in Python

Filtering rules:

- run and branch filters operate on occurrence rows
- accession, protein ID, method, residue, and text search operate on summary
  rows
- exact evidence filters such as `length_*` and `purity_*` remain semantically
  correct by using raw-evidence `Exists(...)` checks against `RepeatCall`
  narrowed by merged identity and scope

## Data And UI Contract

The merged semantics from
[docs/django/merged.md](/home/rafael/Documents/GitHub/homorepeat/docs/django/merged.md)
remain unchanged:

- protein identity is `(accession, protein_id, method)`
- residue identity is `(accession, protein_id, method, residue)`
- missing or untrustworthy identity fields still exclude rows from merged
  biological statistics
- raw evidence stays visible and linkable

The page contract should change in one important way for scale:

- merged list pages should stop rendering full backlink chip clouds for every
  row on the first screenful
- list rows should show counts and a small representative preview
- detail or filtered evidence pages should provide the full provenance set

That keeps merged pages responsive while preserving evidence completeness.

## Acceptance Criteria

This pass is complete when all of the following are true:

- merged list and analytics pages no longer depend on materializing large raw
  `RepeatCall` querysets in Python
- merged proteins and merged repeat-call list pages paginate over summary
  querysets rather than grouped Python lists
- accession analytics and accession detail read merged counts from the serving
  layer
- taxon-detail merged counts no longer call `len(merged_*_groups(...))`
- run, branch, method, residue, length, and purity filters preserve current
  merged semantics
- representative evidence selection remains deterministic
- replace-existing imports rebuild the affected merged serving rows correctly
- existing imported runs can be backfilled without re-importing raw data

## Assumptions

- PostgreSQL-backed summary tables are acceptable for merged serving
- a persisted serving layer is preferable to keeping merged fully live in SQL
  because this app is import-heavy and browse-heavy
- exact provenance for one merged unit can stay live against raw evidence
- routine validation should avoid the `chr_all3_raw_2026_04_09` import path
  unless a dedicated profiling pass is explicitly requested
