import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.imports.models import UploadedRun


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

                response = self.client.post(
                    reverse("imports:upload-complete", kwargs={"upload_id": uploaded_run.upload_id})
                )

                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()["ok"])
                self.assertIn("missing chunk", response.json()["error"])
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

                response = self.client.post(
                    reverse("imports:upload-complete", kwargs={"upload_id": uploaded_run.upload_id})
                )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["status"], UploadedRun.Status.RECEIVED)
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

                response = self.client.post(
                    reverse("imports:upload-complete", kwargs={"upload_id": uploaded_run.upload_id})
                )

                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["ok"])
                self.assertEqual(response.json()["status"], UploadedRun.Status.RECEIVED)
                self.assertEqual(response.json()["received_chunks"], [0, 1])

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

                response = self.client.post(
                    reverse("imports:upload-complete", kwargs={"upload_id": uploaded_run.upload_id})
                )

                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()["ok"])
                self.assertIn("expected 11", response.json()["error"])
                uploaded_run.refresh_from_db()
                self.assertEqual(uploaded_run.status, UploadedRun.Status.RECEIVING)
