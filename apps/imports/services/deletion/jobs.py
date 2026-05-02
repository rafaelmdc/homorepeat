from __future__ import annotations

from apps.browser.models import PipelineRun
from apps.imports.models import DeletionJob


def queue_deletion(
    pipeline_run: PipelineRun,
    *,
    reason: str = "",
    requested_by=None,
    requested_by_label: str = "",
) -> DeletionJob:
    """Mark pipeline_run as deleting, create or reuse a DeletionJob, and enqueue the Celery task.

    All synchronous work (lock, hide, bump cache, enqueue) happens in one
    transaction. The Celery task is dispatched via transaction.on_commit().

    Returns the DeletionJob (new or reused active job).
    """
    raise NotImplementedError


def get_active_job(pipeline_run: PipelineRun) -> DeletionJob | None:
    """Return the pending or running DeletionJob for pipeline_run, or None."""
    return (
        DeletionJob.objects.filter(
            pipeline_run=pipeline_run,
            status__in=[DeletionJob.Status.PENDING, DeletionJob.Status.RUNNING],
        )
        .select_for_update(skip_locked=True)
        .first()
    )
