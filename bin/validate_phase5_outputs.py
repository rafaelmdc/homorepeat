#!/usr/bin/env python3
"""Validate a completed HomoRepeat run against the Phase 5 acceptance checks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.phase5_validation import (  # noqa: E402
    build_validation_report,
    require_validation_pass,
    write_validation_report,
)
from lib.repeat_features import CALL_FIELDNAMES  # noqa: E402
from lib.tsv_io import ContractError, read_tsv  # noqa: E402


TAXONOMY_REQUIRED = ["taxon_id", "taxon_name", "parent_taxon_id", "rank", "source"]
GENOMES_REQUIRED = ["genome_id", "taxon_id"]
PROTEINS_REQUIRED = ["protein_id", "genome_id", "protein_length", "taxon_id"]
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
    "median_length",
    "max_length",
    "mean_start_fraction",
    "codon_metric_name",
    "mean_codon_metric",
]
REGRESSION_REQUIRED = [
    "method",
    "repeat_residue",
    "group_label",
    "repeat_length",
    "n_observations",
    "codon_metric_name",
    "mean_codon_metric",
    "filtered_max_length",
    "transformed_codon_metric",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taxonomy-tsv", required=True, help="Path to canonical taxonomy.tsv")
    parser.add_argument("--genomes-tsv", required=True, help="Path to canonical genomes.tsv")
    parser.add_argument("--proteins-tsv", required=True, help="Path to canonical proteins.tsv")
    parser.add_argument(
        "--call-tsv",
        action="append",
        default=[],
        help="Path to one finalized call table. Repeat for multiple methods/residues.",
    )
    parser.add_argument("--summary-tsv", required=True, help="Path to summary_by_taxon.tsv")
    parser.add_argument("--regression-tsv", required=True, help="Path to regression_input.tsv")
    parser.add_argument(
        "--acquisition-validation-json",
        help="Optional path to acquisition_validation.json",
    )
    parser.add_argument(
        "--sqlite-validation-json",
        help="Optional path to sqlite_validation.json",
    )
    parser.add_argument("--outpath", required=True, help="Output path for validation_report.json")
    parser.add_argument("--log-file", help="Reserved log file path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.call_tsv:
        raise ContractError("At least one --call-tsv input is required")

    taxonomy_rows = read_tsv(args.taxonomy_tsv, required_columns=TAXONOMY_REQUIRED)
    genomes_rows = read_tsv(args.genomes_tsv, required_columns=GENOMES_REQUIRED)
    proteins_rows = read_tsv(args.proteins_tsv, required_columns=PROTEINS_REQUIRED)
    summary_rows = read_tsv(args.summary_tsv, required_columns=SUMMARY_REQUIRED)
    regression_rows = read_tsv(args.regression_tsv, required_columns=REGRESSION_REQUIRED)

    call_rows: list[dict[str, str]] = []
    for path in args.call_tsv:
        call_rows.extend(read_tsv(path, required_columns=CALL_FIELDNAMES))

    acquisition_status = _read_status(args.acquisition_validation_json)
    sqlite_status = _read_status(args.sqlite_validation_json)

    payload = build_validation_report(
        taxonomy_rows=taxonomy_rows,
        genomes_rows=genomes_rows,
        proteins_rows=proteins_rows,
        call_rows=call_rows,
        summary_rows=summary_rows,
        regression_rows=regression_rows,
        acquisition_validation_status=acquisition_status,
        sqlite_validation_status=sqlite_status,
    )
    write_validation_report(args.outpath, payload)
    require_validation_pass(payload)
    return 0


def _read_status(path_text: str | None) -> str:
    if not path_text:
        return ""
    payload = json.loads(Path(path_text).read_text(encoding="utf-8"))
    return str(payload.get("status", ""))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(3) from exc
