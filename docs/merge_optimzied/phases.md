# Merged Optimization Phases For `rehaul`

## Purpose

This document turns
[plan.md](/home/rafael/Documents/GitHub/homorepeat/docs/merge_optimzied/plan.md)
into a reviewable execution sequence for merged browser optimization on the
real `rehaul` branch.

Sequencing rules:

- preserve merged semantics from `docs/django/merged.md`
- keep raw imported rows canonical
- move merged list and analytics paths off Python-side full materialization
- prefer rebuildable summary tables over ad hoc caches
- keep provenance and drill-down linked to raw evidence
- validate with focused tests and the smaller sibling dataset by default

## Current Baseline

Verified branch facts:

- merged proteins and merged repeat-call lists now page over summary rows and
  only rematerialize raw evidence for the active page of merged identities
- merged accession analytics, accession detail counters, and taxon-detail
  merged counts now read from summary and occurrence rows
- exact evidence filters now preserve merged inclusion semantics by matching raw
  evidence within the active merged identity and scope
- merged list pages now trim first-page provenance payloads to bounded previews
  while keeping representative evidence and raw drill-down links live
- accession detail still rematerializes raw evidence for its merged residue
  table because full provenance drill-down remains live
- raw browser optimization is already separated from this work
- `PipelineRun.browser_metadata` and `backfill_browser_metadata` already
  provide a working pattern for persisted browser-serving data

Current baseline notes:

- `docs/optimize/merged-fix-2026-04-11.md`
- `docs/django/merged.md`
- `docs/merge_optimzied/baseline-2026-04-13.md`
- `docs/merge_optimzied/contract.md`
- `docs/merge_optimzied/reprofile-2026-04-13.md`

Current status:

- `4.1`, `4.2`, and `5.1` implemented on the small sibling dataset

## Phase 1: Baseline And Serving Contract

### Slice 1.1: Profile current merged paths

Goal:

- record the actual merged bottlenecks before changing schema or read paths

Scope:

- measure first-page timings and dominant query shapes for:
  - `/browser/accessions/`
  - `/browser/proteins/?mode=merged`
  - `/browser/calls/?mode=merged`
  - accession detail
  - taxon detail in merged mode
- confirm where Python-side materialization dominates
- capture the effect of current inline provenance expansion

Out of scope:

- no schema changes
- no view changes

Exit criteria:

- the repo has a dated merged baseline artifact
- the hottest merged paths are documented clearly enough to compare later

Status:

- implemented

### Slice 1.2: Define the merged serving contract

Goal:

- lock the storage and rebuild contract before implementation work starts

Scope:

- define the summary and occurrence table shapes
- define deterministic representative evidence fields
- define rebuild behavior for replace-existing imports
- define the command contract for backfill
- define which merged fields are stored versus computed live

Required behavior:

- protein identity remains `(accession, protein_id, method)`
- residue identity remains `(accession, protein_id, method, residue)`
- summary rows remain fully rebuildable from raw rows
- raw evidence remains reachable from each merged unit

Exit criteria:

- the schema and rebuild rules are decision-complete
- later slices do not need to invent storage semantics

Status:

- implemented

## Phase 2: Persist The Merged Serving Layer

### Slice 2.1: Add merged summary models and indexes

Goal:

- create the database structures that merged pages will browse

Scope:

- add summary models for protein-level and residue-level merged units
- add occurrence models for run- and taxon-scoped filtering
- add browse indexes for:
  - summary identity lookups
  - accession-ordered browsing
  - protein-name browsing
  - method and residue filters
  - occurrence filtering by run and taxon

Out of scope:

- no view rewrites yet
- no import hook yet

Exit criteria:

- migrations apply cleanly
- model-level tests cover uniqueness and intended indexes

Status:

- implemented

### Slice 2.2: Build merged summaries during import

Goal:

- populate the serving layer automatically for new or replaced runs

Scope:

- add a merged summary builder service
- run it after raw import succeeds and before the import batch is marked
  complete
- extend batch progress reporting with a merged summary phase
- ensure replace-existing imports remove stale occurrence rows and refresh the
  affected summaries

Exit criteria:

- new imports populate merged serving rows
- replace-existing imports rebuild the correct merged summaries
- import-focused tests cover the new phase and rebuild behavior

Status:

- implemented

### Slice 2.3: Add backfill and rebuild tooling

Goal:

- make existing imported runs usable without re-importing them

Scope:

- add `backfill_merged_summaries`
- support `--run-id`
- support `--force`
- skip already-complete runs unless forced

Exit criteria:

- existing runs can populate merged serving rows after the feature lands
- command tests cover per-run and force behavior

Status:

- implemented

## Phase 3: Move Merged Read Paths To The Serving Layer

### Slice 3.1: Replace merged protein and residue list reads

Goal:

- make the main merged browse pages page over summary rows instead of grouped
  Python lists

Scope:

- reimplement `merged_protein_groups()` on summary tables
- reimplement `merged_repeat_call_groups()` on summary tables
- keep the existing public helper surfaces stable for callers
- update list-page ordering and pagination to operate on querysets where
  possible

Required behavior:

- run and branch filters use occurrence rows
- text, accession, method, and residue filters use summary rows

Exit criteria:

- merged proteins and repeat-call list views no longer materialize whole raw
  evidence scopes in Python
- focused browser tests still pass

Status:

- implemented

### Slice 3.2: Replace accession analytics and taxon merged counts

Goal:

- move the remaining merged summary pages off raw evidence materialization

Scope:

- reimplement accession analytics on summary and occurrence tables
- reimplement accession detail top-level counters on the serving layer
- reimplement taxon-detail merged counts on the serving layer

Out of scope:

- no full provenance redesign yet

Exit criteria:

- accessions and taxon-detail merged counts no longer depend on
  `list(RepeatCall queryset)`
- focused merged browser tests still pass

Status:

- implemented

## Phase 4: Exact Filters And Provenance Drill-Down

### Slice 4.1: Preserve exact evidence filters

Goal:

- keep merged semantics exact even after summary-table serving is introduced

Scope:

- implement length and purity filters using raw-evidence `Exists(...)`
  constrained by merged identity and active scope
- verify method and residue filters still match the documented inclusion rules

Exit criteria:

- filtered merged views still include a merged unit when at least one
  contributing raw row matches
- helper and browser tests cover the exact-filter behavior

Status:

- implemented

### Slice 4.2: Shrink first-page provenance payloads

Goal:

- keep merged pages responsive without hiding evidence completeness

Scope:

- replace large inline backlink clouds in hot list rows with:
  - counts
  - representative evidence links
  - small previews where useful
- keep full provenance available from detail or filtered evidence pages

Exit criteria:

- merged list pages no longer expand the entire provenance set inline for every
  row
- evidence drill-down remains available

Status:

- implemented

## Phase 5: Validation And Profile Pass

### Slice 5.1: Reprofile merged mode after the redesign

Goal:

- prove that the new merged architecture removed the known scaling failure mode

Scope:

- rerun the merged timing and query-shape checks from slice `1.1`
- compare old and new dominant costs
- verify that merged pages now scale with summary rows and scope filters rather
  than full raw evidence materialization

Validation rule:

- use the smaller sibling dataset and focused test coverage by default
- do not use `chr_all3_raw_2026_04_09` unless explicitly requested for a
  dedicated profiling session

Exit criteria:

- a dated merged reprofile artifact is recorded
- the remaining merged bottlenecks, if any, are clearly documented

Status:

- implemented
