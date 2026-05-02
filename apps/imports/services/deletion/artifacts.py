from __future__ import annotations

from pathlib import Path

from apps.browser.models import PipelineRun


class ArtifactPathError(Exception):
    pass


def resolve_run_artifact_roots(pipeline_run: PipelineRun) -> list[Path]:
    """Return app-owned artifact roots approved for deletion for this run.

    Only paths under HOMOREPEAT_IMPORTS_ROOT/library/<run_id>/ are returned.
    Raises ArtifactPathError for any path that resolves outside approved roots.
    """
    raise NotImplementedError


def delete_run_artifacts(pipeline_run: PipelineRun) -> int:
    """Delete approved artifact roots. Returns number of roots removed."""
    raise NotImplementedError
