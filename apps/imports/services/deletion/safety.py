from __future__ import annotations

from apps.browser.models import PipelineRun


class DeletionTargetError(Exception):
    pass


def validate_deletion_target(pipeline_run: PipelineRun) -> None:
    """Raise DeletionTargetError if the run cannot be queued for deletion.

    Active runs and deleting runs (which return the existing job) are allowed.
    Deleted and delete_failed runs are not re-queueable through the normal path.
    """
    status = pipeline_run.lifecycle_status
    if status == PipelineRun.LifecycleStatus.DELETED:
        raise DeletionTargetError(
            f"Run {pipeline_run.run_id!r} is already deleted."
        )
    if status == PipelineRun.LifecycleStatus.DELETE_FAILED:
        raise DeletionTargetError(
            f"Run {pipeline_run.run_id!r} is in delete_failed state. "
            "Use retry_deletion_job --job-id <id> --confirm to retry."
        )
