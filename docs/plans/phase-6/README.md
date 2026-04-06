# Phase 6 Reference

This folder defines the first real reporting implementation layer on top of the finalized Phase 4 outputs.

Current goal:
- turn report-prep JSON into one inspectable HTML report
- keep chart derivation in Python
- keep the HTML layer renderer-only

Current implementation files:
- [render_echarts_report.py](../../../bin/render_echarts_report.py)
- [report_render.py](../../../lib/report_render.py)
- [render_echarts_report.nf](../../../modules/local/reporting/render_echarts_report.nf)

Current workflow boundary:
- [prepare_report_tables.py](../../../bin/prepare_report_tables.py) builds `echarts_options.json`
- [render_echarts_report.py](../../../bin/render_echarts_report.py) consumes the finalized summary tables plus the options bundle and emits `echarts_report.html`
- the renderer also copies a pinned local ECharts bundle into the report directory so the HTML works offline

Current first-pass chart scope:
- `taxon_method_overview`
- `repeat_length_distribution`

Deferred from this pass:
- static image export
- multi-page reporting
- residue-composition chart families
- frontend-only biological transformations
