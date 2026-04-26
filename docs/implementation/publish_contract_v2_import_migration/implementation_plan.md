# Publish Contract v2 Import Migration: Implementation Plan

## Likely Root Cause

The current web importer is tied to the old raw publish layout, not only to the
scientific content. It resolves per-batch acquisition directories, full FASTA
files, status directories, and finalized codon-usage fragments. The pipeline now
publishes a compact v2 contract where those broad artifacts are internal and the
public import surface is a small set of run-level flat tables.

The migration should be a contract adapter and staging rewrite, not a broad
browser/statistics rewrite.

This plan assumes the pipeline v2 contract is amended so
`tables/matched_sequences.tsv` includes `nucleotide_sequence` and
`tables/matched_proteins.tsv` includes `amino_acid_sequence`. Those columns
replace the old public `cds.fna` and `proteins.faa` inputs for matched records.

## Phase 1. Contract Inspection And Artifact Resolution

### Goal

Teach `apps/imports/services/published_run/` to recognize and validate publish
contract v2 without relying on old raw directories.

### Files

- `apps/imports/services/published_run/contracts.py`
- `apps/imports/services/published_run/artifacts.py`
- `apps/imports/services/published_run/manifest.py`
- `apps/imports/services/published_run/load.py`
- focused tests in `web_tests/test_import_published_run.py` or a new
  `web_tests/test_import_published_run_v2.py` module

### Changes

1. Add v2 artifact path dataclass and retire v1-only dataclasses in
   `contracts.py`:

   - Remove `BatchArtifactPaths` (per-batch directory paths no longer exist)
   - Remove `CodonUsageArtifactPath` (per-file fragment paths no longer exist)
   - Replace `RequiredArtifactPaths` with `V2ArtifactPaths`:

   ```text
   V2ArtifactPaths
     publish_root
     manifest
     repeat_calls_tsv          (calls/repeat_calls.tsv)
     run_params_tsv            (calls/run_params.tsv)
     genomes_tsv               (tables/genomes.tsv)
     taxonomy_tsv              (tables/taxonomy.tsv)
     matched_sequences_tsv     (tables/matched_sequences.tsv)
     matched_proteins_tsv      (tables/matched_proteins.tsv)
     repeat_call_codon_usage_tsv (tables/repeat_call_codon_usage.tsv)
     repeat_context_tsv        (tables/repeat_context.tsv)
     download_manifest_tsv     (tables/download_manifest.tsv)
     normalization_warnings_tsv (tables/normalization_warnings.tsv)
     accession_status_tsv      (tables/accession_status.tsv)
     accession_call_counts_tsv (tables/accession_call_counts.tsv)
     status_summary_json       (summaries/status_summary.json)
     acquisition_validation_json (summaries/acquisition_validation.json)
   ```

   Update `InspectedPublishedRun.artifact_paths` to hold `V2ArtifactPaths`.

2. Add `publish_contract_version` to `MANIFEST_REQUIRED_KEYS` in `contracts.py`.
   The validation error should clearly name the missing key and its expected
   value.

3. In `artifacts.py`, replace `resolve_required_artifacts()`,
   `_resolve_batch_artifacts()`, and `_resolve_codon_usage_artifacts()` with a
   `resolve_v2_artifacts(publish_root: Path) -> V2ArtifactPaths` function that
   reads only the v2 layout. Remove the old functions — do not keep dead code.

4. In `manifest.py`:

   - Replace `_ensure_raw_publish_mode()` with
     `_ensure_v2_contract(manifest)` that validates
     `publish_contract_version == 2`. The old function hard-rejects
     `acquisition_publish_mode != "raw"` — remove that rejection entirely; the
     v2 contract supports both raw and merged modes.

   - Update `_normalize_pipeline_run()` to accept `V2ArtifactPaths` instead of
     `RequiredArtifactPaths`.

   - Update `_read_acquisition_validation_payload()`: the v2 contract publishes
     one run-level `summaries/acquisition_validation.json` instead of per-batch
     files. Remove the `batch_id` parameter and `_ensure_matching_batch_id()`
     call. The payload's `scope` field should be validated as `"run"` rather
     than `"batch"`.

5. In `load.py`:

   - Rewrite `inspect_published_run()` to call `resolve_v2_artifacts()` and
     `_ensure_v2_contract()`.

   - Remove `iter_codon_usage_artifact_rows()` entirely. This function wraps
     iteration over multiple per-file `CodonUsageArtifactPath` objects — in v2
     there is one run-level codon-usage table and no artifact list to iterate.
     Callers should use `iter_codon_usage_rows(paths.repeat_call_codon_usage_tsv)`
     directly.

6. Derive acquisition batch IDs from distinct `batch_id` values across all
   batch-bearing v2 tables rather than from directories. The importer
   (PostgreSQL and non-PostgreSQL paths) should discover batches via SQL query
   over staged temp tables or by a streaming scan of the small batch-bearing
   tables. Batch discovery from the filesystem (`acquisition/batches/`) is gone.

### Validation

- v2 minimal fixture resolves all required paths.
- missing `tables/repeat_call_codon_usage.tsv` fails with a clear contract error.
- `acquisition_publish_mode=merged` is accepted when v2 flat files exist.
- `publish_contract_version != 2` fails with a clear unsupported-contract message.
- old raw-only fixtures fail with an explicit unsupported-contract message (no
  silent fallback).

## Phase 2. V2 Row Iterators And Validation

### Goal

Add streaming iterators for the exact v2 table names and validation rules.

### Files

- `apps/imports/services/published_run/contracts.py`
- `apps/imports/services/published_run/iterators.py`
- tests for column validation and row coercion

### Changes

1. Rename iterator functions and column constants to match v2 table names:

   - `iter_sequence_rows(path, batch_id)` → `iter_matched_sequence_rows(path)`
     (no `batch_id` parameter; `batch_id` is a column value in the run-level
     table)
   - `iter_protein_rows(path, batch_id)` → `iter_matched_protein_rows(path)`

   Rename the corresponding column constants:
   - `SEQUENCE_REQUIRED_COLUMNS` → `MATCHED_SEQUENCE_REQUIRED_COLUMNS`
   - `PROTEIN_REQUIRED_COLUMNS` → `MATCHED_PROTEIN_REQUIRED_COLUMNS`

   Add the amended sequence-body fields to the new constants:
   - `nucleotide_sequence` in `MATCHED_SEQUENCE_REQUIRED_COLUMNS`
   - `amino_acid_sequence` in `MATCHED_PROTEIN_REQUIRED_COLUMNS`

2. Remove `_ensure_matching_batch_id()` from the matched-sequence and
   matched-protein iterators. In v2, `batch_id` is a column value shared across
   a run-level table — there is no per-file expected batch_id to enforce. Keep
   `_ensure_matching_batch_id()` only if it is still used by other per-batch
   paths.

3. Add `iter_repeat_context_rows(path)`. Required columns:

   ```text
   call_id, protein_id, sequence_id,
   aa_left_flank, aa_right_flank,
   nt_left_flank, nt_right_flank,
   aa_context_window_size, nt_context_window_size
   ```

4. Update `iter_codon_usage_rows(path)`:

   - Remove the `batch_id` parameter (v2 has one run-level table).
   - Tighten codon count: reject `codon_count < 1` (current code allows 0).
   - Validate codon as a DNA triplet (length 3, characters A/T/G/C
     case-insensitively).
   - Keep `codon_fraction` finite and in `[0, 1]` via `isfinite()`.

5. Keep all iterators generator-based. Do not add helper APIs that return
   complete table lists.

6. Validate table headers exactly enough to catch contract drift. Missing or
   reordered required columns must raise `ImportContractError` immediately.
   Allow forward-compatible extra columns only if that is a deliberate policy.

### Validation

- iterator tests cover empty tables with headers, bad numeric values, duplicate
  detection inputs, and codon validation.
- `iter_matched_sequence_rows` and `iter_matched_protein_rows` yield the amended
  sequence-body fields.
- no iterator test uses a whole-file materializing helper as the production API.

## Phase 3. PostgreSQL Staging Rewrite

### Goal

Make the PostgreSQL importer consume v2 run-level tables directly and keep the
large-import path low-memory.

### Files

- `apps/imports/services/import_run/postgresql.py`
- `apps/imports/services/import_run/prepare.py`
- `apps/imports/services/import_run/entities.py`
- `apps/imports/services/import_run/operational.py`
- `apps/imports/services/import_run/taxonomy.py`
- `apps/imports/services/import_run/copy.py`
- `apps/imports/services/import_run/state.py`
- `apps/imports/models.py`

### Changes

1. Stage `calls/repeat_calls.tsv` first, as today, using `COPY` into
   `tmp_homorepeat_import_repeat_calls`. Keep indexes on `call_id`, `genome_id`,
   `sequence_id`, and `protein_id`. The existing temp table naming convention
   (`tmp_homorepeat_import_*`) should be kept — do not rename to `v2_*`.

2. Stage v2 run-level tables with `COPY` into new temp tables:

   ```text
   tmp_homorepeat_import_genomes         (tables/genomes.tsv)
   tmp_homorepeat_import_taxonomy        (tables/taxonomy.tsv)
   tmp_homorepeat_import_matched_seqs    (tables/matched_sequences.tsv)
   tmp_homorepeat_import_matched_prots   (tables/matched_proteins.tsv)
   tmp_homorepeat_import_codon_usage     (tables/repeat_call_codon_usage.tsv)
   tmp_homorepeat_import_dl_manifest     (tables/download_manifest.tsv)
   tmp_homorepeat_import_norm_warnings   (tables/normalization_warnings.tsv)
   tmp_homorepeat_import_accession_status (tables/accession_status.tsv)
   tmp_homorepeat_import_accession_counts (tables/accession_call_counts.tsv)
   tmp_homorepeat_import_repeat_context  (tables/repeat_context.tsv, optional)
   ```

   The temp tables for `matched_sequences` and `matched_proteins` must include
   `nucleotide_sequence` and `amino_acid_sequence` columns respectively —
   update `copy.py` staging schemas to include these new fields.

3. Remove `_read_fasta_subset()` from `prepare.py`. This function reads FASTA
   files — it is dead code in v2. The sequence/protein body columns now come
   from the matched TSV columns staged in the temp tables above.

4. Create `AcquisitionBatch` rows from distinct staged `batch_id` values. Use a
   SQL query over the staged temp tables, then bulk insert/update only the small
   batch set. Drop the filesystem-based `_resolve_batch_artifacts()` path from
   `entities.py`.

5. Insert `Genome`, `Sequence`, and `Protein` rows from staged v2 tables with
   `INSERT ... SELECT`:

   - `Sequence.nucleotide_sequence` from
     `tmp_homorepeat_import_matched_seqs.nucleotide_sequence`
   - `Protein.amino_acid_sequence` from
     `tmp_homorepeat_import_matched_prots.amino_acid_sequence`
   - `Protein.repeat_call_count` from a GROUP BY on staged repeat calls via
     SQL, not Python

6. Keep retained-entity validation in SQL:

   - every staged repeat call must reference a staged matched sequence and
     matched protein
   - every matched sequence/protein row inserted should be repeat-linked
   - no FASTA coverage checks should remain in the v2 path

7. Insert repeat calls after genomes/sequences/proteins with the existing
   relationship joins.

8. Stage and insert codon usage from
   `tables/repeat_call_codon_usage.tsv`. Validate staged rows against staged
   repeat calls before inserting into `RepeatCallCodonUsage`.

9. Insert operational rows from run-level v2 tables. Join their `batch_id` to
   `AcquisitionBatch` where required.

10. Load taxonomy from `tables/taxonomy.tsv` via staging temp table and SQL
    conflict checks before converting only the upsert set into model rows.

11. In `state.py`, remove the `LOADING_FASTA` / `"loading_fasta"` phase. The
    v2 import path has no distinct FASTA-loading step. In `models.py`, remove
    `("loading_fasta", "FASTA")` from `ImportBatch.PROGRESS_STEPS`.

    This is a database change: add a Django migration that updates or removes
    the `loading_fasta` label. Existing `ImportBatch` rows with
    `phase="loading_fasta"` should be migrated to `"importing_rows"` or left
    as-is with no breakage (the phase column is a free-text field, not a choice
    field). Decide on the migration strategy before writing the migration.

    Consider replacing the `loading_fasta` step with a `staging_tables` step
    that reflects the new v2 COPY-staging phase, so the UI progress bar remains
    informative.

### Validation

- import a v2 fixture without `publish/acquisition/`, FASTA files,
  `publish/status/`, or `calls/finalized/`.
- verify raw row counts:

  ```text
  RepeatCall == rows(calls/repeat_calls.tsv)
  RepeatCallCodonUsage == rows(tables/repeat_call_codon_usage.tsv)
  Sequence == rows(tables/matched_sequences.tsv)
  Protein == rows(tables/matched_proteins.tsv)
  ```

- verify `Protein.repeat_call_count` matches grouped staged repeat calls.
- verify imported `Sequence.nucleotide_sequence` and
  `Protein.amino_acid_sequence` match the amended matched TSV columns.
- verify no PostgreSQL path builds Python sets of all sequence/protein IDs.

## Phase 4. Non-PostgreSQL Fallback Policy

### Goal

Keep local SQLite tests useful without pretending SQLite is the production path
for large imports.

### Files

- `apps/imports/services/import_run/orchestrator.py`
- `apps/imports/services/import_run/prepare.py`
- `apps/imports/services/import_run/entities.py`

### Options

Preferred option:

- make PostgreSQL staging the primary v2 implementation
- keep a small SQLite fallback for tests by streaming rows in bounded batches
- avoid full-table memory materialization where practical

Acceptable temporary option:

- support v2 only on PostgreSQL at first
- mark SQLite v2 import as unsupported with a clear error
- adjust tests to exercise parser/iterator behavior separately and use
  PostgreSQL for end-to-end large-import validation

### Non-PostgreSQL Path Changes

If the preferred option is chosen, `orchestrator.py` and `prepare.py` need
updating:

- `_prepare_streamed_import_data()` in `prepare.py` still does a single pass
  through `repeat_calls.tsv` to build retained entity ID sets for the
  non-PostgreSQL path. Its result `PreparedStreamedImportData` should be kept
  but the fields no longer drive FASTA reads — they drive filtered ORM inserts
  from the matched TSV iterators (`iter_matched_sequence_rows`,
  `iter_matched_protein_rows`).

- `_read_fasta_subset()` is removed (see Phase 3). The non-PostgreSQL path
  reads sequence bodies from matched TSV rows, filtering to retained IDs.

- `orchestrator.py` imports `iter_codon_usage_artifact_rows` from `load.py`
  today. That function is removed in Phase 1. Replace the call with
  `iter_codon_usage_rows(paths.repeat_call_codon_usage_tsv)` directly.

- `_create_call_linked_entities_for_batches()` in `entities.py` currently
  iterates per-batch paths and reads per-batch FASTA files. In v2, it should
  iterate over retained IDs from the pre-scan result, streaming from the single
  run-level matched TSV files.

### Validation

- SQLite tests prove contract parsing and small fixture import behavior.
- PostgreSQL tests or manual Compose import prove the low-memory path.

## Phase 5. Repeat Context Handling

### Goal

Import or validate v2's compact repeat-local context while full matched sequence
bodies come from the amended matched TSVs.

### Files

- `apps/browser/models/` (new `RepeatCallContext` model in the raw observation
  layer alongside `Sequence`, `Protein`, `RepeatCall`)
- a new Django migration under `apps/browser/migrations/`
- `apps/imports/services/import_run/postgresql.py`
- `apps/imports/services/import_run/orchestrator.py`

### Recommended MVP

Add a raw repeat-context model to `apps/browser/` linked one-to-one to
`RepeatCall`:

```text
RepeatCallContext
  repeat_call        (OneToOneField → RepeatCall)
  pipeline_run       (FK → PipelineRun, for run-scoped deletes on replace)
  protein_id         (char, sourced from repeat_context.tsv)
  sequence_id        (char, sourced from repeat_context.tsv)
  aa_left_flank
  aa_right_flank
  nt_left_flank
  nt_right_flank
  aa_context_window_size
  nt_context_window_size
```

The model belongs in `apps/browser/` (raw observation layer) because it is
per-run provenance data. Do not add a canonical context counterpart unless a
browser view needs current-serving flank context independent of run provenance.

Import it with a temp table (`tmp_homorepeat_import_repeat_context`) and
`INSERT ... SELECT` joining on `pipeline_run_id + call_id`.

If UI work is deferred, still stage and validate `repeat_context.tsv` to ensure
every context row references a real repeat call. The detail-page update can
come later.

### Potential Canonical Impact

Canonical repeat calls do not currently need flank context for statistical
views. Do not add canonical context unless a user-facing browser surface needs
current-serving context independent of raw run provenance.

### Validation

- context rows import for calls with flanks clipped at sequence boundaries.
- context rows referencing missing calls fail.
- repeat-call detail page can display flanks without recomputing them from full
  sequence bodies.

## Phase 6. Canonical Sync And Metadata Parity

### Goal

Ensure the existing canonical sync and browser metadata builders continue to
copy the amended matched sequence/protein body fields.

### Files

- `apps/browser/services/catalog/` (contains `sync_canonical_catalog_for_run()`)
  — check the exact module path and update column copy statements

### Checks

1. `sync_canonical_catalog_for_run()` should copy populated
   `nucleotide_sequence` and `amino_acid_sequence` from raw rows into canonical
   rows.

2. Canonical repeat calls should still copy:

   - `aa_sequence`
   - `codon_sequence`
   - codon metric fields
   - method/residue/length/purity fields

3. Codon rollups should be unchanged because they depend on repeat calls,
   taxon closure, and codon-usage rows. Full sequence bodies should not be part
   of rollup calculations.

4. Browser metadata counts should use imported raw row counts and continue to
   report sequence/protein counts from matched tables.

### Validation

- `web_tests.test_canonical_catalog`
- `web_tests.test_browser_stats`
- `web_tests.test_browser_lengths`
- `web_tests.test_browser_codon_ratios`
- `web_tests.test_browser_codon_composition_lengths`

Update tests that previously expected bodies from FASTA files so they now prove
the amended matched TSV body columns populate raw and canonical sequence body
fields.

## Phase 7. Test Fixtures

### Goal

Replace old import fixtures with compact v2 fixtures while keeping focused
coverage for compatibility decisions.

### Changes

1. Add `build_minimal_v2_publish_root()` test helper that writes:

   ```text
   publish/calls/repeat_calls.tsv
   publish/calls/run_params.tsv
   publish/tables/genomes.tsv
   publish/tables/taxonomy.tsv
   publish/tables/matched_sequences.tsv         (includes nucleotide_sequence)
   publish/tables/matched_proteins.tsv          (includes amino_acid_sequence)
   publish/tables/repeat_call_codon_usage.tsv
   publish/tables/repeat_context.tsv
   publish/tables/download_manifest.tsv
   publish/tables/normalization_warnings.tsv
   publish/tables/accession_status.tsv
   publish/tables/accession_call_counts.tsv
   publish/summaries/status_summary.json
   publish/summaries/acquisition_validation.json
   publish/metadata/run_manifest.json           (publish_contract_version: 2)
   ```

2. Decide on v1 fixture fate: old raw fixtures in existing tests should either
   be updated to v2 or explicitly kept to test the v1 unsupported-contract
   error path. Do not leave stale v1 fixtures that silently pass because they
   are no longer exercised.

3. Add no-call fixture:

   - accession status contains `completed_no_calls`
   - repeat calls are header-only
   - matched sequence/protein/codon/context tables are header-only
   - operational rows still import

4. Add contract-error fixtures:

   - missing required v2 table
   - `publish_contract_version` absent or not `2`
   - codon usage references missing call
   - repeat call references missing matched protein
   - conflicting duplicate genome/sequence/protein natural keys
   - taxonomy missing parent

5. Add merged-mode fixture with optional database/report artifacts present but
   ignored by importer.

### Validation

- existing import command tests pass after fixture updates.
- new v2-specific tests verify counts and key relationships.

## Phase 8. Performance And Memory Validation

### Goal

Prove the migration keeps imports fast and memory bounded.

### Checks

For PostgreSQL imports:

- use `COPY` for every large v2 table
- create temp-table indexes before relationship joins
- use `INSERT ... SELECT` for raw model inserts
- use SQL grouping for repeat-call counts and duplicate/conflict checks
- run `ANALYZE` on large temp tables if planner behavior is poor
- keep the canonical sync transaction split and summary-rollup `work_mem`
  improvements from the existing import optimization work

Instrumentation to add or preserve:

- per-stage progress messages for staging each v2 table
- counts for staged repeat calls, matched sequences, matched proteins, codon
  usage rows, and operational rows
- timing logs around the largest `COPY` and `INSERT ... SELECT` steps

Manual validation on a real v2 run:

```bash
docker compose exec web python manage.py import_run \
  --publish-root /workspace/homorepeat_pipeline/runs/<run-id>/publish
```

Then compare:

- source table row counts vs raw model row counts
- raw repeat/codon counts vs canonical repeat/codon counts after sync
- rollup row counts before and after codon rollup rebuild
- PostgreSQL temp-file spill indicators during rollups and large joins

## Phase 9. Documentation Updates After Implementation

### Goal

Move durable behavior from this implementation plan into evergreen docs once
the migration lands.

### Files

- `docs/usage.md`
- `docs/architecture.md`
- `docs/operations.md`
- `docs/statistics.md` only if scientific semantics change

### Updates

- document v2 publish layout as the supported import contract
- remove references to required public `acquisition/`, `status/`,
  `calls/finalized/`, `cds.fna`, and `proteins.faa`
- document that full matched sequence/protein bodies come from amended matched
  TSV columns
- document repeat-context behavior if the model/UI is implemented
- document PostgreSQL as the required path for large v2 imports

## Acceptance Criteria

- The importer accepts publish contract v2 roots from `../homorepeat_pipeline`.
- The importer does not require old broad raw artifacts.
- Large tables are streamed into PostgreSQL temp tables with `COPY`.
- Repeat-linked entities are resolved with SQL joins, not Python full-table
  sets.
- Codon usage imports from `tables/repeat_call_codon_usage.tsv`.
- Matched sequence/protein body columns populate raw and canonical sequence
  body fields.
- Raw and canonical counts match v2 source rows.
- Existing statistical semantics and rollups remain unchanged.
- Tests cover populated, no-call, merged-mode, and contract-error v2 runs.
- Repeat context is imported or validated as compact repeat-local detail data.
