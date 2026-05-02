from __future__ import annotations

from apps.browser.models import PipelineRun


class DeletionTargetError(Exception):
    pass


def validate_deletion_target(pipeline_run: PipelineRun) -> None:
    """Raise DeletionTargetError if the run cannot be queued for deletion."""
    raise NotImplementedError
