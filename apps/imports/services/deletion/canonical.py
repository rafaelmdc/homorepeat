from __future__ import annotations

from apps.browser.models import PipelineRun


def repair_canonical_catalog(pipeline_run: PipelineRun) -> dict[str, int]:
    """Promote or remove canonical rows whose latest_pipeline_run is pipeline_run.

    For each impacted canonical entity:
    - If an active predecessor exists in another run: promote canonical row to that run.
    - If no active predecessor exists: delete the canonical row (children first).

    Returns a dict of affected counts keyed by table name.
    """
    raise NotImplementedError


def rebuild_canonical_rollups() -> None:
    """Rebuild CanonicalCodonCompositionSummary and CanonicalCodonCompositionLengthSummary."""
    raise NotImplementedError
