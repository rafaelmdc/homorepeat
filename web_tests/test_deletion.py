from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from apps.browser.models import (
    CanonicalGenome,
    Genome,
    PipelineRun,
    Protein,
    RepeatCall,
    Sequence,
)
from apps.imports.models import CatalogVersion, DeletionJob, ImportBatch
from apps.imports.services.deletion.artifacts import ArtifactPathError
from apps.imports.services.deletion.cache import bump_catalog_version
from apps.imports.services.deletion.chunks import delete_in_chunks
from apps.imports.services.deletion.jobs import (
    claim_deletion_job,
    execute_deletion_phases,
    mark_job_failed,
    queue_deletion,
    retry_deletion,
)
from apps.imports.services.deletion.planning import build_deletion_plan
from apps.imports.services.deletion.safety import DeletionTargetError, validate_deletion_target

from web_tests.support import create_imported_run_fixture, ensure_test_taxonomy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_run(run_id="run-test", publish_root=None, **kwargs):
    return PipelineRun.objects.create(
        run_id=run_id,
        status="success",
        profile="docker",
        acquisition_publish_mode="raw",
        git_revision="abc123",
        manifest_path=f"/tmp/{run_id}/metadata/run_manifest.json",
        publish_root=publish_root if publish_root is not None else f"/tmp/{run_id}/publish",
        manifest_payload={"run_id": run_id, "acquisition_publish_mode": "raw"},
        **kwargs,
    )


def _make_job(pipeline_run, status=DeletionJob.Status.PENDING, **kwargs):
    return DeletionJob.objects.create(
        pipeline_run=pipeline_run,
        status=status,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class DeletionTargetValidationTests(TestCase):
    def setUp(self):
        self.run = _make_run()

    def test_active_run_passes(self):
        validate_deletion_target(self.run)

    def test_deleting_run_passes(self):
        self.run.lifecycle_status = PipelineRun.LifecycleStatus.DELETING
        self.run.save()
        validate_deletion_target(self.run)

    def test_deleted_run_raises(self):
        self.run.lifecycle_status = PipelineRun.LifecycleStatus.DELETED
        self.run.save()
        with self.assertRaises(DeletionTargetError):
            validate_deletion_target(self.run)

    def test_delete_failed_run_raises(self):
        self.run.lifecycle_status = PipelineRun.LifecycleStatus.DELETE_FAILED
        self.run.save()
        with self.assertRaises(DeletionTargetError):
            validate_deletion_target(self.run)


# ---------------------------------------------------------------------------
# Artifact path safety
# ---------------------------------------------------------------------------

class ArtifactPathSafetyTests(TestCase):
    def test_no_publish_root_returns_library_root_only(self):
        from apps.imports.services.deletion.artifacts import resolve_run_artifact_roots
        run = _make_run(run_id="run-no-pub", publish_root="")
        roots = resolve_run_artifact_roots(run)
        self.assertEqual(len(roots), 1)
        self.assertIn("run-no-pub", str(roots[0]))

    def test_publish_root_outside_approved_root_raises(self):
        from apps.imports.services.deletion.artifacts import resolve_run_artifact_roots
        run = _make_run(run_id="run-bad", publish_root="/tmp/outside-root/run-bad/publish")
        with self.assertRaises(ArtifactPathError):
            resolve_run_artifact_roots(run)

    def test_publish_root_inside_library_root_returns_two_roots(self):
        from django.conf import settings
        from apps.imports.services.deletion.artifacts import resolve_run_artifact_roots
        imports_root = settings.HOMOREPEAT_IMPORTS_ROOT
        safe_path = f"{imports_root}/library/run-safe/publish"
        run = _make_run(run_id="run-safe", publish_root=safe_path)
        roots = resolve_run_artifact_roots(run)
        self.assertEqual(len(roots), 2)


# ---------------------------------------------------------------------------
# Cache versioning
# ---------------------------------------------------------------------------

class CacheVersionTests(TestCase):
    def test_bump_increments_version(self):
        before = CatalogVersion.current()
        new_v = bump_catalog_version()
        self.assertEqual(new_v, before + 1)

    def test_bump_twice_increments_twice(self):
        before = CatalogVersion.current()
        bump_catalog_version()
        after = bump_catalog_version()
        self.assertEqual(after, before + 2)


# ---------------------------------------------------------------------------
# Deletion plan (read-only)
# ---------------------------------------------------------------------------

class DeletionPlanTests(TestCase):
    def setUp(self):
        ensure_test_taxonomy()
        self.fixture = create_imported_run_fixture(
            run_id="run-plan",
            genome_id="g-plan",
            sequence_id="seq-plan",
            protein_id="prot-plan",
            call_id="call-plan",
            accession="GCF_PLAN001",
        )
        self.run = self.fixture["pipeline_run"]

    def test_plan_is_readonly(self):
        before_status = self.run.lifecycle_status
        build_deletion_plan(self.run)
        self.run.refresh_from_db()
        self.assertEqual(self.run.lifecycle_status, before_status)

    def test_plan_counts_genomes_and_calls(self):
        plan = build_deletion_plan(self.run)
        genome_table = next(t for t in plan.tables if t.table == "browser_genome")
        call_table = next(t for t in plan.tables if t.table == "browser_repeatcall")
        self.assertEqual(genome_table.row_count, 1)
        self.assertEqual(call_table.row_count, 1)

    def test_plan_shows_no_active_job_initially(self):
        plan = build_deletion_plan(self.run)
        self.assertIsNone(plan.active_job_id)

    def test_plan_shows_active_job_id(self):
        job = _make_job(self.run)
        plan = build_deletion_plan(self.run)
        self.assertEqual(plan.active_job_id, job.pk)

    def test_total_rows_to_delete_is_positive_and_correct(self):
        plan = build_deletion_plan(self.run)
        expected = sum(t.row_count for t in plan.tables if t.action == "delete")
        self.assertEqual(plan.total_rows_to_delete, expected)
        self.assertGreater(plan.total_rows_to_delete, 0)


# ---------------------------------------------------------------------------
# queue_deletion
# ---------------------------------------------------------------------------

class QueueDeletionTests(TestCase):
    def setUp(self):
        self.run = _make_run()

    @patch("apps.imports.services.deletion.jobs._enqueue")
    def test_creates_job_with_pending_status(self, mock_enqueue):
        with self.captureOnCommitCallbacks(execute=True):
            job = queue_deletion(self.run, reason="test reason")
        self.assertEqual(job.status, DeletionJob.Status.PENDING)
        self.assertEqual(job.reason, "test reason")

    @patch("apps.imports.services.deletion.jobs._enqueue")
    def test_sets_run_to_deleting(self, mock_enqueue):
        with self.captureOnCommitCallbacks(execute=True):
            queue_deletion(self.run)
        self.run.refresh_from_db()
        self.assertEqual(self.run.lifecycle_status, PipelineRun.LifecycleStatus.DELETING)

    @patch("apps.imports.services.deletion.jobs._enqueue")
    def test_calls_enqueue_on_commit(self, mock_enqueue):
        with self.captureOnCommitCallbacks(execute=True):
            job = queue_deletion(self.run)
        mock_enqueue.assert_called_once_with(job.pk)

    @patch("apps.imports.services.deletion.jobs._enqueue")
    def test_idempotent_returns_existing_job(self, mock_enqueue):
        with self.captureOnCommitCallbacks(execute=True):
            job_a = queue_deletion(self.run, reason="first")
        # second call should reuse the first job (run is now DELETING)
        with self.captureOnCommitCallbacks(execute=True):
            job_b = queue_deletion(self.run, reason="second")
        self.assertEqual(job_a.pk, job_b.pk)
        self.assertEqual(mock_enqueue.call_count, 1)

    @patch("apps.imports.services.deletion.jobs._enqueue")
    def test_bumps_catalog_version(self, mock_enqueue):
        before = CatalogVersion.current()
        with self.captureOnCommitCallbacks(execute=True):
            queue_deletion(self.run)
        self.assertGreater(CatalogVersion.current(), before)

    def test_deleted_run_raises_before_enqueue(self):
        self.run.lifecycle_status = PipelineRun.LifecycleStatus.DELETED
        self.run.save()
        with self.assertRaises(DeletionTargetError):
            queue_deletion(self.run)

    def test_delete_failed_run_raises_before_enqueue(self):
        self.run.lifecycle_status = PipelineRun.LifecycleStatus.DELETE_FAILED
        self.run.save()
        with self.assertRaises(DeletionTargetError):
            queue_deletion(self.run)


# ---------------------------------------------------------------------------
# claim_deletion_job
# ---------------------------------------------------------------------------

class ClaimDeletionJobTests(TestCase):
    def setUp(self):
        self.run = _make_run()

    def test_claim_pending_job_transitions_to_running(self):
        job = _make_job(self.run, status=DeletionJob.Status.PENDING)
        claimed = claim_deletion_job(job.pk)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.status, DeletionJob.Status.RUNNING)
        self.assertIsNotNone(claimed.started_at)
        self.assertIsNotNone(claimed.last_heartbeat_at)

    def test_claim_running_job_is_reclaimed(self):
        job = _make_job(self.run, status=DeletionJob.Status.RUNNING)
        claimed = claim_deletion_job(job.pk)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.status, DeletionJob.Status.RUNNING)

    def test_claim_done_job_returns_none(self):
        job = _make_job(self.run, status=DeletionJob.Status.DONE)
        self.assertIsNone(claim_deletion_job(job.pk))

    def test_claim_failed_job_returns_none(self):
        job = _make_job(self.run, status=DeletionJob.Status.FAILED)
        self.assertIsNone(claim_deletion_job(job.pk))

    def test_claim_missing_job_returns_none(self):
        self.assertIsNone(claim_deletion_job(999_999))


# ---------------------------------------------------------------------------
# retry_deletion
# ---------------------------------------------------------------------------

class RetryDeletionTests(TestCase):
    def setUp(self):
        self.run = _make_run()
        self.run.lifecycle_status = PipelineRun.LifecycleStatus.DELETE_FAILED
        self.run.save()
        self.job = _make_job(
            self.run,
            status=DeletionJob.Status.FAILED,
            error_message="Something broke",
            error_debug={"traceback": "…"},
        )

    @patch("apps.imports.services.deletion.jobs._enqueue")
    def test_retry_resets_to_pending_and_clears_error(self, mock_enqueue):
        with self.captureOnCommitCallbacks(execute=True):
            updated = retry_deletion(self.job)
        self.assertEqual(updated.status, DeletionJob.Status.PENDING)
        self.assertEqual(updated.retry_count, 1)
        self.assertEqual(updated.error_message, "")
        self.assertEqual(updated.error_debug, {})

    @patch("apps.imports.services.deletion.jobs._enqueue")
    def test_retry_calls_enqueue(self, mock_enqueue):
        with self.captureOnCommitCallbacks(execute=True):
            updated = retry_deletion(self.job)
        mock_enqueue.assert_called_once_with(updated.pk)

    def test_retry_done_job_raises(self):
        from apps.imports.services.deletion.safety import DeletionTargetError
        self.job.status = DeletionJob.Status.DONE
        self.job.save()
        with self.assertRaises(DeletionTargetError):
            retry_deletion(self.job)

    def test_retry_pending_job_raises(self):
        from apps.imports.services.deletion.safety import DeletionTargetError
        self.job.status = DeletionJob.Status.PENDING
        self.job.save()
        with self.assertRaises(DeletionTargetError):
            retry_deletion(self.job)


# ---------------------------------------------------------------------------
# delete_in_chunks
# ---------------------------------------------------------------------------

class DeleteInChunksTests(TestCase):
    def setUp(self):
        ensure_test_taxonomy()
        self.fixture_a = create_imported_run_fixture(
            run_id="run-chunks-a",
            genome_id="g-chunks-a",
            sequence_id="seq-chunks-a",
            protein_id="prot-chunks-a",
            call_id="call-chunks-a",
            accession="GCF_CHUNK001",
        )
        self.run_a = self.fixture_a["pipeline_run"]
        self.fixture_b = create_imported_run_fixture(
            run_id="run-chunks-b",
            genome_id="g-chunks-b",
            sequence_id="seq-chunks-b",
            protein_id="prot-chunks-b",
            call_id="call-chunks-b",
            accession="GCF_CHUNK002",
        )
        self.run_b = self.fixture_b["pipeline_run"]

    def test_direct_delete_returns_correct_count(self):
        from apps.browser.models import RunParameter
        # Each run has 1 RunParameter row; use it as a safe leaf table (no FK children).
        n = delete_in_chunks(
            table="browser_runparameter",
            pipeline_run_id=self.run_a.pk,
        )
        self.assertEqual(n, 1)
        self.assertEqual(RunParameter.objects.filter(pipeline_run=self.run_a).count(), 0)

    def test_direct_delete_does_not_touch_other_run(self):
        from apps.browser.models import RunParameter
        delete_in_chunks(
            table="browser_runparameter",
            pipeline_run_id=self.run_a.pk,
        )
        self.assertEqual(RunParameter.objects.filter(pipeline_run=self.run_b).count(), 1)

    def test_returns_zero_for_run_with_no_rows(self):
        run = _make_run(run_id="run-empty-chunks")
        n = delete_in_chunks(table="browser_runparameter", pipeline_run_id=run.pk)
        self.assertEqual(n, 0)

    def test_chunk_size_one_clears_all_rows(self):
        from apps.browser.models import RunParameter
        # chunk_size=1 forces the loop to run once per row plus one empty iteration.
        n = delete_in_chunks(
            table="browser_runparameter",
            pipeline_run_id=self.run_a.pk,
            chunk_size=1,
        )
        self.assertEqual(n, 1)
        self.assertEqual(RunParameter.objects.filter(pipeline_run=self.run_a).count(), 0)

    def test_indirect_delete_via_join(self):
        from apps.browser.models import RepeatCallCodonUsage
        before = RepeatCallCodonUsage.objects.filter(
            repeat_call__pipeline_run=self.run_a
        ).count()
        n = delete_in_chunks(
            table="browser_repeatcallcodonusage",
            pipeline_run_id=self.run_a.pk,
            join_table="browser_repeatcall",
            join_fk="repeat_call_id",
        )
        self.assertEqual(n, before)
        self.assertEqual(
            RepeatCallCodonUsage.objects.filter(repeat_call__pipeline_run=self.run_a).count(), 0
        )


# ---------------------------------------------------------------------------
# repair_canonical_catalog
# ---------------------------------------------------------------------------

class CanonicalRepairTests(TestCase):
    def setUp(self):
        ensure_test_taxonomy()

    def test_orphan_canonical_genome_is_deleted(self):
        fixture = create_imported_run_fixture(
            run_id="run-orphan",
            genome_id="g-orphan",
            sequence_id="seq-orphan",
            protein_id="prot-orphan",
            call_id="call-orphan",
            accession="GCF_ORPHAN001",
        )
        run = fixture["pipeline_run"]
        self.assertEqual(CanonicalGenome.objects.filter(latest_pipeline_run=run).count(), 1)

        from apps.imports.services.deletion.canonical import repair_canonical_catalog
        counts = repair_canonical_catalog(run)

        self.assertEqual(counts["canonical_genomes_promoted"], 0)
        self.assertGreaterEqual(counts["canonical_genomes_deleted"], 1)
        self.assertEqual(CanonicalGenome.objects.filter(latest_pipeline_run=run).count(), 0)

    def test_canonical_genome_promoted_to_active_predecessor(self):
        # Build two runs sharing the same genome accession.
        # run_a is the older, active, completed predecessor.
        fixture_a = create_imported_run_fixture(
            run_id="run-pred-a",
            genome_id="g-pred-a",
            sequence_id="seq-pred",
            protein_id="prot-pred",
            call_id="call-pred",
            accession="GCF_PROMOTE001",
        )
        run_a = fixture_a["pipeline_run"]
        # Mark run_a's import batch COMPLETED so it qualifies as a predecessor.
        ImportBatch.objects.filter(pipeline_run=run_a).update(status=ImportBatch.Status.COMPLETED)

        # run_b is the newer run (same accession); its sync updates the canonical row.
        fixture_b = create_imported_run_fixture(
            run_id="run-pred-b",
            genome_id="g-pred-b",
            sequence_id="seq-pred",   # same business key
            protein_id="prot-pred",   # same business key
            call_id="call-pred-b",
            accession="GCF_PROMOTE001",  # same accession → updates canonical row
        )
        run_b = fixture_b["pipeline_run"]

        cg = CanonicalGenome.objects.get(accession="GCF_PROMOTE001")
        self.assertEqual(cg.latest_pipeline_run_id, run_b.pk)

        from apps.imports.services.deletion.canonical import repair_canonical_catalog
        counts = repair_canonical_catalog(run_b)

        self.assertGreaterEqual(counts["canonical_genomes_promoted"], 1)
        self.assertEqual(counts["canonical_genomes_deleted"], 0)

        cg.refresh_from_db()
        self.assertEqual(cg.latest_pipeline_run_id, run_a.pk)


# ---------------------------------------------------------------------------
# execute_deletion_phases / mark_job_failed
# ---------------------------------------------------------------------------

class ExecutionPhaseTests(TestCase):
    def setUp(self):
        ensure_test_taxonomy()
        self.fixture = create_imported_run_fixture(
            run_id="run-exec",
            genome_id="g-exec",
            sequence_id="seq-exec",
            protein_id="prot-exec",
            call_id="call-exec",
            accession="GCF_EXEC001",
        )
        self.run = self.fixture["pipeline_run"]
        self.job = _make_job(self.run, status=DeletionJob.Status.RUNNING)
        self.job.started_at = timezone.now()
        self.job.save()

    def test_full_flow_sets_job_done_and_run_deleted(self):
        execute_deletion_phases(self.job)

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, DeletionJob.Status.DONE)
        self.assertIsNotNone(self.job.finished_at)

        self.run.refresh_from_db()
        self.assertEqual(self.run.lifecycle_status, PipelineRun.LifecycleStatus.DELETED)

    def test_full_flow_deletes_raw_rows(self):
        execute_deletion_phases(self.job)

        self.assertEqual(Genome.objects.filter(pipeline_run=self.run).count(), 0)
        self.assertEqual(Sequence.objects.filter(pipeline_run=self.run).count(), 0)
        self.assertEqual(Protein.objects.filter(pipeline_run=self.run).count(), 0)
        self.assertEqual(RepeatCall.objects.filter(pipeline_run=self.run).count(), 0)

    def test_artifact_path_error_is_non_fatal(self):
        # publish_root is /tmp/run-exec/publish (outside approved root) →
        # delete_run_artifacts raises ArtifactPathError, which execute_deletion_phases catches.
        execute_deletion_phases(self.job)

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, DeletionJob.Status.DONE)
        self.assertEqual(self.job.artifacts_deleted, 0)

    def test_mark_job_failed_records_error_and_sets_run_delete_failed(self):
        exc = RuntimeError("boom")
        mark_job_failed(self.job, exc)

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, DeletionJob.Status.FAILED)
        self.assertIn("RuntimeError", self.job.error_message)
        self.assertIn("boom", self.job.error_message)
        self.assertIn("traceback", self.job.error_debug)

        self.run.refresh_from_db()
        self.assertEqual(self.run.lifecycle_status, PipelineRun.LifecycleStatus.DELETE_FAILED)


# ---------------------------------------------------------------------------
# Management commands
# ---------------------------------------------------------------------------

class ManagementCommandTests(TestCase):
    def setUp(self):
        ensure_test_taxonomy()
        self.fixture = create_imported_run_fixture(
            run_id="run-mgmt",
            genome_id="g-mgmt",
            sequence_id="seq-mgmt",
            protein_id="prot-mgmt",
            call_id="call-mgmt",
            accession="GCF_MGMT001",
        )
        self.run = self.fixture["pipeline_run"]

    # --- queue_delete_run ---

    def test_queue_delete_run_dry_run_shows_plan_without_mutation(self):
        out = StringIO()
        call_command("queue_delete_run", "--run-id", "run-mgmt", stdout=out)
        output = out.getvalue()
        self.assertIn("Dry-run", output)
        self.assertIn("Deletion Plan", output)
        self.run.refresh_from_db()
        self.assertEqual(self.run.lifecycle_status, PipelineRun.LifecycleStatus.ACTIVE)
        self.assertFalse(DeletionJob.objects.filter(pipeline_run=self.run).exists())

    @patch("apps.imports.services.deletion.jobs._enqueue")
    def test_queue_delete_run_confirm_creates_job(self, mock_enqueue):
        out = StringIO()
        with self.captureOnCommitCallbacks(execute=True):
            call_command("queue_delete_run", "--run-id", "run-mgmt", "--confirm", stdout=out)
        self.assertTrue(DeletionJob.objects.filter(pipeline_run=self.run).exists())
        self.assertIn("Deletion job queued", out.getvalue())
        mock_enqueue.assert_called_once()

    def test_queue_delete_run_nonexistent_run_raises(self):
        with self.assertRaises(CommandError):
            call_command("queue_delete_run", "--run-id", "does-not-exist")

    def test_queue_delete_run_deleted_run_raises(self):
        self.run.lifecycle_status = PipelineRun.LifecycleStatus.DELETED
        self.run.save()
        with self.assertRaises(CommandError):
            call_command("queue_delete_run", "--run-id", "run-mgmt", "--confirm")

    # --- deletion_status ---

    def test_deletion_status_shows_job_info(self):
        job = _make_job(self.run, reason="test deletion")
        out = StringIO()
        call_command("deletion_status", "--job-id", str(job.pk), stdout=out)
        output = out.getvalue()
        self.assertIn("Deletion Job Status", output)
        self.assertIn(str(job.pk), output)
        self.assertIn("run-mgmt", output)

    def test_deletion_status_missing_job_raises(self):
        with self.assertRaises(CommandError):
            call_command("deletion_status", "--job-id", "999999")

    def test_deletion_status_failed_job_shows_retry_hint(self):
        job = _make_job(self.run, status=DeletionJob.Status.FAILED, error_message="boom")
        out = StringIO()
        call_command("deletion_status", "--job-id", str(job.pk), stdout=out)
        self.assertIn("retry_deletion_job", out.getvalue())

    # --- retry_deletion_job ---

    def test_retry_deletion_job_dry_run_does_not_mutate(self):
        self.run.lifecycle_status = PipelineRun.LifecycleStatus.DELETE_FAILED
        self.run.save()
        job = _make_job(self.run, status=DeletionJob.Status.FAILED)
        out = StringIO()
        call_command("retry_deletion_job", "--job-id", str(job.pk), stdout=out)
        self.assertIn("Dry-run", out.getvalue())
        job.refresh_from_db()
        self.assertEqual(job.status, DeletionJob.Status.FAILED)

    @patch("apps.imports.services.deletion.jobs._enqueue")
    def test_retry_deletion_job_confirm_re_enqueues(self, mock_enqueue):
        self.run.lifecycle_status = PipelineRun.LifecycleStatus.DELETE_FAILED
        self.run.save()
        job = _make_job(self.run, status=DeletionJob.Status.FAILED)
        out = StringIO()
        with self.captureOnCommitCallbacks(execute=True):
            call_command("retry_deletion_job", "--job-id", str(job.pk), "--confirm", stdout=out)
        job.refresh_from_db()
        self.assertEqual(job.status, DeletionJob.Status.PENDING)
        self.assertEqual(job.retry_count, 1)
        mock_enqueue.assert_called_once_with(job.pk)

    def test_retry_deletion_job_non_failed_raises(self):
        job = _make_job(self.run, status=DeletionJob.Status.PENDING)
        with self.assertRaises(CommandError):
            call_command("retry_deletion_job", "--job-id", str(job.pk), "--confirm")
