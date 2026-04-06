# HomoRepeat Django Phases and Slices

## Purpose

This document turns the Django implementation spec in `docs/django/implementation.md`
into a delivery sequence that can be implemented in small, reviewable slices.

The sequencing rules are:

- preserve the TSV + manifest import contract
- keep the browser run-first
- make `Genome` first-class from the start
- keep lineage support in the first real data slice
- defer graph-heavy and pipeline-coupled features until the browser and import path are stable

## Phase 0: Web Foundation

### Slice 0.1: Promote the scaffold into a real Django project

Goal:
- turn `apps/web/` from a minimal healthcheck scaffold into a real Django project layout

Scope:
- add Django app packages under `apps/web/apps/`
- create `core`, `browser`, and `imports` apps
- wire `INSTALLED_APPS`
- expand root URL routing
- add a shared base template and static site shell
- keep the current Compose-based `web` and `postgres` runtime as the only dev entrypoint

Out of scope:
- no data models yet
- no import logic yet
- no graph pages yet

Exit criteria:
- `docker compose up web postgres` still boots cleanly
- `/` resolves to a real Django view
- `/browser/` and `/imports/` resolve to placeholder views
- app layout matches the implementation spec

### Slice 0.2: Testing and local developer baseline

Goal:
- establish a stable web-app test path before data work starts

Scope:
- add Django test settings if needed
- add a minimal web test package under `apps/web`
- add smoke tests for root URLs and basic template rendering
- document the minimal local commands for migrations, tests, and runserver

Out of scope:
- no import fixtures yet
- no database browser queries yet

Exit criteria:
- Django tests run cleanly inside the repo workflow
- web test entrypoints are documented and repeatable

## Phase 1: Browser Schema

### Slice 1.1: Core provenance and taxonomy models

Goal:
- land the schema roots required for run-aware browsing and lineage support

Scope:
- implement `PipelineRun`
- implement `ImportBatch`
- implement `Taxon`
- implement `TaxonClosure`
- register these models in admin
- add initial migrations

Required rules:
- `PipelineRun.run_id` unique
- `Taxon.taxon_id` unique
- `Taxon` keeps a parent self-reference
- `TaxonClosure` stores ancestor, descendant, and depth

Out of scope:
- no biological run tables beyond taxonomy
- no importer yet

Exit criteria:
- migrations apply cleanly on Postgres
- model tests cover uniqueness and closure integrity basics

### Slice 1.2: Biological entity models

Goal:
- land the run-scoped biological schema that the browser and importer will use

Scope:
- implement `Genome`
- implement `Sequence`
- implement `Protein`
- implement `RepeatCall`
- implement `RunParameter`
- add database indexes for the expected browser filters
- register all models in admin

Required rules:
- `Genome` unique on `(pipeline_run, genome_id)`
- `Sequence` unique on `(pipeline_run, sequence_id)`
- `Protein` unique on `(pipeline_run, protein_id)`
- `RepeatCall` unique on `(pipeline_run, call_id)`
- `RunParameter` unique on `(pipeline_run, method, param_name)`
- `Genome.accession` stored explicitly as the future merge key

Out of scope:
- no cross-run merged models
- no importer yet

Exit criteria:
- migrations apply cleanly
- model tests cover FK integrity and run-scoped uniqueness
- same accession can exist in multiple runs without collision

## Phase 2: Import Backend

### Slice 2.1: Read-only import parsing and validation

Goal:
- build the import backend without writing to the database yet

Scope:
- add import service modules under `imports`
- parse `run_manifest.json`
- resolve required TSV paths from `publish/`
- validate required files and required columns
- convert rows into normalized in-memory records ready for import

Required inputs:
- `publish/manifest/run_manifest.json`
- `publish/acquisition/genomes.tsv`
- `publish/acquisition/taxonomy.tsv`
- `publish/acquisition/sequences.tsv`
- `publish/acquisition/proteins.tsv`
- `publish/calls/repeat_calls.tsv`
- `publish/calls/run_params.tsv`

Out of scope:
- no DB writes yet
- no CLI command yet

Exit criteria:
- tests cover success and failure for missing files, missing columns, and malformed manifests
- parser preserves the full published sequence and protein inventories for validation while allowing later import filtering
- parser can compact raw taxonomy to principal ranks plus referenced taxa for web import
- parser works against `runs/latest/publish/`

### Slice 2.2: Transactional import command

Goal:
- make published runs importable into Postgres from the command line

Scope:
- add `python manage.py import_run --publish-root <path>`
- add optional `--replace-existing`
- create `ImportBatch` rows
- create or replace `PipelineRun`
- import in dependency order
- build full reflexive `TaxonClosure`
- commit or roll back transactionally

Import order:
1. manifest and import batch
2. pipeline run
3. compact taxon
4. taxon closure
5. genome plus derived analyzed-protein count metadata
6. repeat-linked sequence
7. repeat-bearing protein
8. run parameter
9. repeat call

Required behavior:
- fail if the run already exists and `--replace-existing` is absent
- replace that run’s scoped rows when `--replace-existing` is passed
- compact imported taxonomy to principal ranks plus any directly referenced taxa
- persist only sequences and proteins referenced by imported repeat calls
- derive per-genome analyzed protein counts from the full published protein inventory
- never partially commit a broken import

Exit criteria:
- a real published run imports successfully
- rerunning without `--replace-existing` fails clearly
- rerunning with `--replace-existing` succeeds cleanly
- import tests cover rollback on failure

## Phase 3: Browser v1

### Slice 3.1: Browser home and run pages

Goal:
- expose the imported run inventory and provenance first

Scope:
- browser home dashboard
- run list view
- run detail view
- counts for taxa, genomes, proteins, calls, and parameters
- links into run-filtered taxa, genomes, proteins, and calls views

Out of scope:
- no taxon lineage UI yet
- no graph pages yet

Exit criteria:
- imported runs are browsable end to end
- run detail page acts as the operational entrypoint into the browser

### Slice 3.2: Taxa and genomes

Goal:
- ship the lineage-aware browsing core and the accession-aware genome core

Scope:
- taxon list/detail views
- genome list/detail views
- querystring filters for run, branch taxon, rank, accession, and genome name
- lineage breadcrumb on taxon detail
- descendant summaries on taxon detail
- genome detail links to proteins and calls
- genome detail shows analyzed protein count metadata

Required behavior:
- branch filters include descendants through `TaxonClosure`
- taxon lineage is presented from the compacted principal-rank web taxonomy
- genome pages show run provenance and accession explicitly

Exit criteria:
- lineage filters work on real imported data
- accession lookup works
- genomes are clearly first-class in the UI

### Slice 3.3: Proteins and repeat calls

Goal:
- complete the first browser surface over the main scientific outputs

Scope:
- protein list/detail views
- repeat call list/detail views
- protein pages cover only imported repeat-bearing proteins
- filters for run, branch taxon, method, residue, gene symbol, tract length, and purity
- navigation links among taxon, genome, protein, and call records

Required behavior:
- filters can combine cleanly
- repeat call detail shows method, residue, tract coordinates, purity, and linked parents

Exit criteria:
- the run-first browser is complete for the first public data model
- browser tests cover combined filters and lineage-aware queries

## Phase 4: Staff Import Surface

### Slice 4.1: Staff-only import pages

Goal:
- add an operator-facing import surface without replacing the management command

Scope:
- `/imports/` landing page
- form to import from a publish-root path
- import history page backed by `ImportBatch`
- status, row counts, timestamps, and error display

Required behavior:
- staff-only access
- command-line importer remains the authoritative import backend
- UI delegates to the same import services used by the management command

Out of scope:
- no file uploads
- no pipeline launch controls yet

Exit criteria:
- staff can trigger and inspect imports through Django
- import provenance is visible from the web app

## Phase 5: Graph and Summary Layer

### Slice 5.1: Run summary charts

Goal:
- add the first graph-capable pages on top of the imported relational data

Scope:
- run summary page under `core`
- ECharts payload builders for:
  - calls by method
  - calls by residue
  - calls by rank
  - calls within a lineage branch
  - tract length distribution
  - purity distribution

Required behavior:
- charts are generated from Postgres-backed queries, not SQLite
- pages remain server-rendered with embedded JSON

Exit criteria:
- one imported run can be explored visually from the web app
- graph tests cover payload generation for a small fixture

### Slice 5.2: Taxonomy-aware summary exploration

Goal:
- make lineage-aware summaries reusable across the browser and graph pages

Scope:
- grouping controls by selected taxonomic rank
- branch-aware rollup queries
- genomes-with-calls summaries by branch and accession
- shared query helpers reused by browser and graphs

Out of scope:
- no custom merged cross-run browser yet

Exit criteria:
- rank-based and branch-based aggregation is stable
- summary pages behave correctly on both narrow and broad branches

## Phase 6: Merge-Ready Views

### Slice 6.1: Cross-run merge contract and grouped browse support

Goal:
- implement reproducible cross-run grouping without changing the import model

Scope:
- add accession-centered query helpers
- add a simple accession search or grouped accession page
- define merged genome groups by shared `accession`
- show all imported `Genome` rows that contribute to one merged accession group
- preserve links back to each source run

Required behavior:
- merged browsing is read-only and derived
- no destructive deduplication or cross-run upsert of imported biological rows
- provenance remains visible on every grouped record
- grouping is deterministic and independent of import order

Exit criteria:
- one accession present in multiple runs can be browsed as one merged group with visible source rows
- merge-readiness tests pass

### Slice 6.2: Derived collapsed summaries and percentages

Goal:
- add the first reproducible merged summaries once accession grouping is stable

Scope:
- exact repeat-call collapse using the documented cross-run fingerprint
- merged percentages and rollups computed from collapsed merged groups, not raw multi-run sums
- accession-based summary queries
- `/browser/accessions/` acts as the merged summary analytics page
- optional materialized summaries if plain ORM queries are not enough
- explicit distinction in the UI between:
  - run-scoped views
  - merged accession views
  - merged collapsed summaries

Out of scope:
- no mutation of canonical imported rows
- no “last imported wins” overwrite behavior

Exit criteria:
- merged views are additive and provenance-safe
- merged percentages are computed from the derived collapsed layer
- run-scoped and merged summaries can coexist without ambiguity

## Phase 7: Launch Nextflow from Django

### Slice 7.1: Stable workflow submission contract

Goal:
- support launching the workflow for a specific set of accession IDs from outside Nextflow

Scope:
- define the official input contract for accession-driven runs
- define the command used to launch Nextflow
- define run ID, output folder, and log behavior
- keep workflow execution independent from Django internals

Required behavior:
- accession IDs can be submitted as supported workflow input
- the workflow produces normal run outputs in a predictable location
- Nextflow does not write directly to Django or Postgres
- the existing import flow remains unchanged

Exit criteria:
- there is one documented and supported way to launch the workflow for selected accession IDs

### Slice 7.2: Django execution wrapper

Goal:
- let the website/backend trigger the workflow using the supported submission contract

Scope:
- add a Django-side wrapper or management command that launches Nextflow with accession IDs
- expose clear logging, run status, and failure reporting
- keep the integration opt-in and loosely coupled

Exit criteria:
- Django can trigger accession-based runs without changing the workflow-to-output contract

## Recommended Implementation Order

Implement in this order:

1. Slice 0.1
2. Slice 0.2
3. Slice 1.1
4. Slice 1.2
5. Slice 2.1
6. Slice 2.2
7. Slice 3.1
8. Slice 3.2
9. Slice 3.3
10. Slice 4.1
11. Slice 5.1
12. Slice 5.2
13. Slice 6.1
14. Slice 6.2
15. Slice 7.1
16. Slice 7.2

This order keeps risk low:

- schema and import contracts land before UI complexity
- lineage support lands before graph work
- merge support stays additive
- pipeline integration only happens after the web data layer is proven

## Definition of Done

The Django implementation should be considered functionally complete for v1 when:

- published runs can be imported from TSV + manifest only
- run-first browser pages exist for runs, taxa, genomes, proteins, and repeat calls
- taxon lineage filters work through closure rows
- genomes are first-class and accession-aware
- staff can inspect import history
- summary charts run from Postgres-backed queries
- cross-run accession grouping is possible without rewriting imported records
