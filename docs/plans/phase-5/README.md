# Phase 5 Validation

## Purpose

Phase 5 is where the pipeline stops being merely runnable and becomes defensible.

The goal is to turn a successful run into a reviewed scientific artifact with explicit checks, explicit exceptions, and a small number of validation cases that can be rerun after method or acquisition changes.

---

## Current scope

Phase 5 should validate:
- taxonomy-tree materialization in `taxonomy.tsv`
- acquisition-to-detection continuity
- pure and threshold call behavior on representative cases
- summary and regression reconciliation
- SQLite relational integrity

Phase 5 does not yet mean:
- large-scale benchmarking across many taxa
- figure polish
- cloud or cluster performance tuning

---

## First implemented artifact

The first concrete Phase 5 artifact is:
- `bin/validate_phase5_outputs.py`

This script audits a completed run and writes:
- `validation_report.json`

It currently checks:
- every genome and call taxon is present in `taxonomy.tsv`
- taxonomy parent links form a valid explicit tree
- `summary_by_taxon.tsv` reconciles with the underlying calls
- `regression_input.tsv` reconciles with the underlying calls
- v1 codon-metric placeholder fields remain empty
- optional upstream `acquisition_validation.json` and `sqlite_validation.json` statuses

The script is designed to pass on `status=warn` when upstream acquisition is conservative but non-failing, and to hard-fail when reconciliation checks break.

---

## Recommended immediate validation set

1. One small human RefSeq run through Nextflow and Docker.
2. One reduced package fixture run in unit tests.
3. One explicit threshold behavior check after threshold changes.
4. One taxonomy-tree check confirming ancestors are materialized, not serialized into one lineage string.

---

## Acceptance direction

Phase 5 should be considered materially complete only when:
- the validation CLI is run on at least one real Nextflow result
- representative curated examples are documented and reproducible
- major scientific expectations are checked explicitly rather than inferred from the absence of crashes

See:
- `validation-checklist.md`
