from __future__ import annotations

from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.imports.models import ImportBatch
from apps.imports.services.import_run.api import dispatch_import_batch, process_import_batch
from apps.imports.services.import_run.state import _mark_batch_stale_failed, _reset_batch_to_pending
from apps.imports.services.published_run import ImportContractError


IMPORT_BATCH_RETRY_DELAY_SECONDS = 30
STALE_IMPORT_BATCH_THRESHOLD = timedelta(minutes=10)


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
