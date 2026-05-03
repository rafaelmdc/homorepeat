from __future__ import annotations

import shutil
from pathlib import Path

from django.conf import settings

from apps.browser.models import PipelineRun


class ArtifactPathError(Exception):
    pass


def _approved_library_root(run_id: str) -> Path:
    imports_root = Path(settings.HOMOREPEAT_IMPORTS_ROOT).resolve()
    return imports_root / "library" / run_id


def _assert_inside_root(candidate: Path, root: Path, label: str) -> None:
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ArtifactPathError(
            f"{label} resolved to {candidate!r} which is outside approved root {root!r}"
        )


def resolve_run_artifact_roots(pipeline_run: PipelineRun) -> list[Path]:
    """Return app-owned artifact roots approved for deletion for this run.

    Only paths under HOMOREPEAT_IMPORTS_ROOT/library/<run_id>/ are returned.
    Raises ArtifactPathError for any path that resolves outside approved roots.
    Missing paths are non-fatal: library root is always included even if absent.
    """
    run_id = pipeline_run.run_id
    library_root = _approved_library_root(run_id)
    roots: list[Path] = [library_root]

    if pipeline_run.publish_root:
        candidate = Path(pipeline_run.publish_root).resolve()
        _assert_inside_root(candidate, library_root, f"publish_root for {run_id!r}")
        if candidate != library_root and candidate not in roots:
            roots.append(candidate)

    return roots


def delete_run_artifacts(pipeline_run: PipelineRun) -> int:
    """Delete approved artifact roots. Returns number of roots removed."""
    roots = resolve_run_artifact_roots(pipeline_run)
    removed = 0
    for root in roots:
        if root.exists():
            shutil.rmtree(root)
            removed += 1
    return removed
