from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.browser.models import PipelineRun
from apps.imports.models import ImportBatch
from apps.imports.services import import_published_run
from apps.imports.views import _discover_publish_runs_in

from .support import build_minimal_v2_publish_root as build_minimal_publish_root


class ImportViewTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.staff_user = self.user_model.objects.create_user(
            username="staff",
            password="password",
            is_staff=True,
        )

    def test_imports_home_requires_staff_access(self):
        response = self.client.get(reverse("imports:home"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response["Location"])

    def test_staff_imports_home_lists_detected_publish_roots(self):
        with TemporaryDirectory() as tempdir:
            runs_root = Path(tempdir) / "runs"
            build_minimal_publish_root(runs_root / "run-alpha", run_id="run-alpha")
            build_minimal_publish_root(runs_root / "run-beta", run_id="run-beta")

            self.client.force_login(self.staff_user)
            with override_settings(HOMOREPEAT_RUNS_ROOT=str(runs_root)):
                response = self.client.get(reverse("imports:home"))

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "run-alpha")
            self.assertContains(response, "run-beta")
            self.assertContains(response, "Latest import batches")

    def test_discover_publish_runs_in_scans_supplied_root(self):
        with TemporaryDirectory() as tempdir:
            runs_root = Path(tempdir) / "runs"
            build_minimal_publish_root(runs_root / "run-alpha", run_id="run-alpha")
            build_minimal_publish_root(runs_root / "run-beta", run_id="run-beta")
            (runs_root / "not-a-run").mkdir()

            detected_runs = _discover_publish_runs_in(runs_root)

            self.assertEqual([run.run_id for run in detected_runs], ["run-alpha", "run-beta"])
            self.assertTrue(all(run.publish_root.endswith("/publish") for run in detected_runs))

    def test_discover_publish_runs_in_returns_empty_for_missing_root(self):
        with TemporaryDirectory() as tempdir:
            missing_root = Path(tempdir) / "missing"

            self.assertEqual(_discover_publish_runs_in(missing_root), [])

    def test_staff_can_import_detected_publish_root_from_home(self):
        with TemporaryDirectory() as tempdir:
            runs_root = Path(tempdir) / "runs"
            publish_root = build_minimal_publish_root(runs_root / "run-alpha", run_id="run-alpha")

            self.client.force_login(self.staff_user)
            with override_settings(HOMOREPEAT_RUNS_ROOT=str(runs_root)), patch(
                "apps.imports.tasks.run_import_batch.delay",
                return_value=SimpleNamespace(id="task-123"),
            ):
                response = self.client.post(
                    reverse("imports:home"),
                    {
                        "detected_publish_root": str(publish_root.resolve()),
                        "publish_root": "",
                        "replace_existing": "",
                    },
                    follow=True,
                )

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Queued import batch")
            self.assertEqual(PipelineRun.objects.count(), 0)
            self.assertEqual(ImportBatch.objects.count(), 1)
            batch = ImportBatch.objects.get()
            self.assertEqual(batch.status, ImportBatch.Status.PENDING)
            self.assertEqual(batch.phase, "queued")
            self.assertEqual(batch.celery_task_id, "task-123")
            self.assertEqual(batch.progress_payload["message"], "Queued for background import.")

    def test_staff_can_import_manual_publish_root_from_home(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir) / "manual-run", run_id="manual-run")

            self.client.force_login(self.staff_user)
            with patch(
                "apps.imports.tasks.run_import_batch.delay",
                return_value=SimpleNamespace(id="task-123"),
            ):
                response = self.client.post(
                    reverse("imports:home"),
                    {
                        "detected_publish_root": "",
                        "publish_root": str(publish_root),
                        "replace_existing": "",
                    },
                    follow=True,
                )

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Queued import batch")
            self.assertEqual(ImportBatch.objects.count(), 1)
            batch = ImportBatch.objects.get()
            self.assertEqual(batch.source_path, str(publish_root.resolve()))
            self.assertEqual(batch.celery_task_id, "task-123")

    def test_staff_imports_home_rejects_missing_manual_publish_root(self):
        with TemporaryDirectory() as tempdir:
            missing_publish_root = Path(tempdir) / "missing" / "publish"

            self.client.force_login(self.staff_user)
            response = self.client.post(
                reverse("imports:home"),
                {
                    "detected_publish_root": "",
                    "publish_root": str(missing_publish_root),
                    "replace_existing": "",
                },
            )

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Publish root does not exist or is not a directory")
            self.assertEqual(ImportBatch.objects.count(), 0)

    def test_staff_imports_home_rejects_manual_publish_root_without_manifest(self):
        with TemporaryDirectory() as tempdir:
            publish_root = Path(tempdir) / "run-alpha" / "publish"
            publish_root.mkdir(parents=True)

            self.client.force_login(self.staff_user)
            response = self.client.post(
                reverse("imports:home"),
                {
                    "detected_publish_root": "",
                    "publish_root": str(publish_root),
                    "replace_existing": "",
                },
            )

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Publish root must contain metadata/run_manifest.json")
            self.assertEqual(ImportBatch.objects.count(), 0)

    def test_upload_endpoints_require_staff_access(self):
        upload_id = uuid4()
        urls = [
            reverse("imports:upload-start"),
            reverse("imports:upload-chunk", kwargs={"upload_id": upload_id}),
            reverse("imports:upload-complete", kwargs={"upload_id": upload_id}),
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.post(url)

                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("admin:login"), response["Location"])

    def test_staff_upload_endpoints_return_json_placeholder_until_services_exist(self):
        upload_id = uuid4()
        endpoints = [
            reverse("imports:upload-start"),
            reverse("imports:upload-chunk", kwargs={"upload_id": upload_id}),
            reverse("imports:upload-complete", kwargs={"upload_id": upload_id}),
        ]

        self.client.force_login(self.staff_user)
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                response = self.client.post(endpoint)

                self.assertEqual(response.status_code, 501)
                self.assertEqual(response["Content-Type"], "application/json")
                self.assertFalse(response.json()["ok"])

    def test_imports_home_auto_refreshes_when_recent_batch_is_active(self):
        ImportBatch.objects.create(
            source_path="/tmp/run-alpha/publish",
            status=ImportBatch.Status.RUNNING,
            phase="importing_rows",
            progress_payload={
                "message": "Importing genome rows.",
                "current": 10,
                "total": 20,
                "percent": 50,
                "unit": "genomes",
            },
        )

        self.client.force_login(self.staff_user)
        response = self.client.get(reverse("imports:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-import-auto-refresh")
        self.assertContains(response, "import-stepper")
        self.assertContains(response, "10/20")

    def test_import_history_shows_completed_and_failed_batches(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir) / "run-alpha", run_id="run-alpha")
            import_published_run(publish_root)
            try:
                import_published_run(publish_root)
            except Exception:
                pass

            self.client.force_login(self.staff_user)
            response = self.client.get(reverse("imports:history"))

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "run-alpha")
            self.assertContains(response, "completed")
            self.assertContains(response, "failed")
            self.assertContains(response, "completed")
            self.assertContains(response, "failed")
            self.assertContains(response, "row counts for historical")
            self.assertContains(response, "imported observations")
            self.assertContains(response, "genomes")
            self.assertContains(response, "already exists")
