from __future__ import annotations

from pathlib import Path

from .artifacts import resolve_v2_artifacts
from .contracts import InspectedPublishedRun
from .manifest import (
    _ensure_v2_contract,
    _normalize_pipeline_run,
    _read_manifest,
)


def inspect_published_run(publish_root: Path | str) -> InspectedPublishedRun:
    root = Path(publish_root).resolve()
    manifest = _read_manifest(root / "metadata" / "run_manifest.json")
    _ensure_v2_contract(manifest)
    artifact_paths = resolve_v2_artifacts(root)
    return InspectedPublishedRun(
        artifact_paths=artifact_paths,
        manifest=manifest,
        pipeline_run=_normalize_pipeline_run(manifest, artifact_paths),
    )
