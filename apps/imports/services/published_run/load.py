from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Iterable

from .artifacts import (
    _resolve_batch_artifacts,
    _resolve_codon_usage_artifacts,
    resolve_required_artifacts,
    resolve_v2_artifacts,
)
from .contracts import (
    CodonUsageArtifactPath,
    ImportContractError,
    InspectedPublishedRun,
)
from .iterators import iter_codon_usage_rows
from .manifest import (
    _ensure_raw_publish_mode,
    _ensure_v2_contract,
    _normalize_pipeline_run,
    _read_manifest,
)


def inspect_published_run(publish_root: Path | str) -> InspectedPublishedRun:
    root = Path(publish_root).resolve()
    manifest = _read_manifest(root / "metadata" / "run_manifest.json")
    if "publish_contract_version" in manifest:
        _ensure_v2_contract(manifest)
        artifact_paths = resolve_v2_artifacts(root)
        return InspectedPublishedRun(
            artifact_paths=artifact_paths,
            manifest=manifest,
            pipeline_run=_normalize_pipeline_run(manifest, artifact_paths),
        )

    artifact_paths = resolve_required_artifacts(root)
    _ensure_raw_publish_mode(manifest)
    batch_artifact_paths = _resolve_batch_artifacts(artifact_paths)
    artifact_paths = replace(
        artifact_paths,
        acquisition_batches=batch_artifact_paths,
        codon_usage_artifacts=_resolve_codon_usage_artifacts(artifact_paths),
    )
    return InspectedPublishedRun(
        artifact_paths=artifact_paths,
        manifest=manifest,
        pipeline_run=_normalize_pipeline_run(manifest, artifact_paths),
    )


def load_published_run(publish_root: Path | str):
    raise ImportContractError(
        "load_published_run() is retired because it materializes large published-run artifacts in memory. "
        "Use inspect_published_run() and the iter_* row helpers instead."
    )


def iter_codon_usage_artifact_rows(
    codon_usage_artifacts: Iterable[CodonUsageArtifactPath],
):
    for artifact in codon_usage_artifacts:
        for row in iter_codon_usage_rows(artifact.codon_usage_tsv):
            if str(row["method"]) != artifact.method:
                raise ImportContractError(
                    f"{artifact.codon_usage_tsv} contains method={row['method']!r}, expected {artifact.method!r}"
                )
            if str(row["repeat_residue"]) != artifact.repeat_residue:
                raise ImportContractError(
                    f"{artifact.codon_usage_tsv} contains repeat_residue={row['repeat_residue']!r}, "
                    f"expected {artifact.repeat_residue!r}"
                )
            yield {
                **row,
                "batch_id": artifact.batch_id,
            }
