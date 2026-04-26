from __future__ import annotations

from pathlib import Path

from .contracts import (
    BatchArtifactPaths,
    CodonUsageArtifactPath,
    ImportContractError,
    RequiredArtifactPaths,
    VALID_METHODS,
    V2ArtifactPaths,
)


def resolve_required_artifacts(publish_root: Path | str) -> RequiredArtifactPaths:
    root = Path(publish_root).resolve()
    if not root.is_dir():
        raise ImportContractError(f"Publish root does not exist or is not a directory: {root}")

    paths = RequiredArtifactPaths(
        publish_root=root,
        manifest=root / "metadata" / "run_manifest.json",
        acquisition_batches_root=root / "acquisition" / "batches",
        acquisition_batches=(),
        codon_usage_artifacts=(),
        accession_status_tsv=root / "status" / "accession_status.tsv",
        accession_call_counts_tsv=root / "status" / "accession_call_counts.tsv",
        run_params_tsv=root / "calls" / "run_params.tsv",
        repeat_calls_tsv=root / "calls" / "repeat_calls.tsv",
    )
    for label, path in paths.__dict__.items():
        if label in {
            "publish_root",
            "acquisition_batches_root",
            "acquisition_batches",
            "codon_usage_artifacts",
        }:
            continue
        if not path.is_file():
            raise ImportContractError(f"Required import artifact is missing: {path}")
    return paths


def resolve_v2_artifacts(publish_root: Path | str) -> V2ArtifactPaths:
    root = Path(publish_root).resolve()
    if not root.is_dir():
        raise ImportContractError(f"Publish root does not exist or is not a directory: {root}")

    paths = V2ArtifactPaths(
        publish_root=root,
        manifest=root / "metadata" / "run_manifest.json",
        repeat_calls_tsv=root / "calls" / "repeat_calls.tsv",
        run_params_tsv=root / "calls" / "run_params.tsv",
        genomes_tsv=root / "tables" / "genomes.tsv",
        taxonomy_tsv=root / "tables" / "taxonomy.tsv",
        matched_sequences_tsv=root / "tables" / "matched_sequences.tsv",
        matched_proteins_tsv=root / "tables" / "matched_proteins.tsv",
        repeat_call_codon_usage_tsv=root / "tables" / "repeat_call_codon_usage.tsv",
        repeat_context_tsv=root / "tables" / "repeat_context.tsv",
        download_manifest_tsv=root / "tables" / "download_manifest.tsv",
        normalization_warnings_tsv=root / "tables" / "normalization_warnings.tsv",
        accession_status_tsv=root / "tables" / "accession_status.tsv",
        accession_call_counts_tsv=root / "tables" / "accession_call_counts.tsv",
        status_summary_json=root / "summaries" / "status_summary.json",
        acquisition_validation_json=root / "summaries" / "acquisition_validation.json",
    )
    for label, path in paths.__dict__.items():
        if label == "publish_root":
            continue
        if not path.is_file():
            raise ImportContractError(f"Required import artifact is missing: {path}")
    return paths


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


def _resolve_codon_usage_artifacts(
    artifact_paths: RequiredArtifactPaths,
) -> tuple[CodonUsageArtifactPath, ...]:
    finalized_root = artifact_paths.publish_root / "calls" / "finalized"
    if not finalized_root.is_dir():
        return ()

    codon_usage_artifacts: list[CodonUsageArtifactPath] = []
    for method_root in sorted(path for path in finalized_root.iterdir() if path.is_dir()):
        method = method_root.name.strip()
        if method not in VALID_METHODS:
            raise ImportContractError(f"Unexpected finalized codon-usage method directory: {method_root}")

        for residue_root in sorted(path for path in method_root.iterdir() if path.is_dir()):
            repeat_residue = residue_root.name.strip()
            if not repeat_residue:
                raise ImportContractError(f"Unexpected empty finalized codon-usage residue directory: {residue_root}")

            for batch_root in sorted(path for path in residue_root.iterdir() if path.is_dir()):
                expected_path = batch_root / f"final_{method}_{repeat_residue}_{batch_root.name}_codon_usage.tsv"
                if not expected_path.is_file():
                    raise ImportContractError(f"Required import artifact is missing: {expected_path}")

                codon_usage_artifacts.append(
                    CodonUsageArtifactPath(
                        batch_id=batch_root.name,
                        method=method,
                        repeat_residue=repeat_residue,
                        codon_usage_tsv=expected_path,
                    )
                )

    return tuple(codon_usage_artifacts)
