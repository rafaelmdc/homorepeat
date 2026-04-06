# Phase 5 Checklist

## Run-level validation

- run one accession-driven Docker workflow end to end
- confirm `acquisition_validation.json` is `pass` or `warn`, never `fail`
- confirm `sqlite_validation.json` is `pass`
- run `bin/validate_phase5_outputs.py`
- inspect `validation_report.json`

## Taxonomy validation

- confirm `taxonomy.tsv` contains explicit ancestor rows
- confirm `parent_taxon_id` links form a valid tree
- confirm all genome taxids exist in `taxonomy.tsv`
- confirm all call taxids exist in `taxonomy.tsv`

## Detection validation

- confirm pure contiguous behavior on representative examples
- confirm threshold sliding-window behavior on representative examples
- confirm pure and threshold remain schema-compatible
- confirm no method-specific column drift in finalized calls

## Reporting validation

- confirm `summary_by_taxon.tsv` reconciles with raw calls
- confirm `regression_input.tsv` reconciles with raw calls
- confirm taxon labels in reporting come from `taxonomy.tsv`
- confirm v1 codon metric placeholders remain empty unless the contract changes

## SQLite validation

- confirm row counts reconcile with flat imports
- confirm foreign-key reachability checks pass
- confirm taxonomy ancestors import cleanly into SQLite

## Remaining manual review

- inspect a few longest tracts per method
- inspect one or two expected negative cases
- confirm the chosen validation taxon still produces biologically plausible output counts
