from __future__ import annotations

import csv
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


GENOME_REQUIRED_COLUMNS = [
    "genome_id",
    "source",
    "accession",
    "genome_name",
    "assembly_type",
    "taxon_id",
]
TAXONOMY_REQUIRED_COLUMNS = [
    "taxon_id",
    "taxon_name",
    "parent_taxon_id",
    "rank",
    "source",
]
SEQUENCE_REQUIRED_COLUMNS = [
    "sequence_id",
    "genome_id",
    "sequence_name",
    "sequence_length",
]
PROTEIN_REQUIRED_COLUMNS = [
    "protein_id",
    "sequence_id",
    "genome_id",
    "protein_name",
    "protein_length",
]
DOWNLOAD_MANIFEST_REQUIRED_COLUMNS = [
    "batch_id",
    "assembly_accession",
    "download_status",
    "package_mode",
    "download_path",
    "rehydrated_path",
    "checksum",
    "file_size_bytes",
    "download_started_at",
    "download_finished_at",
    "notes",
]
NORMALIZATION_WARNING_REQUIRED_COLUMNS = [
    "warning_code",
    "warning_scope",
    "warning_message",
    "batch_id",
    "genome_id",
    "sequence_id",
    "protein_id",
    "assembly_accession",
    "source_file",
    "source_record_id",
]
ACCESSION_STATUS_REQUIRED_COLUMNS = [
    "assembly_accession",
    "batch_id",
    "download_status",
    "normalize_status",
    "translate_status",
    "detect_status",
    "finalize_status",
    "terminal_status",
    "failure_stage",
    "failure_reason",
    "n_genomes",
    "n_proteins",
    "n_repeat_calls",
    "notes",
]
ACCESSION_CALL_COUNT_REQUIRED_COLUMNS = [
    "assembly_accession",
    "batch_id",
    "method",
    "repeat_residue",
    "detect_status",
    "finalize_status",
    "n_repeat_calls",
]
RUN_PARAM_REQUIRED_COLUMNS = ["method", "repeat_residue", "param_name", "param_value"]
REPEAT_CALL_REQUIRED_COLUMNS = [
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
MANIFEST_REQUIRED_KEYS = [
    "run_id",
    "status",
    "started_at_utc",
    "finished_at_utc",
    "profile",
    "acquisition_publish_mode",
    "git_revision",
    "inputs",
    "paths",
    "params",
    "enabled_methods",
    "repeat_residues",
    "artifacts",
]
ACQUISITION_VALIDATION_REQUIRED_KEYS = [
    "status",
    "scope",
    "counts",
    "checks",
    "failed_accessions",
    "warning_summary",
    "notes",
]
ACQUISITION_VALIDATION_COUNT_KEYS = [
    "n_selected_assemblies",
    "n_downloaded_packages",
    "n_genomes",
    "n_sequences",
    "n_proteins",
    "n_warning_rows",
]
VALID_METHODS = {"pure", "threshold", "seed_extend"}


class ImportContractError(ValueError):
    """Raised when a published run does not satisfy the import contract."""


@dataclass(frozen=True)
class BatchArtifactPaths:
    batch_id: str
    batch_root: Path
    genomes_tsv: Path
    taxonomy_tsv: Path
    sequences_tsv: Path
    proteins_tsv: Path
    cds_fna: Path
    proteins_faa: Path
    download_manifest_tsv: Path
    normalization_warnings_tsv: Path
    acquisition_validation_json: Path


@dataclass(frozen=True)
class RepeatLinkedIds:
    genome_ids: tuple[str, ...]
    sequence_ids: tuple[str, ...]
    protein_ids: tuple[str, ...]


@dataclass(frozen=True)
class ParsedAcquisitionBatch:
    artifact_paths: BatchArtifactPaths
    acquisition_validation: dict[str, Any]
    total_genomes: int
    total_sequences: int
    total_proteins: int
    total_download_manifest_rows: int
    total_normalization_warning_rows: int
    total_repeat_calls: int
    total_repeat_linked_genomes: int
    total_repeat_linked_sequences: int
    total_repeat_linked_proteins: int


@dataclass(frozen=True)
class RequiredArtifactPaths:
    publish_root: Path
    manifest: Path
    acquisition_batches_root: Path
    acquisition_batches: tuple[BatchArtifactPaths, ...]
    accession_status_tsv: Path
    accession_call_counts_tsv: Path
    run_params_tsv: Path
    repeat_calls_tsv: Path


@dataclass(frozen=True)
class InspectedPublishedRun:
    artifact_paths: RequiredArtifactPaths
    manifest: dict[str, Any]
    pipeline_run: dict[str, Any]


@dataclass(frozen=True)
class ParsedPublishedRun:
    artifact_paths: RequiredArtifactPaths
    manifest: dict[str, Any]
    pipeline_run: dict[str, Any]
    batch_summaries: tuple[ParsedAcquisitionBatch, ...]
    taxonomy_rows: list[dict[str, Any]]
    genome_rows: list[dict[str, Any]]
    sequence_rows: list[dict[str, Any]]
    protein_rows: list[dict[str, Any]]
    download_manifest_rows: list[dict[str, Any]]
    normalization_warning_rows: list[dict[str, Any]]
    accession_status_rows: list[dict[str, Any]]
    accession_call_count_rows: list[dict[str, Any]]
    run_parameter_rows: list[dict[str, Any]]
    repeat_call_rows: list[dict[str, Any]]
    repeat_linked_ids: RepeatLinkedIds


def resolve_required_artifacts(publish_root: Path | str) -> RequiredArtifactPaths:
    root = Path(publish_root).resolve()
    if not root.is_dir():
        raise ImportContractError(f"Publish root does not exist or is not a directory: {root}")

    paths = RequiredArtifactPaths(
        publish_root=root,
        manifest=root / "metadata" / "run_manifest.json",
        acquisition_batches_root=root / "acquisition" / "batches",
        acquisition_batches=(),
        accession_status_tsv=root / "status" / "accession_status.tsv",
        accession_call_counts_tsv=root / "status" / "accession_call_counts.tsv",
        run_params_tsv=root / "calls" / "run_params.tsv",
        repeat_calls_tsv=root / "calls" / "repeat_calls.tsv",
    )
    for label, path in paths.__dict__.items():
        if label in {"publish_root", "acquisition_batches_root", "acquisition_batches"}:
            continue
        if not path.is_file():
            raise ImportContractError(f"Required import artifact is missing: {path}")
    return paths


def inspect_published_run(publish_root: Path | str) -> InspectedPublishedRun:
    artifact_paths = resolve_required_artifacts(publish_root)
    manifest = _read_manifest(artifact_paths.manifest)
    _ensure_raw_publish_mode(manifest)
    batch_artifact_paths = _resolve_batch_artifacts(artifact_paths)
    artifact_paths = replace(artifact_paths, acquisition_batches=batch_artifact_paths)
    return InspectedPublishedRun(
        artifact_paths=artifact_paths,
        manifest=manifest,
        pipeline_run=_normalize_pipeline_run(manifest, artifact_paths),
    )


def load_published_run(publish_root: Path | str) -> ParsedPublishedRun:
    inspected = inspect_published_run(publish_root)
    artifact_paths = inspected.artifact_paths
    manifest = inspected.manifest
    batch_artifact_paths = artifact_paths.acquisition_batches

    raw_taxonomy_rows: list[dict[str, Any]] = []
    raw_genome_rows: list[dict[str, Any]] = []
    raw_sequence_rows: list[dict[str, Any]] = []
    raw_protein_rows: list[dict[str, Any]] = []
    download_manifest_rows: list[dict[str, Any]] = []
    normalization_warning_rows: list[dict[str, Any]] = []
    acquisition_validation_by_batch: dict[str, dict[str, Any]] = {}
    for batch_paths in batch_artifact_paths:
        raw_taxonomy_rows.extend(_read_taxonomy_rows(batch_paths.taxonomy_tsv))
        raw_genome_rows.extend(_read_genome_rows(batch_paths.genomes_tsv, batch_id=batch_paths.batch_id))
        raw_sequence_rows.extend(_read_sequence_rows(batch_paths.sequences_tsv, batch_id=batch_paths.batch_id))
        raw_protein_rows.extend(_read_protein_rows(batch_paths.proteins_tsv, batch_id=batch_paths.batch_id))
        download_manifest_rows.extend(
            _read_download_manifest_rows(batch_paths.download_manifest_tsv, batch_id=batch_paths.batch_id)
        )
        normalization_warning_rows.extend(
            _read_normalization_warning_rows(
                batch_paths.normalization_warnings_tsv,
                batch_id=batch_paths.batch_id,
            )
        )
        acquisition_validation_by_batch[batch_paths.batch_id] = _read_acquisition_validation_payload(
            batch_paths.acquisition_validation_json,
            batch_id=batch_paths.batch_id,
        )

    accession_status_rows = _read_accession_status_rows(artifact_paths.accession_status_tsv)
    accession_call_count_rows = _read_accession_call_count_rows(artifact_paths.accession_call_counts_tsv)
    run_parameter_rows = _read_run_parameter_rows(artifact_paths.run_params_tsv)
    repeat_call_rows = _read_repeat_call_rows(artifact_paths.repeat_calls_tsv)
    repeat_linked_ids = _build_repeat_linked_ids(repeat_call_rows)

    genome_rows = _merge_unique_rows(raw_genome_rows, key_field="genome_id", label="genome")
    sequence_rows = _merge_unique_rows(raw_sequence_rows, key_field="sequence_id", label="sequence")
    protein_rows = _merge_unique_rows(raw_protein_rows, key_field="protein_id", label="protein")

    return ParsedPublishedRun(
        artifact_paths=artifact_paths,
        manifest=manifest,
        pipeline_run=_normalize_pipeline_run(manifest, artifact_paths),
        batch_summaries=_build_batch_summaries(
            batch_artifact_paths=batch_artifact_paths,
            raw_genome_rows=raw_genome_rows,
            raw_sequence_rows=raw_sequence_rows,
            raw_protein_rows=raw_protein_rows,
            genome_rows=genome_rows,
            sequence_rows=sequence_rows,
            protein_rows=protein_rows,
            download_manifest_rows=download_manifest_rows,
            normalization_warning_rows=normalization_warning_rows,
            acquisition_validation_by_batch=acquisition_validation_by_batch,
            repeat_call_rows=repeat_call_rows,
            repeat_linked_ids=repeat_linked_ids,
        ),
        taxonomy_rows=_merge_unique_rows(raw_taxonomy_rows, key_field="taxon_id", label="taxonomy"),
        genome_rows=genome_rows,
        sequence_rows=sequence_rows,
        protein_rows=protein_rows,
        download_manifest_rows=download_manifest_rows,
        normalization_warning_rows=normalization_warning_rows,
        accession_status_rows=_merge_unique_rows(
            accession_status_rows,
            key_field="assembly_accession",
            label="accession status",
        ),
        accession_call_count_rows=_merge_unique_rows(
            accession_call_count_rows,
            key_field="unique_key",
            label="accession call count",
        ),
        run_parameter_rows=run_parameter_rows,
        repeat_call_rows=repeat_call_rows,
        repeat_linked_ids=repeat_linked_ids,
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


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ImportContractError(f"Malformed run manifest JSON: {path}") from exc

    if not isinstance(payload, dict):
        raise ImportContractError(f"Run manifest must contain a top-level JSON object: {path}")

    missing = [key for key in MANIFEST_REQUIRED_KEYS if key not in payload]
    if missing:
        raise ImportContractError(
            f"Run manifest is missing required keys: {', '.join(missing)}"
        )
    return payload


def _normalize_pipeline_run(
    manifest: dict[str, Any],
    artifact_paths: RequiredArtifactPaths,
) -> dict[str, Any]:
    return {
        "run_id": _require_manifest_value(manifest, "run_id"),
        "status": _require_manifest_value(manifest, "status"),
        "profile": _require_manifest_value(manifest, "profile"),
        "acquisition_publish_mode": _require_manifest_value(manifest, "acquisition_publish_mode"),
        "git_revision": _string_value(manifest.get("git_revision")),
        "started_at_utc": _parse_timestamp(manifest.get("started_at_utc"), "started_at_utc"),
        "finished_at_utc": _parse_timestamp(manifest.get("finished_at_utc"), "finished_at_utc"),
        "manifest_path": str(artifact_paths.manifest),
        "publish_root": str(artifact_paths.publish_root),
        "manifest_payload": manifest,
    }


def _ensure_raw_publish_mode(manifest: dict[str, Any]) -> None:
    acquisition_publish_mode = _require_manifest_value(manifest, "acquisition_publish_mode")
    if acquisition_publish_mode != "raw":
        raise ImportContractError(
            f"Published run uses acquisition_publish_mode={acquisition_publish_mode!r}; only 'raw' is supported."
        )


def _resolve_batch_artifacts(artifact_paths: RequiredArtifactPaths) -> tuple[BatchArtifactPaths, ...]:
    batches_root = artifact_paths.acquisition_batches_root
    if not batches_root.is_dir():
        raise ImportContractError(f"Required import artifact is missing: {batches_root}")

    batch_paths: list[BatchArtifactPaths] = []
    for batch_root in sorted(path for path in batches_root.iterdir() if path.is_dir()):
        batch_paths.append(
            BatchArtifactPaths(
                batch_id=batch_root.name,
                batch_root=batch_root,
                genomes_tsv=batch_root / "genomes.tsv",
                taxonomy_tsv=batch_root / "taxonomy.tsv",
                sequences_tsv=batch_root / "sequences.tsv",
                proteins_tsv=batch_root / "proteins.tsv",
                cds_fna=batch_root / "cds.fna",
                proteins_faa=batch_root / "proteins.faa",
                download_manifest_tsv=batch_root / "download_manifest.tsv",
                normalization_warnings_tsv=batch_root / "normalization_warnings.tsv",
                acquisition_validation_json=batch_root / "acquisition_validation.json",
            )
        )

    if not batch_paths:
        raise ImportContractError(f"No raw acquisition batches were found under {batches_root}")

    for batch_path in batch_paths:
        for path in (
            batch_path.genomes_tsv,
            batch_path.taxonomy_tsv,
            batch_path.sequences_tsv,
            batch_path.proteins_tsv,
            batch_path.cds_fna,
            batch_path.proteins_faa,
            batch_path.download_manifest_tsv,
            batch_path.normalization_warnings_tsv,
            batch_path.acquisition_validation_json,
        ):
            if not path.is_file():
                raise ImportContractError(f"Required import artifact is missing: {path}")

    return tuple(batch_paths)


def _read_taxonomy_rows(path: Path) -> list[dict[str, Any]]:
    return list(iter_taxonomy_rows(path))


def _read_genome_rows(path: Path, *, batch_id: str) -> list[dict[str, Any]]:
    return list(iter_genome_rows(path, batch_id=batch_id))


def _read_sequence_rows(path: Path, *, batch_id: str) -> list[dict[str, Any]]:
    return list(iter_sequence_rows(path, batch_id=batch_id))


def _read_protein_rows(path: Path, *, batch_id: str) -> list[dict[str, Any]]:
    return list(iter_protein_rows(path, batch_id=batch_id))


def _read_download_manifest_rows(path: Path, *, batch_id: str) -> list[dict[str, Any]]:
    return list(iter_download_manifest_rows(path, batch_id=batch_id))


def _read_normalization_warning_rows(path: Path, *, batch_id: str) -> list[dict[str, Any]]:
    return list(iter_normalization_warning_rows(path, batch_id=batch_id))


def _read_acquisition_validation_payload(path: Path, *, batch_id: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ImportContractError(f"Malformed acquisition validation JSON: {path}") from exc

    if not isinstance(payload, dict):
        raise ImportContractError(f"Acquisition validation must contain a top-level JSON object: {path}")

    missing = [key for key in ACQUISITION_VALIDATION_REQUIRED_KEYS if key not in payload]
    if missing:
        raise ImportContractError(
            f"Acquisition validation is missing required keys: {', '.join(missing)}"
        )

    counts = payload.get("counts")
    if not isinstance(counts, dict):
        raise ImportContractError(f"Acquisition validation counts must be a JSON object: {path}")

    missing_count_keys = [key for key in ACQUISITION_VALIDATION_COUNT_KEYS if key not in counts]
    if missing_count_keys:
        raise ImportContractError(
            f"Acquisition validation counts are missing required keys: {', '.join(missing_count_keys)}"
        )

    payload_batch_id = _string_value(payload.get("batch_id"))
    if payload_batch_id:
        _ensure_matching_batch_id(path, expected_batch_id=batch_id, row_batch_id=payload_batch_id)
    return payload


def _read_run_parameter_rows(path: Path) -> list[dict[str, Any]]:
    return list(iter_run_parameter_rows(path))


def _read_accession_status_rows(path: Path) -> list[dict[str, Any]]:
    return list(iter_accession_status_rows(path))


def _read_accession_call_count_rows(path: Path) -> list[dict[str, Any]]:
    return list(iter_accession_call_count_rows(path))


def _read_repeat_call_rows(path: Path) -> list[dict[str, Any]]:
    return list(iter_repeat_call_rows(path))


def _build_repeat_linked_ids(repeat_call_rows: list[dict[str, Any]]) -> RepeatLinkedIds:
    return RepeatLinkedIds(
        genome_ids=tuple(sorted({str(row["genome_id"]) for row in repeat_call_rows})),
        sequence_ids=tuple(sorted({str(row["sequence_id"]) for row in repeat_call_rows})),
        protein_ids=tuple(sorted({str(row["protein_id"]) for row in repeat_call_rows})),
    )


def _build_batch_summaries(
    *,
    batch_artifact_paths: tuple[BatchArtifactPaths, ...],
    raw_genome_rows: list[dict[str, Any]],
    raw_sequence_rows: list[dict[str, Any]],
    raw_protein_rows: list[dict[str, Any]],
    genome_rows: list[dict[str, Any]],
    sequence_rows: list[dict[str, Any]],
    protein_rows: list[dict[str, Any]],
    download_manifest_rows: list[dict[str, Any]],
    normalization_warning_rows: list[dict[str, Any]],
    acquisition_validation_by_batch: dict[str, dict[str, Any]],
    repeat_call_rows: list[dict[str, Any]],
    repeat_linked_ids: RepeatLinkedIds,
) -> tuple[ParsedAcquisitionBatch, ...]:
    genome_batch_by_id = {str(row["genome_id"]): str(row["batch_id"]) for row in genome_rows}
    sequence_batch_by_id = {str(row["sequence_id"]): str(row["batch_id"]) for row in sequence_rows}
    protein_batch_by_id = {str(row["protein_id"]): str(row["batch_id"]) for row in protein_rows}

    summaries: list[ParsedAcquisitionBatch] = []
    for batch_paths in batch_artifact_paths:
        batch_id = batch_paths.batch_id
        summaries.append(
            ParsedAcquisitionBatch(
                artifact_paths=batch_paths,
                acquisition_validation=acquisition_validation_by_batch[batch_id],
                total_genomes=sum(1 for row in raw_genome_rows if str(row["batch_id"]) == batch_id),
                total_sequences=sum(1 for row in raw_sequence_rows if str(row["batch_id"]) == batch_id),
                total_proteins=sum(1 for row in raw_protein_rows if str(row["batch_id"]) == batch_id),
                total_download_manifest_rows=sum(
                    1 for row in download_manifest_rows if str(row["batch_id"]) == batch_id
                ),
                total_normalization_warning_rows=sum(
                    1 for row in normalization_warning_rows if str(row["batch_id"]) == batch_id
                ),
                total_repeat_calls=sum(
                    1 for row in repeat_call_rows if genome_batch_by_id.get(str(row["genome_id"])) == batch_id
                ),
                total_repeat_linked_genomes=sum(
                    1 for genome_id in repeat_linked_ids.genome_ids if genome_batch_by_id.get(genome_id) == batch_id
                ),
                total_repeat_linked_sequences=sum(
                    1
                    for sequence_id in repeat_linked_ids.sequence_ids
                    if sequence_batch_by_id.get(sequence_id) == batch_id
                ),
                total_repeat_linked_proteins=sum(
                    1 for protein_id in repeat_linked_ids.protein_ids if protein_batch_by_id.get(protein_id) == batch_id
                ),
            )
        )
    return tuple(summaries)


def _merge_unique_rows(
    rows: list[dict[str, Any]],
    *,
    key_field: str,
    label: str,
) -> list[dict[str, Any]]:
    merged_by_key: dict[Any, dict[str, Any]] = {}
    ordered_keys: list[Any] = []

    for row in rows:
        key = row[key_field]
        existing = merged_by_key.get(key)
        if existing is None:
            merged_by_key[key] = row
            ordered_keys.append(key)
            continue
        if existing != row:
            raise ImportContractError(
                f"Conflicting duplicate {label} rows were found for {key_field}={key!r}"
            )

    return [merged_by_key[key] for key in ordered_keys]


def _read_tsv(path: Path, required_columns: list[str]) -> list[dict[str, str]]:
    return list(_iter_tsv(path, required_columns))


def _iter_tsv(path: Path, required_columns: list[str]):
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        missing = [column for column in required_columns if column not in (reader.fieldnames or [])]
        if missing:
            raise ImportContractError(
                f"{path} is missing required columns: {', '.join(missing)}"
            )
        for row in reader:
            yield dict(row)


def _require_manifest_value(manifest: dict[str, Any], key: str) -> str:
    value = _string_value(manifest.get(key))
    if not value:
        raise ImportContractError(f"Run manifest contains an empty required value for {key!r}")
    return value


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
