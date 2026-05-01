from __future__ import annotations

from datetime import timedelta
from io import BytesIO
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.browser.models import PipelineRun
from apps.imports.models import ImportBatch, UploadedRun
from apps.imports.services import dispatch_import_batch
from apps.imports.services.published_run import ImportContractError
from apps.imports.tasks import (
    cleanup_stale_uploaded_runs,
    extract_uploaded_run,
    reset_stale_import_batches,
    run_import_batch,
)
from .support import build_minimal_v2_publish_root


class RetryTriggered(Exception):
    pass


def _zip_bytes(files: dict[str, str]) -> bytes:
    payload = BytesIO()
    with zipfile.ZipFile(payload, mode="w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return payload.getvalue()


def _zip_directory(root: Path) -> bytes:
    payload = BytesIO()
    with zipfile.ZipFile(payload, mode="w") as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(root).as_posix())
    return payload.getvalue()


def _zip_bytes_with_symlink(name: str, target: str) -> bytes:
    payload = BytesIO()
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(payload, mode="w") as archive:
        archive.writestr(info, target)
    return payload.getvalue()


def _create_received_upload_from_zip_bytes(original_filename: str, zip_payload: bytes) -> UploadedRun:
    uploaded_run = UploadedRun.objects.create(
        original_filename=original_filename,
        status=UploadedRun.Status.RECEIVED,
        size_bytes=len(zip_payload),
        received_bytes=len(zip_payload),
        chunk_size_bytes=max(len(zip_payload), 1),
        total_chunks=1,
        received_chunks=[0],
    )
    uploaded_run.chunks_root.mkdir(parents=True)
    (uploaded_run.chunks_root / "0.part").write_bytes(zip_payload)
    return uploaded_run


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

    def test_extract_uploaded_run_moves_validated_publish_root_to_library(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                source_root = Path(tempdir) / "source"
                build_minimal_v2_publish_root(source_root, run_id="run-uploaded")
                zip_payload = _zip_directory(source_root)
                split_at = 10
                uploaded_run = UploadedRun.objects.create(
                    original_filename="run-alpha.zip",
                    status=UploadedRun.Status.RECEIVED,
                    size_bytes=len(zip_payload),
                    received_bytes=len(zip_payload),
                    chunk_size_bytes=10,
                    total_chunks=2,
                    received_chunks=[0, 1],
                )
                uploaded_run.chunks_root.mkdir(parents=True)
                (uploaded_run.chunks_root / "0.part").write_bytes(zip_payload[:split_at])
                (uploaded_run.chunks_root / "1.part").write_bytes(zip_payload[split_at:])

                extract_uploaded_run(uploaded_run.pk)

                uploaded_run.refresh_from_db()
                self.assertEqual(uploaded_run.status, UploadedRun.Status.READY)
                self.assertEqual(uploaded_run.run_id, "run-uploaded")
                self.assertEqual(uploaded_run.zip_path.read_bytes(), zip_payload)
                self.assertEqual(
                    uploaded_run.publish_root,
                    str((Path(tempdir) / "library" / "run-uploaded" / "publish").resolve()),
                )
                self.assertTrue((Path(uploaded_run.publish_root) / "metadata" / "run_manifest.json").is_file())

    def test_extract_uploaded_run_uses_existing_assembled_zip_and_moves_to_library(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                source_root = Path(tempdir) / "source"
                build_minimal_v2_publish_root(source_root, run_id="already-assembled")
                zip_payload = _zip_directory(source_root)
                uploaded_run = UploadedRun.objects.create(
                    original_filename="run-alpha.zip",
                    status=UploadedRun.Status.EXTRACTING,
                    size_bytes=len(zip_payload),
                    received_bytes=len(zip_payload),
                    chunk_size_bytes=10,
                    total_chunks=1,
                    received_chunks=[0],
                )
                uploaded_run.upload_root.mkdir(parents=True)
                uploaded_run.zip_path.write_bytes(zip_payload)

                extract_uploaded_run(uploaded_run.pk)

                uploaded_run.refresh_from_db()
                self.assertEqual(uploaded_run.status, UploadedRun.Status.READY)
                self.assertEqual(uploaded_run.run_id, "already-assembled")
                self.assertTrue((Path(uploaded_run.publish_root) / "metadata" / "run_manifest.json").is_file())

    def test_extract_uploaded_run_fails_when_library_run_id_exists(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                source_root = Path(tempdir) / "source"
                build_minimal_v2_publish_root(source_root, run_id="duplicate-run")
                existing_library_root = Path(tempdir) / "library" / "duplicate-run"
                existing_library_root.mkdir(parents=True)
                uploaded_run = _create_received_upload_from_zip_bytes(
                    "run.zip",
                    _zip_directory(source_root),
                )

                extract_uploaded_run(uploaded_run.pk)

                uploaded_run.refresh_from_db()
                self.assertEqual(uploaded_run.status, UploadedRun.Status.FAILED)
                self.assertIn("already exists in the upload library", uploaded_run.error_message)
                self.assertEqual(uploaded_run.publish_root, "")

    def test_extract_uploaded_run_marks_invalid_upload_failed(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                uploaded_run = UploadedRun.objects.create(
                    original_filename="run-alpha.zip",
                    status=UploadedRun.Status.RECEIVED,
                    size_bytes=11,
                    received_bytes=10,
                    chunk_size_bytes=10,
                    total_chunks=2,
                    received_chunks=[0],
                )
                uploaded_run.chunks_root.mkdir(parents=True)
                (uploaded_run.chunks_root / "0.part").write_bytes(b"abcdefghij")

                extract_uploaded_run(uploaded_run.pk)

                uploaded_run.refresh_from_db()
                self.assertEqual(uploaded_run.status, UploadedRun.Status.FAILED)
                self.assertIn("missing chunk", uploaded_run.error_message)

    def test_extract_uploaded_run_rejects_missing_publish_root(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                uploaded_run = _create_received_upload_from_zip_bytes(
                    "run.zip",
                    _zip_bytes({"data.txt": "ok"}),
                )

                extract_uploaded_run(uploaded_run.pk)

                uploaded_run.refresh_from_db()
                self.assertEqual(uploaded_run.status, UploadedRun.Status.FAILED)
                self.assertIn("does not contain publish/metadata/run_manifest.json", uploaded_run.error_message)

    def test_extract_uploaded_run_rejects_multiple_publish_roots(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                uploaded_run = _create_received_upload_from_zip_bytes(
                    "run.zip",
                    _zip_bytes(
                        {
                            "run-a/publish/metadata/run_manifest.json": "{}",
                            "run-b/publish/metadata/run_manifest.json": "{}",
                        }
                    ),
                )

                extract_uploaded_run(uploaded_run.pk)

                uploaded_run.refresh_from_db()
                self.assertEqual(uploaded_run.status, UploadedRun.Status.FAILED)
                self.assertIn("multiple publish/metadata/run_manifest.json", uploaded_run.error_message)

    def test_extract_uploaded_run_rejects_invalid_publish_contract(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                uploaded_run = _create_received_upload_from_zip_bytes(
                    "run.zip",
                    _zip_bytes({"publish/metadata/run_manifest.json": "{}"}),
                )

                extract_uploaded_run(uploaded_run.pk)

                uploaded_run.refresh_from_db()
                self.assertEqual(uploaded_run.status, UploadedRun.Status.FAILED)
                self.assertIn("Run manifest is missing required keys", uploaded_run.error_message)

    def test_extract_uploaded_run_rejects_path_traversal(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                uploaded_run = _create_received_upload_from_zip_bytes(
                    "run.zip",
                    _zip_bytes({"../evil.txt": "nope"}),
                )

                extract_uploaded_run(uploaded_run.pk)

                uploaded_run.refresh_from_db()
                self.assertEqual(uploaded_run.status, UploadedRun.Status.FAILED)
                self.assertIn("path traversal", uploaded_run.error_message)
                self.assertFalse((uploaded_run.upload_root / "evil.txt").exists())

    @override_settings(HOMOREPEAT_UPLOAD_MAX_EXTRACTED_BYTES=5)
    def test_extract_uploaded_run_rejects_extracted_size_over_limit(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                uploaded_run = _create_received_upload_from_zip_bytes(
                    "run.zip",
                    _zip_bytes({"publish/data.txt": "too-large"}),
                )

                extract_uploaded_run(uploaded_run.pk)

                uploaded_run.refresh_from_db()
                self.assertEqual(uploaded_run.status, UploadedRun.Status.FAILED)
                self.assertIn("extracted size", uploaded_run.error_message)
                self.assertFalse(uploaded_run.extracted_root.exists())

    @override_settings(HOMOREPEAT_UPLOAD_MAX_FILES=1)
    def test_extract_uploaded_run_rejects_file_count_over_limit(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                uploaded_run = _create_received_upload_from_zip_bytes(
                    "run.zip",
                    _zip_bytes(
                        {
                            "publish/one.txt": "one",
                            "publish/two.txt": "two",
                        }
                    ),
                )

                extract_uploaded_run(uploaded_run.pk)

                uploaded_run.refresh_from_db()
                self.assertEqual(uploaded_run.status, UploadedRun.Status.FAILED)
                self.assertIn("entries", uploaded_run.error_message)
                self.assertFalse(uploaded_run.extracted_root.exists())

    def test_extract_uploaded_run_rejects_symlink_member(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                uploaded_run = _create_received_upload_from_zip_bytes(
                    "run.zip",
                    _zip_bytes_with_symlink("publish/link", "target"),
                )

                extract_uploaded_run(uploaded_run.pk)

                uploaded_run.refresh_from_db()
                self.assertEqual(uploaded_run.status, UploadedRun.Status.FAILED)
                self.assertIn("symlink or special file", uploaded_run.error_message)

    @override_settings(
        HOMOREPEAT_UPLOAD_INCOMPLETE_RETENTION_HOURS=1,
        HOMOREPEAT_UPLOAD_FAILED_RETENTION_HOURS=2,
    )
    def test_cleanup_stale_uploaded_runs_removes_incomplete_and_failed_working_dirs(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                stale_receiving = UploadedRun.objects.create(
                    original_filename="stale-receiving.zip",
                    status=UploadedRun.Status.RECEIVING,
                    size_bytes=10,
                    total_chunks=1,
                )
                stale_receiving.upload_root.mkdir(parents=True)
                (stale_receiving.upload_root / "chunk.tmp").write_text("old", encoding="utf-8")
                UploadedRun.objects.filter(pk=stale_receiving.pk).update(
                    updated_at=timezone.now() - timedelta(hours=3)
                )

                stale_failed = UploadedRun.objects.create(
                    original_filename="stale-failed.zip",
                    status=UploadedRun.Status.FAILED,
                    size_bytes=10,
                    total_chunks=1,
                    error_message="bad zip",
                )
                stale_failed.upload_root.mkdir(parents=True)
                (stale_failed.upload_root / "source.zip").write_bytes(b"bad")
                UploadedRun.objects.filter(pk=stale_failed.pk).update(
                    updated_at=timezone.now() - timedelta(hours=4)
                )

                fresh_receiving = UploadedRun.objects.create(
                    original_filename="fresh-receiving.zip",
                    status=UploadedRun.Status.RECEIVING,
                    size_bytes=10,
                    total_chunks=1,
                )
                fresh_receiving.upload_root.mkdir(parents=True)

                result = cleanup_stale_uploaded_runs()

                self.assertEqual(
                    result,
                    {
                        "incomplete_failed": 1,
                        "incomplete_dirs_removed": 1,
                        "failed_dirs_removed": 1,
                    },
                )
                stale_receiving.refresh_from_db()
                stale_failed.refresh_from_db()
                self.assertEqual(stale_receiving.status, UploadedRun.Status.FAILED)
                self.assertIn("expired", stale_receiving.error_message)
                self.assertEqual(stale_failed.status, UploadedRun.Status.FAILED)
                self.assertFalse(stale_receiving.upload_root.exists())
                self.assertFalse(stale_failed.upload_root.exists())
                self.assertTrue(fresh_receiving.upload_root.exists())

    @override_settings(
        HOMOREPEAT_UPLOAD_INCOMPLETE_RETENTION_HOURS=1,
        HOMOREPEAT_UPLOAD_FAILED_RETENTION_HOURS=1,
    )
    def test_cleanup_stale_uploaded_runs_preserves_ready_imported_library_data(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                for status in (UploadedRun.Status.READY, UploadedRun.Status.IMPORTED):
                    uploaded_run = UploadedRun.objects.create(
                        original_filename=f"{status}.zip",
                        status=status,
                        size_bytes=10,
                        received_bytes=10,
                        total_chunks=1,
                        run_id=f"run-{status}",
                        publish_root=str(Path(tempdir) / "library" / f"run-{status}" / "publish"),
                    )
                    uploaded_run.upload_root.mkdir(parents=True)
                    uploaded_run.library_root.mkdir(parents=True)
                    (uploaded_run.library_root / "publish").mkdir()
                    (uploaded_run.library_root / "publish" / "data.txt").write_text("keep", encoding="utf-8")
                    UploadedRun.objects.filter(pk=uploaded_run.pk).update(
                        updated_at=timezone.now() - timedelta(hours=3)
                    )

                result = cleanup_stale_uploaded_runs()

                self.assertEqual(
                    result,
                    {
                        "incomplete_failed": 0,
                        "incomplete_dirs_removed": 0,
                        "failed_dirs_removed": 0,
                    },
                )
                for uploaded_run in UploadedRun.objects.all():
                    self.assertTrue(uploaded_run.upload_root.exists())
                    self.assertTrue((uploaded_run.library_root / "publish" / "data.txt").is_file())

    def test_cleanup_stale_uploaded_runs_is_scheduled(self):
        self.assertEqual(
            settings.CELERY_BEAT_SCHEDULE["cleanup-stale-uploaded-runs"]["task"],
            "apps.imports.tasks.cleanup_stale_uploaded_runs",
        )

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
