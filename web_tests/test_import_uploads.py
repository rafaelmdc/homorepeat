import hashlib
import json
import shutil
import uuid
from collections import namedtuple
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.imports.models import ImportBatch, UploadedRun, UploadedRunChunk
from apps.imports.services.uploads import UploadValidationError

from .support import build_minimal_v2_publish_root


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ImportUploadApiTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.staff_user = self.user_model.objects.create_user(
            username="staff",
            password="password",
            is_staff=True,
        )
        self.client.force_login(self.staff_user)

    def test_start_upload_rejects_non_zip_filename(self):
        response = self.client.post(
            reverse("imports:upload-start"),
            data=json.dumps(
                {
                    "filename": "run-alpha.txt",
                    "size_bytes": 100,
                    "total_chunks": 1,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertIn(".zip", response.json()["error"])
        self.assertEqual(UploadedRun.objects.count(), 0)

    @override_settings(HOMOREPEAT_UPLOAD_MAX_ZIP_BYTES=10)
    def test_start_upload_rejects_size_over_configured_limit(self):
        response = self.client.post(
            reverse("imports:upload-start"),
            data=json.dumps(
                {
                    "filename": "run-alpha.zip",
                    "size_bytes": 11,
                    "total_chunks": 1,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertIn("maximum zip size", response.json()["error"])
        self.assertEqual(UploadedRun.objects.count(), 0)

    @override_settings(HOMOREPEAT_UPLOAD_CHUNK_BYTES=10)
    def test_start_upload_rejects_inconsistent_total_chunks(self):
        response = self.client.post(
            reverse("imports:upload-start"),
            data=json.dumps(
                {
                    "filename": "run-alpha.zip",
                    "size_bytes": 21,
                    "total_chunks": 2,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertIn("total_chunks must be 3", response.json()["error"])
        self.assertEqual(UploadedRun.objects.count(), 0)

    @override_settings(HOMOREPEAT_UPLOAD_CHUNK_BYTES=10)
    def test_start_upload_creates_uploaded_run(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                response = self.client.post(
                    reverse("imports:upload-start"),
                    data=json.dumps(
                        {
                            "filename": "run-alpha.zip",
                            "size_bytes": 21,
                            "total_chunks": 3,
                        }
                    ),
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertTrue(payload["ok"])
                uploaded_run = UploadedRun.objects.get(upload_id=payload["upload_id"])
                self.assertEqual(uploaded_run.original_filename, "run-alpha.zip")
                self.assertEqual(uploaded_run.size_bytes, 21)
                self.assertEqual(uploaded_run.chunk_size_bytes, 10)
                self.assertEqual(uploaded_run.total_chunks, 3)
                self.assertEqual(uploaded_run.status, UploadedRun.Status.RECEIVING)
                self.assertTrue(uploaded_run.chunks_root.is_dir())

    @override_settings(HOMOREPEAT_UPLOAD_CHUNK_BYTES=10)
    def test_chunk_upload_writes_part_file_and_records_chunk_index(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                uploaded_run = UploadedRun.objects.create(
                    original_filename="run-alpha.zip",
                    size_bytes=21,
                    chunk_size_bytes=10,
                    total_chunks=3,
                )
                chunk = SimpleUploadedFile("0.part", b"abcdefghij")

                response = self.client.post(
                    reverse("imports:upload-chunk", kwargs={"upload_id": uploaded_run.upload_id}),
                    data={
                        "chunk_index": "0",
                        "chunk": chunk,
                    },
                )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertTrue(payload["ok"])
                uploaded_run.refresh_from_db()
                self.assertEqual(uploaded_run.received_chunks, [0])
                self.assertEqual(uploaded_run.received_bytes, 10)
                self.assertEqual((uploaded_run.chunks_root / "0.part").read_bytes(), b"abcdefghij")

    @override_settings(HOMOREPEAT_UPLOAD_CHUNK_BYTES=10)
    def test_chunk_upload_rejects_out_of_range_chunk_index(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                uploaded_run = UploadedRun.objects.create(
                    original_filename="run-alpha.zip",
                    size_bytes=21,
                    chunk_size_bytes=10,
                    total_chunks=3,
                )
                chunk = SimpleUploadedFile("3.part", b"x")

                response = self.client.post(
                    reverse("imports:upload-chunk", kwargs={"upload_id": uploaded_run.upload_id}),
                    data={
                        "chunk_index": "3",
                        "chunk": chunk,
                    },
                )

                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()["ok"])
                self.assertFalse(Path(uploaded_run.chunks_root / "3.part").exists())

    def test_complete_upload_rejects_missing_chunks(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                uploaded_run = UploadedRun.objects.create(
                    original_filename="run-alpha.zip",
                    size_bytes=11,
                    chunk_size_bytes=10,
                    total_chunks=2,
                )
                uploaded_run.chunks_root.mkdir(parents=True)
                (uploaded_run.chunks_root / "0.part").write_bytes(b"abcdefghij")

                with patch("apps.imports.tasks.extract_uploaded_run.delay") as delay_mock:
                    response = self.client.post(
                        reverse("imports:upload-complete", kwargs={"upload_id": uploaded_run.upload_id})
                    )

                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()["ok"])
                self.assertIn("missing chunk", response.json()["error"])
                delay_mock.assert_not_called()
                uploaded_run.refresh_from_db()
                self.assertEqual(uploaded_run.status, UploadedRun.Status.RECEIVING)

    def test_complete_upload_marks_received_from_filesystem_chunks(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                uploaded_run = UploadedRun.objects.create(
                    original_filename="run-alpha.zip",
                    size_bytes=11,
                    chunk_size_bytes=10,
                    total_chunks=2,
                    received_chunks=[],
                )
                uploaded_run.chunks_root.mkdir(parents=True)
                (uploaded_run.chunks_root / "0.part").write_bytes(b"abcdefghij")
                (uploaded_run.chunks_root / "1.part").write_bytes(b"k")

                with patch("apps.imports.tasks.extract_uploaded_run.delay") as delay_mock:
                    response = self.client.post(
                        reverse("imports:upload-complete", kwargs={"upload_id": uploaded_run.upload_id})
                    )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["status"], UploadedRun.Status.RECEIVED)
                delay_mock.assert_called_once_with(uploaded_run.pk)
                uploaded_run.refresh_from_db()
                self.assertEqual(uploaded_run.status, UploadedRun.Status.RECEIVED)
                self.assertEqual(uploaded_run.received_chunks, [0, 1])
                self.assertEqual(uploaded_run.received_bytes, 11)

    def test_complete_upload_is_idempotent_when_already_received(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                uploaded_run = UploadedRun.objects.create(
                    original_filename="run-alpha.zip",
                    status=UploadedRun.Status.RECEIVED,
                    size_bytes=11,
                    received_bytes=11,
                    chunk_size_bytes=10,
                    total_chunks=2,
                    received_chunks=[0, 1],
                )

                with patch("apps.imports.tasks.extract_uploaded_run.delay") as delay_mock:
                    response = self.client.post(
                        reverse("imports:upload-complete", kwargs={"upload_id": uploaded_run.upload_id})
                    )

                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["ok"])
                self.assertEqual(response.json()["status"], UploadedRun.Status.RECEIVED)
                self.assertEqual(response.json()["received_chunks"], [0, 1])
                delay_mock.assert_not_called()

    def test_complete_upload_rejects_byte_total_mismatch(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                uploaded_run = UploadedRun.objects.create(
                    original_filename="run-alpha.zip",
                    size_bytes=11,
                    chunk_size_bytes=10,
                    total_chunks=2,
                )
                uploaded_run.chunks_root.mkdir(parents=True)
                (uploaded_run.chunks_root / "0.part").write_bytes(b"abc")
                (uploaded_run.chunks_root / "1.part").write_bytes(b"def")

                with patch("apps.imports.tasks.extract_uploaded_run.delay") as delay_mock:
                    response = self.client.post(
                        reverse("imports:upload-complete", kwargs={"upload_id": uploaded_run.upload_id})
                    )

                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()["ok"])
                self.assertIn("expected 11", response.json()["error"])
                delay_mock.assert_not_called()
                uploaded_run.refresh_from_db()
                self.assertEqual(uploaded_run.status, UploadedRun.Status.RECEIVING)

    def test_import_ready_uploaded_run_queues_import_batch(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_v2_publish_root(Path(tempdir) / "run-alpha", run_id="run-alpha")
            uploaded_run = UploadedRun.objects.create(
                original_filename="run-alpha.zip",
                status=UploadedRun.Status.READY,
                size_bytes=100,
                received_bytes=100,
                total_chunks=1,
                run_id="run-alpha",
                publish_root=str(publish_root),
            )

            with patch(
                "apps.imports.tasks.run_import_batch.delay",
                return_value=SimpleNamespace(id="task-123"),
            ) as delay_mock:
                response = self.client.post(
                    reverse("imports:upload-import", kwargs={"upload_id": uploaded_run.upload_id})
                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["queued_now"])
            self.assertEqual(payload["status"], UploadedRun.Status.QUEUED)
            uploaded_run.refresh_from_db()
            self.assertEqual(uploaded_run.status, UploadedRun.Status.QUEUED)
            self.assertIsNotNone(uploaded_run.import_batch)
            self.assertEqual(uploaded_run.import_batch.source_path, str(publish_root.resolve()))
            self.assertEqual(uploaded_run.import_batch.status, ImportBatch.Status.PENDING)
            self.assertEqual(uploaded_run.import_batch.phase, "queued")
            self.assertEqual(uploaded_run.import_batch.celery_task_id, "task-123")
            self.assertEqual(payload["import_batch"]["id"], uploaded_run.import_batch_id)
            self.assertEqual(payload["import_batch"]["celery_task_id"], "task-123")
            delay_mock.assert_called_once_with(uploaded_run.import_batch_id)

    def test_import_ready_uploaded_run_honors_replace_existing(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_v2_publish_root(Path(tempdir) / "run-alpha", run_id="run-alpha")
            uploaded_run = UploadedRun.objects.create(
                original_filename="run-alpha.zip",
                status=UploadedRun.Status.READY,
                size_bytes=100,
                received_bytes=100,
                total_chunks=1,
                run_id="run-alpha",
                publish_root=str(publish_root),
            )

            with patch(
                "apps.imports.tasks.run_import_batch.delay",
                return_value=SimpleNamespace(id="task-123"),
            ):
                response = self.client.post(
                    reverse("imports:upload-import", kwargs={"upload_id": uploaded_run.upload_id}),
                    data={"replace_existing": "on"},
                )

            self.assertEqual(response.status_code, 200)
            uploaded_run.refresh_from_db()
            self.assertTrue(uploaded_run.import_batch.replace_existing)

    def test_import_uploaded_run_rejects_non_ready_status(self):
        uploaded_run = UploadedRun.objects.create(
            original_filename="run-alpha.zip",
            status=UploadedRun.Status.RECEIVING,
            size_bytes=100,
            received_bytes=50,
            total_chunks=1,
        )

        with patch("apps.imports.tasks.run_import_batch.delay") as delay_mock:
            response = self.client.post(
                reverse("imports:upload-import", kwargs={"upload_id": uploaded_run.upload_id})
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertIn("not ready", response.json()["error"])
        delay_mock.assert_not_called()
        self.assertEqual(ImportBatch.objects.count(), 0)

    def test_import_uploaded_run_returns_existing_linked_batch(self):
        statuses = [UploadedRun.Status.QUEUED, UploadedRun.Status.IMPORTED]

        for status in statuses:
            ImportBatch.objects.all().delete()
            UploadedRun.objects.all().delete()
            import_batch = ImportBatch.objects.create(
                source_path="/tmp/run-alpha/publish",
                status=ImportBatch.Status.PENDING,
                phase="queued",
                celery_task_id="task-existing",
            )
            uploaded_run = UploadedRun.objects.create(
                original_filename="run-alpha.zip",
                status=status,
                size_bytes=100,
                received_bytes=100,
                total_chunks=1,
                run_id="run-alpha",
                publish_root="/tmp/run-alpha/publish",
                import_batch=import_batch,
            )

            with patch("apps.imports.tasks.run_import_batch.delay") as delay_mock:
                response = self.client.post(
                    reverse("imports:upload-import", kwargs={"upload_id": uploaded_run.upload_id})
                )

            with self.subTest(status=status):
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertTrue(payload["ok"])
                self.assertFalse(payload["queued_now"])
                self.assertEqual(payload["status"], status)
                self.assertEqual(payload["import_batch"]["id"], import_batch.pk)
                self.assertEqual(payload["import_batch"]["celery_task_id"], "task-existing")
                self.assertEqual(ImportBatch.objects.count(), 1)
                delay_mock.assert_not_called()


class UploadChecksumTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.staff_user = self.user_model.objects.create_user(
            username="staff",
            password="password",
            is_staff=True,
        )
        self.client.force_login(self.staff_user)

    @override_settings(HOMOREPEAT_UPLOAD_CHUNK_BYTES=10)
    def test_start_upload_accepts_valid_file_sha256(self):
        valid_sha256 = "a" * 64
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                response = self.client.post(
                    reverse("imports:upload-start"),
                    data=json.dumps({
                        "filename": "run-alpha.zip",
                        "size_bytes": 10,
                        "total_chunks": 1,
                        "file_sha256": valid_sha256,
                    }),
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["ok"])
                uploaded_run = UploadedRun.objects.get(upload_id=response.json()["upload_id"])
                self.assertEqual(uploaded_run.file_sha256, valid_sha256)

    @override_settings(HOMOREPEAT_UPLOAD_CHUNK_BYTES=10)
    def test_start_upload_rejects_malformed_file_sha256(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                response = self.client.post(
                    reverse("imports:upload-start"),
                    data=json.dumps({
                        "filename": "run-alpha.zip",
                        "size_bytes": 10,
                        "total_chunks": 1,
                        "file_sha256": "not-a-valid-hash",
                    }),
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()["ok"])
                self.assertIn("file_sha256", response.json()["error"])
                self.assertEqual(UploadedRun.objects.count(), 0)

    @override_settings(HOMOREPEAT_UPLOAD_CHUNK_BYTES=10)
    def test_chunk_upload_accepts_matching_chunk_sha256(self):
        chunk_data = b"abcdefghij"
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                uploaded_run = UploadedRun.objects.create(
                    original_filename="run-alpha.zip",
                    size_bytes=10,
                    chunk_size_bytes=10,
                    total_chunks=1,
                )
                uploaded_run.chunks_root.mkdir(parents=True)

                response = self.client.post(
                    reverse("imports:upload-chunk", kwargs={"upload_id": uploaded_run.upload_id}),
                    data={
                        "chunk_index": "0",
                        "chunk_sha256": _sha256(chunk_data),
                        "chunk": SimpleUploadedFile("0.part", chunk_data),
                    },
                )

                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["ok"])
                record = UploadedRunChunk.objects.get(uploaded_run=uploaded_run, chunk_index=0)
                self.assertEqual(record.sha256, _sha256(chunk_data))
                self.assertEqual(record.size_bytes, 10)

    @override_settings(HOMOREPEAT_UPLOAD_CHUNK_BYTES=10)
    def test_chunk_upload_rejects_checksum_mismatch(self):
        chunk_data = b"abcdefghij"
        wrong_sha256 = "b" * 64
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                uploaded_run = UploadedRun.objects.create(
                    original_filename="run-alpha.zip",
                    size_bytes=10,
                    chunk_size_bytes=10,
                    total_chunks=1,
                )
                uploaded_run.chunks_root.mkdir(parents=True)

                response = self.client.post(
                    reverse("imports:upload-chunk", kwargs={"upload_id": uploaded_run.upload_id}),
                    data={
                        "chunk_index": "0",
                        "chunk_sha256": wrong_sha256,
                        "chunk": SimpleUploadedFile("0.part", chunk_data),
                    },
                )

                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()["ok"])
                self.assertIn("checksum mismatch", response.json()["error"])
                self.assertFalse((uploaded_run.chunks_root / "0.part").exists())
                self.assertEqual(UploadedRunChunk.objects.filter(uploaded_run=uploaded_run).count(), 0)

    @override_settings(HOMOREPEAT_UPLOAD_CHUNK_BYTES=10)
    def test_chunk_upload_idempotent_for_identical_chunk(self):
        chunk_data = b"abcdefghij"
        chunk_sha256 = _sha256(chunk_data)
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                uploaded_run = UploadedRun.objects.create(
                    original_filename="run-alpha.zip",
                    size_bytes=10,
                    chunk_size_bytes=10,
                    total_chunks=1,
                )
                uploaded_run.chunks_root.mkdir(parents=True)

                for _ in range(2):
                    response = self.client.post(
                        reverse("imports:upload-chunk", kwargs={"upload_id": uploaded_run.upload_id}),
                        data={
                            "chunk_index": "0",
                            "chunk_sha256": chunk_sha256,
                            "chunk": SimpleUploadedFile("0.part", chunk_data),
                        },
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.json()["ok"])

                self.assertEqual(
                    UploadedRunChunk.objects.filter(uploaded_run=uploaded_run, chunk_index=0).count(), 1
                )

    @override_settings(HOMOREPEAT_UPLOAD_CHUNK_BYTES=10)
    def test_chunk_upload_rejects_conflicting_chunk(self):
        chunk_data = b"abcdefghij"
        different_chunk_data = b"ABCDEFGHIJ"
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                uploaded_run = UploadedRun.objects.create(
                    original_filename="run-alpha.zip",
                    size_bytes=10,
                    chunk_size_bytes=10,
                    total_chunks=1,
                )
                uploaded_run.chunks_root.mkdir(parents=True)

                self.client.post(
                    reverse("imports:upload-chunk", kwargs={"upload_id": uploaded_run.upload_id}),
                    data={
                        "chunk_index": "0",
                        "chunk_sha256": _sha256(chunk_data),
                        "chunk": SimpleUploadedFile("0.part", chunk_data),
                    },
                )

                response = self.client.post(
                    reverse("imports:upload-chunk", kwargs={"upload_id": uploaded_run.upload_id}),
                    data={
                        "chunk_index": "0",
                        "chunk_sha256": _sha256(different_chunk_data),
                        "chunk": SimpleUploadedFile("0.part", different_chunk_data),
                    },
                )

                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()["ok"])
                self.assertIn("conflicts", response.json()["error"])
                self.assertEqual(
                    UploadedRunChunk.objects.filter(uploaded_run=uploaded_run, chunk_index=0).count(), 1
                )

    def test_assembled_zip_checksum_mismatch_marks_upload_failed(self):
        chunk_data = b"abcdefghij"
        wrong_file_sha256 = "b" * 64
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                uploaded_run = UploadedRun.objects.create(
                    original_filename="run-alpha.zip",
                    status=UploadedRun.Status.RECEIVED,
                    size_bytes=10,
                    chunk_size_bytes=10,
                    total_chunks=1,
                    received_chunks=[0],
                    received_bytes=10,
                    file_sha256=wrong_file_sha256,
                )
                uploaded_run.chunks_root.mkdir(parents=True)
                (uploaded_run.chunks_root / "0.part").write_bytes(chunk_data)

                from apps.imports.services.uploads import assemble_uploaded_zip

                with self.assertRaises(UploadValidationError):
                    assemble_uploaded_zip(uploaded_run_id=uploaded_run.pk)

                uploaded_run.refresh_from_db()
                self.assertEqual(uploaded_run.status, UploadedRun.Status.FAILED)
                self.assertIsNotNone(uploaded_run.assembled_sha256)
                self.assertEqual(uploaded_run.checksum_status, "failed")
                self.assertIn("does not match", uploaded_run.checksum_error)


class UploadStatusApiTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.staff_user = self.user_model.objects.create_user(
            username="staff",
            password="password",
            is_staff=True,
        )
        self.client.force_login(self.staff_user)

    def test_status_returns_404_for_unknown_upload(self):
        response = self.client.get(
            reverse("imports:upload-status", kwargs={"upload_id": uuid.uuid4()})
        )
        self.assertEqual(response.status_code, 404)

    def test_status_reports_filesystem_chunks_when_db_record_is_missing(self):
        """Filesystem-present .part files appear in status even without a DB chunk record."""
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                uploaded_run = UploadedRun.objects.create(
                    original_filename="run-alpha.zip",
                    size_bytes=20,
                    chunk_size_bytes=10,
                    total_chunks=2,
                    received_chunks=[],
                )
                uploaded_run.chunks_root.mkdir(parents=True)
                (uploaded_run.chunks_root / "0.part").write_bytes(b"abcdefghij")
                # No UploadedRunChunk record — simulating stale DB after a crash

                response = self.client.get(
                    reverse("imports:upload-status", kwargs={"upload_id": uploaded_run.upload_id})
                )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(len(payload["received_chunks"]), 1)
                chunk = payload["received_chunks"][0]
                self.assertEqual(chunk["index"], 0)
                self.assertEqual(chunk["size_bytes"], 10)
                self.assertIsNone(chunk["sha256"])

    def test_status_shows_only_filesystem_present_chunks(self):
        """Chunks present on filesystem are listed; missing chunks are not."""
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                chunk_data = b"abcdefghij"
                uploaded_run = UploadedRun.objects.create(
                    original_filename="run-alpha.zip",
                    size_bytes=30,
                    chunk_size_bytes=10,
                    total_chunks=3,
                )
                uploaded_run.chunks_root.mkdir(parents=True)
                (uploaded_run.chunks_root / "0.part").write_bytes(chunk_data)
                UploadedRunChunk.objects.create(
                    uploaded_run=uploaded_run,
                    chunk_index=0,
                    size_bytes=10,
                    sha256=_sha256(chunk_data),
                )

                response = self.client.get(
                    reverse("imports:upload-status", kwargs={"upload_id": uploaded_run.upload_id})
                )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["total_chunks"], 3)
                self.assertEqual(len(payload["received_chunks"]), 1)
                self.assertEqual(payload["received_chunks"][0]["index"], 0)
                self.assertEqual(payload["received_chunks"][0]["sha256"], _sha256(chunk_data))
                self.assertIn("upload_chunks", payload["allowed_actions"])

    def test_status_includes_import_batch_when_linked(self):
        import_batch = ImportBatch.objects.create(
            source_path="/tmp/run-alpha/publish",
            status=ImportBatch.Status.RUNNING,
            phase="importing_rows",
        )
        uploaded_run = UploadedRun.objects.create(
            original_filename="run-alpha.zip",
            status=UploadedRun.Status.QUEUED,
            size_bytes=10,
            chunk_size_bytes=10,
            total_chunks=1,
            run_id="run-alpha",
            import_batch=import_batch,
        )

        response = self.client.get(
            reverse("imports:upload-status", kwargs={"upload_id": uploaded_run.upload_id})
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNotNone(payload["import_batch"])
        self.assertEqual(payload["import_batch"]["id"], import_batch.pk)
        self.assertEqual(payload["import_batch"]["status"], ImportBatch.Status.RUNNING)
        self.assertEqual(payload["import_batch"]["phase"], "importing_rows")
        self.assertIn("wait", payload["allowed_actions"])

    def test_status_allowed_actions_ready(self):
        uploaded_run = UploadedRun.objects.create(
            original_filename="run-alpha.zip",
            status=UploadedRun.Status.READY,
            size_bytes=10,
            chunk_size_bytes=10,
            total_chunks=1,
            run_id="run-alpha",
            publish_root="/tmp/run-alpha/publish",
        )

        response = self.client.get(
            reverse("imports:upload-status", kwargs={"upload_id": uploaded_run.upload_id})
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("import", response.json()["allowed_actions"])

    def test_status_full_payload_shape(self):
        """Verify all documented status fields are present in the response."""
        uploaded_run = UploadedRun.objects.create(
            original_filename="run-alpha.zip",
            status=UploadedRun.Status.RECEIVING,
            size_bytes=10,
            chunk_size_bytes=10,
            total_chunks=1,
            file_sha256="a" * 64,
        )

        response = self.client.get(
            reverse("imports:upload-status", kwargs={"upload_id": uploaded_run.upload_id})
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        for field in (
            "upload_id", "status", "filename", "size_bytes", "chunk_size_bytes",
            "total_chunks", "received_chunks", "received_bytes",
            "file_sha256", "checksum_status", "import_batch", "allowed_actions",
        ):
            self.assertIn(field, payload, msg=f"missing field: {field}")
        self.assertEqual(payload["file_sha256"], "a" * 64)


_DiskUsage = namedtuple("DiskUsage", ["total", "used", "free"])
_DISK_USAGE_PATCH = "apps.imports.services.uploads.shutil.disk_usage"


class DiskPreflightTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.staff_user = self.user_model.objects.create_user(
            username="staff",
            password="password",
            is_staff=True,
        )
        self.client.force_login(self.staff_user)

    @override_settings(
        HOMOREPEAT_UPLOAD_CHUNK_BYTES=10,
        HOMOREPEAT_UPLOAD_DISK_PREFLIGHT_ENABLED=True,
        HOMOREPEAT_UPLOAD_MIN_FREE_BYTES=1000,
    )
    def test_start_rejects_when_free_space_below_threshold(self):
        # size_bytes=10 requires 10*2 + 1000 = 1020 free; mock returns only 100
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                with patch(_DISK_USAGE_PATCH, return_value=_DiskUsage(10000, 9900, 100)):
                    response = self.client.post(
                        reverse("imports:upload-start"),
                        data=json.dumps({
                            "filename": "run-alpha.zip",
                            "size_bytes": 10,
                            "total_chunks": 1,
                        }),
                        content_type="application/json",
                    )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertIn("Insufficient disk space", response.json()["error"])
        self.assertEqual(UploadedRun.objects.count(), 0)

    @override_settings(
        HOMOREPEAT_UPLOAD_CHUNK_BYTES=10,
        HOMOREPEAT_UPLOAD_DISK_PREFLIGHT_ENABLED=True,
        HOMOREPEAT_UPLOAD_MIN_FREE_BYTES=1000,
    )
    def test_start_error_message_includes_required_and_available_bytes(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                with patch(_DISK_USAGE_PATCH, return_value=_DiskUsage(10000, 9900, 42)):
                    response = self.client.post(
                        reverse("imports:upload-start"),
                        data=json.dumps({
                            "filename": "run-alpha.zip",
                            "size_bytes": 10,
                            "total_chunks": 1,
                        }),
                        content_type="application/json",
                    )

        error = response.json()["error"]
        self.assertIn("42", error)   # available bytes
        self.assertIn("1,020", error)  # required bytes (10*2 + 1000)

    @override_settings(
        HOMOREPEAT_UPLOAD_CHUNK_BYTES=10,
        HOMOREPEAT_UPLOAD_DISK_PREFLIGHT_ENABLED=False,
        HOMOREPEAT_UPLOAD_MIN_FREE_BYTES=1000,
    )
    def test_disk_preflight_disabled_allows_upload_despite_low_space(self):
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                with patch(_DISK_USAGE_PATCH, return_value=_DiskUsage(10000, 9999, 1)):
                    response = self.client.post(
                        reverse("imports:upload-start"),
                        data=json.dumps({
                            "filename": "run-alpha.zip",
                            "size_bytes": 10,
                            "total_chunks": 1,
                        }),
                        content_type="application/json",
                    )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    @override_settings(
        HOMOREPEAT_UPLOAD_DISK_PREFLIGHT_ENABLED=True,
        HOMOREPEAT_UPLOAD_MIN_FREE_BYTES=1000,
        HOMOREPEAT_UPLOAD_EXTRACTION_SPACE_MULTIPLIER=3.0,
        HOMOREPEAT_UPLOAD_MAX_EXTRACTED_BYTES=50 * 1024 * 1024 * 1024,
    )
    def test_extraction_rejects_when_free_space_drops_before_extraction(self):
        chunk_data = b"abcdefghij"
        with TemporaryDirectory() as tempdir:
            with override_settings(HOMOREPEAT_IMPORTS_ROOT=tempdir):
                uploaded_run = UploadedRun.objects.create(
                    original_filename="run-alpha.zip",
                    status=UploadedRun.Status.RECEIVED,
                    size_bytes=10,
                    chunk_size_bytes=10,
                    total_chunks=1,
                    received_chunks=[0],
                    received_bytes=10,
                )
                uploaded_run.chunks_root.mkdir(parents=True)
                (uploaded_run.chunks_root / "0.part").write_bytes(chunk_data)

                from apps.imports.services.uploads import assemble_uploaded_zip

                # 10 bytes * 3 multiplier = 30 extracted; 30*2 + 1000 = 1060 required; 50 free
                with patch(_DISK_USAGE_PATCH, return_value=_DiskUsage(10000, 9950, 50)):
                    with self.assertRaises(UploadValidationError) as ctx:
                        assemble_uploaded_zip(uploaded_run_id=uploaded_run.pk)

        self.assertIn("Insufficient disk space", str(ctx.exception))
        uploaded_run.refresh_from_db()
        self.assertEqual(uploaded_run.status, UploadedRun.Status.RECEIVED)
