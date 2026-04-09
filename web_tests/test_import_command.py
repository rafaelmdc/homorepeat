from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import TestCase

from apps.browser.models import (
    AccessionCallCount,
    AccessionStatus,
    AcquisitionBatch,
    DownloadManifestEntry,
    Genome,
    NormalizationWarning,
    PipelineRun,
    Protein,
    RepeatCall,
    RunParameter,
    Sequence,
    Taxon,
    TaxonClosure,
)
from apps.imports.models import ImportBatch

from .support import build_minimal_publish_root, build_multibatch_publish_root


class ImportRunCommandTests(TestCase):
    def test_import_run_keeps_only_repeat_linked_sequences_and_proteins(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))

            stdout = StringIO()
            call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            self.assertIn("Imported run run-alpha", stdout.getvalue())
            self.assertEqual(PipelineRun.objects.count(), 1)
            self.assertEqual(ImportBatch.objects.count(), 1)
            self.assertEqual(PipelineRun.objects.get().acquisition_publish_mode, "raw")
            self.assertEqual(AcquisitionBatch.objects.count(), 1)
            self.assertEqual(DownloadManifestEntry.objects.count(), 1)
            self.assertEqual(NormalizationWarning.objects.count(), 0)
            self.assertEqual(AccessionStatus.objects.count(), 1)
            self.assertEqual(AccessionCallCount.objects.count(), 1)
            self.assertEqual(Taxon.objects.count(), 2)
            self.assertEqual(TaxonClosure.objects.count(), 3)
            self.assertEqual(Genome.objects.count(), 1)
            self.assertEqual(Sequence.objects.count(), 1)
            self.assertEqual(Protein.objects.count(), 1)
            self.assertEqual(Genome.objects.get().analyzed_protein_count, 2)
            self.assertEqual(RunParameter.objects.count(), 1)
            self.assertEqual(RunParameter.objects.get().repeat_residue, "Q")
            self.assertEqual(RepeatCall.objects.count(), 1)
            self.assertEqual(Sequence.objects.get().nucleotide_sequence, "CAG" * 30)
            self.assertEqual(Protein.objects.get().amino_acid_sequence, "Q" * 30)
            self.assertEqual(Genome.objects.get().batch.batch_id, "batch_0001")
            self.assertEqual(AccessionStatus.objects.get().terminal_status, "completed")
            self.assertEqual(AccessionCallCount.objects.get().n_repeat_calls, 1)
            self.assertEqual(DownloadManifestEntry.objects.get().download_status, "downloaded")
            self.assertEqual(Protein.objects.get().accession, Genome.objects.get().accession)
            self.assertEqual(Protein.objects.get().repeat_call_count, 1)
            self.assertEqual(RepeatCall.objects.get().accession, Genome.objects.get().accession)
            self.assertEqual(RepeatCall.objects.get().protein_name, Protein.objects.get().protein_name)
            self.assertEqual(ImportBatch.objects.get().status, ImportBatch.Status.COMPLETED)
            self.assertEqual(ImportBatch.objects.get().phase, "completed")
            self.assertIsNotNone(ImportBatch.objects.get().heartbeat_at)

    def test_import_run_keeps_matched_sequences_and_proteins_but_counts_all_batch_proteins(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_multibatch_publish_root(Path(tempdir), run_id="run-multi-batch-retained")
            stdout = StringIO()
            (publish_root / "calls" / "repeat_calls.tsv").write_text(
                "call_id\tmethod\tgenome_id\ttaxon_id\tsequence_id\tprotein_id\tstart\tend\tlength\trepeat_residue\trepeat_count\tnon_repeat_count\tpurity\taa_sequence\tcodon_sequence\tcodon_metric_name\tcodon_metric_value\twindow_definition\ttemplate_name\tmerge_rule\tscore\n"
                "call_1\tpure\tgenome_1\t9606\tseq_1\tprot_1\t10\t20\t11\tQ\t11\t0\t1.0\tQQQQQQQQQQQ\t\t\t\t\t\t\t\n",
                encoding="utf-8",
            )
            (publish_root / "calls" / "run_params.tsv").write_text(
                "method\trepeat_residue\tparam_name\tparam_value\n"
                "pure\tQ\tmin_repeat_count\t6\n",
                encoding="utf-8",
            )
            (publish_root / "status" / "accession_call_counts.tsv").write_text(
                "assembly_accession\tbatch_id\tmethod\trepeat_residue\tdetect_status\tfinalize_status\tn_repeat_calls\n"
                "GCF_000001405.40\tbatch_0001\tpure\tQ\tsuccess\tsuccess\t1\n",
                encoding="utf-8",
            )

            call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            self.assertIn("Imported run run-multi-batch-retained", stdout.getvalue())
            self.assertEqual(Genome.objects.count(), 2)
            self.assertEqual(Sequence.objects.count(), 1)
            self.assertEqual(Protein.objects.count(), 1)
            self.assertEqual(RepeatCall.objects.count(), 1)
            self.assertEqual(DownloadManifestEntry.objects.count(), 2)
            self.assertEqual(NormalizationWarning.objects.count(), 1)
            self.assertEqual(Genome.objects.get(genome_id="genome_1").analyzed_protein_count, 2)
            self.assertEqual(Genome.objects.get(genome_id="genome_2").analyzed_protein_count, 1)
            self.assertEqual(
                set(Sequence.objects.values_list("genome__genome_id", flat=True)),
                {"genome_1"},
            )
            self.assertEqual(
                set(Protein.objects.values_list("genome__genome_id", flat=True)),
                {"genome_1"},
            )

    def test_import_run_fails_without_replace_for_existing_run(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))
            stdout = StringIO()

            call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            with self.assertRaises(CommandError):
                call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            self.assertEqual(PipelineRun.objects.count(), 1)
            self.assertEqual(ImportBatch.objects.count(), 2)
            self.assertEqual(
                ImportBatch.objects.filter(status=ImportBatch.Status.FAILED).count(),
                1,
            )

    def test_import_run_replace_existing_reloads_run_scoped_rows(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))
            stdout = StringIO()
            call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            (publish_root / "acquisition" / "batches" / "batch_0001" / "genomes.tsv").write_text(
                "genome_id\tsource\taccession\tgenome_name\tassembly_type\ttaxon_id\tassembly_level\tspecies_name\tnotes\n"
                "genome_1\tncbi_datasets\tGCF_000001405.40\tReplacement genome\thaploid\t9606\tChromosome\tHomo sapiens\tupdated\n",
                encoding="utf-8",
            )
            (publish_root / "calls" / "repeat_calls.tsv").write_text(
                "call_id\tmethod\tgenome_id\ttaxon_id\tsequence_id\tprotein_id\tstart\tend\tlength\trepeat_residue\trepeat_count\tnon_repeat_count\tpurity\taa_sequence\tcodon_sequence\tcodon_metric_name\tcodon_metric_value\twindow_definition\ttemplate_name\tmerge_rule\tscore\n"
                "call_2\tpure\tgenome_1\t9606\tseq_1\tprot_1\t11\t21\t11\tQ\t11\t0\t1.0\tQQQQQQQQQQQ\t\t\t\t\t\t\t\n",
                encoding="utf-8",
            )
            (publish_root / "acquisition" / "batches" / "batch_0001" / "download_manifest.tsv").write_text(
                "batch_id\tassembly_accession\tdownload_status\tpackage_mode\tdownload_path\trehydrated_path\tchecksum\tfile_size_bytes\tdownload_started_at\tdownload_finished_at\tnotes\n"
                "batch_0001\tGCF_000001405.40\trehydrated\tdirect_zip\t\t\t\t106807993\t\t\treplaced\n",
                encoding="utf-8",
            )
            (publish_root / "acquisition" / "batches" / "batch_0001" / "normalization_warnings.tsv").write_text(
                "warning_code\twarning_scope\twarning_message\tbatch_id\tgenome_id\tsequence_id\tprotein_id\tassembly_accession\tsource_file\tsource_record_id\n"
                "partial_cds\tsequence\tCDS is partial\tbatch_0001\tgenome_1\tseq_1\t\tGCF_000001405.40\t/source/path\tcds-1\n",
                encoding="utf-8",
            )

            call_command(
                "import_run",
                publish_root=str(publish_root),
                replace_existing=True,
                stdout=stdout,
            )

            self.assertEqual(PipelineRun.objects.count(), 1)
            self.assertEqual(Genome.objects.count(), 1)
            self.assertEqual(RepeatCall.objects.count(), 1)
            self.assertEqual(DownloadManifestEntry.objects.count(), 1)
            self.assertEqual(NormalizationWarning.objects.count(), 1)
            self.assertEqual(Genome.objects.get().genome_name, "Replacement genome")
            self.assertEqual(Genome.objects.get().analyzed_protein_count, 2)
            self.assertEqual(RepeatCall.objects.get().call_id, "call_2")
            self.assertEqual(DownloadManifestEntry.objects.get().download_status, "rehydrated")
            self.assertEqual(DownloadManifestEntry.objects.get().notes, "replaced")
            self.assertEqual(NormalizationWarning.objects.get().warning_code, "partial_cds")

    def test_import_run_rolls_back_on_broken_references(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir), run_id="run-broken")
            stdout = StringIO()
            (publish_root / "acquisition" / "batches" / "batch_0001" / "sequences.tsv").write_text(
                "sequence_id\tgenome_id\tsequence_name\tsequence_length\tgene_symbol\ttranscript_id\tisoform_id\tassembly_accession\ttaxon_id\tsource_record_id\tprotein_external_id\ttranslation_table\tgene_group\tlinkage_status\tpartial_status\n"
                "seq_1\tmissing_genome\tNM_000001.1\t900\tGENE1\tNM_000001.1\tNP_000001.1\tGCF_000001405.40\t9606\tcds-1\tNP_000001.1\t1\tGENE1\tgff\t\n",
                encoding="utf-8",
            )

            with self.assertRaises(CommandError):
                call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            self.assertFalse(PipelineRun.objects.filter(run_id="run-broken").exists())
            self.assertEqual(DownloadManifestEntry.objects.count(), 0)
            self.assertEqual(NormalizationWarning.objects.count(), 0)
            self.assertEqual(AccessionStatus.objects.count(), 0)
            self.assertEqual(AccessionCallCount.objects.count(), 0)
            self.assertEqual(Genome.objects.count(), 0)
            self.assertEqual(Sequence.objects.count(), 0)
            self.assertEqual(Protein.objects.count(), 0)
            self.assertEqual(RunParameter.objects.count(), 0)
            self.assertEqual(RepeatCall.objects.count(), 0)
            self.assertEqual(Taxon.objects.count(), 0)
            self.assertEqual(TaxonClosure.objects.count(), 0)
            self.assertEqual(ImportBatch.objects.count(), 1)
            self.assertEqual(ImportBatch.objects.get().status, ImportBatch.Status.FAILED)

    def test_import_run_still_validates_unreferenced_inventory_rows(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir), run_id="run-bad-protein")
            stdout = StringIO()
            (publish_root / "acquisition" / "batches" / "batch_0001" / "proteins.tsv").write_text(
                "protein_id\tsequence_id\tgenome_id\tprotein_name\tprotein_length\tgene_symbol\ttranslation_method\ttranslation_status\tassembly_accession\ttaxon_id\tgene_group\tprotein_external_id\n"
                "prot_1\tseq_1\tgenome_1\tNP_000001.1\t300\tGENE1\ttranslated\ttranslated\tGCF_000001405.40\t9606\tGENE1\tNP_000001.1\n"
                "prot_2\tmissing_seq\tgenome_1\tNP_000002.1\t280\tGENE2\ttranslated\ttranslated\tGCF_000001405.40\t9606\tGENE2\tNP_000002.1\n",
                encoding="utf-8",
            )

            with self.assertRaises(CommandError):
                call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            self.assertFalse(PipelineRun.objects.filter(run_id="run-bad-protein").exists())
            self.assertEqual(DownloadManifestEntry.objects.count(), 0)
            self.assertEqual(NormalizationWarning.objects.count(), 0)
            self.assertEqual(AccessionStatus.objects.count(), 0)
            self.assertEqual(AccessionCallCount.objects.count(), 0)
            self.assertEqual(Genome.objects.count(), 0)
            self.assertEqual(Sequence.objects.count(), 0)
            self.assertEqual(Protein.objects.count(), 0)
            self.assertEqual(RepeatCall.objects.count(), 0)

    def test_import_run_preserves_full_taxonomy_before_storing_closure(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir), run_id="run-taxonomy-compact")
            stdout = StringIO()
            (publish_root / "acquisition" / "batches" / "batch_0001" / "taxonomy.tsv").write_text(
                "taxon_id\ttaxon_name\tparent_taxon_id\trank\tsource\n"
                "1\troot\t\tno rank\ttest\n"
                "131567\tcellular organisms\t1\tno rank\ttest\n"
                "2759\tEukaryota\t131567\tsuperkingdom\ttest\n"
                "33208\tMetazoa\t2759\tkingdom\ttest\n"
                "7711\tChordata\t33208\tphylum\ttest\n"
                "7742\tVertebrata\t7711\tno rank\ttest\n"
                "40674\tMammalia\t7742\tclass\ttest\n"
                "314146\tEuarchontoglires\t40674\tno rank\ttest\n"
                "9443\tPrimates\t314146\torder\ttest\n"
                "9604\tHominidae\t9443\tfamily\ttest\n"
                "9605\tHomo\t9604\tgenus\ttest\n"
                "9606\tHomo sapiens\t9605\tspecies\ttest\n",
                encoding="utf-8",
            )

            call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            self.assertEqual(Taxon.objects.count(), 12)
            self.assertTrue(Taxon.objects.filter(taxon_id=131567).exists())
            self.assertTrue(Taxon.objects.filter(taxon_id=7742).exists())
            self.assertTrue(Taxon.objects.filter(taxon_id=314146).exists())
            self.assertEqual(Taxon.objects.get(taxon_id=2759).parent_taxon.taxon_id, 131567)
            self.assertEqual(Taxon.objects.get(taxon_id=9443).parent_taxon.taxon_id, 314146)
            self.assertEqual(Taxon.objects.get(taxon_id=9606).parent_taxon.taxon_id, 9605)

    def test_import_run_stores_residue_scoped_run_params(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir), run_id="run-multi-residue")
            stdout = StringIO()
            (publish_root / "calls" / "run_params.tsv").write_text(
                "method\trepeat_residue\tparam_name\tparam_value\n"
                "pure\tQ\tmin_repeat_count\t6\n"
                "pure\tN\tmin_repeat_count\t6\n",
                encoding="utf-8",
            )

            call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            self.assertEqual(RunParameter.objects.count(), 2)
            self.assertEqual(
                set(RunParameter.objects.values_list("repeat_residue", flat=True)),
                {"Q", "N"},
            )

    def test_import_run_can_process_one_queued_batch_by_id(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir), run_id="run-queued")
            batch = ImportBatch.objects.create(
                source_path=str(Path(publish_root).resolve()),
                status=ImportBatch.Status.PENDING,
                phase="queued",
                progress_payload={"message": "Queued for background import."},
            )
            stdout = StringIO()

            call_command("import_run", batch_id=batch.pk, stdout=stdout)

            self.assertIn("Imported run run-queued", stdout.getvalue())
            batch.refresh_from_db()
            self.assertEqual(batch.status, ImportBatch.Status.COMPLETED)
            self.assertEqual(batch.phase, "completed")
            self.assertTrue(PipelineRun.objects.filter(run_id="run-queued").exists())

    def test_import_run_can_process_next_pending_batch(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir), run_id="run-next-pending")
            ImportBatch.objects.create(
                source_path=str(Path(publish_root).resolve()),
                status=ImportBatch.Status.PENDING,
                phase="queued",
                progress_payload={"message": "Queued for background import."},
            )
            stdout = StringIO()

            call_command("import_run", next_pending=True, stdout=stdout)

            self.assertIn("Imported run run-next-pending", stdout.getvalue())
            self.assertTrue(PipelineRun.objects.filter(run_id="run-next-pending").exists())

    def test_import_run_next_pending_reports_when_queue_is_empty(self):
        stdout = StringIO()

        call_command("import_run", next_pending=True, stdout=stdout)

        self.assertIn("No pending import batches were available.", stdout.getvalue())

    def test_import_run_does_not_depend_on_fully_materialized_parser(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir), run_id="run-streamed")
            stdout = StringIO()

            with patch(
                "apps.imports.services.import_run.load_published_run",
                side_effect=AssertionError("full parser should not be used by runtime import"),
            ):
                call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            self.assertIn("Imported run run-streamed", stdout.getvalue())
            self.assertTrue(PipelineRun.objects.filter(run_id="run-streamed").exists())

    def test_import_run_reports_progress_during_transactional_import_phase(self):
        recorded_payloads: list[dict[str, object]] = []

        class FakeReporter:
            def __init__(self, batch):
                self.batch = batch

            def save(self, update_fields, *, force=False):
                recorded_payloads.append(dict(self.batch.progress_payload))

            def close(self):
                return None

        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir), run_id="run-progress")
            stdout = StringIO()

            with patch("apps.imports.services.import_run._ImportBatchStateReporter", FakeReporter):
                call_command("import_run", publish_root=str(publish_root), stdout=stdout)

        self.assertIn("Imported run run-progress", stdout.getvalue())
        self.assertTrue(
            any(payload.get("message") == "Importing retained sequence rows." for payload in recorded_payloads)
        )
        self.assertTrue(
            any(payload.get("message") == "Importing retained protein rows." for payload in recorded_payloads)
        )
        self.assertTrue(
            any(payload.get("message") == "Importing repeat-call rows." for payload in recorded_payloads)
        )

    def test_import_run_triggers_post_load_analyze_hook(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir), run_id="run-analyze")
            stdout = StringIO()

            with patch(
                "apps.imports.services.import_run._analyze_models",
                return_value=True,
            ) as analyze_models:
                call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            self.assertIn("Imported run run-analyze", stdout.getvalue())
            analyze_models.assert_called_once()
