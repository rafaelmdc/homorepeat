from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.browser.models import PipelineRun
from apps.imports.models import ImportBatch
from apps.imports.services import dispatch_import_batch
from apps.imports.services.published_run import ImportContractError
from apps.imports.tasks import reset_stale_import_batches, run_import_batch


class RetryTriggered(Exception):
    pass


class ImportTaskTests(TestCase):
    def test_dispatch_import_batch_stores_task_id(self):
        batch = ImportBatch.objects.create(
            source_path="/tmp/run-alpha/publish",
            status=ImportBatch.Status.PENDING,
            phase="queued",
            progress_payload={"message": "Queued for background import."},
        )

        with patch(
            "apps.imports.tasks.run_import_batch.delay",
            return_value=SimpleNamespace(id="task-123"),
        ):
            task_id = dispatch_import_batch(batch)

        batch.refresh_from_db()
        self.assertEqual(task_id, "task-123")
        self.assertEqual(batch.celery_task_id, "task-123")

    def test_run_import_batch_requeues_precommit_failure_for_retry(self):
        batch = ImportBatch.objects.create(
            source_path="/tmp/run-alpha/publish",
            status=ImportBatch.Status.FAILED,
            phase="failed",
            error_message="boom",
        )

        with patch(
            "apps.imports.tasks.process_import_batch",
            side_effect=RuntimeError("boom"),
        ), patch.object(
            run_import_batch,
            "retry",
            side_effect=RetryTriggered("retry"),
        ) as retry_mock:
            with self.assertRaises(RetryTriggered):
                run_import_batch(batch.pk)

        batch.refresh_from_db()
        self.assertEqual(batch.status, ImportBatch.Status.PENDING)
        self.assertEqual(batch.phase, "queued")
        self.assertEqual(batch.error_message, "")
        self.assertEqual(
            batch.progress_payload["message"],
            "Import failed before the raw import committed. Re-queued for retry.",
        )
        retry_mock.assert_called_once()

    def test_run_import_batch_preserves_permanent_import_contract_error(self):
        batch = ImportBatch.objects.create(
            source_path="/tmp/run-alpha/publish",
            status=ImportBatch.Status.PENDING,
            phase="queued",
            celery_task_id="task-123",
        )

        with patch(
            "apps.imports.tasks.process_import_batch",
            side_effect=ImportContractError("contract boom"),
        ):
            with self.assertRaises(ImportContractError):
                run_import_batch(batch.pk)

    def test_reset_stale_import_batches_requeues_precommit_batch(self):
        batch = ImportBatch.objects.create(
            source_path="/tmp/run-alpha/publish",
            status=ImportBatch.Status.RUNNING,
            phase="importing_rows",
            heartbeat_at=timezone.now() - timedelta(minutes=20),
            progress_payload={"message": "Importing rows."},
            celery_task_id="old-task",
        )

        with patch(
            "apps.imports.tasks.run_import_batch.delay",
            return_value=SimpleNamespace(id="task-requeued"),
        ):
            result = reset_stale_import_batches()

        batch.refresh_from_db()
        self.assertEqual(result, {"requeued": 1, "failed": 0})
        self.assertEqual(batch.status, ImportBatch.Status.PENDING)
        self.assertEqual(batch.phase, "queued")
        self.assertEqual(batch.celery_task_id, "task-requeued")
        self.assertEqual(
            batch.progress_payload["message"],
            "Worker heartbeat expired before the raw import committed. Re-queued automatically.",
        )

    def test_reset_stale_import_batches_fails_postcommit_batch_without_requeue(self):
        pipeline_run = PipelineRun.objects.create(run_id="run-alpha", status="success")
        batch = ImportBatch.objects.create(
            source_path="/tmp/run-alpha/publish",
            pipeline_run=pipeline_run,
            status=ImportBatch.Status.RUNNING,
            phase="syncing_canonical_catalog",
            heartbeat_at=timezone.now() - timedelta(minutes=20),
            progress_payload={"message": "Syncing canonical catalog rows."},
            celery_task_id="old-task",
        )

        with patch("apps.imports.tasks.run_import_batch.delay") as delay_mock:
            result = reset_stale_import_batches()

        batch.refresh_from_db()
        self.assertEqual(result, {"requeued": 0, "failed": 1})
        self.assertEqual(batch.status, ImportBatch.Status.FAILED)
        self.assertEqual(batch.phase, "failed")
        self.assertEqual(batch.celery_task_id, "old-task")
        self.assertEqual(
            batch.progress_payload["message"],
            "Import failed after the worker heartbeat went stale.",
        )
        self.assertIn("Manual follow-up is required", batch.error_message)
        delay_mock.assert_not_called()
