"""Tests for Phase 5 and Phase 8: download service boundary and DownloadBuild model."""

import json
from datetime import timedelta

from django.test import TestCase, SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from apps.browser.downloads import (
    DownloadBuildType,
    DownloadClassification,
    classify_download,
    get_or_create_download_build,
)
from apps.browser.models import DownloadBuild


class DownloadClassificationTests(SimpleTestCase):
    def test_all_list_page_types_are_sync(self):
        list_types = [
            DownloadBuildType.RUN_LIST,
            DownloadBuildType.ACCESSION_LIST,
            DownloadBuildType.GENOME_LIST,
            DownloadBuildType.SEQUENCE_LIST,
            DownloadBuildType.REPEAT_CALL_LIST,
        ]
        for build_type in list_types:
            with self.subTest(build_type=build_type):
                self.assertEqual(classify_download(build_type), DownloadClassification.SYNC)

    def test_all_stats_types_are_sync(self):
        stats_types = [
            DownloadBuildType.LENGTH_SUMMARY,
            DownloadBuildType.LENGTH_OVERVIEW_TYPICAL,
            DownloadBuildType.LENGTH_OVERVIEW_TAIL,
            DownloadBuildType.LENGTH_INSPECT,
            DownloadBuildType.CODON_RATIO_SUMMARY,
            DownloadBuildType.CODON_RATIO_OVERVIEW,
            DownloadBuildType.CODON_RATIO_BROWSE,
            DownloadBuildType.CODON_RATIO_INSPECT,
            DownloadBuildType.CODON_LENGTH_SUMMARY,
            DownloadBuildType.CODON_LENGTH_PREFERENCE,
            DownloadBuildType.CODON_LENGTH_DOMINANCE,
            DownloadBuildType.CODON_LENGTH_SHIFT,
            DownloadBuildType.CODON_LENGTH_SIMILARITY,
            DownloadBuildType.CODON_LENGTH_BROWSE,
            DownloadBuildType.CODON_LENGTH_INSPECT,
            DownloadBuildType.CODON_LENGTH_COMPARISON,
        ]
        for build_type in stats_types:
            with self.subTest(build_type=build_type):
                self.assertEqual(classify_download(build_type), DownloadClassification.SYNC)

    def test_download_build_type_covers_all_payload_inventory_entries(self):
        # Every download listed in payload_inventory.md must have a DownloadBuildType entry.
        expected_values = {
            "run_list", "accession_list", "genome_list", "sequence_list", "repeat_call_list",
            "length.summary", "length.overview_typical", "length.overview_tail", "length.inspect",
            "codon_ratio.summary", "codon_ratio.overview", "codon_ratio.browse", "codon_ratio.inspect",
            "codon_length.summary", "codon_length.preference", "codon_length.dominance",
            "codon_length.shift", "codon_length.similarity", "codon_length.browse",
            "codon_length.inspect", "codon_length.comparison",
        }
        actual_values = {t.value for t in DownloadBuildType}
        self.assertEqual(actual_values, expected_values)


class DownloadBuildModelTests(TestCase):
    def _make_build(self, **kwargs):
        defaults = {
            "build_type": DownloadBuildType.GENOME_LIST,
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


class GetOrCreateDownloadBuildTests(TestCase):
    def test_creates_new_build_when_none_exists(self):
        build, created = get_or_create_download_build(
            DownloadBuildType.GENOME_LIST, "scope-a", catalog_version=1
        )
        self.assertTrue(created)
        self.assertEqual(build.status, DownloadBuild.Status.PENDING)
        self.assertEqual(build.build_type, DownloadBuildType.GENOME_LIST)
        self.assertEqual(build.scope_key, "scope-a")
        self.assertEqual(build.catalog_version, 1)

    def test_reuses_existing_pending_build(self):
        existing = DownloadBuild.objects.create(
            build_type=DownloadBuildType.GENOME_LIST,
            scope_key="scope-b",
            catalog_version=2,
            status=DownloadBuild.Status.PENDING,
        )
        build, created = get_or_create_download_build(
            DownloadBuildType.GENOME_LIST, "scope-b", catalog_version=2
        )
        self.assertFalse(created)
        self.assertEqual(build.pk, existing.pk)

    def test_reuses_existing_ready_build(self):
        existing = DownloadBuild.objects.create(
            build_type=DownloadBuildType.SEQUENCE_LIST,
            scope_key="scope-c",
            catalog_version=3,
            status=DownloadBuild.Status.READY,
        )
        build, created = get_or_create_download_build(
            DownloadBuildType.SEQUENCE_LIST, "scope-c", catalog_version=3
        )
        self.assertFalse(created)
        self.assertEqual(build.pk, existing.pk)

    def test_does_not_reuse_failed_build(self):
        DownloadBuild.objects.create(
            build_type=DownloadBuildType.GENOME_LIST,
            scope_key="scope-d",
            catalog_version=4,
            status=DownloadBuild.Status.FAILED,
        )
        build, created = get_or_create_download_build(
            DownloadBuildType.GENOME_LIST, "scope-d", catalog_version=4
        )
        self.assertTrue(created)

    def test_does_not_reuse_expired_build(self):
        DownloadBuild.objects.create(
            build_type=DownloadBuildType.GENOME_LIST,
            scope_key="scope-e",
            catalog_version=4,
            status=DownloadBuild.Status.EXPIRED,
        )
        build, created = get_or_create_download_build(
            DownloadBuildType.GENOME_LIST, "scope-e", catalog_version=4
        )
        self.assertTrue(created)

    def test_does_not_reuse_build_from_different_catalog_version(self):
        DownloadBuild.objects.create(
            build_type=DownloadBuildType.GENOME_LIST,
            scope_key="scope-f",
            catalog_version=1,
            status=DownloadBuild.Status.READY,
        )
        build, created = get_or_create_download_build(
            DownloadBuildType.GENOME_LIST, "scope-f", catalog_version=2
        )
        self.assertTrue(created)


class DownloadBuildStatusViewTests(TestCase):
    def test_returns_404_for_unknown_pk(self):
        response = self.client.get(reverse("browser:downloadbuild-status", kwargs={"pk": 9999}))
        self.assertEqual(response.status_code, 404)

    def test_returns_json_status_for_pending_build(self):
        build = DownloadBuild.objects.create(
            build_type=DownloadBuildType.GENOME_LIST,
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
        from django.utils import timezone

        now = timezone.now()
        build = DownloadBuild.objects.create(
            build_type=DownloadBuildType.SEQUENCE_LIST,
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
            build_type=DownloadBuildType.GENOME_LIST,
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
            build_type=DownloadBuildType.GENOME_LIST,
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


class DownloadServiceBoundaryTests(SimpleTestCase):
    """Verify that downloads.py does not import from the view layer."""

    def test_downloads_module_has_no_view_layer_imports(self):
        import apps.browser.downloads as mod
        import sys

        view_modules = [k for k in sys.modules if "apps.browser.views" in k]
        for view_mod in view_modules:
            self.assertFalse(
                hasattr(mod, view_mod.split(".")[-1]),
                f"downloads.py must not import from view layer ({view_mod})",
            )
