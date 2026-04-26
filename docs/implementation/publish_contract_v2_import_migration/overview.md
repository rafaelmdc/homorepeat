# Publish Contract v2 Import Migration: Overview

## Context

The sister pipeline repository at `../homorepeat_pipeline` now publishes the
default import surface as publish contract version `2`. The scientific
information needed by the web app is intended to be the same, but the public
artifact layout is compact and table-first.

The current web importer still assumes the older broad raw publish tree:

- `publish/acquisition/batches/<batch_id>/genomes.tsv`
- `publish/acquisition/batches/<batch_id>/sequences.tsv`
- `publish/acquisition/batches/<batch_id>/proteins.tsv`
- `publish/acquisition/batches/<batch_id>/cds.fna`
- `publish/acquisition/batches/<batch_id>/proteins.faa`
- `publish/status/accession_status.tsv`
- `publish/status/accession_call_counts.tsv`
- `publish/calls/finalized/<method>/<residue>/<batch>/...codon_usage.tsv`

The new default pipeline contract publishes:

```text
publish/
  calls/
    repeat_calls.tsv
    run_params.tsv
  tables/
    genomes.tsv
    taxonomy.tsv
    matched_sequences.tsv
    matched_proteins.tsv
    repeat_call_codon_usage.tsv
    repeat_context.tsv
    download_manifest.tsv
    normalization_warnings.tsv
    accession_status.tsv
    accession_call_counts.tsv
  summaries/
    status_summary.json
    acquisition_validation.json
  metadata/
    run_manifest.json
    launch_metadata.json
    nextflow/
```

The default v2 contract does not publish `publish/acquisition/`,
`publish/status/`, `publish/calls/finalized/`, `cds.fna`, or `proteins.faa`.
Those are now internal pipeline execution artifacts.

This migration plan assumes the pipeline v2 contract is amended so the matched
tables carry the full sequence bodies for the already retained records:

- `tables/matched_sequences.tsv` includes `nucleotide_sequence`
- `tables/matched_proteins.tsv` includes `amino_acid_sequence`

With those columns present, the web app can preserve the data it currently uses
without reintroducing broad public FASTA artifacts.

## Migration Goal

Update the web import path so a v2 `publish/` directory imports the same browser
catalog and statistical data without depending on unpublished pipeline
internals.

The importer should:

- use `metadata/run_manifest.json` as the run index and contract-version check
- read canonical public files under `calls/`, `tables/`, `summaries/`, and
  `metadata/`
- preserve current raw observation tables and canonical sync behavior where the
  data model still matches
- keep imports fast by streaming TSV rows into PostgreSQL temp tables with
  `COPY`
- avoid loading entire large tables, sequence body columns, repeat calls, codon
  usage, or matched sequence/protein tables into Python memory
- preserve the current statistical semantics: repeat calls, taxonomy, codon
  usage, species-weighted codon composition, and rollup rebuilds

## Contract Differences

### Artifact Layout

The importer must stop resolving required artifacts from batch directories and
finalized method directories. V2 exposes one run-level table for each logical
dataset.

| Current importer assumption | V2 source |
| --- | --- |
| Per-batch `genomes.tsv` | `tables/genomes.tsv` |
| Per-batch `taxonomy.tsv` | `tables/taxonomy.tsv` |
| Per-batch `sequences.tsv` | `tables/matched_sequences.tsv` |
| Per-batch `proteins.tsv` | `tables/matched_proteins.tsv` |
| Per-batch `download_manifest.tsv` | `tables/download_manifest.tsv` |
| Per-batch `normalization_warnings.tsv` | `tables/normalization_warnings.tsv` |
| `status/accession_status.tsv` | `tables/accession_status.tsv` |
| `status/accession_call_counts.tsv` | `tables/accession_call_counts.tsv` |
| `calls/finalized/**/codon_usage.tsv` | `tables/repeat_call_codon_usage.tsv` |
| Batch `acquisition_validation.json` files | `summaries/acquisition_validation.json` |
| Full `cds.fna` and `proteins.faa` | Replaced by matched-only sequence body columns |
| No public repeat flank table | `tables/repeat_context.tsv` |

### Sequence And Protein Bodies

The current web models have optional text fields for full sequence bodies:

- `Sequence.nucleotide_sequence`
- `Protein.amino_acid_sequence`

The amended v2 contract should populate these from the matched-only tables:

- `matched_sequences.tsv.nucleotide_sequence`
- `matched_proteins.tsv.amino_acid_sequence`

This keeps current sequence/protein detail pages supportable without importing
unmatched acquisition records. These columns may be large, so they must be
streamed through the importer and never materialized as whole-table Python
structures.

`tables/repeat_context.tsv` should still be imported or at least validated. It
provides compact repeat-local flanks and is useful for repeat-call detail views,
but it is no longer needed as a replacement for full sequence bodies.

### Batch Semantics

V2 run-level tables still include `batch_id` where batch provenance matters.
The web app should continue creating `AcquisitionBatch` rows, but should derive
them from distinct `batch_id` values across v2 tables rather than from
directories under `publish/acquisition/batches/`.

Potential issue: some tables may be empty except for headers in no-call or
failed-accession runs. Batch rows should be discovered from all batch-bearing
tables, especially `download_manifest.tsv`, `accession_status.tsv`, and
`genomes.tsv`, not only from repeat-linked tables.

### Codon Usage

V2 has one run-level `tables/repeat_call_codon_usage.tsv` instead of per-method,
per-residue finalized codon-usage files. The row shape is already close to the
current `RepeatCallCodonUsage` importer.

Validation should tighten to the v2 contract:

- `codon_count >= 1`
- `codon` is normalized DNA alphabet with length 3
- `method`, `repeat_residue`, `sequence_id`, and `protein_id` match the staged
  repeat-call row for the same `call_id`

Calls without validated codon sequence simply have no codon-usage rows.

### Raw And Merged Publish Modes

The public v2 flat-file contract is the import surface in both
`acquisition_publish_mode=raw` and `acquisition_publish_mode=merged`. The web
importer should no longer reject non-`raw` publish mode merely because merged
mode also publishes SQLite/report artifacts.

The importer should validate `publish_contract_version == 2` and ignore optional
merged-mode derived artifacts for the primary import path.

## Proposed Import Architecture

Keep the current high-level flow:

```text
inspect publish root
  -> validate v2 artifacts
  -> create/update PipelineRun
  -> stage v2 tables
  -> insert raw browser observations
  -> sync canonical catalog
  -> rebuild rollups and browser metadata
```

For PostgreSQL, use run-level staging tables:

- `tmp_homorepeat_v2_repeat_calls`
- `tmp_homorepeat_v2_genomes`
- `tmp_homorepeat_v2_taxonomy`
- `tmp_homorepeat_v2_matched_sequences`
- `tmp_homorepeat_v2_matched_proteins`
- `tmp_homorepeat_v2_codon_usage`
- `tmp_homorepeat_v2_download_manifest`
- `tmp_homorepeat_v2_normalization_warnings`
- `tmp_homorepeat_v2_accession_status`
- `tmp_homorepeat_v2_accession_call_counts`
- optional `tmp_homorepeat_v2_repeat_context`

Load each table with streamed TSV iterators and `COPY`. Build indexes on join
keys immediately after staging:

- `call_id`
- `genome_id`
- `sequence_id`
- `protein_id`
- `taxon_id`
- `batch_id`
- `assembly_accession`

Then insert into existing Django model tables with `INSERT ... SELECT`, using
database joins for validation and relationship resolution.

## Low-Memory Rules

Large imports must follow these rules:

- do not use `list(...)` on repeat calls, codon usage, matched sequences,
  matched proteins, sequence body columns, or operational tables
- do not build Python sets of all retained sequence/protein IDs for the
  PostgreSQL path
- use PostgreSQL temp tables and indexed joins for retained-entity checks
- use `.iterator()` or streaming file readers for any fallback path
- keep Python dictionaries limited to genuinely small lookup domains, such as
  manifest metadata or a small batch-id map
- do not reintroduce public FASTA reads from pipeline internal work directories

The SQLite/non-PostgreSQL path can remain a lightweight test/dev fallback, but
large production-like imports should continue to use PostgreSQL.

## Expected Data Preservation

The v2 contract should preserve the information needed for:

- run provenance
- acquisition batch provenance
- accession status and call counts
- genomes and taxonomy
- repeat-linked sequence/protein metadata and full matched sequence bodies
- repeat calls
- repeat-call codon usage
- canonical catalog sync
- codon composition rollups
- length and codon statistical views

No website-used data should be lost if the amended matched tables include full
sequence body columns. The public contract remains compact because only
repeat-linked matched rows carry sequence bodies; broad unmatched acquisition
FASTA remains internal to the pipeline.

## Main Risks

- **Contract path mismatch**: current artifact resolution will fail immediately
  on v2 because required old directories are absent.
- **Sequence body column drift**: detail pages and some tests expect full
  sequence strings. The amended v2 contract must include and populate
  `nucleotide_sequence` and `amino_acid_sequence` for matched rows.
- **Batch discovery edge cases**: failed or no-call runs may have no repeat-linked
  rows but still need importable operational provenance.
- **Codon usage parity**: switching from finalized fragments to one run-level
  table must keep the same codon share semantics and rollup results.
- **Taxonomy completeness**: `tables/taxonomy.tsv` must contain every taxon
  referenced by genomes/repeat calls plus parents required for closure.
- **Duplicate/conflicting rows**: v2 tables are compact but can still contain
  duplicate natural keys. The importer should detect conflicts with SQL
  grouping, not Python materialization.
- **Merged-mode confusion**: optional SQLite/report artifacts must not become
  the import source or a required dependency.

## Success Criteria

The migration is complete when:

- a v2 `publish/` directory imports without old `acquisition/`, `status/`,
  `calls/finalized/`, `cds.fna`, or `proteins.faa` artifacts
- PostgreSQL import streams all large TSVs through `COPY` into temp tables
- raw and canonical browser counts match the v2 source tables
- codon usage imports from `tables/repeat_call_codon_usage.tsv`
- matched sequence/protein body columns populate existing raw and canonical
  sequence body fields
- canonical sync and codon rollup rebuilds still pass existing statistical tests
- no production import path loads entire large tables into Python memory
- repeat context is available for repeat-local display or validated as part of
  the v2 contract
