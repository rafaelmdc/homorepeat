"""Tests for download build status and expiry bookkeeping."""

import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.browser.models import DownloadBuild


class DownloadBuildModelTests(TestCase):
    def _make_build(self, **kwargs):
        defaults = {
            "build_type": "genome_list",
            "scope_key": "abc123",
            "catalog_version": 1,
        }
        defaults.update(kwargs)
        return DownloadBuild.objects.create(**defaults)

    def test_default_status_is_pending(self):
        build = self._make_build()
        self.assertEqual(build.status, DownloadBuild.Status.PENDING)

    def test_is_ready_only_for_ready_status(self):
        for status, expected in [
            (DownloadBuild.Status.PENDING, False),
            (DownloadBuild.Status.BUILDING, False),
            (DownloadBuild.Status.READY, True),
            (DownloadBuild.Status.FAILED, False),
            (DownloadBuild.Status.EXPIRED, False),
        ]:
            with self.subTest(status=status):
                build = self._make_build(status=status)
                self.assertEqual(build.is_ready, expected)

    def test_is_terminal_for_ready_failed_expired(self):
        for status, expected in [
            (DownloadBuild.Status.PENDING, False),
            (DownloadBuild.Status.BUILDING, False),
            (DownloadBuild.Status.READY, True),
            (DownloadBuild.Status.FAILED, True),
            (DownloadBuild.Status.EXPIRED, True),
        ]:
            with self.subTest(status=status):
                build = self._make_build(status=status)
                self.assertEqual(build.is_terminal, expected)

    def test_str_representation(self):
        build = self._make_build(
            build_type="genome_list", status=DownloadBuild.Status.READY, catalog_version=5
        )
        self.assertIn("genome_list", str(build))
        self.assertIn("ready", str(build))
        self.assertIn("5", str(build))


class DownloadBuildStatusViewTests(TestCase):
    def test_returns_404_for_unknown_pk(self):
        response = self.client.get(reverse("browser:downloadbuild-status", kwargs={"pk": 9999}))
        self.assertEqual(response.status_code, 404)

    def test_returns_json_status_for_pending_build(self):
        build = DownloadBuild.objects.create(
            build_type="genome_list",
            scope_key="scope-test",
            catalog_version=1,
            status=DownloadBuild.Status.PENDING,
        )
        response = self.client.get(reverse("browser:downloadbuild-status", kwargs={"pk": build.pk}))
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["id"], build.pk)
        self.assertEqual(data["status"], "pending")
        self.assertFalse(data["is_ready"])
        self.assertIsNone(data["finished_at"])
        self.assertIsNone(data["artifact_path"])
        self.assertIsNone(data["error_message"])

    def test_returns_json_status_for_ready_build(self):
        now = timezone.now()
        build = DownloadBuild.objects.create(
            build_type="sequence_list",
            scope_key="scope-ready",
            catalog_version=2,
            status=DownloadBuild.Status.READY,
            finished_at=now,
            artifact_path="exports/sequence_list_abc.tsv",
            size_bytes=12345,
        )
        response = self.client.get(reverse("browser:downloadbuild-status", kwargs={"pk": build.pk}))
        data = json.loads(response.content)
        self.assertEqual(data["status"], "ready")
        self.assertTrue(data["is_ready"])
        self.assertEqual(data["artifact_path"], "exports/sequence_list_abc.tsv")
        self.assertEqual(data["size_bytes"], 12345)
        self.assertIsNotNone(data["finished_at"])

    def test_returns_json_status_for_failed_build(self):
        build = DownloadBuild.objects.create(
            build_type="genome_list",
            scope_key="scope-fail",
            catalog_version=1,
            status=DownloadBuild.Status.FAILED,
            error_message="Connection reset by peer",
        )
        response = self.client.get(reverse("browser:downloadbuild-status", kwargs={"pk": build.pk}))
        data = json.loads(response.content)
        self.assertEqual(data["status"], "failed")
        self.assertFalse(data["is_ready"])
        self.assertEqual(data["error_message"], "Connection reset by peer")


class ExpireStaleDownloadBuildsTaskTests(TestCase):
    def _make_build(self, **kwargs):
        return DownloadBuild.objects.create(
            build_type="genome_list",
            scope_key="scope-expire",
            catalog_version=1,
            **kwargs,
        )

    def test_expires_stuck_pending_build(self):
        from apps.browser.tasks import expire_stale_download_builds

        build = self._make_build(status=DownloadBuild.Status.PENDING)
        DownloadBuild.objects.filter(pk=build.pk).update(
            created_at=timezone.now() - timedelta(hours=2)
        )

        result = expire_stale_download_builds()

        build.refresh_from_db()
        self.assertEqual(build.status, DownloadBuild.Status.EXPIRED)
        self.assertEqual(result["stuck"], 1)
        self.assertEqual(result["aged"], 0)

    def test_expires_stuck_building_build(self):
        from apps.browser.tasks import expire_stale_download_builds

        build = self._make_build(status=DownloadBuild.Status.BUILDING)
        DownloadBuild.objects.filter(pk=build.pk).update(
            created_at=timezone.now() - timedelta(hours=2)
        )

        result = expire_stale_download_builds()

        build.refresh_from_db()
        self.assertEqual(build.status, DownloadBuild.Status.EXPIRED)
        self.assertEqual(result["stuck"], 1)

    def test_does_not_expire_recent_pending_build(self):
        from apps.browser.tasks import expire_stale_download_builds

        build = self._make_build(status=DownloadBuild.Status.PENDING)

        result = expire_stale_download_builds()

        build.refresh_from_db()
        self.assertEqual(build.status, DownloadBuild.Status.PENDING)
        self.assertEqual(result["stuck"], 0)

    def test_expires_aged_ready_build(self):
        from apps.browser.tasks import expire_stale_download_builds

        now = timezone.now()
        build = self._make_build(status=DownloadBuild.Status.READY, finished_at=now)
        DownloadBuild.objects.filter(pk=build.pk).update(
            finished_at=now - timedelta(days=8)
        )

        result = expire_stale_download_builds()

        build.refresh_from_db()
        self.assertEqual(build.status, DownloadBuild.Status.EXPIRED)
        self.assertEqual(result["aged"], 1)
        self.assertEqual(result["stuck"], 0)

    def test_does_not_expire_recent_ready_build(self):
        from apps.browser.tasks import expire_stale_download_builds

        build = self._make_build(
            status=DownloadBuild.Status.READY,
            finished_at=timezone.now() - timedelta(days=1),
        )

        result = expire_stale_download_builds()

        build.refresh_from_db()
        self.assertEqual(build.status, DownloadBuild.Status.READY)
        self.assertEqual(result["aged"], 0)

    def test_returns_zero_counts_when_nothing_to_expire(self):
        from apps.browser.tasks import expire_stale_download_builds

        result = expire_stale_download_builds()

        self.assertEqual(result, {"stuck": 0, "aged": 0})
