# Contracts

## Purpose

This document defines the stable file and schema contracts used across the HomoRepeat workflow.

A contract is a promise:
- what a step receives
- what a step emits
- which columns are required
- which IDs must remain stable

If implementation changes but the contract remains valid, downstream steps should continue to work.

---

## General rules

### 1. Tabular intermediates use TSV
Unless otherwise stated, structured intermediate outputs should be TSV files with headers.

### 2. UTF-8 everywhere
All text outputs must be UTF-8 encoded.

### 3. One row = one biological unit
Each table must define its row unit clearly.

### 4. Stable column names
Column names are part of the contract and should not change casually.

### 5. Missing values
Missing values must be encoded consistently as empty fields unless a documented sentinel is required.

### 6. Method outputs must be schema-compatible
Pure and threshold outputs must share the same call schema.

---

## Canonical identifiers

The following internal identifiers are recommended:

- `genome_id`
- `taxon_id`
- `sequence_id`
- `protein_id`
- `call_id`

Rules:
- internal IDs must be stable within a pipeline run
- downstream tables should prefer internal IDs over fragile filename parsing
- external identifiers may be preserved in separate columns

---

## Acquisition contract

Workflow driver note:
- the current Nextflow pipeline starts from a plain-text accession list, one assembly accession per line
- downstream acquisition normalization still emits the flat canonical artifacts documented below
- taxonomy DB location is treated as a runtime dependency, not a biological input record

### Input: `acquisition_targets.tsv`

One row per acquisition target to normalize into the workflow contracts.

Required columns:
- `source`
- `genome_name`
- `taxon_id`

Source-specific required columns:
- for `source=ncbi_datasets`: `accession`
- for `source=local`: at least one of `cds_fasta` or `protein_fasta`

Optional columns:
- `accession`
- `assembly_type`
- `assembly_level`
- `species_name`
- `taxon_name`
- `parent_taxon_id`
- `annotation_gff`
- `cds_fasta`
- `protein_fasta`
- `notes`

Rules:
- `source` must currently be one of: `ncbi_datasets`, `local`
- rows in `acquisition_targets.tsv` are intent records, not downstream biological entities
- local-mode paths must be readable from the execution environment
- local mode should prefer `cds_fasta` plus `annotation_gff` when translation-driven normalization is desired
- NCBI mode must retain the downloaded package path in `genomes.tsv.download_path`

### Output: `genomes.tsv`

One row per genome or assembly-level unit.

Required columns:
- `genome_id`
- `source`
- `accession`
- `genome_name`
- `assembly_type`
- `taxon_id`

Optional columns:
- `assembly_level`
- `species_name`
- `download_path`
- `notes`

---

## Taxonomy contract

### Output: `taxonomy.tsv`

One row per taxonomic unit.

Required columns:
- `taxon_id`
- `taxon_name`
- `parent_taxon_id`
- `rank`
- `source`

Optional columns:
- none

---

## Sequence contract

### Output: `sequences.tsv`

One row per retained CDS or other nucleotide sequence used as a translation source.

Required columns:
- `sequence_id`
- `genome_id`
- `sequence_name`
- `sequence_length`
- `sequence_path`

Optional columns:
- `gene_symbol`
- `transcript_id`
- `isoform_id`

---

## Protein contract

### Output: `proteins.tsv`

One row per locally translated or explicitly provided protein.

Required columns:
- `protein_id`
- `sequence_id`
- `genome_id`
- `protein_name`
- `protein_length`
- `protein_path`

Optional columns:
- `gene_symbol`
- `translation_method`
- `translation_status`

---

## Detection call contract

### Outputs
- `pure_calls.tsv`
- `threshold_calls.tsv`

Each row represents one detected homorepeat region.

Required columns:
- `call_id`
- `method`
- `genome_id`
- `taxon_id`
- `sequence_id`
- `protein_id`
- `start`
- `end`
- `length`
- `repeat_residue`
- `repeat_count`
- `non_repeat_count`
- `purity`
- `aa_sequence`

Optional but strongly recommended columns:
- `codon_sequence`
- `codon_metric_name`
- `codon_metric_value`
- `window_definition`
- `template_name`
- `merge_rule`
- `score`
- `source_file`

### Rules
- `method` must be one of: `pure`, `threshold`
- `start` and `end` use the same coordinate system across all methods
- `repeat_residue` is the targeted amino-acid residue for the call
- `length` is the total tract length, including non-target residues if the method definition allows them
- `purity` is a numeric fraction from 0 to 1
- `aa_sequence` must reflect the called tract sequence exactly
- for `pure`, `aa_sequence` is expected to be a contiguous run of `repeat_residue`
- for `threshold`, `window_definition` should record the qualifying sliding-window rule, such as `Q6/8`

---

## Method-specific parameter record contract

### Output: `run_params.tsv`

One row per run configuration block.

Required columns:
- `method`
- `param_name`
- `param_value`

Purpose:
- preserve method settings used in a given run
- support traceability
- make database builds auditable

---

## Summary table contract

### Output: `summary_by_taxon.tsv`

One row per taxon and method.

Required columns:
- `method`
- `repeat_residue`
- `taxon_id`
- `taxon_name`
- `n_genomes`
- `n_proteins`
- `n_calls`
- `mean_length`
- `mean_purity`

Optional columns:
- `codon_metric_name`
- `mean_codon_metric`
- `median_length`
- `max_length`
- `mean_start_fraction`

---

## Regression input contract

### Output: `regression_input.tsv`

One row per grouped observation used in downstream regression.

Required columns:
- `method`
- `repeat_residue`
- `group_label`
- `repeat_length`
- `n_observations`

Optional columns:
- `codon_metric_name`
- `mean_codon_metric`
- `filtered_max_length`
- `transformed_codon_metric`

---

## Reporting contract

### Outputs
- `summary_by_taxon.tsv`
- `regression_input.tsv`
- `echarts_report.html`
- `echarts_options.json`
- `echarts.min.js`

Rules:
- all report outputs must be derivable from finalized tables or SQLite, not raw detection code
- `echarts_options.json` must be a valid JSON object keyed by chart name
- `echarts_report.html` must be reproducible from the JSON payload and analysis-ready tables
- `echarts_report.html` must render the required chart blocks present in `echarts_options.json`
- `echarts.min.js` must be shipped locally with the report bundle so the HTML report works without a CDN

---

## SQLite table contract

The initial v1 database schema owns the following tables:
- `genomes`
- `taxonomy`
- `sequences`
- `proteins`
- `repeat_calls`
- `run_params`

Rules:
- `repeat_calls` is the unified import target for `pure_calls.tsv` and `threshold_calls.tsv`
- flat files remain the canonical exchange artifacts even after import
- table and index definitions live under `assets/sql/`

---

## SQLite ownership rules

### Database build philosophy
SQLite is not the source of truth during active computation.

The source of truth is:
- standardized flat outputs
- schema definition files
- parameter records

SQLite is the integrated build artifact.

### Import rules
- raw method outputs are imported only after validation
- indexes should be created after bulk import
- imports should run in transactions
- row count checks should be performed after import

---

## Validation rules

Every pipeline run should validate at least:

### Detection-level checks
- required columns exist
- no invalid method names
- `start <= end`
- `length > 0`
- `0 <= purity <= 1`

### Relational checks
- every `protein_id` in calls exists in proteins
- every `sequence_id` in proteins exists in sequences
- every `genome_id` exists in genomes

### Summary checks
- grouped counts are non-negative
- no impossible means
- method-level totals reconcile with source call tables

---

## File naming conventions

Preferred names:
- `genomes.tsv`
- `taxonomy.tsv`
- `sequences.tsv`
- `proteins.tsv`
- `pure_calls.tsv`
- `threshold_calls.tsv`
- `run_params.tsv`
- `summary_by_taxon.tsv`
- `regression_input.tsv`
- `homorepeat.sqlite`

Avoid embedding critical metadata only in filenames.

---

## Contract evolution policy

Contracts may evolve, but changes must be explicit.

If a contract changes:
- update this file
- update tests
- update downstream scripts
- document the versioned change in the changelog or roadmap

Do not silently change column names or semantics.
