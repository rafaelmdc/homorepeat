"""HTML report rendering helpers for ECharts report-prep outputs."""

from __future__ import annotations

import json
from html import escape
from typing import Sequence

from .tsv_io import ContractError


REQUIRED_CHART_BLOCKS = ("taxon_method_overview", "repeat_length_distribution")


def validate_echarts_options_bundle(options: object) -> dict[str, object]:
    """Validate the minimal ECharts bundle contract for report rendering."""

    if not isinstance(options, dict):
        raise ContractError("echarts_options.json must contain a JSON object")

    missing = [name for name in REQUIRED_CHART_BLOCKS if name not in options]
    if missing:
        missing_text = ", ".join(missing)
        raise ContractError(f"echarts_options.json is missing required chart blocks: {missing_text}")
    return options


def build_report_metadata(
    summary_rows: Sequence[dict[str, str]],
    regression_rows: Sequence[dict[str, str]],
) -> dict[str, object]:
    """Build a small provenance payload from finalized reporting tables."""

    methods = sorted({row.get("method", "") for row in summary_rows if row.get("method", "")})
    repeat_residues = sorted({row.get("repeat_residue", "") for row in summary_rows if row.get("repeat_residue", "")})
    taxa = sorted({row.get("taxon_name", "") for row in summary_rows if row.get("taxon_name", "")})
    total_calls = sum(int(row.get("n_calls", "0")) for row in summary_rows)
    return {
        "methods": methods,
        "repeat_residues": repeat_residues,
        "taxa": taxa,
        "n_taxa": len(taxa),
        "n_summary_rows": len(summary_rows),
        "n_regression_rows": len(regression_rows),
        "total_calls": total_calls,
    }


def render_echarts_report(
    options: dict[str, object],
    metadata: dict[str, object],
    *,
    title: str = "HomoRepeat ECharts Report",
    echarts_asset_path: str = "./echarts.min.js",
) -> str:
    """Render one minimal HTML report around a validated ECharts bundle."""

    validated_options = validate_echarts_options_bundle(options)
    ordered_chart_names = list(REQUIRED_CHART_BLOCKS) + sorted(
        name for name in validated_options if name not in REQUIRED_CHART_BLOCKS
    )
    chart_sections = []
    for chart_name in ordered_chart_names:
        chart_title = _extract_chart_title(validated_options.get(chart_name))
        chart_sections.append(
            "\n".join(
                [
                    '    <section class="chart-card">',
                    f"      <h2>{escape(chart_title)}</h2>",
                    f'      <div id="chart-{escape(chart_name)}" class="chart-panel"></div>',
                    "    </section>",
                ]
            )
        )

    options_json = json.dumps(validated_options, indent=2, sort_keys=True).replace("</", "<\\/")
    metadata_json = json.dumps(metadata, indent=2, sort_keys=True).replace("</", "<\\/")
    methods = ", ".join(metadata.get("methods", [])) or "none"
    repeat_residues = ", ".join(metadata.get("repeat_residues", [])) or "none"
    taxa = ", ".join(metadata.get("taxa", [])) or "none"

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escape(title)}</title>
    <style>
      :root {{
        color-scheme: light;
        --ink: #183153;
        --muted: #5b728a;
        --border: #d8e1ea;
        --panel: #f6f9fc;
        --page: #eef3f7;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
        color: var(--ink);
        background: linear-gradient(180deg, #f9fbfd 0%, var(--page) 100%);
      }}
      main {{
        width: min(1200px, calc(100% - 32px));
        margin: 24px auto 48px;
      }}
      .hero,
      .chart-card {{
        background: rgba(255, 255, 255, 0.92);
        border: 1px solid var(--border);
        border-radius: 18px;
        box-shadow: 0 16px 40px rgba(24, 49, 83, 0.08);
      }}
      .hero {{
        padding: 24px 28px;
        margin-bottom: 18px;
      }}
      h1 {{
        margin: 0 0 8px;
        font-size: 2rem;
        line-height: 1.1;
      }}
      .lede {{
        margin: 0;
        color: var(--muted);
      }}
      .facts {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 12px;
        margin: 20px 0 0;
        padding: 0;
        list-style: none;
      }}
      .facts li {{
        padding: 14px 16px;
        border-radius: 14px;
        background: var(--panel);
      }}
      .facts strong {{
        display: block;
        margin-bottom: 4px;
        font-size: 0.85rem;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.04em;
      }}
      .chart-stack {{
        display: grid;
        gap: 18px;
      }}
      .chart-card {{
        padding: 20px 22px;
      }}
      .chart-card h2 {{
        margin: 0 0 12px;
        font-size: 1.1rem;
      }}
      .chart-panel {{
        width: 100%;
        min-height: 460px;
      }}
      @media (max-width: 720px) {{
        main {{
          width: calc(100% - 20px);
          margin: 12px auto 28px;
        }}
        .hero,
        .chart-card {{
          padding: 16px;
          border-radius: 14px;
        }}
        .chart-panel {{
          min-height: 360px;
        }}
      }}
    </style>
    <script src="{escape(echarts_asset_path)}"></script>
  </head>
  <body>
    <main>
      <section class="hero">
        <h1>{escape(title)}</h1>
        <p class="lede">Rendered directly from finalized report-prep outputs. No biology is recomputed in the HTML layer.</p>
        <ul class="facts">
          <li><strong>Methods</strong><span>{escape(methods)}</span></li>
          <li><strong>Repeat Residues</strong><span>{escape(repeat_residues)}</span></li>
          <li><strong>Taxa</strong><span>{escape(taxa)}</span></li>
          <li><strong>Total Calls</strong><span>{int(metadata.get("total_calls", 0))}</span></li>
          <li><strong>Summary Rows</strong><span>{int(metadata.get("n_summary_rows", 0))}</span></li>
          <li><strong>Regression Rows</strong><span>{int(metadata.get("n_regression_rows", 0))}</span></li>
        </ul>
      </section>
      <div class="chart-stack">
{chr(10).join(chart_sections)}
      </div>
    </main>
    <script id="echarts-options" type="application/json">{options_json}</script>
    <script id="report-metadata" type="application/json">{metadata_json}</script>
    <script>
      const options = JSON.parse(document.getElementById('echarts-options').textContent);
      const charts = [];
      for (const [chartName, chartOptions] of Object.entries(options)) {{
        const node = document.getElementById(`chart-${{chartName}}`);
        if (!node) {{
          continue;
        }}
        const chart = echarts.init(node);
        chart.setOption(chartOptions);
        charts.push(chart);
      }}
      window.addEventListener('resize', () => {{
        for (const chart of charts) {{
          chart.resize();
        }}
      }});
    </script>
  </body>
</html>
"""


def _extract_chart_title(chart_options: object) -> str:
    if not isinstance(chart_options, dict):
        return "Untitled Chart"
    title_block = chart_options.get("title")
    if isinstance(title_block, dict):
        title_text = title_block.get("text")
        if isinstance(title_text, str) and title_text:
            return title_text
    return "Untitled Chart"
