from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.browser.models import PipelineRun
from apps.imports.models import ImportBatch
from apps.imports.services import import_published_run

from .support import build_minimal_publish_root


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

    def test_staff_can_import_detected_publish_root_from_home(self):
        with TemporaryDirectory() as tempdir:
            runs_root = Path(tempdir) / "runs"
            publish_root = build_minimal_publish_root(runs_root / "run-alpha", run_id="run-alpha")

            self.client.force_login(self.staff_user)
            with override_settings(HOMOREPEAT_RUNS_ROOT=str(runs_root)):
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
            self.assertEqual(batch.progress_payload["message"], "Queued for background import.")

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
