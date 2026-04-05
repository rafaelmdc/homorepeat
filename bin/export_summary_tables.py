#!/usr/bin/env python3
"""Export residue-neutral summary tables from finalized call outputs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.summaries import (  # noqa: E402
    REGRESSION_FIELDNAMES,
    SUMMARY_FIELDNAMES,
    build_regression_input,
    build_summary_by_taxon,
)
from lib.tsv_io import ContractError, read_tsv, write_tsv  # noqa: E402


PROTEINS_REQUIRED = [
    "protein_id",
    "sequence_id",
    "genome_id",
    "protein_name",
    "protein_length",
    "protein_path",
]
TAXONOMY_REQUIRED = ["taxon_id", "taxon_name", "parent_taxon_id", "rank", "lineage", "source"]
CALLS_REQUIRED = [
    "call_id",
    "method",
    "genome_id",
    "taxon_id",
    "sequence_id",
    "protein_id",
    "start",
    "end",
    "length",
    "repeat_residue",
    "repeat_count",
    "non_repeat_count",
    "purity",
    "aa_sequence",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taxonomy-tsv", required=True, help="Path to canonical taxonomy.tsv")
    parser.add_argument("--proteins-tsv", required=True, help="Path to canonical proteins.tsv")
    parser.add_argument(
        "--call-tsv",
        action="append",
        default=[],
        help="Path to one finalized call table",
    )
    parser.add_argument("--outdir", required=True, help="Output directory for summary tables")
    parser.add_argument("--log-file", help="Reserved log file path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.call_tsv:
        raise ContractError("At least one --call-tsv input is required")

    taxonomy_rows = read_tsv(args.taxonomy_tsv, required_columns=TAXONOMY_REQUIRED)
    proteins_rows = read_tsv(args.proteins_tsv, required_columns=PROTEINS_REQUIRED)
    call_rows: list[dict[str, str]] = []
    for path in args.call_tsv:
        call_rows.extend(read_tsv(path, required_columns=CALLS_REQUIRED))

    outdir = Path(args.outdir)
    summary_rows = build_summary_by_taxon(call_rows, proteins_rows, taxonomy_rows)
    regression_rows = build_regression_input(call_rows, taxonomy_rows)

    write_tsv(outdir / "summary_by_taxon.tsv", summary_rows, fieldnames=SUMMARY_FIELDNAMES)
    write_tsv(outdir / "regression_input.tsv", regression_rows, fieldnames=REGRESSION_FIELDNAMES)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(3) from exc
