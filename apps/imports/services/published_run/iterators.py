from __future__ import annotations

import csv
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any

from .contracts import (
    CODON_USAGE_REQUIRED_COLUMNS,
    ACCESSION_CALL_COUNT_REQUIRED_COLUMNS,
    ACCESSION_STATUS_REQUIRED_COLUMNS,
    DOWNLOAD_MANIFEST_REQUIRED_COLUMNS,
    GENOME_REQUIRED_COLUMNS,
    ImportContractError,
    NORMALIZATION_WARNING_REQUIRED_COLUMNS,
    PROTEIN_REQUIRED_COLUMNS,
    REPEAT_CALL_REQUIRED_COLUMNS,
    RUN_PARAM_REQUIRED_COLUMNS,
    SEQUENCE_REQUIRED_COLUMNS,
    TAXONOMY_REQUIRED_COLUMNS,
    VALID_METHODS,
)


def iter_taxonomy_rows(path: Path):
    for row in _iter_tsv(path, TAXONOMY_REQUIRED_COLUMNS):
        yield {
            "taxon_id": _parse_int(row, "taxon_id", path),
            "taxon_name": _require_row_value(row, "taxon_name", path),
            "parent_taxon_id": _parse_optional_int(row, "parent_taxon_id", path),
            "rank": _string_value(row.get("rank")),
            "source": _string_value(row.get("source")),
        }


def iter_genome_rows(path: Path, *, batch_id: str):
    for row in _iter_tsv(path, GENOME_REQUIRED_COLUMNS):
        yield {
            "genome_id": _require_row_value(row, "genome_id", path),
            "batch_id": batch_id,
            "source": _require_row_value(row, "source", path),
            "accession": _require_row_value(row, "accession", path),
            "genome_name": _require_row_value(row, "genome_name", path),
            "assembly_type": _require_row_value(row, "assembly_type", path),
            "taxon_id": _parse_int(row, "taxon_id", path),
            "assembly_level": _string_value(row.get("assembly_level")),
            "species_name": _string_value(row.get("species_name")),
            "notes": _string_value(row.get("notes")),
        }


def iter_sequence_rows(path: Path, *, batch_id: str):
    for row in _iter_tsv(path, SEQUENCE_REQUIRED_COLUMNS):
        yield {
            "sequence_id": _require_row_value(row, "sequence_id", path),
            "batch_id": batch_id,
            "genome_id": _require_row_value(row, "genome_id", path),
            "sequence_name": _require_row_value(row, "sequence_name", path),
            "sequence_length": _parse_int(row, "sequence_length", path),
            "gene_symbol": _string_value(row.get("gene_symbol")),
            "transcript_id": _string_value(row.get("transcript_id")),
            "isoform_id": _string_value(row.get("isoform_id")),
            "assembly_accession": _string_value(row.get("assembly_accession")),
            "taxon_id": _parse_optional_int(row, "taxon_id", path),
            "source_record_id": _string_value(row.get("source_record_id")),
            "protein_external_id": _string_value(row.get("protein_external_id")),
            "translation_table": _string_value(row.get("translation_table")),
            "gene_group": _string_value(row.get("gene_group")),
            "linkage_status": _string_value(row.get("linkage_status")),
            "partial_status": _string_value(row.get("partial_status")),
        }


def iter_protein_rows(path: Path, *, batch_id: str):
    for row in _iter_tsv(path, PROTEIN_REQUIRED_COLUMNS):
        yield {
            "protein_id": _require_row_value(row, "protein_id", path),
            "batch_id": batch_id,
            "sequence_id": _require_row_value(row, "sequence_id", path),
            "genome_id": _require_row_value(row, "genome_id", path),
            "protein_name": _require_row_value(row, "protein_name", path),
            "protein_length": _parse_int(row, "protein_length", path),
            "gene_symbol": _string_value(row.get("gene_symbol")),
            "translation_method": _string_value(row.get("translation_method")),
            "translation_status": _string_value(row.get("translation_status")),
            "assembly_accession": _string_value(row.get("assembly_accession")),
            "taxon_id": _parse_optional_int(row, "taxon_id", path),
            "gene_group": _string_value(row.get("gene_group")),
            "protein_external_id": _string_value(row.get("protein_external_id")),
        }


def iter_download_manifest_rows(path: Path, *, batch_id: str):
    for row in _iter_tsv(path, DOWNLOAD_MANIFEST_REQUIRED_COLUMNS):
        row_batch_id = _require_row_value(row, "batch_id", path)
        _ensure_matching_batch_id(path, expected_batch_id=batch_id, row_batch_id=row_batch_id)
        yield {
            "batch_id": row_batch_id,
            "assembly_accession": _require_row_value(row, "assembly_accession", path),
            "download_status": _require_row_value(row, "download_status", path),
            "package_mode": _require_row_value(row, "package_mode", path),
            "download_path": _string_value(row.get("download_path")),
            "rehydrated_path": _string_value(row.get("rehydrated_path")),
            "checksum": _string_value(row.get("checksum")),
            "file_size_bytes": _parse_optional_int_value(row.get("file_size_bytes"), "file_size_bytes", path),
            "download_started_at": _parse_optional_timestamp(
                row.get("download_started_at"),
                "download_started_at",
                path,
            ),
            "download_finished_at": _parse_optional_timestamp(
                row.get("download_finished_at"),
                "download_finished_at",
                path,
            ),
            "notes": _string_value(row.get("notes")),
        }


def iter_normalization_warning_rows(path: Path, *, batch_id: str):
    for row in _iter_tsv(path, NORMALIZATION_WARNING_REQUIRED_COLUMNS):
        row_batch_id = _require_row_value(row, "batch_id", path)
        _ensure_matching_batch_id(path, expected_batch_id=batch_id, row_batch_id=row_batch_id)
        yield {
            "warning_code": _require_row_value(row, "warning_code", path),
            "warning_scope": _require_row_value(row, "warning_scope", path),
            "warning_message": _require_row_value(row, "warning_message", path),
            "batch_id": row_batch_id,
            "genome_id": _string_value(row.get("genome_id")),
            "sequence_id": _string_value(row.get("sequence_id")),
            "protein_id": _string_value(row.get("protein_id")),
            "assembly_accession": _string_value(row.get("assembly_accession")),
            "source_file": _string_value(row.get("source_file")),
            "source_record_id": _string_value(row.get("source_record_id")),
        }


def iter_run_parameter_rows(path: Path):
    for row in _iter_tsv(path, RUN_PARAM_REQUIRED_COLUMNS):
        method = _require_row_value(row, "method", path)
        if method not in VALID_METHODS:
            raise ImportContractError(f"{path} contains an invalid method: {method!r}")
        yield {
            "method": method,
            "repeat_residue": _require_row_value(row, "repeat_residue", path),
            "param_name": _require_row_value(row, "param_name", path),
            "param_value": _require_row_value(row, "param_value", path),
        }


def iter_accession_status_rows(path: Path):
    for row in _iter_tsv(path, ACCESSION_STATUS_REQUIRED_COLUMNS):
        yield {
            "assembly_accession": _require_row_value(row, "assembly_accession", path),
            "batch_id": _require_row_value(row, "batch_id", path),
            "download_status": _require_row_value(row, "download_status", path),
            "normalize_status": _require_row_value(row, "normalize_status", path),
            "translate_status": _require_row_value(row, "translate_status", path),
            "detect_status": _require_row_value(row, "detect_status", path),
            "finalize_status": _require_row_value(row, "finalize_status", path),
            "terminal_status": _require_row_value(row, "terminal_status", path),
            "failure_stage": _string_value(row.get("failure_stage")),
            "failure_reason": _string_value(row.get("failure_reason")),
            "n_genomes": _parse_int(row, "n_genomes", path),
            "n_proteins": _parse_int(row, "n_proteins", path),
            "n_repeat_calls": _parse_int(row, "n_repeat_calls", path),
            "notes": _string_value(row.get("notes")),
        }


def iter_accession_call_count_rows(path: Path):
    for row in _iter_tsv(path, ACCESSION_CALL_COUNT_REQUIRED_COLUMNS):
        method = _require_row_value(row, "method", path)
        if method not in VALID_METHODS:
            raise ImportContractError(f"{path} contains an invalid method: {method!r}")
        assembly_accession = _require_row_value(row, "assembly_accession", path)
        repeat_residue = _require_row_value(row, "repeat_residue", path)
        yield {
            "unique_key": f"{assembly_accession}::{method}::{repeat_residue}",
            "assembly_accession": assembly_accession,
            "batch_id": _require_row_value(row, "batch_id", path),
            "method": method,
            "repeat_residue": repeat_residue,
            "detect_status": _require_row_value(row, "detect_status", path),
            "finalize_status": _require_row_value(row, "finalize_status", path),
            "n_repeat_calls": _parse_int(row, "n_repeat_calls", path),
        }


def iter_repeat_call_rows(path: Path):
    for row in _iter_tsv(path, REPEAT_CALL_REQUIRED_COLUMNS):
        method = _require_row_value(row, "method", path)
        start = _parse_int(row, "start", path)
        end = _parse_int(row, "end", path)
        purity = _parse_float(row, "purity", path)

        if method not in VALID_METHODS:
            raise ImportContractError(f"{path} contains an invalid method: {method!r}")
        if end < start:
            raise ImportContractError(f"{path} contains a repeat call with end < start")
        if purity < 0 or purity > 1:
            raise ImportContractError(f"{path} contains a repeat call with purity outside 0..1")

        yield {
            "call_id": _require_row_value(row, "call_id", path),
            "method": method,
            "genome_id": _require_row_value(row, "genome_id", path),
            "taxon_id": _parse_int(row, "taxon_id", path),
            "sequence_id": _require_row_value(row, "sequence_id", path),
            "protein_id": _require_row_value(row, "protein_id", path),
            "start": start,
            "end": end,
            "length": _parse_int(row, "length", path),
            "repeat_residue": _require_row_value(row, "repeat_residue", path),
            "repeat_count": _parse_int(row, "repeat_count", path),
            "non_repeat_count": _parse_int(row, "non_repeat_count", path),
            "purity": purity,
            "aa_sequence": _require_row_value(row, "aa_sequence", path),
            "codon_sequence": _string_value(row.get("codon_sequence")),
            "codon_metric_name": _string_value(row.get("codon_metric_name")),
            "codon_metric_value": _string_value(row.get("codon_metric_value")),
            "window_definition": _string_value(row.get("window_definition")),
            "template_name": _string_value(row.get("template_name")),
            "merge_rule": _string_value(row.get("merge_rule")),
            "score": _string_value(row.get("score")),
        }


def iter_codon_usage_rows(path: Path):
    for row in _iter_tsv(path, CODON_USAGE_REQUIRED_COLUMNS):
        method = _require_row_value(row, "method", path)
        codon_count = _parse_int(row, "codon_count", path)
        codon_fraction = _parse_float(row, "codon_fraction", path)

        if method not in VALID_METHODS:
            raise ImportContractError(f"{path} contains an invalid method: {method!r}")
        if codon_count < 0:
            raise ImportContractError(f"{path} contains a negative codon_count")
        if not isfinite(codon_fraction) or codon_fraction < 0 or codon_fraction > 1:
            raise ImportContractError(f"{path} contains a codon_fraction outside 0..1")

        yield {
            "call_id": _require_row_value(row, "call_id", path),
            "method": method,
            "repeat_residue": _require_row_value(row, "repeat_residue", path),
            "sequence_id": _require_row_value(row, "sequence_id", path),
            "protein_id": _require_row_value(row, "protein_id", path),
            "amino_acid": _require_row_value(row, "amino_acid", path),
            "codon": _require_row_value(row, "codon", path),
            "codon_count": codon_count,
            "codon_fraction": codon_fraction,
        }


def _iter_tsv(path: Path, required_columns: list[str]):
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        missing = [column for column in required_columns if column not in (reader.fieldnames or [])]
        if missing:
            raise ImportContractError(f"{path} is missing required columns: {', '.join(missing)}")
        for row in reader:
            yield dict(row)


def _require_row_value(row: dict[str, str], key: str, path: Path) -> str:
    value = _string_value(row.get(key))
    if not value:
        raise ImportContractError(f"{path} contains an empty required value for {key!r}")
    return value


def _parse_int(row: dict[str, str], key: str, path: Path) -> int:
    value = _require_row_value(row, key, path)
    try:
        return int(value)
    except ValueError as exc:
        raise ImportContractError(f"{path} contains a non-integer value for {key!r}") from exc


def _parse_optional_int(row: dict[str, str], key: str, path: Path) -> int | None:
    value = _string_value(row.get(key))
    if not value:
        return None
    return _parse_optional_int_value(value, key, path)


def _parse_optional_int_value(value: Any, field_name: str, path: Path) -> int | None:
    text = _string_value(value)
    if not text:
        return None
    try:
        return int(text)
    except ValueError as exc:
        raise ImportContractError(f"{path} contains a non-integer value for {field_name!r}") from exc


def _parse_float(row: dict[str, str], key: str, path: Path) -> float:
    value = _require_row_value(row, key, path)
    try:
        return float(value)
    except ValueError as exc:
        raise ImportContractError(f"{path} contains a non-numeric value for {key!r}") from exc


def _parse_timestamp(value: Any, field_name: str) -> datetime:
    text = _string_value(value)
    if not text:
        raise ImportContractError(f"Run manifest contains an empty required value for {field_name!r}")
    return _parse_timestamp_value(text, field_name)


def _parse_optional_timestamp(value: Any, field_name: str, path: Path) -> datetime | None:
    text = _string_value(value)
    if not text:
        return None
    try:
        return _parse_timestamp_value(text, field_name)
    except ImportContractError as exc:
        raise ImportContractError(f"{path} contains an invalid timestamp for {field_name!r}") from exc


def _parse_timestamp_value(text: str, field_name: str) -> datetime:
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ImportContractError(
            f"Run manifest contains an invalid timestamp for {field_name!r}"
        ) from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _ensure_matching_batch_id(path: Path, *, expected_batch_id: str, row_batch_id: str) -> None:
    if row_batch_id != expected_batch_id:
        raise ImportContractError(
            f"{path} contains batch_id={row_batch_id!r}, expected {expected_batch_id!r}"
        )


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
