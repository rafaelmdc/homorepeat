from __future__ import annotations

import csv
import json
from dataclasses import dataclass
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
    "sequence_path",
]
PROTEIN_REQUIRED_COLUMNS = [
    "protein_id",
    "sequence_id",
    "genome_id",
    "protein_name",
    "protein_length",
    "protein_path",
]
RUN_PARAM_REQUIRED_COLUMNS = ["method", "param_name", "param_value"]
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
    "git_revision",
    "inputs",
    "paths",
    "params",
    "enabled_methods",
    "repeat_residues",
    "artifacts",
]
VALID_METHODS = {"pure", "threshold"}
COMPACT_TAXONOMY_RANKS = {
    "superkingdom",
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "species",
}


class ImportContractError(ValueError):
    """Raised when a published run does not satisfy the import contract."""


@dataclass(frozen=True)
class RequiredArtifactPaths:
    publish_root: Path
    manifest: Path
    genomes_tsv: Path
    taxonomy_tsv: Path
    sequences_tsv: Path
    proteins_tsv: Path
    run_params_tsv: Path
    repeat_calls_tsv: Path


@dataclass(frozen=True)
class ParsedPublishedRun:
    artifact_paths: RequiredArtifactPaths
    manifest: dict[str, Any]
    pipeline_run: dict[str, Any]
    taxonomy_rows: list[dict[str, Any]]
    genome_rows: list[dict[str, Any]]
    sequence_rows: list[dict[str, Any]]
    protein_rows: list[dict[str, Any]]
    run_parameter_rows: list[dict[str, Any]]
    repeat_call_rows: list[dict[str, Any]]


def resolve_required_artifacts(publish_root: Path | str) -> RequiredArtifactPaths:
    root = Path(publish_root).resolve()
    if not root.is_dir():
        raise ImportContractError(f"Publish root does not exist or is not a directory: {root}")

    paths = RequiredArtifactPaths(
        publish_root=root,
        manifest=root / "manifest" / "run_manifest.json",
        genomes_tsv=root / "acquisition" / "genomes.tsv",
        taxonomy_tsv=root / "acquisition" / "taxonomy.tsv",
        sequences_tsv=root / "acquisition" / "sequences.tsv",
        proteins_tsv=root / "acquisition" / "proteins.tsv",
        run_params_tsv=root / "calls" / "run_params.tsv",
        repeat_calls_tsv=root / "calls" / "repeat_calls.tsv",
    )
    for label, path in paths.__dict__.items():
        if label == "publish_root":
            continue
        if not path.is_file():
            raise ImportContractError(f"Required import artifact is missing: {path}")
    return paths


def load_published_run(publish_root: Path | str) -> ParsedPublishedRun:
    artifact_paths = resolve_required_artifacts(publish_root)
    manifest = _read_manifest(artifact_paths.manifest)
    raw_taxonomy_rows = _read_taxonomy_rows(artifact_paths.taxonomy_tsv)
    genome_rows = _read_genome_rows(artifact_paths.genomes_tsv)
    sequence_rows = _read_sequence_rows(artifact_paths.sequences_tsv)
    protein_rows = _read_protein_rows(artifact_paths.proteins_tsv)
    run_parameter_rows = _read_run_parameter_rows(artifact_paths.run_params_tsv)
    repeat_call_rows = _read_repeat_call_rows(artifact_paths.repeat_calls_tsv)

    return ParsedPublishedRun(
        artifact_paths=artifact_paths,
        manifest=manifest,
        pipeline_run=_normalize_pipeline_run(manifest, artifact_paths),
        taxonomy_rows=_compact_taxonomy_rows(
            raw_taxonomy_rows,
            referenced_taxon_ids=_referenced_taxon_ids(
                genome_rows,
                sequence_rows,
                protein_rows,
                repeat_call_rows,
            ),
        ),
        genome_rows=genome_rows,
        sequence_rows=sequence_rows,
        protein_rows=protein_rows,
        run_parameter_rows=run_parameter_rows,
        repeat_call_rows=repeat_call_rows,
    )


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
        "git_revision": _string_value(manifest.get("git_revision")),
        "started_at_utc": _parse_timestamp(manifest.get("started_at_utc"), "started_at_utc"),
        "finished_at_utc": _parse_timestamp(manifest.get("finished_at_utc"), "finished_at_utc"),
        "manifest_path": str(artifact_paths.manifest),
        "publish_root": str(artifact_paths.publish_root),
        "manifest_payload": manifest,
    }


def _read_taxonomy_rows(path: Path) -> list[dict[str, Any]]:
    rows = _read_tsv(path, TAXONOMY_REQUIRED_COLUMNS)
    normalized = []
    for row in rows:
        normalized.append(
            {
                "taxon_id": _parse_int(row, "taxon_id", path),
                "taxon_name": _require_row_value(row, "taxon_name", path),
                "parent_taxon_id": _parse_optional_int(row, "parent_taxon_id", path),
                "rank": _string_value(row.get("rank")),
                "source": _string_value(row.get("source")),
            }
        )
    return normalized


def _read_genome_rows(path: Path) -> list[dict[str, Any]]:
    rows = _read_tsv(path, GENOME_REQUIRED_COLUMNS)
    normalized = []
    for row in rows:
        normalized.append(
            {
                "genome_id": _require_row_value(row, "genome_id", path),
                "source": _require_row_value(row, "source", path),
                "accession": _require_row_value(row, "accession", path),
                "genome_name": _require_row_value(row, "genome_name", path),
                "assembly_type": _require_row_value(row, "assembly_type", path),
                "taxon_id": _parse_int(row, "taxon_id", path),
                "assembly_level": _string_value(row.get("assembly_level")),
                "species_name": _string_value(row.get("species_name")),
                "download_path": _string_value(row.get("download_path")),
                "notes": _string_value(row.get("notes")),
            }
        )
    return normalized


def _read_sequence_rows(path: Path) -> list[dict[str, Any]]:
    rows = _read_tsv(path, SEQUENCE_REQUIRED_COLUMNS)
    normalized = []
    for row in rows:
        normalized.append(
            {
                "sequence_id": _require_row_value(row, "sequence_id", path),
                "genome_id": _require_row_value(row, "genome_id", path),
                "sequence_name": _require_row_value(row, "sequence_name", path),
                "sequence_length": _parse_int(row, "sequence_length", path),
                "sequence_path": _require_row_value(row, "sequence_path", path),
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
        )
    return normalized


def _read_protein_rows(path: Path) -> list[dict[str, Any]]:
    rows = _read_tsv(path, PROTEIN_REQUIRED_COLUMNS)
    normalized = []
    for row in rows:
        normalized.append(
            {
                "protein_id": _require_row_value(row, "protein_id", path),
                "sequence_id": _require_row_value(row, "sequence_id", path),
                "genome_id": _require_row_value(row, "genome_id", path),
                "protein_name": _require_row_value(row, "protein_name", path),
                "protein_length": _parse_int(row, "protein_length", path),
                "protein_path": _require_row_value(row, "protein_path", path),
                "gene_symbol": _string_value(row.get("gene_symbol")),
                "translation_method": _string_value(row.get("translation_method")),
                "translation_status": _string_value(row.get("translation_status")),
                "assembly_accession": _string_value(row.get("assembly_accession")),
                "taxon_id": _parse_optional_int(row, "taxon_id", path),
                "gene_group": _string_value(row.get("gene_group")),
                "protein_external_id": _string_value(row.get("protein_external_id")),
            }
        )
    return normalized


def _read_run_parameter_rows(path: Path) -> list[dict[str, Any]]:
    rows = _read_tsv(path, RUN_PARAM_REQUIRED_COLUMNS)
    normalized = []
    for row in rows:
        method = _require_row_value(row, "method", path)
        if method not in VALID_METHODS:
            raise ImportContractError(f"{path} contains an invalid method: {method!r}")
        normalized.append(
            {
                "method": method,
                "param_name": _require_row_value(row, "param_name", path),
                "param_value": _require_row_value(row, "param_value", path),
            }
        )
    return normalized


def _read_repeat_call_rows(path: Path) -> list[dict[str, Any]]:
    rows = _read_tsv(path, REPEAT_CALL_REQUIRED_COLUMNS)
    normalized = []
    for row in rows:
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

        normalized.append(
            {
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
                "source_file": _string_value(row.get("source_file")),
            }
        )
    return normalized


def _referenced_taxon_ids(
    genome_rows: list[dict[str, Any]],
    sequence_rows: list[dict[str, Any]],
    protein_rows: list[dict[str, Any]],
    repeat_call_rows: list[dict[str, Any]],
) -> set[int]:
    referenced_sequence_ids = {str(row["sequence_id"]) for row in repeat_call_rows}
    referenced_protein_ids = {str(row["protein_id"]) for row in repeat_call_rows}

    taxon_ids = {int(row["taxon_id"]) for row in genome_rows}
    taxon_ids.update(int(row["taxon_id"]) for row in repeat_call_rows)
    taxon_ids.update(
        int(row["taxon_id"])
        for row in sequence_rows
        if row.get("taxon_id") is not None and str(row["sequence_id"]) in referenced_sequence_ids
    )
    taxon_ids.update(
        int(row["taxon_id"])
        for row in protein_rows
        if row.get("taxon_id") is not None and str(row["protein_id"]) in referenced_protein_ids
    )
    return taxon_ids


def _compact_taxonomy_rows(
    rows: list[dict[str, Any]],
    *,
    referenced_taxon_ids: set[int],
) -> list[dict[str, Any]]:
    rows_by_taxon_id = {int(row["taxon_id"]): row for row in rows}
    retained_taxon_ids: set[int] = set()

    for row in rows:
        taxon_id = int(row["taxon_id"])
        rank = str(row.get("rank", "")).strip().lower()
        if row.get("parent_taxon_id") is None or rank in COMPACT_TAXONOMY_RANKS or taxon_id in referenced_taxon_ids:
            retained_taxon_ids.add(taxon_id)

    compacted_rows: list[dict[str, Any]] = []
    for row in rows:
        taxon_id = int(row["taxon_id"])
        if taxon_id not in retained_taxon_ids:
            continue
        compacted_rows.append(
            {
                **row,
                "parent_taxon_id": _nearest_retained_parent_taxon_id(
                    taxon_id,
                    rows_by_taxon_id,
                    retained_taxon_ids,
                ),
            }
        )
    return compacted_rows


def _nearest_retained_parent_taxon_id(
    taxon_id: int,
    rows_by_taxon_id: dict[int, dict[str, Any]],
    retained_taxon_ids: set[int],
) -> int | None:
    row = rows_by_taxon_id.get(taxon_id)
    if row is None:
        raise ImportContractError(f"Taxonomy is missing taxon_id {taxon_id!r}")

    current_parent_taxon_id = row.get("parent_taxon_id")
    seen: set[int] = set()
    while current_parent_taxon_id is not None:
        parent_taxon_id = int(current_parent_taxon_id)
        if parent_taxon_id in seen:
            raise ImportContractError("Taxonomy contains a parent cycle and cannot be compacted")
        seen.add(parent_taxon_id)
        if parent_taxon_id in retained_taxon_ids:
            return parent_taxon_id
        parent_row = rows_by_taxon_id.get(parent_taxon_id)
        if parent_row is None:
            raise ImportContractError(
                f"Taxonomy references missing parent taxon_id {parent_taxon_id!r}"
            )
        current_parent_taxon_id = parent_row.get("parent_taxon_id")
    return None


def _read_tsv(path: Path, required_columns: list[str]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        missing = [column for column in required_columns if column not in (reader.fieldnames or [])]
        if missing:
            raise ImportContractError(
                f"{path} is missing required columns: {', '.join(missing)}"
            )
        return [dict(row) for row in reader]


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
    try:
        return int(value)
    except ValueError as exc:
        raise ImportContractError(f"{path} contains a non-integer value for {key!r}") from exc


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


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
