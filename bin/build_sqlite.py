#!/usr/bin/env python3
"""Assemble validated flat outputs into the final HomoRepeat SQLite artifact."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.sqlite_build import (  # noqa: E402
    GENOMES_FIELDNAMES,
    PROTEINS_FIELDNAMES,
    SEQUENCES_FIELDNAMES,
    TAXONOMY_FIELDNAMES,
    build_sqlite_database,
    load_import_rows,
    validate_repeat_call_rows,
    validate_run_params_rows,
    validate_unique_keys,
    write_sqlite_validation,
)
from lib.repeat_features import CALL_FIELDNAMES  # noqa: E402
from lib.run_params import RUN_PARAM_FIELDNAMES  # noqa: E402
from lib.tsv_io import ContractError  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taxonomy-tsv", required=True, help="Path to canonical taxonomy.tsv")
    parser.add_argument("--genomes-tsv", required=True, help="Path to canonical genomes.tsv")
    parser.add_argument("--sequences-tsv", required=True, help="Path to canonical sequences.tsv")
    parser.add_argument("--proteins-tsv", required=True, help="Path to canonical proteins.tsv")
    parser.add_argument(
        "--call-tsv",
        action="append",
        default=[],
        help="Path to one call table to import into repeat_calls",
    )
    parser.add_argument(
        "--run-params-tsv",
        action="append",
        default=[],
        help="Path to one run_params.tsv fragment",
    )
    parser.add_argument(
        "--schema-sql",
        default=str(REPO_ROOT / "assets" / "sql" / "schema.sql"),
        help="Path to the SQLite schema SQL file",
    )
    parser.add_argument(
        "--indexes-sql",
        default=str(REPO_ROOT / "assets" / "sql" / "indexes.sql"),
        help="Path to the SQLite indexes SQL file",
    )
    parser.add_argument("--outdir", required=True, help="Output directory for the SQLite artifact")
    parser.add_argument("--log-file", help="Reserved log file path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    outdir = Path(args.outdir)
    sqlite_path = outdir / "homorepeat.sqlite"
    validation_path = outdir / "sqlite_validation.json"

    taxonomy_rows = load_import_rows(args.taxonomy_tsv, required_columns=TAXONOMY_FIELDNAMES)
    genomes_rows = load_import_rows(args.genomes_tsv, required_columns=GENOMES_FIELDNAMES)
    sequences_rows = load_import_rows(args.sequences_tsv, required_columns=SEQUENCES_FIELDNAMES)
    proteins_rows = load_import_rows(args.proteins_tsv, required_columns=PROTEINS_FIELDNAMES)

    validate_unique_keys(taxonomy_rows, "taxon_id", label="taxonomy")
    validate_unique_keys(genomes_rows, "genome_id", label="genomes")
    validate_unique_keys(sequences_rows, "sequence_id", label="sequences")
    validate_unique_keys(proteins_rows, "protein_id", label="proteins")

    run_params_rows: list[dict[str, str]] = []
    for path in args.run_params_tsv:
        run_params_rows.extend(load_import_rows(path, required_columns=RUN_PARAM_FIELDNAMES))
    validate_run_params_rows(run_params_rows)

    repeat_call_rows: list[dict[str, str]] = []
    for path in args.call_tsv:
        repeat_call_rows.extend(load_import_rows(path, required_columns=CALL_FIELDNAMES))
    validate_repeat_call_rows(repeat_call_rows)

    try:
        validation_payload = build_sqlite_database(
            sqlite_path,
            schema_sql_path=args.schema_sql,
            indexes_sql_path=args.indexes_sql,
            taxonomy_rows=taxonomy_rows,
            genomes_rows=genomes_rows,
            sequences_rows=sequences_rows,
            proteins_rows=proteins_rows,
            run_params_rows=run_params_rows,
            repeat_call_rows=repeat_call_rows,
        )
    except sqlite3.IntegrityError as exc:
        raise ContractError(f"SQLite import failed integrity checks: {exc}") from exc
    except sqlite3.DatabaseError as exc:
        raise ContractError(f"SQLite build failed: {exc}") from exc

    if validation_payload.get("status") != "pass":
        write_sqlite_validation(validation_path, validation_payload)
        raise ContractError("SQLite validation checks failed after import")

    write_sqlite_validation(validation_path, validation_payload)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(3) from exc
