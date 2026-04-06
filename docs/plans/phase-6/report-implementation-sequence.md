# Report Implementation Sequence

## Order

1. Keep chart derivation in Python.
   - `prepare_report_tables.py` owns `echarts_options.json`

2. Add a standalone renderer CLI.
   - `render_echarts_report.py` reads finalized summary tables plus the JSON bundle
   - it emits one `echarts_report.html`

3. Validate the renderer locally.
   - required chart blocks must exist
   - the HTML must contain one chart container per chart block
   - metadata should reflect the finalized summary tables

4. Wrap the renderer in Nextflow.
   - one isolated reporting process
   - no new biological logic in the workflow layer

## Boundaries

Keep these responsibilities separate:
- `export_summary_tables.py`: summary and regression tables
- `prepare_report_tables.py`: ECharts option generation
- `render_echarts_report.py`: HTML rendering only

Do not merge these into one mixed reporting script unless the contract changes explicitly.
