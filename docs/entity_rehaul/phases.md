# Entity-Centric Rehaul Phases

## Purpose

This document turns
[context.md](/home/rafael/Documents/GitHub/homorepeat/docs/entity_rehaul/context.md)
into a reviewable execution sequence for moving HomoRepeat from a run-centric,
merged-serving browser to a canonical biological catalog with import
provenance.

Sequencing rules:

- keep the current `PipelineRun`-scoped biological tables as the stage-1
  provenance/history layer
- add a canonical current-serving layer alongside the existing run-scoped
  tables before deleting old read paths
- remove merged from the steady-state import and browser contract early, not at
  the very end
- validate catalog sync on the small sibling run before any large-run replay
- keep run/import pages available as secondary provenance pages throughout the
  transition
- do not redesign the scientific import contract while doing the storage and UX
  cutover

## Current Baseline

Verified branch facts:

- the main browser URLs still serve run-scoped data from the current browser
  app:
  - `/browser/accessions/`
  - `/browser/genomes/`
  - `/browser/sequences/`
  - `/browser/proteins/`
  - `/browser/calls/`
- merged behavior is still a first-class product path via `mode=merged` on the
  existing list and detail pages
- merged serving tables still exist in `apps/browser/models/merged.py`
- import completion now enters `ImportPhase.CATALOG_SYNC`
- `apps/imports/services/import_run/api.py` now syncs canonical catalog rows
  before batch completion and analyzes the canonical serving models
- `backfill_canonical_catalog` exists as the active backfill command for
  existing imported runs
- `backfill_merged_summaries` remains only as an explicit legacy/debug command
- `PipelineRun`, `ImportBatch`, and the current run-scoped biological models
  remain the only stored scientific entities the browser reads directly

Current next slice:

- `3.1` move accession and genome pages to canonical reads

## Phase 1: Canonical Catalog Contract

### Slice 1.1: Add canonical current-serving models

Goal:

- create the current catalog layer without disturbing the existing historical
  import layer

Scope:

- add a new browser model module for canonical serving entities
- introduce these models:
  - `CanonicalGenome`
  - `CanonicalSequence`
  - `CanonicalProtein`
  - `CanonicalRepeatCall`
- keep the current run-scoped `Genome`, `Sequence`, `Protein`, and
  `RepeatCall` models unchanged in this slice

Required identity rules:

- `CanonicalGenome` unique on `accession`
- `CanonicalSequence` unique on `(genome, sequence_id)`
- `CanonicalProtein` unique on `(genome, protein_id)`
- `CanonicalRepeatCall` belongs to one canonical protein and one canonical
  sequence
- `CanonicalRepeatCall` uniqueness is method-scoped and location-scoped:
  `(canonical_protein, canonical_sequence, method, repeat_residue, start, end)`

Required provenance fields:

- every canonical model stores:
  - `latest_pipeline_run`
  - `latest_import_batch`
  - `last_seen_at`
- canonical repeat calls also store the latest backing historical
  `RepeatCall`

Required serving fields:

- canonical models carry the current display/filter fields needed by the
  existing browser list pages so stage-1 canonical reads do not require broad
  joins back into the history layer

Out of scope:

- no browser view rewrites yet
- no import sync yet
- no merged deletion yet

Exit criteria:

- migrations apply cleanly
- model tests cover uniqueness and provenance FKs
- the current run-scoped import path still works unchanged

### Slice 1.2: Define catalog sync ownership and replacement boundaries

Goal:

- lock the update contract before importer changes begin

Scope:

- add a catalog-sync service package under the browser/import service layer
- define the touched-entity replacement rules for current canonical rows
- make the replacement grain explicit for canonical repeat calls

Required behavior:

- canonical genome, sequence, and protein rows are upserted from the imported
  run
- importing the same canonical protein/sequence again updates the current row
  in place
- canonical repeat calls are refreshed only for touched
  `(canonical protein, canonical sequence, method)` scopes
- current canonical repeat calls for untouched methods remain intact
- historical run-scoped rows remain untouched and continue to provide full
  provenance

Exit criteria:

- the repo has one catalog sync surface that later importer and backfill code
  can call
- tests cover the replacement-grain rules without requiring browser work

## Phase 2: Import And Backfill Cutover

### Slice 2.1: Replace merged rebuild with catalog sync during import

Goal:

- make canonical catalog sync the steady-state post-import step

Scope:

- replace `SUMMARIZING_MERGED` with a catalog-sync import phase
- call the canonical sync service after raw import succeeds
- stop rebuilding merged summary tables during import completion
- stop analyzing merged summary models during the post-load `ANALYZE` pass

Required behavior:

- successful imports still persist `PipelineRun.browser_metadata`
- successful imports now populate the canonical current-serving layer
- failed catalog sync leaves the import batch failed with the correct phase
- the existing run-scoped history rows remain committed exactly as before

Exit criteria:

- import batches complete without any merged rebuild dependency
- focused importer tests cover canonical sync after fresh import

### Slice 2.2: Add canonical backfill/sync tooling

Goal:

- make existing imported runs usable without re-importing them

Scope:

- add `backfill_canonical_catalog`
- support `--run-id`
- support `--force`
- process runs in deterministic run-id order

Required behavior:

- default behavior skips already-synced runs unless forced
- rebuilding one run refreshes the touched canonical entities and current
  repeat-call scopes
- the command never deletes historical run-scoped rows

Exit criteria:

- existing imported runs can populate the canonical serving layer after the
  feature lands
- command tests cover per-run, skip, and force behavior

### Slice 2.3: Retire merged operational paths

Goal:

- stop treating merged as an active runtime subsystem

Scope:

- remove merged rebuild calls from the import service layer
- stop advertising `backfill_merged_summaries` as an operator workflow
- mark merged tables and codepaths as stage-2 cleanup targets only

Exit criteria:

- no steady-state import or operator workflow depends on merged rebuilds
- docs and command help point operators at canonical sync instead

## Phase 3: Canonical Browser Read Paths

### Slice 3.1: Move accession and genome pages to canonical reads

Goal:

- make the browser entry point reflect current biological state first

Scope:

- rework `/browser/accessions/`, accession detail, `/browser/genomes/`, and
  genome detail to read from canonical models
- keep run/import provenance visible on detail pages
- keep links into historical run pages from the canonical detail pages

Required behavior:

- accession and genome counts describe current canonical state, not merged
  derived counts
- accession detail surfaces the latest import provenance and links to prior
  imported observations
- the old accession-level merged summaries and wording disappear from the UI

Exit criteria:

- canonical accession/genome pages work without `mode=merged`
- focused browser tests cover current-state rendering plus provenance links

### Slice 3.2: Move sequence, protein, and repeat-call pages to canonical reads

Goal:

- finish the main scientific browser cutover onto the canonical catalog

Scope:

- rework `/browser/sequences/`, `/browser/proteins/`, and `/browser/calls/`
  plus their detail pages to read from canonical models
- keep list queries narrow and preserve the current cursor/virtual-scroll rules
  where they still help
- preserve explicit provenance/history sections on the detail pages

Required behavior:

- current list pages no longer depend on `PipelineRun`-scoped biological rows
  for their primary read path
- protein and repeat-call filters use canonical current rows
- detail pages still link to the latest historical imported observations and
  run/import records

Exit criteria:

- the main biological list/detail pages browse current canonical state
- hot-path tests still pass with the canonical layer in place

### Slice 3.3: Keep run/import pages as secondary provenance views

Goal:

- preserve auditability without letting runs remain the primary product model

Scope:

- keep `/browser/runs/` and run detail available
- retitle run-scoped biological links and copy as imported observations or
  history
- make canonical detail pages the preferred destination from browser home and
  cross-links

Required behavior:

- run pages remain useful for operators and provenance review
- the browser no longer implies that run-scoped rows are the main catalog truth

Exit criteria:

- navigation favors canonical entity browsing while keeping run history intact

## Phase 4: Remove Merged From The Product Surface

### Slice 4.1: Remove merged navigation and redirects

Goal:

- stop exposing merged as a first-class user-facing concept

Scope:

- remove merged navigation links, labels, and summaries from templates
- remove `mode=merged` controls from list pages
- redirect merged query-path entry points to the equivalent canonical page when
  the mapping is obvious

Required behavior:

- no primary browser navigation path points users into merged mode
- old merged links fail soft through redirect or clear compatibility handling
  during stage 1

Exit criteria:

- merged disappears from the normal UI without breaking the new canonical paths

### Slice 4.2: Remove merged read dependencies from views and tests

Goal:

- make merged dead code instead of a hidden fallback

Scope:

- remove merged branches from browser views
- delete merged-specific browser test suites once the canonical replacements
  exist
- replace merged assertions with canonical current-state assertions

Exit criteria:

- no browser view dispatches on `mode=merged`
- the active browser test suite no longer depends on merged behavior

## Phase 5: Historical Layer Naming And Cleanup

### Slice 5.1: Clarify historical import-scoped storage

Goal:

- make the remaining run-scoped biological layer explicitly historical

Scope:

- update docs, labels, and admin naming so the current run-scoped models are
  clearly treated as imported observations/history
- make provenance sections and any operator-only history pages use consistent
  terminology

Required behavior:

- current canonical rows are described as the current catalog state
- run-scoped rows are described as historical imported observations

Exit criteria:

- the product vocabulary matches the new architecture

### Slice 5.2: Delete merged schema and code

Goal:

- remove the old subsystem once canonical browsing is stable

Scope:

- delete merged models, build/rebuild helpers, commands, view branches,
  template fragments, and stale tests
- add schema migrations to drop merged tables
- remove merged-specific analyze and maintenance code

Required behavior:

- no runtime code imports `apps.browser.merged`
- no operator workflow references merged rebuilds
- migrations leave the canonical and historical layers intact

Exit criteria:

- merged is gone from schema, code, docs, and tests

## Phase 6: Validation And Acceptance

### Slice 6.1: Small-run catalog validation

Goal:

- prove the canonical cutover is correct on the fast feedback dataset

Scope:

- import the small sibling run into a clean database
- run canonical backfill/sync when needed
- validate current-state browser pages plus provenance links

Required checks:

- importing a run creates canonical current entities
- re-importing the same data updates canonical rows in place
- method-scoped canonical repeat-call replacement behaves correctly
- historical run-scoped rows remain visible

Exit criteria:

- focused importer and browser suites pass on the small run

### Slice 6.2: Large-run acceptance and final cleanup sweep

Goal:

- confirm the new catalog architecture on the realistic data volume

Scope:

- rerun the large raw import
- validate canonical sync counts and replacement behavior
- verify the browser serves canonical pages without merged codepaths
- verify run/import provenance pages still function

Required checks:

- canonical entity counts reconcile with the imported run
- no stale current repeat calls remain for touched method scopes
- import completion no longer depends on merged rebuild work
- the browser entry points no longer depend on `mode=merged`

Exit criteria:

- the canonical catalog path works on the large run
- merged removal is complete
- the repo can treat the entity-centric rehaul as the new default architecture
