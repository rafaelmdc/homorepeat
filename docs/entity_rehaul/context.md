# Entity-Centric Catalog Simplification

For the phased delivery sequence, see
[phases.md](/home/rafael/Documents/GitHub/homorepeat/docs/entity_rehaul/phases.md).

  ## Summary

  Shift HomoRepeat from a run-centric + merged-serving design to a canonical biological catalog with import provenance.

  Chosen direction:

  - canonical current entities become the primary browse model
  - runs/imports remain as provenance and audit surfaces, but not the primary UX
  - merged stops being a product concept
  - current canonical identity anchors are:
      - genome: accession
      - sequence: (genome, sequence_id)
      - protein: (genome, protein_id)
  - repeat calls are not treated as globally stable entities; they are method-scoped observations attached to canonical sequence/protein identity
  - when a canonical sequence/protein is re-imported for a method, that method’s current repeat-call set is replaced, while import-scoped history is
    preserved
  - use a two-stage cutover:
      - stage 1 adds canonical serving data alongside the current run-scoped tables
      - stage 2 removes merged and demotes the old run-centric serving paths

  ## Key Changes

  ### 1. Canonical storage model

  Add a new canonical catalog layer for current serving data.

  Required behavior:

  - canonical browse pages read from the current catalog layer, not from run-scoped raw tables
  - each canonical row stores latest-import provenance such as latest_pipeline_run / latest_import_batch / last_seen_at
  - latest successful import wins for the canonical current state
  - existing run-scoped imported rows remain available in stage 1 as historical provenance

  Canonical identity/update rules:

  - genome upsert by accession
  - sequence upsert by (genome, sequence_id)
  - protein upsert by (genome, protein_id)
  - repeat calls are refreshed per canonical sequence/protein and method
  - for a touched canonical sequence/protein + method:
      - keep import-scoped repeat-call rows as history
      - replace the current canonical repeat-call set for that method
      - do not keep stale current calls from older imports for that same method

  ### 2. Import pipeline changes

  Refactor the importer so it builds canonical current state after raw import succeeds.

  Stage 1 flow:

  1. keep the existing raw import into run-scoped tables as the provenance/history layer
  2. remove merged-summary rebuild from completion flow
  3. add a canonical catalog sync phase after raw import
  4. upsert canonical genomes, sequences, and proteins from the imported run
  5. replace current repeat-call sets for touched canonical sequence/protein + method scopes
  6. persist provenance links from canonical rows back to the import batch and run

  Operational changes:

  - remove summarizing_merged from the steady-state import contract
  - replace it with a catalog-sync phase
  - retire backfill_merged_summaries in favor of a canonical backfill/sync command
  - keep ImportBatch and PipelineRun as audit records

  ### 3. Browser and product model

  Redesign the browser around current canonical biology.

  Primary UX:

  - accessions / genomes / sequences / proteins / repeat calls show current canonical state
  - detail pages show “current value” plus provenance links to the latest import and prior imported observations
  - list/detail pages no longer expose mode=merged

  Secondary UX:

  - keep run/import pages available as provenance and operational history
  - keep them reachable from canonical detail pages, but not as the primary browse path

  Stage 1 compatibility:

  - hide merged navigation from the main UI
  - redirect merged entry points where practical to canonical pages with equivalent filters
  - keep old run-scoped raw pages only as provenance/history views until the canonical path is validated

  Stage 2 cleanup:

  - delete merged models, rebuild code, views, templates, commands, and tests
  - remove merged URL/query contracts such as mode=merged
  - rename or clearly document remaining run-scoped tables/pages as historical import observations rather than the main browse truth

  ### 4. Data and schema direction

  Prefer a clean separation between:

  - current canonical serving tables
  - historical import-scoped observation tables

  Stage 1 default:

  - keep the existing PipelineRun-owned biological tables as the historical layer to avoid a risky all-at-once rewrite
  - add new canonical serving tables rather than immediately mutating every current FK and uniqueness contract in place

  Stage 2 optional cleanup:

  - once the canonical path is stable, either:
      - keep the run-scoped tables as explicit observation/history tables, or
      - rename/restructure them to make the provenance role obvious

  Public interface changes to plan for:

  - remove merged browser mode and merged summary terminology from templates and route behavior
  - replace merged counters with current-canonical counters
  - introduce explicit provenance/history sections on canonical detail pages
  - add a canonical backfill command for existing imported runs

  ## Test Plan

  Required scenarios:

  - importing a run creates canonical current entities and links them to the latest import batch/run
  - importing the same accession/sequence/protein again updates canonical current rows in place
  - prior run-scoped rows remain queryable as provenance/history
  - repeat calls for the same canonical sequence/protein + method are replaced in the current catalog on re-import
  - repeat calls for other methods remain intact
  - corrected NCBI metadata updates canonical fields without requiring merged logic
  - run/import pages still work as secondary provenance pages
  - browser entry points no longer depend on merged models or mode=merged
  - import completion no longer runs merged rebuild logic
  - replacement import does not leave stale current repeat calls for the touched method scope
  - backfill/sync command can build the canonical layer for already imported runs

  Acceptance pass:

  - focused importer tests for canonical upsert and method-scoped repeat-call replacement
  - focused browser tests for canonical list/detail pages and provenance links
  - migration check to confirm merged-specific codepaths are no longer required in stage 2
  - one real-run validation on the small sibling run before any large-run replay
  - one large-run validation after stage-1 canonical sync is stable

  ## Assumptions And Defaults

  - HomoRepeat is primarily a biological catalog, not a run browser
  - NCBI is the only upstream source for now
  - identifier continuity is strong enough that canonical upsert is the right default
  - latest successful import wins for current canonical state
  - field-level historical traceability is satisfied in stage 1 by retaining the current run-scoped imported rows as provenance
  - method remains a meaningful dimension for repeat calls and should not be collapsed
  - sequence/genome identity is the anchor for repeat-call refresh behavior
  - merged is intentionally being removed rather than semantically repaired
