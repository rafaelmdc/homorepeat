# Validation

## Purpose

This document describes the current Phase 5 validation entrypoint for completed pipeline runs.

---

## Main CLI

Use:

```bash
python3 bin/validate_phase5_outputs.py \
  --taxonomy-tsv results/<run>/acquisition/acquisition_artifacts/taxonomy.tsv \
  --genomes-tsv results/<run>/acquisition/acquisition_artifacts/genomes.tsv \
  --proteins-tsv results/<run>/acquisition/acquisition_artifacts/proteins.tsv \
  --call-tsv results/<run>/calls/pure/Q/finalized_pure_Q/final_pure_Q_calls.tsv \
  --call-tsv results/<run>/calls/threshold/Q/finalized_threshold_Q/final_threshold_Q_calls.tsv \
  --summary-tsv results/<run>/reports/summary_by_taxon.tsv \
  --regression-tsv results/<run>/reports/regression_input.tsv \
  --acquisition-validation-json results/<run>/acquisition/acquisition_artifacts/acquisition_validation.json \
  --sqlite-validation-json results/<run>/sqlite/sqlite_validation.json \
  --outpath results/<run>/reports/validation_report.json
```

---

## Current status behavior

- `pass`
  All implemented reconciliation checks passed.

- `warn`
  Reconciliation checks passed, but an upstream optional status such as acquisition validation reported `warn`.

- `fail`
  One or more reconciliation checks failed. This should be treated as a real regression until explained.

---

## What this validates today

- taxonomy tree completeness for referenced taxa
- summary-table reconciliation against finalized calls
- regression-table reconciliation against finalized calls
- SQLite validation status when provided
- acquisition validation status when provided

It does not replace human scientific review. It is the first concrete gate, not the last one.
