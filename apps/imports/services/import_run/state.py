from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.utils import timezone

from apps.browser.models.runs import PipelineRun
from apps.imports.models import ImportBatch
from apps.imports.services.published_run import ImportContractError


HEARTBEAT_FLUSH_INTERVAL_SECONDS = 2.0


@dataclass(frozen=True)
class ImportRunResult:
    batch: ImportBatch
    pipeline_run: PipelineRun
    counts: dict[str, int]


class ImportPhase:
    QUEUED = "queued"
    PARSING = "parsing_contract"
    PREPARING = "preparing_import"
    LOADING_FASTA = "loading_fasta"
    IMPORTING = "importing_rows"
    CATALOG_SYNC = "syncing_canonical_catalog"
    COMPLETED = "completed"
    FAILED = "failed"


class _ImportBatchStateReporter:
    def __init__(self, batch: ImportBatch) -> None:
        self.batch = batch
        self.connection = None
        self.last_flush_at = 0.0

        default_connection = connections[DEFAULT_DB_ALIAS]
        if default_connection.vendor != "postgresql":
            return

        self.connection = default_connection.copy()
        self.connection.ensure_connection()
        self.connection.set_autocommit(True)

    def save(self, update_fields: list[str], *, force: bool = False) -> None:
        if self.connection is None:
            self.batch.save(update_fields=update_fields)
            return

        now = monotonic()
        if not force and (now - self.last_flush_at) < HEARTBEAT_FLUSH_INTERVAL_SECONDS:
            return

        quoted_table = self.connection.ops.quote_name(self.batch._meta.db_table)
        quoted_pk = self.connection.ops.quote_name(self.batch._meta.pk.column)
        assignments: list[str] = []
        params: list[object] = []

        for field_name in update_fields:
            field = self.batch._meta.get_field(field_name)
            assignments.append(f"{self.connection.ops.quote_name(field.column)} = %s")
            params.append(
                field.get_db_prep_save(
                    getattr(self.batch, field.attname),
                    connection=self.connection,
                )
            )

        params.append(self.batch.pk)
        sql = f"UPDATE {quoted_table} SET {', '.join(assignments)} WHERE {quoted_pk} = %s"
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            updated_rows = cursor.rowcount
        if updated_rows == 0:
            self.batch.save(update_fields=update_fields)
        self.last_flush_at = now

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None


def _claim_import_batch(batch_or_id: ImportBatch | int) -> ImportBatch:
    batch_id = batch_or_id.pk if isinstance(batch_or_id, ImportBatch) else int(batch_or_id)
    with transaction.atomic():
        batch = ImportBatch.objects.select_for_update().get(pk=batch_id)
        if batch.status != ImportBatch.Status.PENDING:
            raise ImportContractError(
                f"Import batch {batch.pk} is {batch.status!r} and cannot be claimed for processing."
            )
        batch.status = ImportBatch.Status.RUNNING
        batch.phase = ImportPhase.PARSING
        batch.heartbeat_at = timezone.now()
        batch.progress_payload = {
            "message": "Worker claimed queued import batch.",
        }
        batch.error_message = ""
        batch.save(
            update_fields=[
                "status",
                "phase",
                "heartbeat_at",
                "progress_payload",
                "error_message",
            ]
        )
    return batch


def _set_batch_state(
    batch: ImportBatch,
    *,
    phase: str,
    progress_payload: dict[str, object],
    reporter: _ImportBatchStateReporter | None = None,
    force: bool = False,
) -> None:
    phase_changed = batch.phase != phase
    batch.phase = phase
    batch.heartbeat_at = timezone.now()
    batch.progress_payload = _normalize_progress_payload(progress_payload)
    if reporter is None:
        batch.save(update_fields=["phase", "heartbeat_at", "progress_payload"])
        return
    reporter.save(
        ["phase", "heartbeat_at", "progress_payload"],
        force=force or phase_changed,
    )


def _mark_batch_failed(
    batch: ImportBatch,
    exc: Exception,
    *,
    reporter: _ImportBatchStateReporter | None = None,
) -> None:
    failed_phase = batch.phase
    batch.status = ImportBatch.Status.FAILED
    batch.phase = ImportPhase.FAILED
    batch.finished_at = timezone.now()
    batch.heartbeat_at = batch.finished_at
    batch.error_count = 1
    batch.row_counts = {}
    batch.progress_payload = _normalize_progress_payload({
        "message": "Import failed.",
        "failed_phase": failed_phase,
    })
    batch.error_message = str(exc)
    update_fields = [
        "status",
        "phase",
        "finished_at",
        "heartbeat_at",
        "error_count",
        "row_counts",
        "progress_payload",
        "error_message",
    ]
    if reporter is None:
        batch.save(update_fields=update_fields)
        return
    reporter.save(update_fields, force=True)


def _mark_batch_completed(
    batch: ImportBatch,
    pipeline_run: PipelineRun,
    counts: dict[str, int],
    *,
    reporter: _ImportBatchStateReporter | None = None,
) -> None:
    finished_at = timezone.now()
    batch.pipeline_run = pipeline_run
    batch.status = ImportBatch.Status.COMPLETED
    batch.phase = ImportPhase.COMPLETED
    batch.finished_at = finished_at
    batch.heartbeat_at = finished_at
    batch.success_count = sum(counts.values())
    batch.error_count = 0
    batch.progress_payload = _normalize_progress_payload({
        "message": "Import completed successfully.",
        "counts": counts,
        "current": batch.success_count,
        "total": batch.success_count,
        "percent": 100,
        "unit": "rows",
    })
    batch.row_counts = counts
    batch.error_message = ""
    update_fields = [
        "pipeline_run",
        "status",
        "phase",
        "finished_at",
        "heartbeat_at",
        "success_count",
        "error_count",
        "progress_payload",
        "row_counts",
        "error_message",
    ]
    if reporter is None:
        batch.save(update_fields=update_fields)
        return
    reporter.save(update_fields, force=True)


def _normalize_progress_payload(progress_payload: dict[str, object]) -> dict[str, object]:
    normalized = dict(progress_payload)
    if "current" not in normalized and "processed" in normalized:
        normalized["current"] = normalized["processed"]

    try:
        current = float(normalized["current"])
        total = float(normalized["total"])
    except (KeyError, TypeError, ValueError):
        return normalized

    if total <= 0:
        return normalized

    percent = max(0.0, min(100.0, (current / total) * 100.0))
    normalized["percent"] = round(percent, 1)
    return normalized
