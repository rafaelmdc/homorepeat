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
    CanonicalGenome,
    CanonicalProtein,
    CanonicalRepeatCall,
    CanonicalRepeatCallCodonUsage,
    CanonicalSequence,
    DownloadManifestEntry,
    Genome,
    NormalizationWarning,
    PipelineRun,
    Protein,
    RepeatCall,
    RepeatCallCodonUsage,
    RunParameter,
    Sequence,
    Taxon,
    TaxonClosure,
)
from apps.imports.models import CatalogVersion, ImportBatch

from .support import (
    add_finalized_codon_usage_artifact,
    build_minimal_v2_publish_root as build_minimal_publish_root,
    build_multibatch_v2_publish_root as build_multibatch_publish_root,
)


class ImportRunCommandTests(TestCase):
    def test_import_run_persists_browser_metadata(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir), run_id="run-browser-metadata")
            stdout = StringIO()

            call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            self.assertIn("Imported run run-browser-metadata", stdout.getvalue())
            pipeline_run = PipelineRun.objects.get(run_id="run-browser-metadata")
            batch = ImportBatch.objects.get()
            self.assertEqual(
                pipeline_run.browser_metadata["raw_counts"],
                {
                    "genomes": batch.row_counts["genomes"],
                    "sequences": batch.row_counts["sequences"],
                    "proteins": batch.row_counts["proteins"],
                    "repeat_calls": batch.row_counts["repeat_calls"],
                    "repeat_call_contexts": batch.row_counts.get("repeat_call_contexts", 0),
                    "accession_status_rows": batch.row_counts["accession_status_rows"],
                    "accession_call_count_rows": batch.row_counts["accession_call_count_rows"],
                    "download_manifest_entries": batch.row_counts["download_manifest_entries"],
                    "normalization_warnings": batch.row_counts["normalization_warnings"],
                },
            )
            self.assertEqual(
                pipeline_run.browser_metadata["facets"],
                {
                    "methods": [RunParameter.Method.PURE],
                    "residues": ["Q"],
                },
            )
            self.assertEqual(CanonicalGenome.objects.count(), 1)
            self.assertEqual(CanonicalSequence.objects.count(), 1)
            self.assertEqual(CanonicalProtein.objects.count(), 1)
            self.assertEqual(CanonicalRepeatCall.objects.count(), 1)
            self.assertEqual(CanonicalGenome.objects.get().latest_pipeline_run, pipeline_run)
            self.assertEqual(CanonicalGenome.objects.get().latest_import_batch, batch)
            self.assertEqual(CanonicalProtein.objects.get().repeat_call_count, 1)
            self.assertEqual(CanonicalRepeatCall.objects.get().latest_repeat_call.call_id, "call_1")
            self.assertEqual(CanonicalRepeatCall.objects.get().source_call_id, "call_1")
            self.assertEqual(pipeline_run.canonical_sync_batch, batch)
            self.assertIsNotNone(pipeline_run.canonical_synced_at)

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
            self.assertEqual(Genome.objects.get().analyzed_protein_count, 1)
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
            self.assertEqual(CatalogVersion.current(), 1)

    def test_import_run_parses_numeric_codon_ratio_value_for_raw_and_canonical_repeat_calls(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir), run_id="run-codon-ratio")
            stdout = StringIO()
            (publish_root / "calls" / "repeat_calls.tsv").write_text(
                "call_id\tmethod\tgenome_id\ttaxon_id\tsequence_id\tprotein_id\tstart\tend\tlength\trepeat_residue\trepeat_count\tnon_repeat_count\tpurity\taa_sequence\tcodon_sequence\tcodon_metric_name\tcodon_metric_value\twindow_definition\ttemplate_name\tmerge_rule\tscore\n"
                "call_1\tpure\tgenome_1\t9606\tseq_1\tprot_1\t10\t20\t11\tQ\t11\t0\t1.0\tQQQQQQQQQQQ\tCAGCAGCAGCAGCAGCAGCAGCAGCAGCAGCAG\tcodon_ratio\t1.25\t\t\t\t\n",
                encoding="utf-8",
            )

            call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            repeat_call = RepeatCall.objects.get()
            canonical_repeat_call = CanonicalRepeatCall.objects.get()

            self.assertEqual(repeat_call.codon_metric_value, "1.25")
            self.assertEqual(repeat_call.codon_ratio_value, 1.25)
            self.assertEqual(canonical_repeat_call.codon_metric_value, "1.25")
            self.assertEqual(canonical_repeat_call.codon_ratio_value, 1.25)

    def test_import_run_leaves_blank_and_invalid_codon_ratio_values_null(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir), run_id="run-codon-ratio-null")
            stdout = StringIO()
            (publish_root / "calls" / "repeat_calls.tsv").write_text(
                "call_id\tmethod\tgenome_id\ttaxon_id\tsequence_id\tprotein_id\tstart\tend\tlength\trepeat_residue\trepeat_count\tnon_repeat_count\tpurity\taa_sequence\tcodon_sequence\tcodon_metric_name\tcodon_metric_value\twindow_definition\ttemplate_name\tmerge_rule\tscore\n"
                "call_blank\tpure\tgenome_1\t9606\tseq_1\tprot_1\t10\t20\t11\tQ\t11\t0\t1.0\tQQQQQQQQQQQ\t\tcodon_ratio\t\t\t\t\t\n"
                "call_invalid\tpure\tgenome_1\t9606\tseq_1\tprot_1\t30\t40\t11\tQ\t11\t0\t1.0\tQQQQQQQQQQQ\t\tcodon_ratio\tnot-a-number\t\t\t\t\n",
                encoding="utf-8",
            )
            (publish_root / "tables" / "accession_status.tsv").write_text(
                "assembly_accession\tbatch_id\tdownload_status\tnormalize_status\ttranslate_status\tdetect_status\tfinalize_status\tterminal_status\tfailure_stage\tfailure_reason\tn_genomes\tn_proteins\tn_repeat_calls\tnotes\n"
                "GCF_000001405.40\tbatch_0001\tsuccess\tsuccess\tsuccess\tsuccess\tsuccess\tcompleted\t\t\t1\t1\t2\t\n",
                encoding="utf-8",
            )
            (publish_root / "tables" / "accession_call_counts.tsv").write_text(
                "assembly_accession\tbatch_id\tmethod\trepeat_residue\tdetect_status\tfinalize_status\tn_repeat_calls\n"
                "GCF_000001405.40\tbatch_0001\tpure\tQ\tsuccess\tsuccess\t2\n",
                encoding="utf-8",
            )

            call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            self.assertEqual(
                list(
                    RepeatCall.objects.order_by("call_id").values_list(
                        "call_id",
                        "codon_metric_value",
                        "codon_ratio_value",
                    )
                ),
                [
                    ("call_blank", "", None),
                    ("call_invalid", "not-a-number", None),
                ],
            )
            self.assertEqual(
                list(
                    CanonicalRepeatCall.objects.order_by("source_call_id").values_list(
                        "source_call_id",
                        "codon_metric_value",
                        "codon_ratio_value",
                    )
                ),
                [
                    ("call_blank", "", None),
                    ("call_invalid", "not-a-number", None),
                ],
            )

    def test_import_run_imports_repeat_call_codon_usage_rows_into_raw_and_canonical_tables(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir), run_id="run-codon-usage")
            stdout = StringIO()
            add_finalized_codon_usage_artifact(
                publish_root,
                method="pure",
                repeat_residue="Q",
                batch_id="batch_0001",
                rows=[
                    {
                        "call_id": "call_1",
                        "sequence_id": "seq_1",
                        "protein_id": "prot_1",
                        "amino_acid": "Q",
                        "codon": "CAA",
                        "codon_count": 1,
                        "codon_fraction": "0.0909090909",
                    },
                    {
                        "call_id": "call_1",
                        "sequence_id": "seq_1",
                        "protein_id": "prot_1",
                        "amino_acid": "Q",
                        "codon": "CAG",
                        "codon_count": 10,
                        "codon_fraction": "0.9090909091",
                    },
                ],
            )

            call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            self.assertEqual(RepeatCallCodonUsage.objects.count(), 2)
            self.assertEqual(CanonicalRepeatCallCodonUsage.objects.count(), 2)
            self.assertEqual(ImportBatch.objects.get().row_counts["repeat_call_codon_usages"], 2)
            self.assertEqual(
                list(
                    RepeatCallCodonUsage.objects.order_by("codon").values_list(
                        "repeat_call__call_id",
                        "amino_acid",
                        "codon",
                        "codon_count",
                    )
                ),
                [
                    ("call_1", "Q", "CAA", 1),
                    ("call_1", "Q", "CAG", 10),
                ],
            )
            self.assertEqual(
                list(
                    CanonicalRepeatCallCodonUsage.objects.order_by("codon").values_list(
                        "repeat_call__source_call_id",
                        "amino_acid",
                        "codon",
                        "codon_fraction",
                    )
                ),
                [
                    ("call_1", "Q", "CAA", 0.0909090909),
                    ("call_1", "Q", "CAG", 0.9090909091),
                ],
            )

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
            (publish_root / "tables" / "repeat_call_codon_usage.tsv").write_text(
                "call_id\tmethod\trepeat_residue\tsequence_id\tprotein_id\tamino_acid\tcodon\tcodon_count\tcodon_fraction\n"
                "call_1\tpure\tQ\tseq_1\tprot_1\tQ\tCAG\t11\t1.0\n",
                encoding="utf-8",
            )
            (publish_root / "tables" / "repeat_context.tsv").write_text(
                "call_id\tprotein_id\tsequence_id\taa_left_flank\taa_right_flank\tnt_left_flank\tnt_right_flank\taa_context_window_size\tnt_context_window_size\n"
                "call_1\tprot_1\tseq_1\tM\tA\tATG\tGCT\t12\t36\n",
                encoding="utf-8",
            )
            (publish_root / "tables" / "matched_sequences.tsv").write_text(
                "batch_id\tsequence_id\tgenome_id\tsequence_name\tsequence_length\tgene_symbol\ttranscript_id\tisoform_id\tassembly_accession\ttaxon_id\tsource_record_id\tprotein_external_id\ttranslation_table\tgene_group\tlinkage_status\tpartial_status\tnucleotide_sequence\n"
                f"batch_0001\tseq_1\tgenome_1\tNM_000001.1\t90\tGENE1\tNM_000001.1\tNP_000001.1\tGCF_000001405.40\t9606\tcds-1\tNP_000001.1\t1\tGENE1\tgff\t\t{'CAG' * 30}\n",
                encoding="utf-8",
            )
            (publish_root / "tables" / "matched_proteins.tsv").write_text(
                "batch_id\tprotein_id\tsequence_id\tgenome_id\tprotein_name\tprotein_length\tgene_symbol\ttranslation_method\ttranslation_status\tassembly_accession\ttaxon_id\tgene_group\tprotein_external_id\tamino_acid_sequence\n"
                f"batch_0001\tprot_1\tseq_1\tgenome_1\tNP_000001.1\t30\tGENE1\ttranslated\ttranslated\tGCF_000001405.40\t9606\tGENE1\tNP_000001.1\t{'Q' * 30}\n",
                encoding="utf-8",
            )
            (publish_root / "tables" / "accession_call_counts.tsv").write_text(
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
            self.assertEqual(Genome.objects.get(genome_id="genome_1").analyzed_protein_count, 1)
            self.assertEqual(Genome.objects.get(genome_id="genome_2").analyzed_protein_count, 0)
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

            (publish_root / "tables" / "genomes.tsv").write_text(
                "batch_id\tgenome_id\tsource\taccession\tgenome_name\tassembly_type\ttaxon_id\tassembly_level\tspecies_name\tnotes\n"
                "batch_0001\tgenome_1\tncbi_datasets\tGCF_000001405.40\tReplacement genome\thaploid\t9606\tChromosome\tHomo sapiens\tupdated\n",
                encoding="utf-8",
            )
            (publish_root / "calls" / "repeat_calls.tsv").write_text(
                "call_id\tmethod\tgenome_id\ttaxon_id\tsequence_id\tprotein_id\tstart\tend\tlength\trepeat_residue\trepeat_count\tnon_repeat_count\tpurity\taa_sequence\tcodon_sequence\tcodon_metric_name\tcodon_metric_value\twindow_definition\ttemplate_name\tmerge_rule\tscore\n"
                "call_2\tseed_extend\tgenome_1\t9606\tseq_1\tprot_1\t11\t21\t11\tA\t11\t0\t1.0\tAAAAAAAAAAA\t\t\t\tseed:A6/8|extend:A8/12\t\tseed_extend_connected_windows\t\n",
                encoding="utf-8",
            )
            (publish_root / "calls" / "run_params.tsv").write_text(
                "method\trepeat_residue\tparam_name\tparam_value\n"
                "seed_extend\tA\tseed_window_size\t8\n",
                encoding="utf-8",
            )
            (publish_root / "tables" / "repeat_call_codon_usage.tsv").write_text(
                "call_id\tmethod\trepeat_residue\tsequence_id\tprotein_id\tamino_acid\tcodon\tcodon_count\tcodon_fraction\n"
                "call_2\tseed_extend\tA\tseq_1\tprot_1\tA\tGCT\t11\t1.0\n",
                encoding="utf-8",
            )
            (publish_root / "tables" / "repeat_context.tsv").write_text(
                "call_id\tprotein_id\tsequence_id\taa_left_flank\taa_right_flank\tnt_left_flank\tnt_right_flank\taa_context_window_size\tnt_context_window_size\n"
                "call_2\tprot_1\tseq_1\tM\tA\tATG\tGCT\t12\t36\n",
                encoding="utf-8",
            )
            (publish_root / "tables" / "download_manifest.tsv").write_text(
                "batch_id\tassembly_accession\tdownload_status\tpackage_mode\tdownload_path\trehydrated_path\tchecksum\tfile_size_bytes\tdownload_started_at\tdownload_finished_at\tnotes\n"
                "batch_0001\tGCF_000001405.40\trehydrated\tdirect_zip\t\t\t\t106807993\t\t\treplaced\n",
                encoding="utf-8",
            )
            (publish_root / "tables" / "normalization_warnings.tsv").write_text(
                "warning_code\twarning_scope\twarning_message\tbatch_id\tgenome_id\tsequence_id\tprotein_id\tassembly_accession\tsource_file\tsource_record_id\n"
                "partial_cds\tsequence\tCDS is partial\tbatch_0001\tgenome_1\tseq_1\t\tGCF_000001405.40\t/source/path\tcds-1\n",
                encoding="utf-8",
            )
            (publish_root / "tables" / "accession_call_counts.tsv").write_text(
                "assembly_accession\tbatch_id\tmethod\trepeat_residue\tdetect_status\tfinalize_status\tn_repeat_calls\n"
                "GCF_000001405.40\tbatch_0001\tseed_extend\tA\tsuccess\tsuccess\t1\n",
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
            self.assertEqual(Genome.objects.get().analyzed_protein_count, 1)
            self.assertEqual(RepeatCall.objects.get().call_id, "call_2")
            self.assertEqual(RepeatCall.objects.get().method, RepeatCall.Method.SEED_EXTEND)
            self.assertEqual(RepeatCall.objects.get().repeat_residue, "A")
            self.assertEqual(DownloadManifestEntry.objects.get().download_status, "rehydrated")
            self.assertEqual(DownloadManifestEntry.objects.get().notes, "replaced")
            self.assertEqual(NormalizationWarning.objects.get().warning_code, "partial_cds")
            self.assertEqual(CanonicalGenome.objects.count(), 1)
            self.assertEqual(CanonicalSequence.objects.count(), 1)
            self.assertEqual(CanonicalProtein.objects.count(), 1)
            self.assertEqual(CanonicalRepeatCall.objects.count(), 1)
            self.assertEqual(CanonicalGenome.objects.get().genome_name, "Replacement genome")
            self.assertEqual(CanonicalGenome.objects.get().notes, "updated")
            self.assertEqual(CanonicalRepeatCall.objects.get().method, RepeatCall.Method.SEED_EXTEND)
            self.assertEqual(CanonicalRepeatCall.objects.get().repeat_residue, "A")
            self.assertEqual(CanonicalRepeatCall.objects.get().source_call_id, "call_2")
            self.assertEqual(
                PipelineRun.objects.get().browser_metadata,
                {
                    "raw_counts": {
                        "genomes": 1,
                        "sequences": 1,
                        "proteins": 1,
                        "repeat_calls": 1,
                        "repeat_call_contexts": 1,
                        "accession_status_rows": 1,
                        "accession_call_count_rows": 1,
                        "download_manifest_entries": 1,
                        "normalization_warnings": 1,
                    },
                    "facets": {
                        "methods": [RunParameter.Method.SEED_EXTEND],
                        "residues": ["A"],
                    },
                },
            )

    def test_import_run_keeps_raw_rows_when_canonical_sync_fails(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir), run_id="run-sync-failed")
            stdout = StringIO()

            with patch(
                "apps.imports.services.import_run.api.sync_canonical_catalog_for_run",
                side_effect=RuntimeError("sync boom"),
            ):
                with self.assertRaises(RuntimeError):
                    call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            pipeline_run = PipelineRun.objects.get(run_id="run-sync-failed")
            batch = ImportBatch.objects.get()

            self.assertEqual(batch.status, ImportBatch.Status.FAILED)
            self.assertEqual(batch.pipeline_run, pipeline_run)
            self.assertEqual(batch.error_message, "sync boom")
            self.assertEqual(Genome.objects.count(), 1)
            self.assertEqual(Sequence.objects.count(), 1)
            self.assertEqual(Protein.objects.count(), 1)
            self.assertEqual(RepeatCall.objects.count(), 1)
            self.assertEqual(CanonicalGenome.objects.count(), 0)
            self.assertEqual(CanonicalSequence.objects.count(), 0)
            self.assertEqual(CanonicalProtein.objects.count(), 0)
            self.assertEqual(CanonicalRepeatCall.objects.count(), 0)
            self.assertEqual(
                pipeline_run.browser_metadata,
                {
                    "raw_counts": {
                        "genomes": 1,
                        "sequences": 1,
                        "proteins": 1,
                        "repeat_calls": 1,
                        "repeat_call_contexts": 1,
                        "accession_status_rows": 1,
                        "accession_call_count_rows": 1,
                        "download_manifest_entries": 1,
                        "normalization_warnings": 0,
                    },
                    "facets": {
                        "methods": [RunParameter.Method.PURE],
                        "residues": ["Q"],
                    },
                },
            )

    def test_import_run_replace_existing_removes_stale_canonical_repeat_entities(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_multibatch_publish_root(Path(tempdir), run_id="run-replace-stale")
            stdout = StringIO()

            call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            self.assertEqual(CanonicalGenome.objects.count(), 2)
            self.assertEqual(CanonicalSequence.objects.count(), 2)
            self.assertEqual(CanonicalProtein.objects.count(), 2)
            self.assertEqual(CanonicalRepeatCall.objects.count(), 2)

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
            (publish_root / "tables" / "repeat_call_codon_usage.tsv").write_text(
                "call_id\tmethod\trepeat_residue\tsequence_id\tprotein_id\tamino_acid\tcodon\tcodon_count\tcodon_fraction\n"
                "call_1\tpure\tQ\tseq_1\tprot_1\tQ\tCAG\t11\t1.0\n",
                encoding="utf-8",
            )
            (publish_root / "tables" / "repeat_context.tsv").write_text(
                "call_id\tprotein_id\tsequence_id\taa_left_flank\taa_right_flank\tnt_left_flank\tnt_right_flank\taa_context_window_size\tnt_context_window_size\n"
                "call_1\tprot_1\tseq_1\tM\tA\tATG\tGCT\t12\t36\n",
                encoding="utf-8",
            )
            (publish_root / "tables" / "matched_sequences.tsv").write_text(
                "batch_id\tsequence_id\tgenome_id\tsequence_name\tsequence_length\tgene_symbol\ttranscript_id\tisoform_id\tassembly_accession\ttaxon_id\tsource_record_id\tprotein_external_id\ttranslation_table\tgene_group\tlinkage_status\tpartial_status\tnucleotide_sequence\n"
                f"batch_0001\tseq_1\tgenome_1\tNM_000001.1\t90\tGENE1\tNM_000001.1\tNP_000001.1\tGCF_000001405.40\t9606\tcds-1\tNP_000001.1\t1\tGENE1\tgff\t\t{'CAG' * 30}\n",
                encoding="utf-8",
            )
            (publish_root / "tables" / "matched_proteins.tsv").write_text(
                "batch_id\tprotein_id\tsequence_id\tgenome_id\tprotein_name\tprotein_length\tgene_symbol\ttranslation_method\ttranslation_status\tassembly_accession\ttaxon_id\tgene_group\tprotein_external_id\tamino_acid_sequence\n"
                f"batch_0001\tprot_1\tseq_1\tgenome_1\tNP_000001.1\t30\tGENE1\ttranslated\ttranslated\tGCF_000001405.40\t9606\tGENE1\tNP_000001.1\t{'Q' * 30}\n",
                encoding="utf-8",
            )
            (publish_root / "tables" / "accession_status.tsv").write_text(
                "assembly_accession\tbatch_id\tdownload_status\tnormalize_status\ttranslate_status\tdetect_status\tfinalize_status\tterminal_status\tfailure_stage\tfailure_reason\tn_genomes\tn_proteins\tn_repeat_calls\tnotes\n"
                "GCF_000001405.40\tbatch_0001\tsuccess\tsuccess\tsuccess\tsuccess\tsuccess\tcompleted\t\t\t1\t1\t1\t\n",
                encoding="utf-8",
            )
            (publish_root / "tables" / "accession_call_counts.tsv").write_text(
                "assembly_accession\tbatch_id\tmethod\trepeat_residue\tdetect_status\tfinalize_status\tn_repeat_calls\n"
                "GCF_000001405.40\tbatch_0001\tpure\tQ\tsuccess\tsuccess\t1\n",
                encoding="utf-8",
            )

            call_command(
                "import_run",
                publish_root=str(publish_root),
                replace_existing=True,
                stdout=stdout,
            )

            self.assertEqual(RepeatCall.objects.count(), 1)
            self.assertEqual(CanonicalGenome.objects.count(), 2)
            self.assertEqual(CanonicalSequence.objects.count(), 1)
            self.assertEqual(CanonicalProtein.objects.count(), 1)
            self.assertEqual(CanonicalRepeatCall.objects.count(), 1)
            self.assertEqual(CanonicalProtein.objects.get().accession, "GCF_000001405.40")
            self.assertEqual(CanonicalRepeatCall.objects.get().accession, "GCF_000001405.40")

    def test_import_run_canonical_catalog_latest_run_wins_across_runs(self):
        with TemporaryDirectory() as tempdir_alpha, TemporaryDirectory() as tempdir_beta:
            publish_root_alpha = build_minimal_publish_root(Path(tempdir_alpha), run_id="run-latest-alpha")
            publish_root_beta = build_minimal_publish_root(Path(tempdir_beta), run_id="run-latest-beta")
            stdout = StringIO()

            (publish_root_beta / "tables" / "genomes.tsv").write_text(
                "batch_id\tgenome_id\tsource\taccession\tgenome_name\tassembly_type\ttaxon_id\tassembly_level\tspecies_name\tnotes\n"
                "batch_0001\tgenome_1\tncbi_datasets\tGCF_000001405.40\tGenome beta\thaploid\t9606\tChromosome\tHomo sapiens\t\n",
                encoding="utf-8",
            )
            (publish_root_beta / "tables" / "matched_sequences.tsv").write_text(
                "batch_id\tsequence_id\tgenome_id\tsequence_name\tsequence_length\tgene_symbol\ttranscript_id\tisoform_id\tassembly_accession\ttaxon_id\tsource_record_id\tprotein_external_id\ttranslation_table\tgene_group\tlinkage_status\tpartial_status\tnucleotide_sequence\n"
                f"batch_0001\tseq_1\tgenome_1\tNM_BETA.1\t90\tGENE1\tNM_000001.1\tNP_000001.1\tGCF_000001405.40\t9606\tcds-1\tNP_000001.1\t1\tGENE1\tgff\t\t{'CAG' * 30}\n",
                encoding="utf-8",
            )
            (publish_root_beta / "tables" / "matched_proteins.tsv").write_text(
                "batch_id\tprotein_id\tsequence_id\tgenome_id\tprotein_name\tprotein_length\tgene_symbol\ttranslation_method\ttranslation_status\tassembly_accession\ttaxon_id\tgene_group\tprotein_external_id\tamino_acid_sequence\n"
                f"batch_0001\tprot_1\tseq_1\tgenome_1\tNP_BETA.1\t30\tGENE1\ttranslated\ttranslated\tGCF_000001405.40\t9606\tGENE1\tNP_000001.1\t{'Q' * 30}\n",
                encoding="utf-8",
            )
            (publish_root_beta / "calls" / "repeat_calls.tsv").write_text(
                "call_id\tmethod\tgenome_id\ttaxon_id\tsequence_id\tprotein_id\tstart\tend\tlength\trepeat_residue\trepeat_count\tnon_repeat_count\tpurity\taa_sequence\tcodon_sequence\tcodon_metric_name\tcodon_metric_value\twindow_definition\ttemplate_name\tmerge_rule\tscore\n"
                "call_beta\tpure\tgenome_1\t9606\tseq_1\tprot_1\t12\t24\t13\tQ\t13\t0\t1.0\tQQQQQQQQQQQQQ\t\t\t\t\t\t\t\n",
                encoding="utf-8",
            )
            (publish_root_beta / "tables" / "repeat_call_codon_usage.tsv").write_text(
                "call_id\tmethod\trepeat_residue\tsequence_id\tprotein_id\tamino_acid\tcodon\tcodon_count\tcodon_fraction\n"
                "call_beta\tpure\tQ\tseq_1\tprot_1\tQ\tCAG\t13\t1.0\n",
                encoding="utf-8",
            )
            (publish_root_beta / "tables" / "repeat_context.tsv").write_text(
                "call_id\tprotein_id\tsequence_id\taa_left_flank\taa_right_flank\tnt_left_flank\tnt_right_flank\taa_context_window_size\tnt_context_window_size\n"
                "call_beta\tprot_1\tseq_1\tM\tA\tATG\tGCT\t12\t36\n",
                encoding="utf-8",
            )

            call_command("import_run", publish_root=str(publish_root_alpha), stdout=stdout)
            call_command("import_run", publish_root=str(publish_root_beta), stdout=stdout)

            self.assertEqual(Genome.objects.count(), 2)
            self.assertEqual(RepeatCall.objects.count(), 2)
            self.assertEqual(CanonicalGenome.objects.count(), 1)
            self.assertEqual(CanonicalSequence.objects.count(), 1)
            self.assertEqual(CanonicalProtein.objects.count(), 1)
            self.assertEqual(CanonicalRepeatCall.objects.count(), 1)
            self.assertEqual(CanonicalGenome.objects.get().genome_name, "Genome beta")
            self.assertEqual(CanonicalSequence.objects.get().sequence_name, "NM_BETA.1")
            self.assertEqual(CanonicalProtein.objects.get().protein_name, "NP_BETA.1")
            self.assertEqual(CanonicalRepeatCall.objects.get().source_call_id, "call_beta")
            self.assertEqual(
                CanonicalGenome.objects.get().latest_pipeline_run.run_id,
                "run-latest-beta",
            )

    def test_import_run_rolls_back_on_broken_references(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir), run_id="run-broken")
            stdout = StringIO()
            (publish_root / "tables" / "matched_sequences.tsv").write_text(
                "batch_id\tsequence_id\tgenome_id\tsequence_name\tsequence_length\tgene_symbol\ttranscript_id\tisoform_id\tassembly_accession\ttaxon_id\tsource_record_id\tprotein_external_id\ttranslation_table\tgene_group\tlinkage_status\tpartial_status\tnucleotide_sequence\n"
                f"batch_0001\tseq_1\tmissing_genome\tNM_000001.1\t900\tGENE1\tNM_000001.1\tNP_000001.1\tGCF_000001405.40\t9606\tcds-1\tNP_000001.1\t1\tGENE1\tgff\t\t{'CAG' * 30}\n",
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

    def test_import_run_fails_when_codon_usage_references_missing_call(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir), run_id="run-bad-codon-usage")
            stdout = StringIO()
            (publish_root / "tables" / "repeat_call_codon_usage.tsv").write_text(
                "call_id\tmethod\trepeat_residue\tsequence_id\tprotein_id\tamino_acid\tcodon\tcodon_count\tcodon_fraction\n"
                "missing_call\tpure\tQ\tseq_1\tprot_1\tQ\tCAG\t11\t1.0\n",
                encoding="utf-8",
            )

            with self.assertRaises(CommandError):
                call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            self.assertFalse(PipelineRun.objects.filter(run_id="run-bad-codon-usage").exists())
            self.assertEqual(ImportBatch.objects.get().status, ImportBatch.Status.FAILED)

    def test_import_run_fails_when_repeat_call_references_missing_matched_protein(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir), run_id="run-missing-protein")
            stdout = StringIO()
            (publish_root / "calls" / "repeat_calls.tsv").write_text(
                "call_id\tmethod\tgenome_id\ttaxon_id\tsequence_id\tprotein_id\tstart\tend\tlength\trepeat_residue\trepeat_count\tnon_repeat_count\tpurity\taa_sequence\tcodon_sequence\tcodon_metric_name\tcodon_metric_value\twindow_definition\ttemplate_name\tmerge_rule\tscore\n"
                "call_1\tpure\tgenome_1\t9606\tseq_1\tmissing_prot\t10\t20\t11\tQ\t11\t0\t1.0\tQQQQQQQQQQQ\t\t\t\t\t\t\t\n",
                encoding="utf-8",
            )

            with self.assertRaises(CommandError):
                call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            self.assertFalse(PipelineRun.objects.filter(run_id="run-missing-protein").exists())
            self.assertEqual(ImportBatch.objects.get().status, ImportBatch.Status.FAILED)

    def test_import_run_fails_on_duplicate_v2_entity_keys(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir), run_id="run-duplicate-sequence")
            stdout = StringIO()
            (publish_root / "tables" / "matched_sequences.tsv").write_text(
                "batch_id\tsequence_id\tgenome_id\tsequence_name\tsequence_length\tgene_symbol\ttranscript_id\tisoform_id\tassembly_accession\ttaxon_id\tsource_record_id\tprotein_external_id\ttranslation_table\tgene_group\tlinkage_status\tpartial_status\tnucleotide_sequence\n"
                f"batch_0001\tseq_1\tgenome_1\tNM_000001.1\t90\tGENE1\tNM_000001.1\tNP_000001.1\tGCF_000001405.40\t9606\tcds-1\tNP_000001.1\t1\tGENE1\tgff\t\t{'CAG' * 30}\n"
                f"batch_0001\tseq_1\tgenome_1\tNM_000001.2\t90\tGENE1\tNM_000001.2\tNP_000001.1\tGCF_000001405.40\t9606\tcds-1b\tNP_000001.1\t1\tGENE1\tgff\t\t{'CAG' * 30}\n",
                encoding="utf-8",
            )

            with self.assertRaises(CommandError):
                call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            self.assertFalse(PipelineRun.objects.filter(run_id="run-duplicate-sequence").exists())
            self.assertEqual(ImportBatch.objects.get().status, ImportBatch.Status.FAILED)

    def test_import_run_fails_when_taxonomy_parent_is_missing(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir), run_id="run-missing-tax-parent")
            stdout = StringIO()
            (publish_root / "tables" / "taxonomy.tsv").write_text(
                "taxon_id\ttaxon_name\tparent_taxon_id\trank\tsource\n"
                "9606\tHomo sapiens\t1\tspecies\ttest\n",
                encoding="utf-8",
            )

            with self.assertRaises(CommandError):
                call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            self.assertFalse(PipelineRun.objects.filter(run_id="run-missing-tax-parent").exists())
            self.assertEqual(ImportBatch.objects.get().status, ImportBatch.Status.FAILED)

    def test_import_run_still_validates_unreferenced_inventory_rows(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir), run_id="run-bad-protein")
            stdout = StringIO()
            (publish_root / "tables" / "matched_proteins.tsv").write_text(
                "batch_id\tprotein_id\tsequence_id\tgenome_id\tprotein_name\tprotein_length\tgene_symbol\ttranslation_method\ttranslation_status\tassembly_accession\ttaxon_id\tgene_group\tprotein_external_id\tamino_acid_sequence\n"
                f"batch_0001\tprot_1\tseq_1\tgenome_1\tNP_000001.1\t300\tGENE1\ttranslated\ttranslated\tGCF_000001405.40\t9606\tGENE1\tNP_000001.1\t{'Q' * 30}\n"
                f"batch_0001\tprot_2\tmissing_seq\tgenome_1\tNP_000002.1\t280\tGENE2\ttranslated\ttranslated\tGCF_000001405.40\t9606\tGENE2\tNP_000002.1\t{'A' * 280}\n",
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
            (publish_root / "tables" / "taxonomy.tsv").write_text(
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
            add_finalized_codon_usage_artifact(
                publish_root,
                method="pure",
                repeat_residue="Q",
                batch_id="batch_0001",
                rows=[
                    {
                        "call_id": "call_1",
                        "sequence_id": "seq_1",
                        "protein_id": "prot_1",
                        "amino_acid": "Q",
                        "codon": "CAG",
                        "codon_count": 11,
                        "codon_fraction": "1.0",
                    },
                ],
            )

            with patch("apps.imports.services.import_run.api._ImportBatchStateReporter", FakeReporter):
                call_command("import_run", publish_root=str(publish_root), stdout=stdout)

        self.assertIn("Imported run run-progress", stdout.getvalue())
        self.assertTrue(
            any(payload.get("message") == "Staging v2 run-level tables locally." for payload in recorded_payloads)
        )
        self.assertTrue(any(payload.get("message") == "Importing v2 rows locally." for payload in recorded_payloads))
        self.assertTrue(
            any(payload.get("message") == "Syncing canonical catalog rows." for payload in recorded_payloads)
        )
        self.assertTrue(
            any(payload.get("message") == "Syncing canonical repeat-call rows." for payload in recorded_payloads)
        )
        self.assertTrue(
            any(
                payload.get("message") == "Syncing canonical repeat-call codon-usage rows."
                for payload in recorded_payloads
            )
        )

    def test_import_run_triggers_post_load_analyze_hook(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir), run_id="run-analyze")
            stdout = StringIO()

            with patch(
                "apps.imports.services.import_run.api._analyze_models",
                return_value=True,
            ) as analyze_models:
                call_command("import_run", publish_root=str(publish_root), stdout=stdout)

            self.assertIn("Imported run run-analyze", stdout.getvalue())
            analyze_models.assert_called_once()
            analyzed_models = analyze_models.call_args.args[0]
            self.assertIn(CanonicalGenome, analyzed_models)
            self.assertIn(CanonicalSequence, analyzed_models)
            self.assertIn(CanonicalProtein, analyzed_models)
            self.assertIn(CanonicalRepeatCall, analyzed_models)
