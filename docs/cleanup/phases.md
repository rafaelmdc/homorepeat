# General Cleanup Phases For `rehaul`

## Purpose

This document turns
[cleanup.md](/home/rafael/Documents/GitHub/homorepeat/docs/cleanup/cleanup.md)
into an execution sequence for the current repo.

It is intentionally scoped to structural cleanup and maintainability. It is not
a feature plan.

## Current Baseline

Verified cleanup pressure points:

- `apps/browser/views.py` has been replaced by `apps/browser/views/`, with the
  shared browser view foundations extracted into support modules and the
  URL-facing browser classes now split into domain modules
- `apps/imports/services/import_run.py` is the main import-service monolith at
  2206 lines
- `apps/imports/services/published_run.py` still mixes contract resolution,
  manifest handling, and row iteration at 889 lines
- `apps/browser/merged.py` has been replaced by `apps/browser/merged/`, with
  merged query helpers, identity logic, and aggregation flow split into domain
  modules
- `apps/browser/models.py` is large enough that model ownership is no longer
  obvious at 607 lines
- `web_tests/test_browser_views.py` and related test files still mirror the old
  monolithic runtime layout

Stable public surfaces that must keep working during cleanup:

- `apps.browser.views`
- `apps.browser.merged`
- `apps.browser.models`
- `apps.imports.services`
- `apps.imports.services.import_run`
- `apps.imports.services.published_run`
- browser route names and current management command flags

Current next phase:

- Phase 4

## Phase 1: Split Browser View Foundations

Goal:

- separate shared browser view infrastructure from URL-facing domain views

Scope:

- convert `apps/browser/views.py` into `apps/browser/views/`
- move common base and infrastructure code into focused support modules
- keep `apps.browser.views` as the stable import surface via re-exports

Implementation notes:

- move `BrowserListView` into `views/base.py`
- move cursor and virtual-scroll classes into `views/pagination.py`
- move cursor token and ordering helpers into `views/cursor.py`
- move shared filter-resolution helpers into `views/filters.py`
- move query annotation helpers into `views/querysets.py`
- move browser directory and URL-query helpers into `views/navigation.py`
- keep view-class names unchanged and re-export them from `views/__init__.py`

Exit criteria:

- `apps/browser/urls.py` continues importing from `apps.browser.views`
- browser tests still pass with no route or template regression
- no cross-module helper duplication appears during extraction

Status:

- implemented

## Phase 2: Split Browser Domain Views

Goal:

- organize browser views by browsing reason instead of one large mixed file

Scope:

- move URL-facing views into domain modules under `apps/browser/views/`

Implementation notes:

- create `home.py`, `runs.py`, `taxonomy.py`, `genomes.py`, `sequences.py`,
  `proteins.py`, `repeat_calls.py`, `accessions.py`, and `operations.py`
- keep each domain module responsible for one browser area
- keep shared logic in the foundation modules from Phase 1 rather than
  reintroducing new local helpers everywhere
- avoid changing URLs, templates, or request parameter contracts

Exit criteria:

- each browser area has a clear owning module
- `apps/browser/views/__init__.py` remains the only required import surface for
  URL wiring
- browser list/detail behavior remains unchanged

Status:

- implemented

## Phase 3: Split Browser Merged Logic

Goal:

- isolate merged-mode query and grouping logic into smaller modules

Scope:

- convert `apps/browser/merged.py` into `apps/browser/merged/`

Implementation notes:

- create `accessions.py` for accession-group querysets and summary assembly
- create `proteins.py` for merged protein grouping
- create `repeat_calls.py` for merged repeat-call grouping
- create `identity.py` for identity keys, group collapse rules, and row choice
- create `metrics.py` for purity rounding and other merged numeric helpers
- keep `apps.browser.merged` as the stable import surface via re-exports

Exit criteria:

- merged helpers are grouped by function
- merged tests still pass without changing public call sites
- the split does not introduce extra materialization or broader queryset shape

Status:

- implemented

## Phase 4: Split Published-Run Parsing

Goal:

- separate artifact inspection, manifest handling, and row iteration in the
  import parser layer

Scope:

- convert `apps/imports/services/published_run.py` into
  `apps/imports/services/published_run/`

Implementation notes:

- create `contracts.py` for dataclasses and parser contract types
- create `artifacts.py` for artifact-path discovery and required-file
  resolution
- create `manifest.py` for manifest loading and validation
- create `iterators.py` for TSV row iterators
- create `load.py` for `load_published_run` assembly
- re-export the current public parser API from `published_run/__init__.py`

Exit criteria:

- import parsing responsibilities are clearly separated
- `apps.imports.services.__init__` does not need public API changes
- parser-focused tests still pass unchanged

Status:

- pending

## Phase 5: Split Import-Run Orchestration

Goal:

- separate import orchestration, state reporting, row preparation, and row
  writing in the import execution layer

Scope:

- convert `apps/imports/services/import_run.py` into
  `apps/imports/services/import_run/`

Implementation notes:

- create `api.py` for public service entrypoints
- create `state.py` for `ImportPhase`, claim/fail/complete flow, and reporter
- create `copy.py` for COPY helpers and serialization utilities
- create `prepare.py` for retained-row discovery and FASTA subset loading
- create `taxonomy.py` for taxon upsert and closure rebuild
- create `entities.py` for genome, sequence, protein, and repeat-call creation
- create `operational.py` for run parameters, download manifest, normalization
  warnings, accession status, and accession call counts
- create `orchestrator.py` if needed for the transaction-heavy import assembly
- preserve current patch points used by tests by re-exporting important symbols
  from `import_run/__init__.py`

Exit criteria:

- import orchestration is readable without scrolling through all row writers
- commands and tests continue importing the same top-level service names
- import behavior remains unchanged

Status:

- pending

## Phase 6: Split Browser Models

Goal:

- make model ownership easier to understand without changing schema

Scope:

- convert `apps/browser/models.py` into `apps/browser/models/`

Implementation notes:

- create `base.py` for shared abstract models
- create `runs.py` for `PipelineRun` and acquisition/import-adjacent entities
- create `taxonomy.py` for taxonomy models
- create `genomes.py` for `Genome`, `Sequence`, and `Protein`
- create `repeat_calls.py` for `RunParameter` and `RepeatCall`
- create `operations.py` for accession status/count, download manifest, and
  normalization warnings
- import all model classes from `models/__init__.py` so Django app loading
  stays stable

Exit criteria:

- model files are grouped by domain
- no migration diff is produced
- model and app-loading tests still pass

Status:

- pending

## Phase 7: Split Tests To Match Runtime Structure

Goal:

- make tests reflect the new domain boundaries instead of large catch-all files

Scope:

- split browser and import tests into smaller modules aligned to runtime
  structure

Implementation notes:

- split browser tests by browsing area:
  - home/runs
  - taxonomy/genomes
  - sequences
  - proteins
  - repeat calls
  - accessions/merged
  - operations
- split import tests by parser, orchestration, commands, and views
- keep common builders in `web_tests/support.py` unless a narrower shared
  helper module becomes clearly justified

Exit criteria:

- runtime ownership and test ownership are aligned
- test files are easier to scan and failures are easier to localize
- no coverage is lost during the split

Status:

- pending

## Phase 8: Final Cleanup Pass

Goal:

- remove temporary duplication and normalize import directions after the main
  splits land

Scope:

- clean up compatibility glue that is no longer needed internally
- keep the stable public re-export surfaces

Implementation notes:

- remove dead private helpers created during intermediate extraction
- collapse duplicate logic that was temporarily copied to unblock earlier
  phases
- verify view modules depend on helper modules, not on sibling view modules
- verify import orchestration depends on parser/writer modules, not the other
  way around
- record any intentionally deferred follow-up work

Exit criteria:

- no obvious duplication remains from the refactor program
- import directions are coherent
- the repo has a clean final state recorded in this file

Status:

- pending

## Validation Rules

Each phase should validate the narrowest affected surface first, then widen.

Minimum checks:

- browser phases: affected `web_tests/test_browser_*`
- import phases: affected `web_tests/test_import_*`
- model phase: `python manage.py makemigrations --check --dry-run` and
  `web_tests/test_models.py`
- final pass: full Django test suite

Every phase must also confirm:

- no public import regression on the stable surfaces listed above
- no route or management command regression
- no unintended behavior change mixed into the structural refactor
