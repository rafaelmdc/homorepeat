from __future__ import annotations

import shutil
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.imports.models import DeletionJob, ImportBatch, UploadedRun
from apps.imports.services.import_run.api import dispatch_import_batch, process_import_batch
from apps.imports.services.import_run.state import _mark_batch_stale_failed, _reset_batch_to_pending
from apps.imports.services.published_run import ImportContractError
from apps.imports.services.uploads import UploadValidationError, extract_uploaded_zip


IMPORT_BATCH_RETRY_DELAY_SECONDS = 30
STALE_IMPORT_BATCH_THRESHOLD = timedelta(minutes=10)
STALE_UPLOAD_STATUSES = {
    UploadedRun.Status.RECEIVING,
    UploadedRun.Status.RECEIVED,
    UploadedRun.Status.EXTRACTING,
}


@shared_task(bind=True, max_retries=3)
def run_import_batch(self, batch_id: int) -> None:
    try:
        process_import_batch(batch_id)
    except ImportContractError:
        batch = ImportBatch.objects.filter(pk=batch_id).only("celery_task_id").first()
        if batch is not None and self.request.id and batch.celery_task_id and batch.celery_task_id != self.request.id:
            return
        raise
    except Exception as exc:
        batch = ImportBatch.objects.filter(pk=batch_id).first()
        if batch is not None and batch.pipeline_run_id is None and self.request.retries < self.max_retries:
            _reset_batch_to_pending(
                batch,
                message="Import failed before the raw import committed. Re-queued for retry.",
            )
            raise self.retry(exc=exc, countdown=IMPORT_BATCH_RETRY_DELAY_SECONDS)
        raise


@shared_task(bind=True, max_retries=1)
def extract_uploaded_run(self, uploaded_run_id: int) -> None:
    try:
        extract_uploaded_zip(uploaded_run_id=uploaded_run_id)
    except UploadedRun.DoesNotExist:
        return
    except (ImportContractError, UploadValidationError) as exc:
        UploadedRun.objects.filter(pk=uploaded_run_id).update(
            status=UploadedRun.Status.FAILED,
            error_message=str(exc),
            failed_at=timezone.now(),
        )
        return


@shared_task
def reset_stale_import_batches() -> dict[str, int]:
    stale_cutoff = timezone.now() - STALE_IMPORT_BATCH_THRESHOLD
    stale_batch_ids = list(
        ImportBatch.objects.filter(status=ImportBatch.Status.RUNNING)
        .filter(Q(heartbeat_at__isnull=True) | Q(heartbeat_at__lt=stale_cutoff))
        .values_list("pk", flat=True)
    )

    requeued = 0
    failed = 0

    for batch_id in stale_batch_ids:
        should_dispatch = False

        with transaction.atomic():
            batch = ImportBatch.objects.select_for_update().filter(pk=batch_id).first()
            if batch is None or batch.status != ImportBatch.Status.RUNNING:
                continue
            if batch.heartbeat_at is not None and batch.heartbeat_at >= stale_cutoff:
                continue

            if batch.pipeline_run_id is None:
                _reset_batch_to_pending(
                    batch,
                    message="Worker heartbeat expired before the raw import committed. Re-queued automatically.",
                )
                should_dispatch = True
            else:
                _mark_batch_stale_failed(
                    batch,
                    message=(
                        "Worker heartbeat expired after raw import data was committed. "
                        "Manual follow-up is required before retrying this batch."
                    ),
                )
                failed += 1

        if should_dispatch:
            dispatch_import_batch(batch_id)
            requeued += 1

    return {"requeued": requeued, "failed": failed}


@shared_task
def cleanup_stale_uploaded_runs() -> dict[str, int]:
    now = timezone.now()
    incomplete_cutoff = now - timedelta(hours=settings.HOMOREPEAT_UPLOAD_INCOMPLETE_RETENTION_HOURS)
    failed_cutoff = now - timedelta(hours=settings.HOMOREPEAT_UPLOAD_FAILED_RETENTION_HOURS)
    stale_incomplete_ids = list(
        UploadedRun.objects.filter(
            status__in=STALE_UPLOAD_STATUSES,
            updated_at__lt=incomplete_cutoff,
        ).values_list("pk", flat=True)
    )
    stale_failed_ids = list(
        UploadedRun.objects.filter(
            status=UploadedRun.Status.FAILED,
            updated_at__lt=failed_cutoff,
        ).values_list("pk", flat=True)
    )

    incomplete_failed = 0
    incomplete_dirs_removed = 0
    failed_dirs_removed = 0

    for uploaded_run_id in stale_incomplete_ids:
        with transaction.atomic():
            uploaded_run = UploadedRun.objects.select_for_update().filter(pk=uploaded_run_id).first()
            if uploaded_run is None:
                continue
            if uploaded_run.status not in STALE_UPLOAD_STATUSES:
                continue
            if uploaded_run.updated_at >= incomplete_cutoff:
                continue

            if _remove_upload_working_directory(uploaded_run):
                incomplete_dirs_removed += 1
            uploaded_run.status = UploadedRun.Status.FAILED
            uploaded_run.error_message = "Upload expired before it completed."
            uploaded_run.failed_at = timezone.now()
            uploaded_run.save(update_fields=["status", "error_message", "failed_at", "updated_at"])
            incomplete_failed += 1

    for uploaded_run_id in stale_failed_ids:
        uploaded_run = UploadedRun.objects.filter(pk=uploaded_run_id, status=UploadedRun.Status.FAILED).first()
        if uploaded_run is None:
            continue
        if uploaded_run.updated_at >= failed_cutoff:
            continue
        if _remove_upload_working_directory(uploaded_run):
            failed_dirs_removed += 1

    return {
        "incomplete_failed": incomplete_failed,
        "incomplete_dirs_removed": incomplete_dirs_removed,
        "failed_dirs_removed": failed_dirs_removed,
    }


@shared_task(bind=True, name="imports.delete_pipeline_run_job")
def delete_pipeline_run_job(self, job_id: int) -> None:
    """Claim and execute async deletion for a DeletionJob."""
    from apps.imports.services.deletion.jobs import claim_deletion_job, execute_deletion_phases, mark_job_failed

    job = claim_deletion_job(job_id)
    if job is None:
        return

    try:
        execute_deletion_phases(job)
    except Exception as exc:
        mark_job_failed(job, exc)


def _remove_upload_working_directory(uploaded_run: UploadedRun) -> bool:
    upload_root = uploaded_run.upload_root
    imports_uploads_root = upload_root.parent
    if upload_root == imports_uploads_root or imports_uploads_root not in upload_root.parents:
        return False
    if not upload_root.exists():
        return False
    shutil.rmtree(upload_root)
    return True
