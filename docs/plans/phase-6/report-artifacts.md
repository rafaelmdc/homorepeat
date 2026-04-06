# Report Artifacts

## Purpose

Phase 6 adds one human-facing report artifact without changing the scientific contracts that produce reporting tables.

## Inputs

The HTML renderer consumes only finalized reporting artifacts:
- `summary_by_taxon.tsv`
- `regression_input.tsv`
- `echarts_options.json`

It does not:
- re-read raw call tables
- recompute biology
- invent new groupings in JavaScript

## Outputs

Current first-pass report artifacts:
- `reports/summary_by_taxon.tsv`
- `reports/regression_input.tsv`
- `report_prep/echarts_options.json`
- `report_prep/echarts_report.html`
- `report_prep/echarts.min.js`

## Bundle behavior

`echarts_report.html`:
- renders the required chart blocks already present in `echarts_options.json`
- includes a small provenance summary derived from the finalized summary tables
- remains reproducible from stable TSV/JSON inputs
- references the local `echarts.min.js` bundle shipped beside it

Current required chart blocks:
- `taxon_method_overview`
- `repeat_length_distribution`

## Deferred artifacts

Not part of the first Phase 6 pass:
- PNG export
- SVG export
- PDF export
- static snapshots for publications
