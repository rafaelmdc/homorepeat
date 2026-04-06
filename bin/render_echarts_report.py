#!/usr/bin/env python3
"""Render one HTML report from finalized report-prep artifacts."""

from __future__ import annotations

import argparse
import shutil
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.report_render import (  # noqa: E402
    build_report_metadata,
    render_echarts_report,
    validate_echarts_options_bundle,
)
from lib.tsv_io import ContractError, read_tsv  # noqa: E402


SUMMARY_REQUIRED = [
    "method",
    "repeat_residue",
    "taxon_id",
    "taxon_name",
    "n_genomes",
    "n_proteins",
    "n_calls",
    "mean_length",
    "mean_purity",
]
REGRESSION_REQUIRED = [
    "method",
    "repeat_residue",
    "group_label",
    "repeat_length",
    "n_observations",
]
ECHARTS_BUNDLE_PATH = REPO_ROOT / "assets" / "vendor" / "echarts" / "echarts-5.5.1.min.js"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary-tsv", required=True, help="Path to summary_by_taxon.tsv")
    parser.add_argument("--regression-tsv", required=True, help="Path to regression_input.tsv")
    parser.add_argument("--options-json", required=True, help="Path to echarts_options.json")
    parser.add_argument("--outdir", required=True, help="Output directory for HTML report artifacts")
    parser.add_argument(
        "--report-title",
        default="HomoRepeat ECharts Report",
        help="HTML title to use in the rendered report",
    )
    parser.add_argument("--log-file", help="Reserved log file path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary_rows = read_tsv(args.summary_tsv, required_columns=SUMMARY_REQUIRED)
    regression_rows = read_tsv(args.regression_tsv, required_columns=REGRESSION_REQUIRED)
    options = validate_echarts_options_bundle(json.loads(Path(args.options_json).read_text(encoding="utf-8")))
    metadata = build_report_metadata(summary_rows, regression_rows)
    if not ECHARTS_BUNDLE_PATH.is_file():
        raise ContractError(f"missing local ECharts bundle: {ECHARTS_BUNDLE_PATH.relative_to(REPO_ROOT)}")
    html = render_echarts_report(options, metadata, title=args.report_title, echarts_asset_path="./echarts.min.js")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ECHARTS_BUNDLE_PATH, outdir / "echarts.min.js")
    (outdir / "echarts_report.html").write_text(html, encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ContractError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(3) from exc
