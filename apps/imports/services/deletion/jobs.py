from __future__ import annotations

import traceback as tb

from django.db import transaction
from django.utils import timezone

from apps.browser.models import PipelineRun
from apps.imports.models import DeletionJob
from apps.imports.services.deletion.cache import bump_catalog_version
from apps.imports.services.deletion.safety import validate_deletion_target


# Dependency-ordered table list for chunked raw row deletion.
# Each entry: (db_table, join_table_or_None, join_fk_or_None)
# join_table/join_fk are set for indirect children whose pipeline_run_id is one join away.
_DELETE_ORDER = [
    ("browser_repeatcallcodonusage", "browser_repeatcall", "repeat_call_id"),
    ("browser_repeatcallcontext",    None,                 None),
    ("browser_repeatcall",           None,                 None),
    ("browser_downloadmanifestentry", None,                None),
    ("browser_normalizationwarning", None,                 None),
    ("browser_accessionstatus",      None,                 None),
    ("browser_accessioncallcount",   None,                 None),
    ("browser_protein",              None,                 None),
    ("browser_sequence",             None,                 None),
    ("browser_genome",               None,                 None),
    ("browser_runparameter",         None,                 None),
    ("browser_acquisitionbatch",     None,                 None),
]

_ANALYZE_TABLES = [
    "browser_repeatcallcodonusage", "browser_repeatcallcontext", "browser_repeatcall",
    "browser_downloadmanifestentry", "browser_normalizationwarning",
    "browser_accessionstatus", "browser_accessioncallcount",
    "browser_protein", "browser_sequence", "browser_genome",
    "browser_runparameter", "browser_acquisitionbatch",
    "browser_canonicalgenome", "browser_canonicalsequence", "browser_canonicalprotein",
    "browser_canonicalrepeatcall", "browser_canonicalrepeatcallcodonusage",
]


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
    with transaction.atomic():
        locked_run = PipelineRun.objects.select_for_update().get(pk=pipeline_run.pk)

        validate_deletion_target(locked_run)

        existing_job = DeletionJob.objects.filter(
            pipeline_run=locked_run,
            status__in=[DeletionJob.Status.PENDING, DeletionJob.Status.RUNNING],
        ).first()
        if existing_job is not None:
            return existing_job

        label = requested_by_label or (str(requested_by) if requested_by else "")
        job = DeletionJob.objects.create(
            pipeline_run=locked_run,
            reason=reason,
            requested_by=requested_by,
            requested_by_label=label,
        )

        locked_run.lifecycle_status = PipelineRun.LifecycleStatus.DELETING
        locked_run.deleting_at = timezone.now()
        locked_run.deletion_reason = reason
        locked_run.save(update_fields=["lifecycle_status", "deleting_at", "deletion_reason"])

        new_version = bump_catalog_version()
        job.catalog_versions = [new_version]
        job.save(update_fields=["catalog_versions"])

        job_pk = job.pk
        transaction.on_commit(lambda: _enqueue(job_pk))

    return job


def claim_deletion_job(job_id: int) -> DeletionJob | None:
    """Atomically claim a PENDING (or stale RUNNING) DeletionJob for execution.

    Returns the job with status=running, or None if the job should not be executed
    (already done, missing, or in an unexpected state).
    """
    with transaction.atomic():
        job = (
            DeletionJob.objects.select_related("pipeline_run")
            .select_for_update(of=("self",))
            .filter(pk=job_id)
            .first()
        )
        if job is None:
            return None
        if job.status == DeletionJob.Status.DONE:
            return None
        if job.status not in (DeletionJob.Status.PENDING, DeletionJob.Status.RUNNING):
            return None

        now = timezone.now()
        job.status = DeletionJob.Status.RUNNING
        job.started_at = job.started_at or now
        job.last_heartbeat_at = now
        job.save(update_fields=["status", "started_at", "last_heartbeat_at"])

    return job


def execute_deletion_phases(job: DeletionJob) -> None:
    """Execute all deletion phases in dependency order.

    Calls through to service stubs; phases not yet implemented will raise
    NotImplementedError and the caller should catch and call mark_job_failed().
    """
    from apps.imports.services.deletion.artifacts import ArtifactPathError, delete_run_artifacts
    from apps.imports.services.deletion.canonical import rebuild_canonical_rollups, repair_canonical_catalog
    from apps.imports.services.deletion.chunks import delete_in_chunks
    from apps.imports.services.deletion.postgres import analyze_tables

    run = job.pipeline_run

    _advance(job, "canonical_repair")
    repair_canonical_catalog(run)
    rebuild_canonical_rollups()
    bump_catalog_version()

    _advance(job, "artifact_cleanup")
    try:
        artifacts_removed = delete_run_artifacts(run)
    except ArtifactPathError:
        artifacts_removed = 0
    job.artifacts_deleted = artifacts_removed
    job.save(update_fields=["artifacts_deleted"])

    _advance(job, "row_deletion")
    total_deleted = 0
    for table, join_table, join_fk in _DELETE_ORDER:
        job.current_table = table
        job.last_heartbeat_at = timezone.now()
        job.save(update_fields=["current_table", "last_heartbeat_at"])
        n = delete_in_chunks(
            table=table,
            pipeline_run_id=run.pk,
            join_table=join_table,
            join_fk=join_fk,
        )
        total_deleted += n
    job.rows_deleted = total_deleted
    job.current_table = ""
    job.save(update_fields=["rows_deleted", "current_table"])

    _advance(job, "analyze")
    analyze_tables(_ANALYZE_TABLES)

    now = timezone.now()
    job.status = DeletionJob.Status.DONE
    job.phase = "finished"
    job.finished_at = now
    job.last_heartbeat_at = now
    job.save(update_fields=["status", "phase", "finished_at", "last_heartbeat_at"])

    if run is not None:
        PipelineRun.objects.filter(pk=run.pk).update(
            lifecycle_status=PipelineRun.LifecycleStatus.DELETED,
            deleted_at=now,
        )


def mark_job_failed(job: DeletionJob, exc: Exception) -> None:
    """Mark job as failed and its target run as delete_failed. Stores safe error metadata."""
    now = timezone.now()
    job.status = DeletionJob.Status.FAILED
    job.last_error_at = now
    job.error_message = f"{type(exc).__name__}: {exc}"
    job.error_debug = {"traceback": tb.format_exc()}
    job.last_heartbeat_at = now
    job.save(update_fields=[
        "status", "last_error_at", "error_message", "error_debug", "last_heartbeat_at",
    ])

    run = job.pipeline_run
    if run is not None:
        PipelineRun.objects.filter(pk=run.pk).update(
            lifecycle_status=PipelineRun.LifecycleStatus.DELETE_FAILED,
            delete_failed_at=now,
        )


def retry_deletion(job: DeletionJob) -> DeletionJob:
    """Re-enqueue a failed DeletionJob.

    Only FAILED jobs are eligible. The same job row is reused: retry_count is
    incremented, error fields are cleared, status is reset to PENDING, and the
    Celery task is dispatched via transaction.on_commit().
    """
    from apps.imports.services.deletion.safety import DeletionTargetError

    if job.status != DeletionJob.Status.FAILED:
        raise DeletionTargetError(
            f"DeletionJob {job.pk} has status={job.status!r}. Only failed jobs can be retried."
        )

    with transaction.atomic():
        locked_job = DeletionJob.objects.select_for_update().get(pk=job.pk)

        if locked_job.status != DeletionJob.Status.FAILED:
            raise DeletionTargetError(
                f"DeletionJob {locked_job.pk} is no longer failed (status={locked_job.status!r})."
            )

        locked_job.status = DeletionJob.Status.PENDING
        locked_job.phase = ""
        locked_job.error_message = ""
        locked_job.error_debug = {}
        locked_job.last_error_at = None
        locked_job.retry_count += 1
        locked_job.save(update_fields=[
            "status", "phase", "error_message", "error_debug",
            "last_error_at", "retry_count",
        ])

        job_pk = locked_job.pk
        transaction.on_commit(lambda: _enqueue(job_pk))

    return locked_job


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


def _enqueue(job_pk: int) -> None:
    from apps.imports.tasks import delete_pipeline_run_job
    delete_pipeline_run_job.delay(job_pk)


def _advance(job: DeletionJob, phase: str) -> None:
    job.phase = phase
    job.last_heartbeat_at = timezone.now()
    job.save(update_fields=["phase", "last_heartbeat_at"])
