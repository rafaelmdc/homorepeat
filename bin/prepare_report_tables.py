#!/usr/bin/env python3
"""Prepare minimal report-prep artifacts from finalized summary tables."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.summaries import build_echarts_options, serialize_echarts_options  # noqa: E402
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary-tsv", required=True, help="Path to summary_by_taxon.tsv")
    parser.add_argument("--regression-tsv", required=True, help="Path to regression_input.tsv")
    parser.add_argument("--outdir", required=True, help="Output directory for report-prep artifacts")
    parser.add_argument("--log-file", help="Reserved log file path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary_rows = read_tsv(args.summary_tsv, required_columns=SUMMARY_REQUIRED)
    regression_rows = read_tsv(args.regression_tsv, required_columns=REGRESSION_REQUIRED)
    options = build_echarts_options(summary_rows, regression_rows)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "echarts_options.json").write_text(
        serialize_echarts_options(options),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(3) from exc
