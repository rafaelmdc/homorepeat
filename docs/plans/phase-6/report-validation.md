# Report Validation

## Required checks

The Phase 6 renderer is considered valid when:
- `echarts_options.json` is a JSON object
- required chart blocks are present
- `echarts_report.html` is created
- the HTML contains a container for each required chart block
- the renderer exits cleanly on valid inputs

## Failure policy

Hard-fail when:
- `echarts_options.json` is invalid JSON
- a required chart block is missing
- finalized summary tables are missing required columns

## Minimal runtime validation

Validate in two layers:
- unit/CLI validation for `render_echarts_report.py`
- one workflow-level run that publishes:
  - `report_prep/echarts_options.json`
  - `report_prep/echarts_report.html`

## Current live expectation

The reporting layer should remain deterministic.
If upstream acquisition is `warn`, the HTML report may still be generated as long as the finalized reporting tables are valid.
