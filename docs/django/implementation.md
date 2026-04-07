
  # HomoRepeat Django Website Plan, Revised for TSV-Only Ingestion and Future Merging

  ## Summary

  Build the website as a Compose-managed Django + PostgreSQL app at the repo root, following the broad structure of ../innovhealth_microbiome:

  - core for home, shared layout, and graph pages
  - browser for the lineage-aware database browser
  - imports for staff-only run ingestion and import history

  The import contract is now fixed:

  - authoritative source for the web app: publish/manifest/run_manifest.json plus canonical TSVs
  - SQLite is not imported by Django
  - SQLite remains only a workflow-side reproducibility artifact

  The first browser is run-first, but the schema must be designed so later cross-run merging is possible without data loss. That means Genome is a first-
  class entity from day one, with both:

  - run-scoped identity for provenance
  - accession-based merge identity for future merged views

  ## Core Architecture

  ### 1. Project structure

  Implement the Django project at the repo root with this internal split:

  - config/: settings, root URLs, WSGI/ASGI
  - apps/core/: home page, shared navigation, graph entrypoints, future staff utilities
  - apps/browser/: browser models, list/detail views, filters, and admin registration
  - apps/imports/: import services, management commands, staff-only upload/import views
  - templates/: base.html, plus core/, browser/, and imports/
  - static/: site CSS and minimal JS for charts/pages

  Use the repo-root `compose.yaml` as the local runtime entrypoint for Django + PostgreSQL.

  ### 2. Source-of-truth and ingestion policy

  Lock these rules in early:

  - Django imports only published TSV artifacts and the run manifest
  - Django does not read the workflow SQLite file
  - Postgres is a derived application database for browsing and graphs
  - Nextflow remains file-first and contract-first

  Required imported artifacts:

  - publish/manifest/run_manifest.json
  - publish/acquisition/genomes.tsv
  - publish/acquisition/taxonomy.tsv
  - publish/acquisition/sequences.tsv
  - publish/acquisition/proteins.tsv
  - publish/calls/repeat_calls.tsv
  - publish/calls/run_params.tsv

  Import retention rule:

  - Django may read the full sequence and protein inventories from the published TSVs for validation and summary counts
  - Django may read the full taxonomy inventory from the published TSV for validation and lineage normalization
  - Django should compact taxonomy to principal display ranks plus any directly referenced taxa before storing it in Postgres
  - Django should persist only the sequence and protein rows referenced by imported repeat calls
  - total analyzed protein inventory should be retained only as genome-level metadata, not as a full relational browser inventory

  Optional published reports can be linked later, but not used as the primary import contract.

  ## Data Model

  ### 3. Provenance-first schema

  The first schema must preserve complete run provenance.

  Core models:

  - PipelineRun
  - ImportBatch
  - Taxon
  - TaxonClosure
  - Genome
  - Sequence
  - Protein
  - RepeatCall
  - RunParameter

  Model intent:

  - PipelineRun
      - one imported run
      - keyed by run_id
      - stores status, profile, timestamps, git revision, manifest metadata, import timestamps
  - ImportBatch
      - one import attempt
      - tracks source path, status, counts, errors, started/finished timestamps
  - Taxon
      - imported taxonomy node keyed by canonical taxon_id
      - stores taxon_name, rank, parent_taxon
  - TaxonClosure
      - ancestor/descendant table for lineage-aware queries
  - Genome
      - first-class biological entity
      - belongs to one PipelineRun
      - stores canonical genome_id plus accession metadata
      - stores total analyzed protein count for that genome
      - references one Taxon
  - Sequence
      - belongs to one PipelineRun
      - imported only when linked to an imported repeat call
      - references one Genome and one Taxon
  - Protein
      - belongs to one PipelineRun
      - imported only when linked to an imported repeat call
      - references one Sequence, one Genome, and one Taxon
  - RepeatCall
      - belongs to one PipelineRun
      - references one Protein, one Sequence, one Genome, and one Taxon
  - RunParameter
      - belongs to one PipelineRun
      - mirrors canonical run_params.tsv

  ### 4. Identity and future merge strategy

  This is the critical design point.

  Use two identity layers:

  - provenance identity: “record as imported in one run”
  - merge identity: “records that likely refer to the same biological assembly across runs”

  For v1:

  - keep all imported rows run-scoped
  - do not deduplicate across runs
  - do not overwrite cross-run biological records

  For Genome, store:

  - pipeline_run
  - genome_id
  - accession
  - genome_name
  - assembly_type
  - assembly_level
  - species_name
  - taxon
  - analyzed_protein_count
  - source
  - notes

  Uniqueness rules:

  - PipelineRun.run_id unique
  - Taxon.taxon_id unique globally
  - Genome unique on (pipeline_run, genome_id)
  - Sequence unique on (pipeline_run, sequence_id)
  - Protein unique on (pipeline_run, protein_id)
  - RepeatCall unique on (pipeline_run, call_id)
  - RunParameter unique on (pipeline_run, method, param_name)

  Cross-run merge key:

  - primary merge key for genomes: accession
  - this is not used to collapse imported rows
  - it is used later to build merged query views and rollups

  Exact merged repeat-call fingerprint:

  - accession
  - protein_name
  - protein_length
  - method
  - start
  - end
  - repeat_residue
  - length
  - normalized purity

  Merge behavior:

  - collapse across runs only in a derived merged layer
  - only exact-match call fingerprints collapse
  - import order must not affect merged results
  - `aa_sequence` remains source provenance and is not part of the first merged collapse key
  - if grouped rows disagree on denominator fields such as analyzed protein count, surface the conflict instead of overwriting one row with another

  Design decision:

  - future merging is implemented as derived merged views or materialized summaries over accession plus exact call fingerprints
  - imported run rows remain intact
  - browser can later offer both:
      - run view
      - merged accession view
      - merged collapsed summaries
  - `/browser/accessions/` is the summary entrypoint for the merged layer and links down into per-accession detail pages

  This avoids destructive deduplication and preserves reproducibility.

  ## Browser Behavior

  ### 5. First browser scope

  The first browser must include these first-class sections:

  - runs
  - taxa
  - genomes
  - proteins
  - repeat calls

  This is the default navigation order because it preserves the merge path and keeps the biology legible.

  Recommended routes:

  - / for home
  - /browser/
  - /browser/runs/
  - /browser/runs/<pk>/
  - /browser/taxa/
  - /browser/taxa/<pk>/
  - /browser/genomes/
  - /browser/genomes/<pk>/
  - /browser/proteins/
  - /browser/proteins/<pk>/
  - /browser/calls/
  - /browser/calls/<pk>/
  - /imports/
  - /admin/

  ### 6. Required v1 browser features

  Run pages:

  - list imported runs
  - show run metadata from manifest
  - show counts for genomes, proteins, calls, taxa, and parameters
  - expose links into run-filtered browser pages

  Taxon pages:

  - lineage breadcrumb over the compacted principal-rank lineage
  - descendants
  - linked genomes/proteins/calls within the selected run
  - branch-aware summary counts using closure rows

  Genome pages:

  - accession-centered details
  - linked taxon
  - analyzed protein count metadata
  - linked repeat-bearing sequences
  - linked repeat-bearing proteins
  - linked repeat calls
  - run provenance
  - later-ready field for merged accession navigation

  Protein pages:

  - imported subset only: proteins with at least one repeat call
  - linked genome and taxon
  - gene symbol and protein metadata when present
  - call summaries by method and residue

  Repeat call pages:

  - method
  - residue
  - tract coordinates
  - tract sequence
  - purity and repeat counts
  - parent protein/genome/taxon links

  Required filters:

  - run
  - accession
  - genome name
  - taxon branch
  - taxon rank
  - method
  - repeat residue
  - gene symbol
  - protein name/id
  - tract length range
  - purity range

  ### 7. Lineage-aware query behavior

  Use TaxonClosure from the first implementation.
  Do not defer lineage modeling.

  Required behavior:

  - filtering by a branch taxon includes all descendant taxa
  - taxon detail shows ancestor chain and descendant overview
  - summary counts can be rolled up by selected taxonomic rank
  - graph pages can reuse the same closure structure for aggregation

  Closure generation:

  - built during taxonomy import
  - full reflexive closure rows included
  - built over the compacted web-side taxonomy, not necessarily every raw upstream lineage node
  - imported taxonomy must remain a tree or tree-like parent chain for v1

  ## Imports and Pipeline Integration

  ### 8. Import flow

  Implement import support in two surfaces:

  - management command for reliable operator use
  - staff-only Django UI for import tracking and later convenience

  First command:

  - python manage.py import_run --publish-root <path>
  - optional --replace-existing for same run_id

  Default import behavior:

  - import is transactional
  - if run_id already exists and --replace-existing is not passed, fail
  - if --replace-existing is passed, delete that run’s imported run-scoped rows and reimport inside one transaction
  - global taxonomy rows can be upserted by taxon_id
  - closure rows are rebuilt or refreshed from imported taxonomy data

  Import order:

  1. read manifest and create ImportBatch
  2. create or validate PipelineRun
  3. import Taxon
  4. compact raw taxonomy to principal ranks plus referenced taxa, then rebuild TaxonClosure
  5. import Genome and derive genome-level analyzed protein counts from the full protein inventory
  6. import only repeat-linked Sequence rows
  7. import only repeat-bearing Protein rows
  8. import RunParameter
  9. import RepeatCall
  10. finalize counts and mark import success

  Validation rules:

  - required files must exist
  - required columns must match contracts
  - manifest run_id and import target must agree
  - compacted taxonomy must still preserve referenced taxon IDs and a valid parent chain
  - foreign-key integrity must be enforced in Django/Postgres
  - same-run duplicates must fail
  - failed imports must roll back cleanly

  ### 9. Later pipeline integration

  Only after the browser and imports are stable:

  Phase 1:

  - keep pipeline and web loosely coupled
  - operator runs pipeline, then runs Django import command

  Phase 2:

  - add a supported helper that imports a successful run into Django/Postgres

  Phase 3:

  - optionally add a wrapper flag or automation path that triggers import after a successful run

  Do not add direct Postgres writes inside Nextflow processes.

  ## Graph Phase

  ### 10. First graph layer

  After the browser works, add graph pages under core focused on taxonomy-aware summaries rather than bespoke biology-specific views.

  First graph pages:

  - run overview dashboard
  - calls by method
  - calls by residue
  - calls by taxonomic rank
  - calls within a selected lineage branch
  - tract length and purity distributions
  - genomes-with-calls summaries by branch/accession

  Rendering approach:

  - server-rendered templates
  - embedded JSON payloads
  - ECharts for charts
  - Postgres/ORM-derived aggregates as the source

  Graph grouping controls should support:

  - selected run
  - branch taxon
  - grouping rank
  - method
  - residue

  ## Tests and Acceptance

  ### 11. Model and import tests

  Add tests for:

  - uniqueness and FK constraints
  - taxonomy closure generation
  - run-scoped import correctness
  - repeated import behavior with and without --replace-existing
  - rollback on partial import failure
  - accession-preserving multi-run imports

  ### 12. Browser tests

  Add tests for:

  - run list/detail
  - taxon lineage page
  - genome list/detail
  - protein list/detail
  - repeat call list/detail
  - branch taxon filters including descendants
  - combined filters for run + method + residue + branch
  - accession lookup behavior

  ### 13. Merge-readiness tests

  Even before merged views exist, add tests that prove the schema supports them:

  - same accession imported in two runs creates two Genome rows, not one
  - both rows remain queryable by run
  - accession filter can find both rows
  - provenance is preserved on all downstream entities
  - exact repeat-call fingerprint collapse is deterministic for identical cross-run calls
  - merged denominator conflicts are surfaced explicitly instead of overwritten silently

  ### 14. Acceptance smoke

  The first complete acceptance flow should be:

  1. docker compose up web postgres
  2. run Django migrations
  3. import one explicit publish-root path
  4. verify browser pages for runs, taxa, genomes, proteins, and calls
  5. verify one branch lineage filter
  6. verify one accession appearing in browser search
  7. verify one basic summary chart page

  ## Assumptions and Defaults

  - The site follows the overall app split and operator ergonomics of ../innovhealth_microbiome.
  - The first implementation is server-rendered Django, not a SPA.
  - Imports are staff-only.
  - The browser is run-first.
  - TSV + manifest are the only web import source.
  - SQLite is not imported by Django.
  - Genome is first-class from day one.
  - Cross-run merging will be accession-centered and non-destructive.
  - Closure tables are required from the initial schema, not deferred.
  - Compose at the repo root remains the standard development runtime.
