from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.browser.metadata import BROWSER_METADATA_RAW_COUNT_KEYS, resolve_run_browser_metadata
from apps.browser.models import AccessionCallCount, RunParameter
from apps.imports.models import ImportBatch

from .support import create_imported_run_fixture


class BrowserMetadataTests(TestCase):
    def test_resolve_run_browser_metadata_prefers_persisted_metadata(self):
        alpha = create_imported_run_fixture(
            run_id="run-alpha",
            genome_id="genome_alpha",
            sequence_id="seq_alpha",
            protein_id="prot_alpha",
            call_id="call_alpha",
            accession="GCF_ALPHA",
            taxon_key="human",
        )
        pipeline_run = alpha["pipeline_run"]
        pipeline_run.browser_metadata = {
            "raw_counts": {key: 9 for key in BROWSER_METADATA_RAW_COUNT_KEYS},
            "facets": {
                "methods": [RunParameter.Method.SEED_EXTEND],
                "residues": ["A"],
            },
        }
        pipeline_run.save(update_fields=["browser_metadata"])
        ImportBatch.objects.create(
            pipeline_run=pipeline_run,
            source_path=pipeline_run.publish_root,
            status=ImportBatch.Status.COMPLETED,
            phase="completed",
            finished_at=timezone.now(),
            heartbeat_at=timezone.now(),
            row_counts={key: 1 for key in BROWSER_METADATA_RAW_COUNT_KEYS},
        )
        AccessionCallCount.objects.create(
            pipeline_run=pipeline_run,
            batch=alpha["batch"],
            assembly_accession="GCF_ALPHA_ALT",
            method=RunParameter.Method.THRESHOLD,
            repeat_residue="Q",
            detect_status="success",
            finalize_status="success",
            n_repeat_calls=2,
        )

        metadata = resolve_run_browser_metadata(pipeline_run)

        self.assertEqual(
            metadata,
            {
                "raw_counts": {key: 9 for key in BROWSER_METADATA_RAW_COUNT_KEYS},
                "facets": {
                    "methods": [RunParameter.Method.SEED_EXTEND],
                    "residues": ["A"],
                },
            },
        )

    def test_resolve_run_browser_metadata_falls_back_to_import_batch_counts_and_small_table_facets(self):
        alpha = create_imported_run_fixture(
            run_id="run-fallback",
            genome_id="genome_fallback",
            sequence_id="seq_fallback",
            protein_id="prot_fallback",
            call_id="call_fallback",
            accession="GCF_FALLBACK",
            taxon_key="human",
        )
        pipeline_run = alpha["pipeline_run"]
        AccessionCallCount.objects.create(
            pipeline_run=pipeline_run,
            batch=alpha["batch"],
            assembly_accession="GCF_FALLBACK_ALT",
            method=RunParameter.Method.THRESHOLD,
            repeat_residue="A",
            detect_status="success",
            finalize_status="success",
            n_repeat_calls=3,
        )
        ImportBatch.objects.create(
            source_path=pipeline_run.publish_root,
            status=ImportBatch.Status.COMPLETED,
            phase="completed",
            finished_at=timezone.now(),
            heartbeat_at=timezone.now(),
            row_counts={
                "genomes": 1,
                "sequences": 1,
                "proteins": 1,
                "repeat_calls": 1,
                "accession_status_rows": 1,
                "accession_call_count_rows": 2,
                "download_manifest_entries": 0,
                "normalization_warnings": 0,
            },
        )

        metadata = resolve_run_browser_metadata(pipeline_run)

        self.assertEqual(
            metadata,
            {
                "raw_counts": {
                    "genomes": 1,
                    "sequences": 1,
                    "proteins": 1,
                    "repeat_calls": 1,
                    "accession_status_rows": 1,
                    "accession_call_count_rows": 2,
                    "download_manifest_entries": 0,
                    "normalization_warnings": 0,
                },
                "facets": {
                    "methods": [RunParameter.Method.PURE],
                    "residues": ["A", "Q"],
                },
            },
        )

    def test_backfill_browser_metadata_command_populates_missing_metadata(self):
        alpha = create_imported_run_fixture(
            run_id="run-backfill",
            genome_id="genome_backfill",
            sequence_id="seq_backfill",
            protein_id="prot_backfill",
            call_id="call_backfill",
            accession="GCF_BACKFILL",
            taxon_key="human",
        )
        pipeline_run = alpha["pipeline_run"]
        ImportBatch.objects.create(
            pipeline_run=pipeline_run,
            source_path=pipeline_run.publish_root,
            status=ImportBatch.Status.COMPLETED,
            phase="completed",
            finished_at=timezone.now(),
            heartbeat_at=timezone.now(),
            row_counts={
                "genomes": 1,
                "sequences": 1,
                "proteins": 1,
                "repeat_calls": 1,
                "accession_status_rows": 1,
                "accession_call_count_rows": 1,
                "download_manifest_entries": 0,
                "normalization_warnings": 0,
            },
        )
        stdout = StringIO()

        call_command("backfill_browser_metadata", run_id="run-backfill", stdout=stdout)

        pipeline_run.refresh_from_db()
        self.assertEqual(
            pipeline_run.browser_metadata,
            {
                "raw_counts": {
                    "genomes": 1,
                    "sequences": 1,
                    "proteins": 1,
                    "repeat_calls": 1,
                    "accession_status_rows": 1,
                    "accession_call_count_rows": 1,
                    "download_manifest_entries": 0,
                    "normalization_warnings": 0,
                },
                "facets": {
                    "methods": [RunParameter.Method.PURE],
                    "residues": ["Q"],
                },
            },
        )
        self.assertIn("Backfilled run-backfill", stdout.getvalue())
        self.assertIn("updated: 1", stdout.getvalue())
