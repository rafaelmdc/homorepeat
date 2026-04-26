from __future__ import annotations

from dataclasses import dataclass
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
CODON_USAGE_REQUIRED_COLUMNS = [
    "call_id",
    "method",
    "repeat_residue",
    "sequence_id",
    "protein_id",
    "amino_acid",
    "codon",
    "codon_count",
    "codon_fraction",
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
V2_MANIFEST_REQUIRED_KEYS = [*MANIFEST_REQUIRED_KEYS, "publish_contract_version"]
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
class V2ArtifactPaths:
    publish_root: Path
    manifest: Path
    repeat_calls_tsv: Path
    run_params_tsv: Path
    genomes_tsv: Path
    taxonomy_tsv: Path
    matched_sequences_tsv: Path
    matched_proteins_tsv: Path
    repeat_call_codon_usage_tsv: Path
    repeat_context_tsv: Path
    download_manifest_tsv: Path
    normalization_warnings_tsv: Path
    accession_status_tsv: Path
    accession_call_counts_tsv: Path
    status_summary_json: Path
    acquisition_validation_json: Path


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
class CodonUsageArtifactPath:
    batch_id: str
    method: str
    repeat_residue: str
    codon_usage_tsv: Path


@dataclass(frozen=True)
class RequiredArtifactPaths:
    publish_root: Path
    manifest: Path
    acquisition_batches_root: Path
    acquisition_batches: tuple[BatchArtifactPaths, ...]
    codon_usage_artifacts: tuple[CodonUsageArtifactPath, ...]
    accession_status_tsv: Path
    accession_call_counts_tsv: Path
    run_params_tsv: Path
    repeat_calls_tsv: Path


@dataclass(frozen=True)
class InspectedPublishedRun:
    artifact_paths: RequiredArtifactPaths | V2ArtifactPaths
    manifest: dict[str, Any]
    pipeline_run: dict[str, Any]
