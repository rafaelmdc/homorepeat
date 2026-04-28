from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from django.test import TestCase
from django.urls import resolve, reverse
from django.utils import timezone

from apps.browser.catalog import sync_canonical_catalog_for_run
from apps.browser.metadata import BROWSER_METADATA_RAW_COUNT_KEYS
from apps.browser.models import (
    AccessionCallCount,
    AccessionStatus,
    AcquisitionBatch,
    DownloadManifestEntry,
    NormalizationWarning,
    Protein,
    RepeatCall,
    RepeatCallCodonUsage,
    RunParameter,
    Sequence,
)
from apps.browser.views import (
    CodonUsageListView,
    CodonUsageRowListView,
    HomorepeatListView,
    ProteinListView,
    RepeatCallListView,
    SequenceListView,
)
from apps.imports.models import ImportBatch

from .support import build_test_repeat_call_values, create_imported_run_fixture


class BrowserViewTests(TestCase):
    def setUp(self):
        self.alpha = create_imported_run_fixture(
            run_id="run-alpha",
            genome_id="genome_alpha",
            sequence_id="seq_alpha",
            protein_id="prot_alpha",
            call_id="call_alpha",
            accession="GCF_ALPHA",
            taxon_key="human",
            genome_name="Human reference genome",
        )
        self.beta = create_imported_run_fixture(
            run_id="run-beta",
            genome_id="genome_beta",
            sequence_id="seq_beta",
            protein_id="prot_beta",
            call_id="call_beta",
            accession="GCF_BETA",
            taxon_key="mouse",
            genome_name="Mouse reference genome",
        )
        self.mammalia = self.alpha["taxa"]["mammalia"]
        self.primates = self.alpha["taxa"]["primates"]

    def _browser_metadata(self, *, methods, residues):
        return {
            "raw_counts": {key: 1 for key in BROWSER_METADATA_RAW_COUNT_KEYS},
            "facets": {
                "methods": methods,
                "residues": residues,
            },
        }

    def _create_repeat_call(
        self,
        run_data,
        *,
        suffix,
        gene_symbol,
        method,
        residue,
        length,
        purity,
        start=10,
        protein=None,
        sequence=None,
        taxon=None,
    ):
        pipeline_run = run_data["pipeline_run"]
        genome = run_data["genome"]
        taxon = taxon or run_data["taxon"]

        if protein is None:
            sequence = Sequence.objects.create(
                pipeline_run=pipeline_run,
                genome=genome,
                taxon=taxon,
                sequence_id=f"seq_{suffix}",
                sequence_name=f"NM_{suffix}",
                sequence_length=900,
                gene_symbol=gene_symbol,
            )
            protein = Protein.objects.create(
                pipeline_run=pipeline_run,
                genome=genome,
                sequence=sequence,
                taxon=taxon,
                protein_id=f"prot_{suffix}",
                protein_name=f"NP_{suffix}",
                protein_length=300,
                accession=genome.accession,
                gene_symbol=gene_symbol,
                assembly_accession=genome.accession,
            )
        else:
            sequence = sequence or protein.sequence
            genome = protein.genome
            taxon = protein.taxon

        repeat_call_values = build_test_repeat_call_values(
            residue=residue,
            length=length,
            purity=purity,
        )
        repeat_call = RepeatCall.objects.create(
            pipeline_run=pipeline_run,
            genome=genome,
            sequence=sequence,
            protein=protein,
            taxon=taxon,
            call_id=f"call_{suffix}",
            method=method,
            accession=genome.accession,
            gene_symbol=protein.gene_symbol or sequence.gene_symbol,
            protein_name=protein.protein_name,
            protein_length=protein.protein_length,
            start=start,
            end=start + length - 1,
            length=length,
            repeat_residue=residue,
            repeat_count=repeat_call_values["repeat_count"],
            non_repeat_count=repeat_call_values["non_repeat_count"],
            purity=purity,
            aa_sequence=repeat_call_values["aa_sequence"],
            codon_sequence=repeat_call_values["codon_sequence"],
            codon_metric_name=repeat_call_values["codon_metric_name"],
            codon_metric_value=repeat_call_values["codon_metric_value"],
            codon_ratio_value=repeat_call_values["codon_ratio_value"],
        )
        sync_canonical_catalog_for_run(
            pipeline_run,
            import_batch=pipeline_run.canonical_sync_batch,
            last_seen_at=timezone.now(),
            replace_all_repeat_call_methods=True,
        )
        return {"sequence": sequence, "protein": protein, "repeat_call": repeat_call}

    def _set_repeat_call_codon_usages(self, run_data, *, repeat_call=None, rows):
        target_repeat_call = repeat_call or run_data["repeat_call"]
        RepeatCallCodonUsage.objects.filter(repeat_call=target_repeat_call).delete()
        RepeatCallCodonUsage.objects.bulk_create(
            [
                RepeatCallCodonUsage(
                    repeat_call=target_repeat_call,
                    amino_acid=row["amino_acid"],
                    codon=row["codon"],
                    codon_count=row["codon_count"],
                    codon_fraction=row["codon_fraction"],
                )
                for row in rows
            ]
        )
        sync_canonical_catalog_for_run(
            target_repeat_call.pipeline_run,
            import_batch=target_repeat_call.pipeline_run.canonical_sync_batch,
            last_seen_at=timezone.now(),
            replace_all_repeat_call_methods=True,
        )
        return target_repeat_call

    def test_browser_home_shows_counts_and_recent_runs(self):
        response = self.client.get(reverse("browser:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Primary scientific tables")
        self.assertContains(response, "Open Homorepeats")
        self.assertContains(response, reverse("browser:homorepeat-list"))
        self.assertContains(response, "Open Codon Usage")
        self.assertContains(response, reverse("browser:codon-usage-list"))
        self.assertContains(response, "Supporting catalog")
        self.assertContains(response, reverse("browser:accession-list"))
        self.assertContains(response, "Technical canonical repeat-call table")
        self.assertContains(response, "Repeat lengths")
        self.assertContains(response, reverse("browser:lengths"))
        self.assertContains(response, "Codon ratios")
        self.assertContains(response, reverse("browser:codon-ratios"))
        self.assertContains(response, "Codon*length")
        self.assertContains(response, reverse("browser:codon-composition-length"))
        self.assertContains(response, "Run provenance")
        self.assertContains(response, "Operational provenance")
        self.assertContains(response, "Codon usage rows")
        self.assertContains(response, reverse("browser:codonusage-row-list"))
        self.assertContains(response, reverse("browser:accessionstatus-list"))
        self.assertContains(response, reverse("browser:downloadmanifest-list"))
        self.assertContains(response, "run-alpha")
        self.assertContains(response, "run-beta")
        section_titles = [section["title"] for section in response.context["directory_sections"]]
        self.assertLess(section_titles.index("Statistical explorers"), section_titles.index("Supporting catalog"))
        primary_items = response.context["directory_sections"][0]["items"]
        self.assertEqual(primary_items[1]["count"], primary_items[0]["count"])

    def test_browser_home_recent_runs_use_browser_metadata_counts(self):
        self.alpha["pipeline_run"].browser_metadata = {
            "raw_counts": {
                "genomes": 17,
                "sequences": 0,
                "proteins": 23,
                "repeat_calls": 31,
                "repeat_call_contexts": 0,
                "accession_status_rows": 0,
                "accession_call_count_rows": 0,
                "download_manifest_entries": 0,
                "normalization_warnings": 0,
            },
            "facets": {
                "methods": [RunParameter.Method.PURE],
                "residues": ["Q"],
            },
        }
        self.alpha["pipeline_run"].save(update_fields=["browser_metadata"])

        response = self.client.get(reverse("browser:home"))

        self.assertEqual(response.status_code, 200)
        recent_runs = {pipeline_run.run_id: pipeline_run for pipeline_run in response.context["recent_runs"]}
        self.assertEqual(recent_runs["run-alpha"].genomes_count, 17)
        self.assertEqual(recent_runs["run-alpha"].proteins_count, 23)
        self.assertEqual(recent_runs["run-alpha"].repeat_calls_count, 31)

    def test_run_list_renders_imported_runs(self):
        response = self.client.get(reverse("browser:run-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Imported run history")
        self.assertContains(response, "Primary browsing now starts from the canonical entity")
        self.assertContains(response, "run-alpha")
        self.assertContains(response, "run-beta")
        self.assertContains(response, reverse("browser:run-detail", args=[self.alpha["pipeline_run"].pk]))

    def test_run_list_uses_completed_import_batch_count_fallback(self):
        pipeline_run = self.alpha["pipeline_run"]
        ImportBatch.objects.create(
            source_path=pipeline_run.publish_root,
            status=ImportBatch.Status.COMPLETED,
            phase="completed",
            finished_at=timezone.now(),
            heartbeat_at=timezone.now(),
            row_counts={
                "genomes": 9,
                "sequences": 8,
                "proteins": 7,
                "repeat_calls": 6,
            },
        )

        response = self.client.get(reverse("browser:run-list"))

        self.assertEqual(response.status_code, 200)
        runs = {pipeline_run.run_id: pipeline_run for pipeline_run in response.context["runs"]}
        self.assertEqual(runs["run-alpha"].genomes_count, 9)
        self.assertEqual(runs["run-alpha"].sequences_count, 8)
        self.assertEqual(runs["run-alpha"].proteins_count, 7)
        self.assertEqual(runs["run-alpha"].repeat_calls_count, 6)

    def test_run_list_leaves_summary_counts_blank_without_metadata_or_import_batch_counts(self):
        response = self.client.get(reverse("browser:run-list"))

        self.assertEqual(response.status_code, 200)
        runs = {pipeline_run.run_id: pipeline_run for pipeline_run in response.context["runs"]}
        self.assertIsNone(runs["run-alpha"].genomes_count)
        self.assertIsNone(runs["run-alpha"].sequences_count)
        self.assertIsNone(runs["run-alpha"].proteins_count)
        self.assertIsNone(runs["run-alpha"].repeat_calls_count)

    def test_run_list_search_filters_results(self):
        response = self.client.get(reverse("browser:run-list"), {"q": "run-beta"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "run-beta")
        self.assertNotContains(response, "run-alpha")

    def test_run_list_imported_counts_do_not_link_to_canonical_views(self):
        response = self.client.get(reverse("browser:run-list"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, f'{reverse("browser:genome-list")}?run=run-alpha')
        self.assertNotContains(response, f'{reverse("browser:protein-list")}?run=run-alpha')
        self.assertNotContains(response, f'{reverse("browser:repeatcall-list")}?run=run-alpha')

    def test_run_detail_shows_counts_and_scoped_links(self):
        response = self.client.get(reverse("browser:run-detail", args=[self.alpha["pipeline_run"].pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "run-alpha")
        self.assertContains(response, "Open current accessions")
        self.assertContains(response, "Current accessions")
        self.assertContains(response, "Current sequences")
        self.assertContains(response, "Current proteins")
        self.assertContains(response, "Current repeat calls")
        self.assertContains(response, "Current entities linked to this run")
        self.assertContains(response, "Historical rows stored by this run")
        self.assertContains(response, "historical imported observations")
        self.assertContains(response, "Distinct taxa referenced")
        self.assertContains(response, "Imported genomes")
        self.assertContains(response, "Imported sequences")
        self.assertContains(response, "Imported proteins")
        self.assertContains(response, "Imported repeat calls")
        self.assertContains(response, "?run=run-alpha")
        self.assertContains(response, reverse("browser:accessionstatus-list"))
        self.assertContains(response, reverse("browser:accessioncallcount-list"))
        self.assertContains(response, reverse("browser:downloadmanifest-list"))
        self.assertContains(response, reverse("browser:normalizationwarning-list"))
        self.assertContains(response, "Method: pure")
        self.assertContains(response, "Acquisition batches")
        self.assertContains(response, "Accession status")
        self.assertContains(response, "completed")

    def test_run_detail_shows_batch_provenance_and_import_activity(self):
        pipeline_run = self.alpha["pipeline_run"]
        extra_batch = AcquisitionBatch.objects.create(
            pipeline_run=pipeline_run,
            batch_id="batch_0002",
        )
        DownloadManifestEntry.objects.create(
            pipeline_run=pipeline_run,
            batch=extra_batch,
            assembly_accession="GCF_ALPHA_ALT",
            download_status="downloaded",
            package_mode="direct_zip",
        )
        NormalizationWarning.objects.create(
            pipeline_run=pipeline_run,
            batch=extra_batch,
            warning_code="partial_cds",
            warning_scope="sequence",
            warning_message="CDS is partial",
            assembly_accession="GCF_ALPHA_ALT",
            source_record_id="cds-2",
        )
        AccessionStatus.objects.create(
            pipeline_run=pipeline_run,
            batch=extra_batch,
            assembly_accession="GCF_ALPHA_ALT",
            download_status="success",
            normalize_status="warning",
            translate_status="success",
            detect_status="failed",
            finalize_status="skipped",
            terminal_status="failed",
            failure_stage="detect",
            failure_reason="missing translated sequence",
            n_genomes=1,
            n_proteins=0,
            n_repeat_calls=0,
        )
        AccessionCallCount.objects.create(
            pipeline_run=pipeline_run,
            batch=extra_batch,
            assembly_accession="GCF_ALPHA_ALT",
            method=RunParameter.Method.THRESHOLD,
            repeat_residue="A",
            detect_status="failed",
            finalize_status="skipped",
            n_repeat_calls=0,
        )
        ImportBatch.objects.create(
            pipeline_run=pipeline_run,
            source_path=pipeline_run.publish_root,
            status=ImportBatch.Status.COMPLETED,
            phase="completed",
            finished_at=timezone.now(),
            heartbeat_at=timezone.now(),
            success_count=2,
            progress_payload={"message": "Import completed successfully."},
            row_counts={"genomes": 1, "repeat_calls": 1},
        )
        ImportBatch.objects.create(
            source_path=pipeline_run.publish_root,
            status=ImportBatch.Status.RUNNING,
            replace_existing=True,
            phase="staging_tables",
            heartbeat_at=timezone.now(),
            progress_payload={
                "message": "Staging import tables.",
                "batch_id": "batch_0002",
                "inserted_sequences": 42,
            },
        )

        response = self.client.get(reverse("browser:run-detail", args=[pipeline_run.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Publish mode: raw")
        self.assertContains(response, "Acquisition publish mode")
        self.assertContains(response, "Heartbeat and provenance visibility")
        self.assertContains(response, "Staging import tables.")
        self.assertContains(response, "Inserted sequences")
        self.assertContains(response, "batch_0002")
        self.assertContains(response, "partial_cds")
        self.assertContains(response, "threshold")
        self.assertContains(response, "Latest completed counts")
        self.assertContains(response, "failed")

    def test_run_detail_links_summary_counts_to_filtered_related_views(self):
        response = self.client.get(reverse("browser:run-detail", args=[self.alpha["pipeline_run"].pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{reverse('browser:accession-list')}?run=run-alpha")
        self.assertContains(response, f"{reverse('browser:sequence-list')}?run=run-alpha")
        self.assertContains(response, f"{reverse('browser:protein-list')}?run=run-alpha")
        self.assertContains(response, f"{reverse('browser:repeatcall-list')}?run=run-alpha")
        self.assertContains(response, "terminal_status=completed")
        self.assertContains(response, "method=pure")
        self.assertContains(response, "historical imported status rows")
        self.assertNotContains(response, f"{reverse('browser:repeatcall-list')}?run=run-alpha&amp;method=pure")

    def test_run_detail_replacement_import_separates_current_and_imported_counts(self):
        create_imported_run_fixture(
            run_id="run-gamma",
            genome_id="genome_gamma",
            sequence_id="seq_alpha",
            protein_id="prot_alpha",
            call_id="call_gamma",
            accession="GCF_ALPHA",
            taxon_key="human",
            genome_name="Human reference genome replacement",
        )

        response = self.client.get(reverse("browser:run-detail", args=[self.alpha["pipeline_run"].pk]))

        self.assertEqual(response.status_code, 200)
        pipeline_run = response.context["pipeline_run"]
        self.assertEqual(pipeline_run.genomes_count, 1)
        self.assertEqual(pipeline_run.sequences_count, 1)
        self.assertEqual(pipeline_run.proteins_count, 1)
        self.assertEqual(pipeline_run.repeat_calls_count, 1)
        self.assertEqual(pipeline_run.current_accessions_count, 0)
        self.assertEqual(pipeline_run.current_sequences_count, 0)
        self.assertEqual(pipeline_run.current_proteins_count, 0)
        self.assertEqual(pipeline_run.current_repeat_calls_count, 0)
        accession_response = self.client.get(reverse("browser:accession-list"), {"run": "run-alpha"})
        self.assertEqual(accession_response.status_code, 200)
        self.assertNotContains(accession_response, "GCF_ALPHA")

    def test_run_detail_uses_browser_metadata_facets(self):
        pipeline_run = self.alpha["pipeline_run"]
        pipeline_run.browser_metadata = self._browser_metadata(
            methods=[RunParameter.Method.SEED_EXTEND],
            residues=["A"],
        )
        pipeline_run.save(update_fields=["browser_metadata"])

        response = self.client.get(reverse("browser:run-detail", args=[pipeline_run.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["methods"], [RunParameter.Method.SEED_EXTEND])
        self.assertEqual(response.context["repeat_residues"], ["A"])

    def test_accession_status_list_filters_by_run_batch_and_status(self):
        pipeline_run = self.alpha["pipeline_run"]
        extra_batch = AcquisitionBatch.objects.create(
            pipeline_run=pipeline_run,
            batch_id="batch_0002",
        )
        AccessionStatus.objects.create(
            pipeline_run=pipeline_run,
            batch=extra_batch,
            assembly_accession="GCF_ALPHA_ALT",
            download_status="success",
            normalize_status="warning",
            translate_status="success",
            detect_status="failed",
            finalize_status="skipped",
            terminal_status="failed",
            failure_stage="detect",
            failure_reason="missing translated sequence",
            n_genomes=1,
            n_proteins=0,
            n_repeat_calls=0,
        )
        AccessionStatus.objects.create(
            pipeline_run=self.beta["pipeline_run"],
            batch=self.beta["batch"],
            assembly_accession="GCF_BETA_ALT",
            download_status="success",
            normalize_status="success",
            translate_status="success",
            detect_status="success",
            finalize_status="success",
            terminal_status="completed",
            n_genomes=1,
            n_proteins=1,
            n_repeat_calls=2,
        )

        response = self.client.get(
            reverse("browser:accessionstatus-list"),
            {
                "run": "run-alpha",
                "batch": str(extra_batch.pk),
                "terminal_status": "failed",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GCF_ALPHA_ALT")
        self.assertContains(response, reverse("browser:accession-detail", args=["GCF_ALPHA_ALT"]))
        self.assertContains(response, "missing translated sequence")
        self.assertContains(response, "failed")
        self.assertNotContains(response, "completed")
        self.assertNotContains(response, "GCF_BETA_ALT")

    def test_accession_status_list_tsv_export_honors_filters_and_full_queryset(self):
        pipeline_run = self.alpha["pipeline_run"]
        extra_batch = AcquisitionBatch.objects.create(
            pipeline_run=pipeline_run,
            batch_id="batch_0002",
        )
        AccessionStatus.objects.create(
            pipeline_run=pipeline_run,
            batch=extra_batch,
            assembly_accession="GCF_ALPHA_ALT",
            download_status="success",
            normalize_status="warning",
            translate_status="success",
            detect_status="failed",
            finalize_status="skipped",
            terminal_status="failed",
            failure_stage="detect",
            failure_reason="missing translated sequence",
            n_genomes=1,
            n_proteins=0,
            n_repeat_calls=0,
        )
        AccessionStatus.objects.create(
            pipeline_run=self.beta["pipeline_run"],
            batch=self.beta["batch"],
            assembly_accession="GCF_BETA_ALT",
            download_status="success",
            normalize_status="success",
            translate_status="success",
            detect_status="success",
            finalize_status="success",
            terminal_status="completed",
            n_genomes=1,
            n_proteins=1,
            n_repeat_calls=2,
        )

        response = self.client.get(
            reverse("browser:accessionstatus-list"),
            {
                "run": "run-alpha",
                "batch": str(extra_batch.pk),
                "terminal_status": "failed",
                "page": "2",
                "fragment": "virtual-scroll",
                "download": "tsv",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="homorepeat_accession_status.tsv"')
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn(
            "Run\tBatch\tAccession\tDownload status\tNormalize status\tTranslate status",
            body,
        )
        self.assertIn("GCF_ALPHA_ALT", body)
        self.assertIn("missing translated sequence", body)
        self.assertNotIn("GCF_BETA_ALT", body)

    def test_accession_call_count_list_filters_by_run_batch_method_and_residue(self):
        pipeline_run = self.alpha["pipeline_run"]
        extra_batch = AcquisitionBatch.objects.create(
            pipeline_run=pipeline_run,
            batch_id="batch_0002",
        )
        AccessionCallCount.objects.create(
            pipeline_run=pipeline_run,
            batch=extra_batch,
            assembly_accession="GCF_ALPHA_ALT",
            method=RunParameter.Method.THRESHOLD,
            repeat_residue="A",
            detect_status="failed",
            finalize_status="skipped",
            n_repeat_calls=0,
        )
        AccessionCallCount.objects.create(
            pipeline_run=self.beta["pipeline_run"],
            batch=self.beta["batch"],
            assembly_accession="GCF_BETA_ALT",
            method=RunParameter.Method.SEED_EXTEND,
            repeat_residue="Q",
            detect_status="success",
            finalize_status="success",
            n_repeat_calls=3,
        )

        response = self.client.get(
            reverse("browser:accessioncallcount-list"),
            {
                "run": "run-alpha",
                "batch": str(extra_batch.pk),
                "method": RunParameter.Method.THRESHOLD,
                "residue": "A",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GCF_ALPHA_ALT")
        self.assertContains(response, "threshold")
        self.assertContains(response, "A")
        self.assertNotContains(response, "seed_extend")
        self.assertNotContains(response, "GCF_BETA_ALT")

    def test_accession_call_count_list_tsv_export_honors_filters_and_full_queryset(self):
        pipeline_run = self.alpha["pipeline_run"]
        extra_batch = AcquisitionBatch.objects.create(
            pipeline_run=pipeline_run,
            batch_id="batch_0002",
        )
        AccessionCallCount.objects.create(
            pipeline_run=pipeline_run,
            batch=extra_batch,
            assembly_accession="GCF_ALPHA_ALT",
            method=RunParameter.Method.THRESHOLD,
            repeat_residue="A",
            detect_status="failed",
            finalize_status="skipped",
            n_repeat_calls=0,
        )
        AccessionCallCount.objects.create(
            pipeline_run=self.beta["pipeline_run"],
            batch=self.beta["batch"],
            assembly_accession="GCF_BETA_ALT",
            method=RunParameter.Method.SEED_EXTEND,
            repeat_residue="Q",
            detect_status="success",
            finalize_status="success",
            n_repeat_calls=3,
        )

        response = self.client.get(
            reverse("browser:accessioncallcount-list"),
            {
                "run": "run-alpha",
                "batch": str(extra_batch.pk),
                "method": RunParameter.Method.THRESHOLD,
                "residue": "A",
                "page": "2",
                "fragment": "virtual-scroll",
                "download": "tsv",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="homorepeat_accession_call_counts.tsv"',
        )
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn(
            "Run\tBatch\tAccession\tMethod\tResidue\tDetect status\tFinalize status\tRepeat calls",
            body,
        )
        self.assertIn("GCF_ALPHA_ALT", body)
        self.assertIn("threshold", body)
        self.assertNotIn("GCF_BETA_ALT", body)

    def test_download_manifest_list_filters_by_run_batch_and_status(self):
        pipeline_run = self.alpha["pipeline_run"]
        extra_batch = AcquisitionBatch.objects.create(
            pipeline_run=pipeline_run,
            batch_id="batch_0002",
        )
        DownloadManifestEntry.objects.create(
            pipeline_run=pipeline_run,
            batch=extra_batch,
            assembly_accession="GCF_ALPHA_ALT",
            download_status="rehydrated",
            package_mode="direct_zip",
            download_path="/tmp/download_alpha_alt.zip",
            rehydrated_path="/tmp/rehydrated_alpha_alt",
            checksum="checksum-alpha-alt",
            file_size_bytes=123456,
            notes="rehydrated replacement",
        )
        DownloadManifestEntry.objects.create(
            pipeline_run=self.beta["pipeline_run"],
            batch=self.beta["batch"],
            assembly_accession="GCF_BETA_ALT",
            download_status="downloaded",
            package_mode="prefetched",
            checksum="checksum-beta-alt",
            file_size_bytes=999,
        )

        response = self.client.get(
            reverse("browser:downloadmanifest-list"),
            {
                "run": "run-alpha",
                "batch": str(extra_batch.pk),
                "download_status": "rehydrated",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GCF_ALPHA_ALT")
        self.assertContains(response, "rehydrated")
        self.assertContains(response, "checksum-alpha-alt")
        self.assertContains(response, "/tmp/rehydrated_alpha_alt")
        self.assertNotContains(response, "prefetched")
        self.assertNotContains(response, "GCF_BETA_ALT")

    def test_download_manifest_list_tsv_export_honors_filters_and_full_queryset(self):
        pipeline_run = self.alpha["pipeline_run"]
        extra_batch = AcquisitionBatch.objects.create(
            pipeline_run=pipeline_run,
            batch_id="batch_0002",
        )
        DownloadManifestEntry.objects.create(
            pipeline_run=pipeline_run,
            batch=extra_batch,
            assembly_accession="GCF_ALPHA_ALT",
            download_status="rehydrated",
            package_mode="direct_zip",
            download_path="/tmp/download_alpha_alt.zip",
            rehydrated_path="/tmp/rehydrated_alpha_alt",
            checksum="checksum-alpha-alt",
            file_size_bytes=123456,
            notes="rehydrated replacement",
        )
        DownloadManifestEntry.objects.create(
            pipeline_run=self.beta["pipeline_run"],
            batch=self.beta["batch"],
            assembly_accession="GCF_BETA_ALT",
            download_status="downloaded",
            package_mode="prefetched",
            checksum="checksum-beta-alt",
            file_size_bytes=999,
        )

        response = self.client.get(
            reverse("browser:downloadmanifest-list"),
            {
                "run": "run-alpha",
                "batch": str(extra_batch.pk),
                "download_status": "rehydrated",
                "page": "2",
                "fragment": "virtual-scroll",
                "download": "tsv",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="homorepeat_download_manifest.tsv"')
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn(
            "Run\tBatch\tAccession\tDownload status\tPackage mode\tFile size bytes\tChecksum",
            body,
        )
        self.assertIn("GCF_ALPHA_ALT", body)
        self.assertIn("checksum-alpha-alt", body)
        self.assertIn("/tmp/rehydrated_alpha_alt", body)
        self.assertNotIn("GCF_BETA_ALT", body)

    def test_normalization_warning_list_filters_by_run_batch_and_accession(self):
        pipeline_run = self.alpha["pipeline_run"]
        extra_batch = AcquisitionBatch.objects.create(
            pipeline_run=pipeline_run,
            batch_id="batch_0002",
        )
        NormalizationWarning.objects.create(
            pipeline_run=pipeline_run,
            batch=self.alpha["batch"],
            warning_code="partial_cds",
            warning_scope="sequence",
            warning_message="Alpha batch one warning",
            assembly_accession="GCF_ALPHA",
            genome_id=self.alpha["genome"].genome_id,
            sequence_id=self.alpha["sequence"].sequence_id,
            source_record_id="alpha-1",
        )
        NormalizationWarning.objects.create(
            pipeline_run=pipeline_run,
            batch=extra_batch,
            warning_code="missing_translation",
            warning_scope="protein",
            warning_message="Alpha batch two warning",
            assembly_accession="GCF_ALPHA_ALT",
            protein_id="prot_alpha_alt",
            source_record_id="alpha-2",
        )
        NormalizationWarning.objects.create(
            pipeline_run=self.beta["pipeline_run"],
            batch=self.beta["batch"],
            warning_code="partial_cds",
            warning_scope="sequence",
            warning_message="Beta warning",
            assembly_accession="GCF_BETA",
            genome_id=self.beta["genome"].genome_id,
            source_record_id="beta-1",
        )

        response = self.client.get(
            reverse("browser:normalizationwarning-list"),
            {
                "run": "run-alpha",
                "batch": str(extra_batch.pk),
                "accession": "GCF_ALPHA_ALT",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alpha batch two warning")
        self.assertContains(response, "missing_translation")
        self.assertContains(response, "batch_0002")
        self.assertNotContains(response, "Alpha batch one warning")
        self.assertNotContains(response, "Beta warning")

    def test_normalization_warning_list_tsv_export_honors_filters_and_full_queryset(self):
        pipeline_run = self.alpha["pipeline_run"]
        extra_batch = AcquisitionBatch.objects.create(
            pipeline_run=pipeline_run,
            batch_id="batch_0002",
        )
        NormalizationWarning.objects.create(
            pipeline_run=pipeline_run,
            batch=self.alpha["batch"],
            warning_code="partial_cds",
            warning_scope="sequence",
            warning_message="Alpha batch one warning",
            assembly_accession="GCF_ALPHA",
            genome_id=self.alpha["genome"].genome_id,
            sequence_id=self.alpha["sequence"].sequence_id,
            source_record_id="alpha-1",
        )
        NormalizationWarning.objects.create(
            pipeline_run=pipeline_run,
            batch=extra_batch,
            warning_code="missing_translation",
            warning_scope="protein",
            warning_message="Alpha batch two warning",
            assembly_accession="GCF_ALPHA_ALT",
            protein_id="prot_alpha_alt",
            source_record_id="alpha-2",
        )
        NormalizationWarning.objects.create(
            pipeline_run=self.beta["pipeline_run"],
            batch=self.beta["batch"],
            warning_code="partial_cds",
            warning_scope="sequence",
            warning_message="Beta warning",
            assembly_accession="GCF_BETA",
            genome_id=self.beta["genome"].genome_id,
            source_record_id="beta-1",
        )

        response = self.client.get(
            reverse("browser:normalizationwarning-list"),
            {
                "run": "run-alpha",
                "batch": str(extra_batch.pk),
                "accession": "GCF_ALPHA_ALT",
                "page": "2",
                "fragment": "virtual-scroll",
                "download": "tsv",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="homorepeat_normalization_warnings.tsv"',
        )
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn(
            "Run\tBatch\tWarning code\tWarning scope\tMessage\tAccession",
            body,
        )
        self.assertIn("Alpha batch two warning", body)
        self.assertIn("missing_translation", body)
        self.assertNotIn("Alpha batch one warning", body)
        self.assertNotIn("Beta warning", body)

    def test_operational_list_download_links_preserve_filters(self):
        cases = [
            (
                reverse("browser:normalizationwarning-list"),
                {
                    "run": "run-alpha",
                    "batch": str(self.alpha["batch"].pk),
                    "accession": "GCF_ALPHA",
                    "warning_code": "partial_cds",
                    "order_by": "accession",
                    "page": "1",
                    "fragment": "virtual-scroll",
                },
                (
                    f'?run=run-alpha&amp;batch={self.alpha["batch"].pk}&amp;accession=GCF_ALPHA'
                    "&amp;warning_code=partial_cds&amp;order_by=accession&amp;download=tsv"
                ),
            ),
            (
                reverse("browser:accessionstatus-list"),
                {
                    "run": "run-alpha",
                    "batch": str(self.alpha["batch"].pk),
                    "terminal_status": "completed",
                    "detect_status": "success",
                    "order_by": "repeat_calls",
                    "page": "1",
                    "fragment": "virtual-scroll",
                },
                (
                    f'?run=run-alpha&amp;batch={self.alpha["batch"].pk}&amp;terminal_status=completed'
                    "&amp;detect_status=success&amp;order_by=repeat_calls&amp;download=tsv"
                ),
            ),
            (
                reverse("browser:accessioncallcount-list"),
                {
                    "run": "run-alpha",
                    "batch": str(self.alpha["batch"].pk),
                    "method": RunParameter.Method.PURE,
                    "residue": "Q",
                    "order_by": "method",
                    "page": "1",
                    "fragment": "virtual-scroll",
                },
                (
                    f'?run=run-alpha&amp;batch={self.alpha["batch"].pk}&amp;method=pure'
                    "&amp;residue=Q&amp;order_by=method&amp;download=tsv"
                ),
            ),
            (
                reverse("browser:downloadmanifest-list"),
                {
                    "run": "run-alpha",
                    "batch": str(self.alpha["batch"].pk),
                    "download_status": "downloaded",
                    "package_mode": "ncbi_dataset",
                    "order_by": "checksum",
                    "page": "1",
                    "fragment": "virtual-scroll",
                },
                (
                    f'?run=run-alpha&amp;batch={self.alpha["batch"].pk}&amp;download_status=downloaded'
                    "&amp;package_mode=ncbi_dataset&amp;order_by=checksum&amp;download=tsv"
                ),
            ),
        ]

        for url, params, expected_query in cases:
            with self.subTest(url=url):
                response = self.client.get(url, params)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'href="{url}{expected_query}"')
                self.assertNotContains(response, "page=1&amp;download=tsv")
                self.assertNotContains(response, "fragment=virtual-scroll&amp;download=tsv")

    def test_accession_list_links_summary_counts_to_filtered_related_views(self):
        response = self.client.get(reverse("browser:accession-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f"{reverse('browser:repeatcall-list')}?run=run-alpha&amp;genome=genome_alpha",
        )
        self.assertContains(
            response,
            f"{reverse('browser:protein-list')}?run=run-alpha&amp;genome=genome_alpha",
        )
        self.assertContains(response, "Current canonical state")

    def test_sort_headers_render_across_browser_lists(self):
        cases = [
            (reverse("browser:run-list"), {}),
            (reverse("browser:normalizationwarning-list"), {}),
            (reverse("browser:accessionstatus-list"), {}),
            (reverse("browser:accessioncallcount-list"), {}),
            (reverse("browser:downloadmanifest-list"), {}),
            (reverse("browser:taxon-list"), {}),
            (reverse("browser:genome-list"), {}),
            (reverse("browser:sequence-list"), {}),
            (reverse("browser:protein-list"), {}),
            (reverse("browser:repeatcall-list"), {}),
            (reverse("browser:accession-list"), {}),
        ]

        for url, params in cases:
            with self.subTest(url=url, params=params):
                response = self.client.get(url, params)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "sortable-header-link")
                self.assertNotContains(response, "id_order_by")

    def test_primary_browser_tables_render_sort_links_for_previously_plain_headers(self):
        cases = [
            (
                reverse("browser:run-list"),
                {},
                [
                    "order_by=-status",
                    "order_by=-profile",
                    "order_by=-genomes",
                    "order_by=-sequences",
                    "order_by=-proteins",
                    "order_by=-repeat_calls",
                ],
            ),
            (
                reverse("browser:normalizationwarning-list"),
                {},
                [
                    "order_by=-genome",
                    "order_by=-sequence",
                    "order_by=-protein",
                    "order_by=-message",
                ],
            ),
            (
                reverse("browser:accessionstatus-list"),
                {},
                [
                    "order_by=-download_status",
                    "order_by=-normalize_status",
                    "order_by=-translate_status",
                    "order_by=-detect_status",
                    "order_by=-finalize_status",
                ],
            ),
            (
                reverse("browser:accessioncallcount-list"),
                {},
                [
                    "order_by=-detect_status",
                    "order_by=-finalize_status",
                ],
            ),
            (
                reverse("browser:downloadmanifest-list"),
                {},
                [
                    "order_by=-checksum",
                    "order_by=-paths",
                ],
            ),
            (
                reverse("browser:taxon-list"),
                {},
                [
                    "order_by=-parent",
                ],
            ),
            (
                reverse("browser:genome-list"),
                {},
                [
                    "order_by=-taxon",
                    "order_by=-sequences",
                    "order_by=-repeat_calls",
                ],
            ),
            (
                reverse("browser:sequence-list"),
                {},
                [
                    "order_by=-genome",
                    "order_by=-taxon",
                ],
            ),
            (
                reverse("browser:protein-list"),
                {},
                [
                    "order_by=-accession",
                    "order_by=-taxon",
                ],
            ),
            (
                reverse("browser:accession-list"),
                {},
                [
                    "order_by=-calls",
                    "order_by=-proteins",
                    "order_by=-analyzed_proteins",
                ],
            ),
        ]

        for url, params, expected_links in cases:
            with self.subTest(url=url, params=params):
                response = self.client.get(url, params)
                self.assertEqual(response.status_code, 200)
                for expected_link in expected_links:
                    self.assertContains(response, expected_link)

    def test_run_list_sort_header_cycles_desc_asc_clear(self):
        url = reverse("browser:run-list")

        default_response = self.client.get(url, {"q": "run"})
        self.assertEqual(default_response.status_code, 200)
        self.assertContains(default_response, f'href="{url}?q=run&amp;order_by=-run_id"')
        self.assertContains(default_response, 'data-sort-state="none"')

        descending_response = self.client.get(url, {"q": "run", "order_by": "-run_id"})
        self.assertEqual(descending_response.status_code, 200)
        self.assertContains(descending_response, f'href="{url}?q=run&amp;order_by=run_id"')
        self.assertContains(descending_response, 'data-sort-state="desc"')

        ascending_response = self.client.get(url, {"q": "run", "order_by": "run_id"})
        self.assertEqual(ascending_response.status_code, 200)
        self.assertContains(ascending_response, f'href="{url}?q=run"')
        self.assertContains(ascending_response, 'data-sort-state="asc"')

    def test_virtual_scroll_hooks_render_across_browser_lists(self):
        cases = [
            (reverse("browser:run-list"), {}),
            (reverse("browser:normalizationwarning-list"), {}),
            (reverse("browser:accessionstatus-list"), {}),
            (reverse("browser:accessioncallcount-list"), {}),
            (reverse("browser:downloadmanifest-list"), {}),
            (reverse("browser:taxon-list"), {}),
            (reverse("browser:genome-list"), {}),
            (reverse("browser:sequence-list"), {}),
            (reverse("browser:protein-list"), {}),
            (reverse("browser:repeatcall-list"), {}),
            (reverse("browser:accession-list"), {}),
        ]

        for url, params in cases:
            with self.subTest(url=url):
                response = self.client.get(url, params)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "data-virtual-scroll-root")
                self.assertContains(response, "data-virtual-scroll-body")

    def test_run_list_virtual_scroll_fragment_returns_rows(self):
        response = self.client.get(
            reverse("browser:run-list"),
            {"fragment": "virtual-scroll"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("rows_html", payload)
        self.assertIn("run-alpha", payload["rows_html"])
        self.assertEqual(payload["count"], 2)

    def test_run_list_tsv_export_uses_full_filtered_queryset(self):
        response = self.client.get(
            reverse("browser:run-list"),
            {
                "q": "run",
                "order_by": "run_id",
                "page": "1",
                "fragment": "virtual-scroll",
                "download": "tsv",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/tab-separated-values; charset=utf-8")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="homorepeat_runs.tsv"')

        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("Run\tStatus\tProfile\tImported genomes", body)
        self.assertIn("run-alpha", body)
        self.assertIn("run-beta", body)
        self.assertLess(body.index("run-alpha"), body.index("run-beta"))

    def test_run_list_tsv_export_honors_search_filter(self):
        response = self.client.get(
            reverse("browser:run-list"),
            {
                "q": "run-alpha",
                "download": "tsv",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("run-alpha", body)
        self.assertNotIn("run-beta", body)

    def test_run_list_tsv_export_honors_status_filter(self):
        beta_run = self.beta["pipeline_run"]
        beta_run.status = "failed"
        beta_run.save(update_fields=["status"])

        response = self.client.get(
            reverse("browser:run-list"),
            {
                "status": "success",
                "download": "tsv",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("run-alpha", body)
        self.assertNotIn("run-beta", body)

    def test_run_list_renders_tsv_download_link_with_filters(self):
        url = reverse("browser:run-list")
        response = self.client.get(
            url,
            {
                "q": "run",
                "status": "success",
                "order_by": "run_id",
                "page": "1",
                "fragment": "virtual-scroll",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{url}?q=run&amp;status=success&amp;order_by=run_id&amp;download=tsv"',
        )
        self.assertNotContains(response, "page=1&amp;download=tsv")
        self.assertNotContains(response, "fragment=virtual-scroll&amp;download=tsv")

    def test_accession_list_virtual_scroll_fragment_returns_rows(self):
        response = self.client.get(
            reverse("browser:accession-list"),
            {"fragment": "virtual-scroll"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("rows_html", payload)
        self.assertIn("GCF_ALPHA", payload["rows_html"])
        self.assertEqual(payload["count"], 2)

    def test_accession_list_tsv_export_honors_search_filter(self):
        response = self.client.get(
            reverse("browser:accession-list"),
            {
                "q": "GCF_ALPHA",
                "download": "tsv",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="homorepeat_accessions.tsv"')
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("Accession\tLatest genome id\tLatest run\tImported observations", body)
        self.assertIn("GCF_ALPHA", body)
        self.assertNotIn("GCF_BETA", body)

    def test_genome_list_tsv_export_honors_accession_filter(self):
        response = self.client.get(
            reverse("browser:genome-list"),
            {
                "accession": "GCF_ALPHA",
                "download": "tsv",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="homorepeat_genomes.tsv"')
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("Accession\tGenome id\tGenome\tTaxon id\tTaxon\tLatest run", body)
        self.assertIn("GCF_ALPHA", body)
        self.assertIn("Human reference genome", body)
        self.assertNotIn("GCF_BETA", body)

    def test_sequence_list_tsv_export_uses_full_filtered_queryset(self):
        response = self.client.get(
            reverse("browser:sequence-list"),
            {
                "run": "run-alpha",
                "fragment": "virtual-scroll",
                "download": "tsv",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="homorepeat_sequences.tsv"')
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("Sequence id\tSequence\tGene\tGenome accession", body)
        self.assertIn("seq_alpha", body)
        self.assertIn("NM_run-alpha", body)
        self.assertNotIn("seq_beta", body)

    def test_catalog_list_download_links_preserve_filters(self):
        cases = [
            (
                reverse("browser:accession-list"),
                {"q": "GCF", "order_by": "accession", "page": "1", "fragment": "virtual-scroll"},
                "?q=GCF&amp;order_by=accession&amp;download=tsv",
            ),
            (
                reverse("browser:genome-list"),
                {"accession": "GCF_ALPHA", "order_by": "genome_name", "page": "1"},
                "?accession=GCF_ALPHA&amp;order_by=genome_name&amp;download=tsv",
            ),
            (
                reverse("browser:sequence-list"),
                {"run": "run-alpha", "genome": "genome_alpha", "page": "1", "fragment": "virtual-scroll"},
                "?run=run-alpha&amp;genome=genome_alpha&amp;download=tsv",
            ),
        ]

        for url, params, expected_query in cases:
            with self.subTest(url=url):
                response = self.client.get(url, params)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'href="{url}{expected_query}"')
                self.assertNotContains(response, "page=1&amp;download=tsv")
                self.assertNotContains(response, "fragment=virtual-scroll&amp;download=tsv")

    def test_branch_filter_forms_use_branch_q_text_input_across_hot_pages(self):
        urls = [
            reverse("browser:taxon-list"),
            reverse("browser:genome-list"),
            reverse("browser:sequence-list"),
            reverse("browser:accession-list"),
            reverse("browser:protein-list"),
            reverse("browser:repeatcall-list"),
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'name="branch_q"')
                self.assertContains(response, "Taxonomy ID or name prefix")
                self.assertNotContains(response, 'name="branch"')

    def test_taxon_list_run_filter_keeps_ancestor_path(self):
        response = self.client.get(reverse("browser:taxon-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Homo sapiens")
        self.assertContains(response, "Primates")
        self.assertNotContains(response, "Mus musculus")

    def test_taxon_list_branch_filter_includes_descendants(self):
        response = self.client.get(reverse("browser:taxon-list"), {"branch": str(self.mammalia.pk)})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mammalia")
        self.assertContains(response, "Primates")
        self.assertContains(response, "Homo sapiens")
        self.assertContains(response, "Mus musculus")

    def test_taxon_list_branch_q_name_prefix_filter_includes_descendants(self):
        response = self.client.get(reverse("browser:taxon-list"), {"branch_q": "Mam"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].paginator.count, 4)
        self.assertContains(response, "Mammalia")
        self.assertContains(response, "Primates")
        self.assertContains(response, "Homo sapiens")
        self.assertContains(response, "Mus musculus")

    def test_taxon_list_tsv_export_uses_full_filtered_queryset_and_remains_distinct(self):
        response = self.client.get(
            reverse("browser:taxon-list"),
            {
                "run": "run-alpha",
                "order_by": "taxon_id",
                "page": "2",
                "fragment": "virtual-scroll",
                "download": "tsv",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="homorepeat_taxa.tsv"')
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("Taxon id\tTaxon\tRank\tParent taxon id\tParent taxon", body)

        rows = [line.split("\t") for line in body.strip().splitlines()[1:]]
        exported_ids = [row[0] for row in rows]

        self.assertEqual(set(exported_ids), {"1", "7711", "9443", "9606", "40674"})
        self.assertEqual(len(exported_ids), 5)
        self.assertEqual(len(set(exported_ids)), 5)

    def test_taxon_list_renders_tsv_download_link_with_filters(self):
        url = reverse("browser:taxon-list")
        response = self.client.get(
            url,
            {
                "q": "Mam",
                "run": "run-alpha",
                "branch_q": "Mam",
                "rank": "class",
                "order_by": "taxon_id",
                "page": "1",
                "fragment": "virtual-scroll",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            (
                f'href="{url}?q=Mam&amp;run=run-alpha&amp;branch_q=Mam&amp;rank=class'
                '&amp;order_by=taxon_id&amp;download=tsv"'
            ),
        )
        self.assertNotContains(response, "page=1&amp;download=tsv")
        self.assertNotContains(response, "fragment=virtual-scroll&amp;download=tsv")

    def test_taxon_detail_shows_lineage_and_branch_genomes(self):
        response = self.client.get(
            reverse("browser:taxon-detail", args=[self.alpha["taxon"].pk]),
            {"run": "run-alpha"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Homo sapiens")
        self.assertContains(response, "Primates")
        self.assertContains(response, "Chordata")
        self.assertContains(response, "GCF_ALPHA")
        self.assertNotContains(response, "GCF_BETA")
        self.assertContains(response, "Explore branch lengths")
        self.assertContains(response, "Explore branch codon ratios")
        self.assertContains(response, "Open branch accessions")

        length_query = parse_qs(urlparse(response.context["length_branch_url"]).query)
        self.assertEqual(length_query["run"], ["run-alpha"])
        self.assertEqual(length_query["branch"], [str(self.alpha["taxon"].pk)])
        codon_query = parse_qs(urlparse(response.context["codon_ratio_branch_url"]).query)
        self.assertEqual(codon_query["run"], ["run-alpha"])
        self.assertEqual(codon_query["branch"], [str(self.alpha["taxon"].pk)])

    def test_taxon_detail_length_handoff_omits_run_when_unscoped(self):
        response = self.client.get(reverse("browser:taxon-detail", args=[self.alpha["taxon"].pk]))

        self.assertEqual(response.status_code, 200)
        length_query = parse_qs(urlparse(response.context["length_branch_url"]).query)
        self.assertEqual(length_query["branch"], [str(self.alpha["taxon"].pk)])
        self.assertNotIn("run", length_query)
        codon_query = parse_qs(urlparse(response.context["codon_ratio_branch_url"]).query)
        self.assertEqual(codon_query["branch"], [str(self.alpha["taxon"].pk)])
        self.assertNotIn("run", codon_query)

    def test_genome_list_branch_filter_includes_descendant_taxa(self):
        response = self.client.get(reverse("browser:genome-list"), {"branch": str(self.mammalia.pk)})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GCF_ALPHA")
        self.assertContains(response, "GCF_BETA")

    def test_genome_list_branch_q_numeric_taxon_id_filters_descendants(self):
        response = self.client.get(reverse("browser:genome-list"), {"branch_q": str(self.mammalia.taxon_id)})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GCF_ALPHA")
        self.assertContains(response, "GCF_BETA")

    def test_genome_list_accession_filter_works(self):
        response = self.client.get(reverse("browser:genome-list"), {"accession": "GCF_ALPHA"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GCF_ALPHA")
        self.assertNotContains(response, "GCF_BETA")

    def test_genome_detail_shows_run_provenance_and_related_records(self):
        response = self.client.get(reverse("browser:genome-detail", args=[self.alpha["genome"].pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GCF_ALPHA")
        self.assertContains(response, "run-alpha")
        self.assertContains(response, "NP_run-alpha")
        self.assertContains(response, "call_alpha")
        self.assertContains(response, "Protein browser")
        self.assertContains(response, "Open sequences")
        self.assertNotContains(response, "Open run")

    def test_accession_detail_links_to_source_proteins_and_repeat_calls(self):
        response = self.client.get(reverse("browser:accession-detail", args=["GCF_ALPHA"]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Open current proteins")
        self.assertContains(response, f"{reverse('browser:protein-list')}?run=run-alpha&amp;genome=genome_alpha")
        self.assertContains(
            response,
            f"{reverse('browser:repeatcall-list')}?run=run-alpha&amp;genome=genome_alpha",
        )

    def test_sequence_list_run_filter_scopes_results(self):
        response = self.client.get(reverse("browser:sequence-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NM_run-alpha")
        self.assertNotContains(response, "NM_run-beta")
        self.assertContains(response, reverse("browser:sequence-detail", args=[self.alpha["sequence"].pk]))

    def test_sequence_list_default_ordering_matches_optimize_contract(self):
        self.assertEqual(
            SequenceListView.default_ordering,
            ("latest_pipeline_run_id", "assembly_accession", "sequence_name", "id"),
        )

    def test_sequence_list_keeps_raw_rows_narrow(self):
        response = self.client.get(reverse("browser:sequence-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        sequence = response.context["page_obj"].object_list[0]
        self.assertIn("nucleotide_sequence", sequence.get_deferred_fields())
        self.assertIn("latest_pipeline_run", sequence._state.fields_cache)
        self.assertIn("taxon", sequence._state.fields_cache)
        self.assertNotIn("genome", sequence._state.fields_cache)

    def test_sequence_list_uses_local_ids_and_denormalized_fields_for_links(self):
        response = self.client.get(reverse("browser:sequence-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("browser:genome-detail", args=[self.alpha["genome"].pk]))
        self.assertContains(response, reverse("browser:run-detail", args=[self.alpha["pipeline_run"].pk]))
        self.assertContains(
            response,
            f'{reverse("browser:taxon-detail", args=[self.alpha["taxon"].pk])}?run={self.alpha["pipeline_run"].run_id}',
        )
        self.assertContains(response, self.alpha["sequence"].assembly_accession)

    def test_sequence_list_uses_cursor_pagination_for_default_raw_order(self):
        for index in range(25):
            self._create_repeat_call(
                self.alpha,
                suffix=f"cursor_sequence_{index:02d}",
                gene_symbol=f"SEQCURSOR{index:02d}",
                method=RepeatCall.Method.THRESHOLD,
                residue="A",
                length=8,
                purity=0.75,
            )

        response = self.client.get(reverse("browser:sequence-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        first_page = response.context["page_obj"]
        first_ids = [sequence.sequence_id for sequence in first_page.object_list]
        self.assertTrue(first_page.cursor_pagination)
        self.assertTrue(first_page.has_next())
        self.assertIn("after=", first_page.next_query)
        self.assertNotIn("page=", first_page.next_query)

        next_response = self.client.get(f"{reverse('browser:sequence-list')}?{first_page.next_query}")

        self.assertEqual(next_response.status_code, 200)
        second_page = next_response.context["page_obj"]
        second_ids = [sequence.sequence_id for sequence in second_page.object_list]
        self.assertTrue(second_page.has_previous())
        self.assertIn("before=", second_page.previous_query)
        self.assertTrue(set(first_ids).isdisjoint(second_ids))

    def test_sequence_list_alternate_sort_falls_back_to_page_pagination(self):
        for index in range(25):
            self._create_repeat_call(
                self.alpha,
                suffix=f"page_sequence_{index:02d}",
                gene_symbol=f"SEQPAGE{index:02d}",
                method=RepeatCall.Method.THRESHOLD,
                residue="A",
                length=8,
                purity=0.75,
            )

        response = self.client.get(
            reverse("browser:sequence-list"),
            {"run": "run-alpha", "order_by": "gene_symbol"},
        )

        self.assertEqual(response.status_code, 200)
        first_page = response.context["page_obj"]
        self.assertFalse(getattr(first_page, "cursor_pagination", False))
        self.assertTrue(first_page.has_next())
        self.assertIn("page=2", response.context["virtual_scroll_next_query"])
        self.assertIn("order_by=gene_symbol", response.context["virtual_scroll_next_query"])
        self.assertNotIn("after=", response.context["virtual_scroll_next_query"])

        next_response = self.client.get(
            f"{reverse('browser:sequence-list')}?{response.context['virtual_scroll_next_query']}"
        )

        self.assertEqual(next_response.status_code, 200)
        second_page = next_response.context["page_obj"]
        self.assertFalse(getattr(second_page, "cursor_pagination", False))
        self.assertEqual(second_page.number, 2)

    def test_sequence_detail_shows_linked_records_and_navigation(self):
        response = self.client.get(reverse("browser:sequence-detail", args=[self.alpha["sequence"].pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NM_run-alpha")
        self.assertContains(response, "run-alpha")
        self.assertContains(response, "NP_run-alpha")
        self.assertContains(response, "call_alpha")
        self.assertContains(response, reverse("browser:protein-list"))
        self.assertContains(response, reverse("browser:repeatcall-list"))
        self.assertNotContains(response, "Open run")

    def test_protein_list_run_filter_scopes_results(self):
        response = self.client.get(reverse("browser:protein-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NP_run-alpha")
        self.assertNotContains(response, "NP_run-beta")

    def test_protein_list_default_ordering_matches_optimize_contract(self):
        self.assertEqual(
            ProteinListView.default_ordering,
            ("latest_pipeline_run_id", "accession", "protein_name", "id"),
        )

    def test_protein_list_run_filter_uses_run_metadata_facets(self):
        self.alpha["pipeline_run"].browser_metadata = self._browser_metadata(
            methods=[RunParameter.Method.THRESHOLD],
            residues=["A"],
        )
        self.alpha["pipeline_run"].save(update_fields=["browser_metadata"])
        self.beta["pipeline_run"].browser_metadata = self._browser_metadata(
            methods=[RunParameter.Method.SEED_EXTEND],
            residues=["N"],
        )
        self.beta["pipeline_run"].save(update_fields=["browser_metadata"])

        response = self.client.get(reverse("browser:protein-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["method_choices"], [RunParameter.Method.THRESHOLD])
        self.assertEqual(response.context["residue_choices"], ["A"])

    def test_protein_list_keeps_raw_rows_narrow(self):
        response = self.client.get(reverse("browser:protein-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        protein = response.context["page_obj"].object_list[0]
        self.assertIn("amino_acid_sequence", protein.get_deferred_fields())
        self.assertIn("latest_pipeline_run", protein._state.fields_cache)
        self.assertIn("taxon", protein._state.fields_cache)
        self.assertNotIn("genome", protein._state.fields_cache)

    def test_protein_list_uses_local_ids_and_denormalized_fields_for_links(self):
        response = self.client.get(reverse("browser:protein-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("browser:genome-detail", args=[self.alpha["genome"].pk]))
        self.assertContains(response, reverse("browser:run-detail", args=[self.alpha["pipeline_run"].pk]))
        self.assertContains(
            response,
            f'{reverse("browser:taxon-detail", args=[self.alpha["taxon"].pk])}?run={self.alpha["pipeline_run"].run_id}',
        )
        self.assertContains(response, self.alpha["protein"].accession)

    def test_protein_list_uses_cursor_pagination_for_raw_results(self):
        for index in range(25):
            self._create_repeat_call(
                self.alpha,
                suffix=f"cursor_protein_{index:02d}",
                gene_symbol=f"CURSOR{index:02d}",
                method=RepeatCall.Method.THRESHOLD,
                residue="A",
                length=8,
                purity=0.75,
            )

        response = self.client.get(reverse("browser:protein-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        first_page = response.context["page_obj"]
        first_names = [protein.protein_name for protein in first_page.object_list]
        self.assertTrue(first_page.cursor_pagination)
        self.assertTrue(first_page.has_next())
        self.assertIn("after=", first_page.next_query)
        self.assertNotIn("page=", first_page.next_query)

        next_response = self.client.get(f"{reverse('browser:protein-list')}?{first_page.next_query}")

        self.assertEqual(next_response.status_code, 200)
        second_page = next_response.context["page_obj"]
        second_names = [protein.protein_name for protein in second_page.object_list]
        self.assertTrue(second_page.has_previous())
        self.assertIn("before=", second_page.previous_query)
        self.assertTrue(set(first_names).isdisjoint(second_names))

    def test_protein_list_alternate_sort_falls_back_to_page_pagination(self):
        for index in range(25):
            self._create_repeat_call(
                self.alpha,
                suffix=f"page_protein_{index:02d}",
                gene_symbol=f"PROTPAGE{index:02d}",
                method=RepeatCall.Method.THRESHOLD,
                residue="A",
                length=8,
                purity=0.75,
            )

        response = self.client.get(
            reverse("browser:protein-list"),
            {"run": "run-alpha", "order_by": "gene_symbol"},
        )

        self.assertEqual(response.status_code, 200)
        first_page = response.context["page_obj"]
        self.assertFalse(getattr(first_page, "cursor_pagination", False))
        self.assertTrue(first_page.has_next())
        self.assertIn("page=2", response.context["virtual_scroll_next_query"])
        self.assertIn("order_by=gene_symbol", response.context["virtual_scroll_next_query"])
        self.assertNotIn("after=", response.context["virtual_scroll_next_query"])

        next_response = self.client.get(
            f"{reverse('browser:protein-list')}?{response.context['virtual_scroll_next_query']}"
        )

        self.assertEqual(next_response.status_code, 200)
        second_page = next_response.context["page_obj"]
        self.assertFalse(getattr(second_page, "cursor_pagination", False))
        self.assertEqual(second_page.number, 2)

    def test_protein_list_renders_virtual_scroll_hooks_for_raw_results(self):
        response = self.client.get(reverse("browser:protein-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-virtual-scroll-root")
        self.assertContains(response, "data-virtual-scroll-body")

    def test_protein_list_virtual_scroll_fragment_returns_rows(self):
        response = self.client.get(
            reverse("browser:protein-list"),
            {"run": "run-alpha", "fragment": "virtual-scroll"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("rows_html", payload)
        self.assertIn("NP_run-alpha", payload["rows_html"])
        self.assertEqual(payload["row_count"], 1)
        self.assertNotIn("count", payload)
        self.assertEqual(payload["next_query"], "")

    def test_protein_list_raw_virtual_scroll_fragment_skips_page_chrome_context(self):
        with patch(
            "apps.browser.views.resolve_browser_facets",
            side_effect=AssertionError("fragment request should not resolve facets"),
        ):
            response = self.client.get(
                reverse("browser:protein-list"),
                {"run": "run-alpha", "fragment": "virtual-scroll"},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("rows_html", payload)
        self.assertNotIn("count", payload)

    def test_protein_list_tsv_export_uses_full_filtered_queryset(self):
        matched = self._create_repeat_call(
            self.alpha,
            suffix="protein_tsv_match",
            gene_symbol="MATCHGENE",
            method=RepeatCall.Method.THRESHOLD,
            residue="A",
            length=9,
            purity=0.75,
        )
        split = self._create_repeat_call(
            self.alpha,
            suffix="protein_tsv_split_q",
            gene_symbol="SPLITGENE",
            method=RepeatCall.Method.THRESHOLD,
            residue="Q",
            length=9,
            purity=0.75,
        )
        self._create_repeat_call(
            self.alpha,
            suffix="protein_tsv_split_pure_a",
            gene_symbol="SPLITGENE",
            method=RepeatCall.Method.PURE,
            residue="A",
            length=9,
            purity=0.75,
            protein=split["protein"],
            sequence=split["sequence"],
        )

        response = self.client.get(
            reverse("browser:protein-list"),
            {
                "run": "run-alpha",
                "branch": str(self.mammalia.pk),
                "method": RepeatCall.Method.THRESHOLD,
                "residue": "A",
                "length_min": "8",
                "length_max": "10",
                "purity_min": "0.70",
                "purity_max": "0.80",
                "fragment": "virtual-scroll",
                "download": "tsv",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="homorepeat_proteins.tsv"')
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn(
            "Protein id\tProtein\tGene\tGenome accession\tTaxon id\tTaxon\tLatest run\tProtein length\tRepeat calls",
            body,
        )
        self.assertIn(matched["protein"].protein_id, body)
        self.assertIn(matched["protein"].protein_name, body)
        self.assertNotIn(split["protein"].protein_id, body)
        self.assertNotIn("prot_beta", body)

    def test_protein_list_renders_tsv_download_link_with_filters(self):
        url = reverse("browser:protein-list")
        response = self.client.get(
            url,
            {
                "run": "run-alpha",
                "genome": "genome_alpha",
                "method": RepeatCall.Method.THRESHOLD,
                "residue": "A",
                "order_by": "gene_symbol",
                "page": "1",
                "fragment": "virtual-scroll",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            (
                f'href="{url}?run=run-alpha&amp;genome=genome_alpha&amp;method=threshold'
                '&amp;residue=A&amp;order_by=gene_symbol&amp;download=tsv"'
            ),
        )
        self.assertNotContains(response, "page=1&amp;download=tsv")
        self.assertNotContains(response, "fragment=virtual-scroll&amp;download=tsv")

    def test_protein_list_combined_call_filters_match_same_linked_call(self):
        matched = self._create_repeat_call(
            self.alpha,
            suffix="match_threshold_a",
            gene_symbol="MATCHGENE",
            method=RepeatCall.Method.THRESHOLD,
            residue="A",
            length=9,
            purity=0.75,
        )
        split = self._create_repeat_call(
            self.alpha,
            suffix="split_threshold_q",
            gene_symbol="SPLITGENE",
            method=RepeatCall.Method.THRESHOLD,
            residue="Q",
            length=9,
            purity=0.75,
        )
        self._create_repeat_call(
            self.alpha,
            suffix="split_pure_a",
            gene_symbol="SPLITGENE",
            method=RepeatCall.Method.PURE,
            residue="A",
            length=9,
            purity=0.75,
            protein=split["protein"],
            sequence=split["sequence"],
        )

        response = self.client.get(
            reverse("browser:protein-list"),
            {
                "run": "run-alpha",
                "branch": str(self.mammalia.pk),
                "method": RepeatCall.Method.THRESHOLD,
                "residue": "A",
                "length_min": "8",
                "length_max": "10",
                "purity_min": "0.70",
                "purity_max": "0.80",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, matched["protein"].protein_name)
        self.assertNotContains(response, split["protein"].protein_name)
        self.assertNotContains(response, "NP_run-beta")

    def test_protein_detail_shows_call_summary_and_navigation(self):
        threshold = self._create_repeat_call(
            self.alpha,
            suffix="detail_threshold_a",
            gene_symbol="GENE1",
            method=RepeatCall.Method.THRESHOLD,
            residue="A",
            length=8,
            purity=0.75,
            protein=self.alpha["protein"],
            sequence=self.alpha["sequence"],
        )

        response = self.client.get(reverse("browser:protein-detail", args=[self.alpha["protein"].pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NP_run-alpha")
        self.assertContains(response, "By method and residue")
        self.assertContains(response, "call_alpha")
        self.assertContains(response, threshold["repeat_call"].call_id)
        self.assertContains(response, reverse("browser:genome-detail", args=[self.alpha["genome"].pk]))
        self.assertContains(response, "Stored protein sequence")
        self.assertContains(response, "Q" * 30)
        self.assertContains(response, "CAG" * 30)
        self.assertContains(response, "Compare branch lengths")
        self.assertContains(response, "Compare branch codon ratios")
        protein_length_query = parse_qs(urlparse(response.context["length_explorer_url"]).query)
        self.assertEqual(protein_length_query["run"], ["run-alpha"])
        self.assertEqual(protein_length_query["branch"], [str(self.alpha["taxon"].pk)])
        self.assertEqual(protein_length_query["q"], ["GENE1"])
        protein_codon_query = parse_qs(urlparse(response.context["codon_ratio_explorer_url"]).query)
        self.assertEqual(protein_codon_query["run"], ["run-alpha"])
        self.assertEqual(protein_codon_query["branch"], [str(self.alpha["taxon"].pk)])
        self.assertEqual(protein_codon_query["q"], ["GENE1"])
        self.assertNotContains(response, "Open run")

    def test_repeatcall_list_combined_filters_and_branch_scope_work(self):
        matched = self._create_repeat_call(
            self.alpha,
            suffix="call_filter_match",
            gene_symbol="FILTERGENE",
            method=RepeatCall.Method.THRESHOLD,
            residue="A",
            length=9,
            purity=0.78,
        )
        self._create_repeat_call(
            self.alpha,
            suffix="call_filter_low_purity",
            gene_symbol="FILTERGENE",
            method=RepeatCall.Method.THRESHOLD,
            residue="A",
            length=9,
            purity=0.40,
        )
        self._create_repeat_call(
            self.beta,
            suffix="call_filter_beta",
            gene_symbol="FILTERGENE",
            method=RepeatCall.Method.THRESHOLD,
            residue="A",
            length=9,
            purity=0.78,
            taxon=self.beta["taxon"],
        )

        response = self.client.get(
            reverse("browser:repeatcall-list"),
            {
                "run": "run-alpha",
                "branch": str(self.mammalia.pk),
                "method": RepeatCall.Method.THRESHOLD,
                "residue": "A",
                "gene_symbol": "FILTERGENE",
                "length_min": "8",
                "length_max": "10",
                "purity_min": "0.70",
                "purity_max": "0.80",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, matched["repeat_call"].call_id)
        self.assertNotContains(response, "call_call_filter_low_purity")
        self.assertNotContains(response, "call_call_filter_beta")

    def test_repeatcall_list_all_runs_use_union_of_metadata_facets(self):
        self.alpha["pipeline_run"].browser_metadata = self._browser_metadata(
            methods=[RunParameter.Method.THRESHOLD],
            residues=["A"],
        )
        self.alpha["pipeline_run"].save(update_fields=["browser_metadata"])
        self.beta["pipeline_run"].browser_metadata = self._browser_metadata(
            methods=[RunParameter.Method.SEED_EXTEND],
            residues=["N"],
        )
        self.beta["pipeline_run"].save(update_fields=["browser_metadata"])

        response = self.client.get(reverse("browser:repeatcall-list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["method_choices"],
            [RunParameter.Method.SEED_EXTEND, RunParameter.Method.THRESHOLD],
        )
        self.assertEqual(response.context["residue_choices"], ["A", "N"])

    def test_accession_list_branch_q_scopes_analytics_and_links(self):
        response = self.client.get(reverse("browser:accession-list"), {"branch_q": "Prim"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summary"]["accession_groups_count"], 1)
        self.assertContains(response, "GCF_ALPHA")
        self.assertNotContains(response, "GCF_BETA")
        self.assertContains(
            response,
            f'{reverse("browser:protein-list")}?run=run-alpha&amp;genome=genome_alpha&amp;branch_q=Prim',
        )

    def test_repeatcall_list_keeps_raw_rows_narrow(self):
        response = self.client.get(reverse("browser:repeatcall-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        repeat_call = response.context["page_obj"].object_list[0]
        self.assertIn("aa_sequence", repeat_call.get_deferred_fields())
        self.assertIn("codon_sequence", repeat_call.get_deferred_fields())
        self.assertIn("latest_pipeline_run", repeat_call._state.fields_cache)
        self.assertIn("taxon", repeat_call._state.fields_cache)
        self.assertNotIn("genome", repeat_call._state.fields_cache)
        self.assertNotIn("protein", repeat_call._state.fields_cache)

    def test_repeatcall_list_uses_local_ids_and_denormalized_fields_for_links(self):
        response = self.client.get(reverse("browser:repeatcall-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("browser:protein-detail", args=[self.alpha["protein"].pk]))
        self.assertContains(response, reverse("browser:genome-detail", args=[self.alpha["genome"].pk]))
        self.assertContains(response, reverse("browser:run-detail", args=[self.alpha["pipeline_run"].pk]))
        self.assertContains(
            response,
            f'{reverse("browser:taxon-detail", args=[self.alpha["taxon"].pk])}?run={self.alpha["pipeline_run"].run_id}',
        )
        self.assertContains(response, self.alpha["genome"].accession)
        self.assertContains(response, self.alpha["protein"].protein_name)

    def test_repeatcall_list_default_ordering_matches_optimize_contract(self):
        self.assertEqual(
            RepeatCallListView.default_ordering,
            ("latest_pipeline_run_id", "accession", "protein_name", "start", "id"),
        )

    def test_repeatcall_list_uses_cursor_pagination_for_raw_results(self):
        for index in range(25):
            self._create_repeat_call(
                self.alpha,
                suffix=f"cursor_call_{index:02d}",
                gene_symbol=f"CALLCURSOR{index:02d}",
                method=RepeatCall.Method.THRESHOLD,
                residue="A",
                length=9 + index,
                purity=0.80,
                start=100 + index,
            )

        response = self.client.get(reverse("browser:repeatcall-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        first_page = response.context["page_obj"]
        first_ids = [repeat_call.source_call_id for repeat_call in first_page.object_list]
        self.assertTrue(first_page.cursor_pagination)
        self.assertTrue(first_page.has_next())
        self.assertIn("after=", first_page.next_query)

        next_response = self.client.get(f"{reverse('browser:repeatcall-list')}?{first_page.next_query}")

        self.assertEqual(next_response.status_code, 200)
        second_page = next_response.context["page_obj"]
        second_ids = [repeat_call.source_call_id for repeat_call in second_page.object_list]
        self.assertTrue(second_page.has_previous())
        self.assertTrue(set(first_ids).isdisjoint(second_ids))

    def test_repeatcall_list_alternate_sort_falls_back_to_page_pagination(self):
        for index in range(25):
            self._create_repeat_call(
                self.alpha,
                suffix=f"page_call_{index:02d}",
                gene_symbol=f"CALLPAGE{index:02d}",
                method=RepeatCall.Method.THRESHOLD,
                residue="A",
                length=9 + index,
                purity=0.80,
                start=100 + index,
            )

        response = self.client.get(
            reverse("browser:repeatcall-list"),
            {"run": "run-alpha", "order_by": "gene_symbol"},
        )

        self.assertEqual(response.status_code, 200)
        first_page = response.context["page_obj"]
        self.assertFalse(getattr(first_page, "cursor_pagination", False))
        self.assertTrue(first_page.has_next())
        self.assertIn("page=2", response.context["virtual_scroll_next_query"])
        self.assertIn("order_by=gene_symbol", response.context["virtual_scroll_next_query"])
        self.assertNotIn("after=", response.context["virtual_scroll_next_query"])

        next_response = self.client.get(
            f"{reverse('browser:repeatcall-list')}?{response.context['virtual_scroll_next_query']}"
        )

        self.assertEqual(next_response.status_code, 200)
        second_page = next_response.context["page_obj"]
        self.assertFalse(getattr(second_page, "cursor_pagination", False))
        self.assertEqual(second_page.number, 2)

    def test_repeatcall_list_renders_virtual_scroll_hooks_for_raw_results(self):
        response = self.client.get(reverse("browser:repeatcall-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-virtual-scroll-root")
        self.assertContains(response, "data-virtual-scroll-body")

    def test_repeatcall_list_renders_sort_links_for_all_visible_headers(self):
        response = self.client.get(reverse("browser:repeatcall-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "order_by=-call_id")
        self.assertContains(response, "order_by=-protein_name")
        self.assertContains(response, "order_by=-gene_symbol")
        self.assertContains(response, "order_by=-genome")
        self.assertContains(response, "order_by=-taxon")
        self.assertContains(response, "order_by=-method")
        self.assertContains(response, "order_by=-residue")
        self.assertContains(response, "order_by=-length")
        self.assertContains(response, "order_by=-purity")
        self.assertContains(response, "order_by=-run")

    def test_repeatcall_list_virtual_scroll_fragment_returns_rows(self):
        response = self.client.get(
            reverse("browser:repeatcall-list"),
            {"run": "run-alpha", "fragment": "virtual-scroll"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("rows_html", payload)
        self.assertIn("call_alpha", payload["rows_html"])
        self.assertEqual(payload["row_count"], 1)
        self.assertNotIn("count", payload)
        self.assertEqual(payload["next_query"], "")

    def test_repeatcall_list_tsv_export_uses_full_filtered_queryset(self):
        matched = self._create_repeat_call(
            self.alpha,
            suffix="repeatcall_tsv_match",
            gene_symbol="FILTERGENE",
            method=RepeatCall.Method.THRESHOLD,
            residue="A",
            length=9,
            purity=0.78,
        )
        self._create_repeat_call(
            self.alpha,
            suffix="repeatcall_tsv_low_purity",
            gene_symbol="FILTERGENE",
            method=RepeatCall.Method.THRESHOLD,
            residue="A",
            length=9,
            purity=0.40,
        )
        self._create_repeat_call(
            self.beta,
            suffix="repeatcall_tsv_beta",
            gene_symbol="FILTERGENE",
            method=RepeatCall.Method.THRESHOLD,
            residue="A",
            length=9,
            purity=0.78,
            taxon=self.beta["taxon"],
        )

        response = self.client.get(
            reverse("browser:repeatcall-list"),
            {
                "run": "run-alpha",
                "branch": str(self.mammalia.pk),
                "method": RepeatCall.Method.THRESHOLD,
                "residue": "A",
                "gene_symbol": "FILTERGENE",
                "length_min": "8",
                "length_max": "10",
                "purity_min": "0.70",
                "purity_max": "0.80",
                "fragment": "virtual-scroll",
                "download": "tsv",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="homorepeat_repeat_calls.tsv"')
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn(
            "Call\tAccession\tProtein\tGene\tTaxon id\tTaxon\tMethod\tResidue\tStart\tEnd\tLength\tPurity\tLatest run",
            body,
        )
        self.assertIn(matched["repeat_call"].call_id, body)
        self.assertNotIn("call_repeatcall_tsv_low_purity", body)
        self.assertNotIn("call_repeatcall_tsv_beta", body)

    def test_repeatcall_list_renders_tsv_download_link_with_filters(self):
        url = reverse("browser:repeatcall-list")
        response = self.client.get(
            url,
            {
                "run": "run-alpha",
                "protein": self.alpha["protein"].protein_id,
                "method": RepeatCall.Method.PURE,
                "residue": "Q",
                "order_by": "length",
                "page": "1",
                "fragment": "virtual-scroll",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            (
                f'href="{url}?run=run-alpha&amp;protein={self.alpha["protein"].protein_id}'
                '&amp;method=pure&amp;residue=Q&amp;order_by=length&amp;download=tsv"'
            ),
        )
        self.assertNotContains(response, "page=1&amp;download=tsv")
        self.assertNotContains(response, "fragment=virtual-scroll&amp;download=tsv")

    def test_homorepeat_list_renders_biology_first_table(self):
        response = self.client.get(reverse("browser:homorepeat-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Homorepeats")
        self.assertContains(response, "Organism")
        self.assertContains(response, "Genome / Assembly")
        self.assertContains(response, "Gene / Protein")
        self.assertContains(response, "Repeat class")
        self.assertContains(response, "Pattern")
        self.assertContains(response, "Position")
        self.assertContains(response, "Homo sapiens")
        self.assertContains(response, "GCF_ALPHA")
        self.assertContains(response, "GENE1")
        self.assertContains(response, "11Q")
        self.assertContains(response, "10-20 (5%)")
        self.assertContains(
            response,
            f'href="{reverse("browser:repeatcall-detail", args=[self.alpha["repeat_call"].pk])}" title="Open repeat details"',
        )
        self.assertNotContains(response, "<span>Latest run</span>", html=True)
        self.assertNotContains(response, "<span>Call</span>", html=True)

    def test_homorepeat_list_combined_filters_work(self):
        matched = self._create_repeat_call(
            self.alpha,
            suffix="homorepeat_filter_match",
            gene_symbol="HOMOFLT",
            method=RepeatCall.Method.THRESHOLD,
            residue="A",
            length=9,
            purity=0.78,
        )
        self._create_repeat_call(
            self.alpha,
            suffix="homorepeat_filter_low_purity",
            gene_symbol="HOMOFLT",
            method=RepeatCall.Method.THRESHOLD,
            residue="A",
            length=9,
            purity=0.40,
        )
        self._create_repeat_call(
            self.beta,
            suffix="homorepeat_filter_beta",
            gene_symbol="HOMOFLT",
            method=RepeatCall.Method.THRESHOLD,
            residue="A",
            length=9,
            purity=0.78,
            taxon=self.beta["taxon"],
        )

        response = self.client.get(
            reverse("browser:homorepeat-list"),
            {
                "run": "run-alpha",
                "branch": str(self.mammalia.pk),
                "method": RepeatCall.Method.THRESHOLD,
                "residue": "A",
                "gene_symbol": "HOMOFLT",
                "length_min": "8",
                "length_max": "10",
                "purity_min": "0.70",
                "purity_max": "0.80",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, matched["repeat_call"].protein_name)
        self.assertContains(response, "7A2Q")
        self.assertNotContains(response, "call_homorepeat_filter_low_purity")
        self.assertNotContains(response, "call_homorepeat_filter_beta")

    def test_homorepeat_list_loads_pattern_fields_without_codon_sequence(self):
        response = self.client.get(reverse("browser:homorepeat-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        homorepeat = response.context["page_obj"].object_list[0]
        self.assertNotIn("aa_sequence", homorepeat.get_deferred_fields())
        self.assertNotIn("repeat_count", homorepeat.get_deferred_fields())
        self.assertNotIn("non_repeat_count", homorepeat.get_deferred_fields())
        self.assertIn("codon_sequence", homorepeat.get_deferred_fields())
        self.assertEqual(homorepeat.repeat_pattern, "11Q")

    def test_homorepeat_list_uses_cursor_pagination_for_default_ordering(self):
        self.assertEqual(
            HomorepeatListView.default_ordering,
            ("accession", "protein_name", "start", "id"),
        )

        response = self.client.get(reverse("browser:homorepeat-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["page_obj"].cursor_pagination)

    def test_homorepeat_list_virtual_scroll_fragment_returns_rows(self):
        response = self.client.get(
            reverse("browser:homorepeat-list"),
            {"run": "run-alpha", "fragment": "virtual-scroll"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("rows_html", payload)
        self.assertIn("11Q", payload["rows_html"])
        self.assertEqual(payload["row_count"], 1)
        self.assertNotIn("count", payload)
        self.assertEqual(payload["next_query"], "")

    def test_homorepeat_list_tsv_export_includes_full_sequences(self):
        response = self.client.get(
            reverse("browser:homorepeat-list"),
            {
                "run": "run-alpha",
                "download": "tsv",
                "page": "2",
                "fragment": "virtual-scroll",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="homorepeat_homorepeats.tsv"')
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn(
            "Organism\tGenome / Assembly\tGene\tProtein\tRepeat class\tLength\tPattern\tPurity\tPosition\tMethod",
            body,
        )
        self.assertIn("Source call\tStart\tEnd\tRepeat count\tNon-repeat count\tRepeat sequence\tCodon sequence", body)
        self.assertIn("call_alpha", body)
        self.assertIn("QQQQQQQQQQQ", body)
        self.assertIn("CAGCAGCAGCAGCAGCAGCAGCAGCAGCAGCAG", body)

    def test_homorepeat_list_renders_tsv_download_link_with_filters(self):
        url = reverse("browser:homorepeat-list")
        response = self.client.get(
            url,
            {
                "run": "run-alpha",
                "protein": self.alpha["protein"].protein_id,
                "method": RepeatCall.Method.PURE,
                "residue": "Q",
                "order_by": "length",
                "page": "1",
                "fragment": "virtual-scroll",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Filtered TSV")
        self.assertContains(response, "AA FASTA")
        self.assertContains(response, "DNA FASTA")
        self.assertContains(
            response,
            (
                f'href="{url}?run=run-alpha&amp;protein={self.alpha["protein"].protein_id}'
                '&amp;method=pure&amp;residue=Q&amp;order_by=length&amp;download=tsv"'
            ),
        )
        self.assertContains(
            response,
            (
                f'href="{url}?run=run-alpha&amp;protein={self.alpha["protein"].protein_id}'
                '&amp;method=pure&amp;residue=Q&amp;order_by=length&amp;download=aa_fasta"'
            ),
        )
        self.assertContains(
            response,
            (
                f'href="{url}?run=run-alpha&amp;protein={self.alpha["protein"].protein_id}'
                '&amp;method=pure&amp;residue=Q&amp;order_by=length&amp;download=dna_fasta"'
            ),
        )
        self.assertNotContains(response, "page=1&amp;download=tsv")
        self.assertNotContains(response, "fragment=virtual-scroll&amp;download=tsv")

    def test_homorepeat_list_aa_fasta_export_streams_filtered_sequences(self):
        matched = self._create_repeat_call(
            self.alpha,
            suffix="homorepeat_fasta_match",
            gene_symbol="LONG GENE",
            method=RepeatCall.Method.PURE,
            residue="Q",
            length=85,
            purity=1.0,
        )
        matched["protein"].amino_acid_sequence = "M" * 300
        matched["protein"].save(update_fields=["amino_acid_sequence"])
        sync_canonical_catalog_for_run(
            matched["repeat_call"].pipeline_run,
            import_batch=matched["repeat_call"].pipeline_run.canonical_sync_batch,
            last_seen_at=timezone.now(),
            replace_all_repeat_call_methods=True,
        )
        self._create_repeat_call(
            self.alpha,
            suffix="homorepeat_fasta_split",
            gene_symbol="SPLITGENE",
            method=RepeatCall.Method.PURE,
            residue="A",
            length=9,
            purity=1.0,
        )

        response = self.client.get(
            reverse("browser:homorepeat-list"),
            {
                "run": "run-alpha",
                "gene_symbol": "LONG GENE",
                "download": "aa_fasta",
                "page": "2",
                "fragment": "virtual-scroll",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/x-fasta; charset=utf-8")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="homorepeat_homorepeats.faa"')
        body = b"".join(response.streaming_content).decode("utf-8")
        header = body.splitlines()[0]
        self.assertRegex(header, r"^>homorepeat=\d+ ")
        self.assertNotIn("|GCF_ALPHA|", header)
        self.assertNotIn("|NP_homorepeat_fasta_match|", header)
        self.assertIn("assembly=GCF_ALPHA", header)
        self.assertIn("protein=NP_homorepeat_fasta_match", header)
        self.assertIn("method=pure", header)
        self.assertIn("repeat_class=Q", header)
        self.assertIn("start=10", header)
        self.assertIn("end=94", header)
        self.assertIn("length=85", header)
        self.assertIn("position=10-94", header)
        self.assertIn("position_percent=17", header)
        self.assertIn("sequence_length=300", header)
        self.assertNotIn("aa_start", header)
        self.assertNotIn("aa_end", header)
        self.assertNotIn("aa_length", header)
        self.assertNotIn("dna_start", header)
        self.assertNotIn("dna_end", header)
        self.assertNotIn("dna_length", header)
        self.assertNotIn("protein_position", header)
        self.assertNotIn("source_call", body)
        self.assertNotIn("canonical_repeat_call", body)
        self.assertIn("seq_type=aa_protein", body)
        self.assertIn('gene="LONG GENE"', body)
        self.assertIn("repeat_pattern=85Q", body)
        self.assertIn("M" * 80 + "\n" + "M" * 80 + "\n" + "M" * 80 + "\n" + "M" * 60 + "\n", body)
        self.assertNotIn("Q" * 80 + "\n" + "Q" * 5 + "\n", body)
        self.assertNotIn("SPLITGENE", body)
        self.assertNotIn("page=2", response["Content-Disposition"])

    def test_homorepeat_list_dna_fasta_export_streams_full_nucleotide_sequences(self):
        response = self.client.get(
            reverse("browser:homorepeat-list"),
            {
                "run": "run-alpha",
                "gene_symbol": "GENE1",
                "download": "dna_fasta",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/x-fasta; charset=utf-8")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="homorepeat_homorepeats.fna"')
        body = b"".join(response.streaming_content).decode("utf-8")
        header = body.splitlines()[0]
        self.assertIn("seq_type=dna_sequence", body)
        self.assertIn('organism="Homo sapiens"', body)
        self.assertIn("start=28", header)
        self.assertIn("end=60", header)
        self.assertIn("length=33", header)
        self.assertIn("sequence_length=900", header)
        self.assertNotIn("aa_start", header)
        self.assertNotIn("aa_end", header)
        self.assertNotIn("aa_length", header)
        self.assertNotIn("dna_start", header)
        self.assertNotIn("dna_end", header)
        self.assertNotIn("dna_length", header)
        self.assertNotIn("protein_position", header)
        self.assertNotIn("repeat_length", header)
        self.assertNotIn("%20", body)
        self.assertNotIn("%28", body)
        self.assertIn("CAG" * 26 + "CA\n", body)
        self.assertIn("G" + "CAG" * 26 + "C\n", body)
        self.assertNotEqual(body.count("CAG"), 11)

    def test_homorepeat_fasta_querysets_only_load_needed_sequence_fields_and_stream_by_pk(self):
        view = HomorepeatListView()
        view.request = self.client.get(
            reverse("browser:homorepeat-list"),
            {"run": "run-alpha", "order_by": "-length"},
        ).wsgi_request
        aa_row = view.get_fasta_queryset("aa_fasta").first()
        dna_row = view.get_fasta_queryset("dna_fasta").first()

        self.assertIn("codon_sequence", aa_row.get_deferred_fields())
        self.assertNotIn("aa_sequence", aa_row.get_deferred_fields())
        self.assertNotIn("amino_acid_sequence", aa_row.protein.get_deferred_fields())
        self.assertIn("aa_sequence", dna_row.get_deferred_fields())
        self.assertIn("codon_sequence", dna_row.get_deferred_fields())
        self.assertNotIn("nucleotide_sequence", dna_row.sequence.get_deferred_fields())
        self.assertEqual(tuple(view.get_fasta_queryset("aa_fasta").query.order_by), ("pk",))
        self.assertEqual(tuple(view.get_fasta_queryset("dna_fasta").query.order_by), ("pk",))

    def test_homorepeat_list_dna_fasta_skips_blank_nucleotide_sequences(self):
        blank = self._create_repeat_call(
            self.alpha,
            suffix="homorepeat_blank_dna",
            gene_symbol="BLANKDNA",
            method=RepeatCall.Method.PURE,
            residue="Q",
            length=9,
            purity=1.0,
        )
        blank["sequence"].nucleotide_sequence = ""
        blank["sequence"].save(update_fields=["nucleotide_sequence"])
        sync_canonical_catalog_for_run(
            blank["repeat_call"].pipeline_run,
            import_batch=blank["repeat_call"].pipeline_run.canonical_sync_batch,
            last_seen_at=timezone.now(),
            replace_all_repeat_call_methods=True,
        )

        response = self.client.get(
            reverse("browser:homorepeat-list"),
            {
                "run": "run-alpha",
                "gene_symbol": "BLANKDNA",
                "download": "dna_fasta",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertEqual(body, "")

    def test_codon_usage_list_renders_row_level_profiles(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 8, "codon_fraction": 0.72},
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 3, "codon_fraction": 0.28},
                {"amino_acid": "A", "codon": "GCT", "codon_count": 1, "codon_fraction": 1.0},
            ],
        )

        response = self.client.get(reverse("browser:codon-usage-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Codon Usage")
        self.assertContains(response, "Codon coverage")
        self.assertContains(response, "Codon profile")
        self.assertContains(response, "Codon counts")
        self.assertContains(response, "Dominant codon")
        self.assertContains(response, "Homo sapiens")
        self.assertContains(response, "11Q")
        self.assertContains(response, "11/11")
        self.assertContains(response, "CAG 73%, CAA 27%")
        self.assertContains(response, "CAG 8 / CAA 3")
        self.assertContains(response, "CAG")
        self.assertContains(
            response,
            f'href="{reverse("browser:repeatcall-detail", args=[self.alpha["repeat_call"].pk])}" title="Open repeat details"',
        )
        self.assertNotContains(response, "GCT")

    def test_codon_usage_route_uses_stable_view_export(self):
        match = resolve(reverse("browser:codon-usage-list"))

        self.assertIs(match.func.view_class, CodonUsageListView)

    def test_codon_usage_list_only_shows_calls_with_target_codon_usage(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 11, "codon_fraction": 1.0},
            ],
        )

        response = self.client.get(reverse("browser:codon-usage-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GCF_ALPHA")
        self.assertNotContains(response, "GCF_BETA")

    def test_codon_usage_list_uses_cursor_pagination_for_default_ordering(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 11, "codon_fraction": 1.0},
            ],
        )

        response = self.client.get(reverse("browser:codon-usage-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["page_obj"].cursor_pagination)
        codon_usage_profile = response.context["page_obj"].object_list[0]
        self.assertIn("codon_usages", getattr(codon_usage_profile, "_prefetched_objects_cache", {}))

    def test_codon_usage_list_uses_count_derived_percentages(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 5, "codon_fraction": 0.1},
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 5, "codon_fraction": 0.9},
            ],
        )

        response = self.client.get(reverse("browser:codon-usage-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CAA 50%, CAG 50%")
        self.assertContains(response, "CAA 5 / CAG 5")
        self.assertContains(response, ">CAA</td>")

    def test_codon_usage_list_tsv_export_includes_sequences_and_parseable_counts(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 8, "codon_fraction": 0.72},
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 3, "codon_fraction": 0.28},
            ],
        )

        response = self.client.get(
            reverse("browser:codon-usage-list"),
            {
                "run": "run-alpha",
                "download": "tsv",
                "page": "2",
                "fragment": "virtual-scroll",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="homorepeat_codon_usage.tsv"')
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn(
            "Organism\tGenome / Assembly\tProtein\tGene\tRepeat class\tLength\tPattern\tCodon coverage",
            body,
        )
        self.assertIn("Parseable codon counts\tParseable codon fractions", body)
        self.assertIn("CAG=8;CAA=3", body)
        self.assertIn("CAG=0.727;CAA=0.273", body)
        self.assertIn("QQQQQQQQQQQ", body)
        self.assertIn("CAGCAGCAGCAGCAGCAGCAGCAGCAGCAGCAG", body)

    def test_codon_usage_list_renders_tsv_download_link_with_filters(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 11, "codon_fraction": 1.0},
            ],
        )
        url = reverse("browser:codon-usage-list")
        response = self.client.get(
            url,
            {
                "run": "run-alpha",
                "protein": self.alpha["protein"].protein_id,
                "method": RepeatCall.Method.PURE,
                "residue": "Q",
                "order_by": "length",
                "page": "1",
                "fragment": "virtual-scroll",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            (
                f'href="{url}?run=run-alpha&amp;protein={self.alpha["protein"].protein_id}'
                '&amp;method=pure&amp;residue=Q&amp;order_by=length&amp;download=tsv"'
            ),
        )
        self.assertNotContains(response, "page=1&amp;download=tsv")
        self.assertNotContains(response, "fragment=virtual-scroll&amp;download=tsv")

    def test_codon_usage_list_virtual_scroll_fragment_returns_profiles(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 11, "codon_fraction": 1.0},
            ],
        )

        response = self.client.get(
            reverse("browser:codon-usage-list"),
            {"run": "run-alpha", "fragment": "virtual-scroll"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("rows_html", payload)
        self.assertIn("CAG 100%", payload["rows_html"])
        self.assertEqual(payload["row_count"], 1)
        self.assertNotIn("count", payload)
        self.assertEqual(payload["next_query"], "")

    def test_codon_usage_row_route_uses_stable_view_export(self):
        match = resolve(reverse("browser:codonusage-row-list"))

        self.assertIs(match.func.view_class, CodonUsageRowListView)

    def test_codon_usage_row_list_renders_supporting_catalog_table(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 8, "codon_fraction": 0.72},
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 3, "codon_fraction": 0.28},
            ],
        )

        response = self.client.get(reverse("browser:codonusage-row-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Codon usage rows")
        self.assertContains(response, "Gene / Protein")
        self.assertContains(response, "Amino acid")
        self.assertContains(response, "Codon")
        self.assertContains(response, "Homo sapiens")
        self.assertContains(response, "GCF_ALPHA")
        self.assertContains(response, "GENE1")
        self.assertContains(response, "NP_run-alpha")
        self.assertContains(response, "CAG")
        self.assertContains(response, "0.72")
        self.assertContains(response, reverse("browser:repeatcall-detail", args=[self.alpha["repeat_call"].pk]))
        self.assertNotContains(response, "GCF_BETA")

    def test_codon_usage_row_list_filters_by_codon_and_exports_tsv(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 8, "codon_fraction": 0.72},
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 3, "codon_fraction": 0.28},
            ],
        )

        response = self.client.get(
            reverse("browser:codonusage-row-list"),
            {"run": "run-alpha", "codon": "CAG", "download": "tsv"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="homorepeat_codon_usage_rows.tsv"')
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn(
            "Organism\tGenome / Assembly\tGene\tProtein\tRepeat class\tAmino acid\tCodon\tCodon count\tCodon fraction",
            body,
        )
        self.assertIn("CAG\t8\t0.72", body)
        self.assertNotIn("CAA\t3\t0.28", body)

    def test_codon_usage_row_list_virtual_scroll_fragment_returns_rows(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 11, "codon_fraction": 1.0},
            ],
        )

        response = self.client.get(
            reverse("browser:codonusage-row-list"),
            {"run": "run-alpha", "fragment": "virtual-scroll"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("rows_html", payload)
        self.assertIn("CAG", payload["rows_html"])
        self.assertEqual(payload["row_count"], 1)
        self.assertNotIn("count", payload)
        self.assertEqual(payload["next_query"], "")

    def test_sequence_list_virtual_scroll_fragment_returns_rows_without_count(self):
        response = self.client.get(
            reverse("browser:sequence-list"),
            {"run": "run-alpha", "fragment": "virtual-scroll"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("rows_html", payload)
        self.assertIn("NM_run-alpha", payload["rows_html"])
        self.assertEqual(payload["row_count"], 1)
        self.assertNotIn("count", payload)
        self.assertEqual(payload["next_query"], "")

    def test_repeatcall_detail_shows_linked_parents_and_coordinates(self):
        matched = self._create_repeat_call(
            self.alpha,
            suffix="detail_call",
            gene_symbol="DETAILGENE",
            method=RepeatCall.Method.THRESHOLD,
            residue="A",
            length=9,
            purity=0.78,
            start=21,
        )

        response = self.client.get(reverse("browser:repeatcall-detail", args=[matched["repeat_call"].pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, matched["repeat_call"].call_id)
        self.assertContains(response, "Coordinates 21-29")
        self.assertContains(response, "DETAILGENE")
        self.assertContains(response, matched["protein"].protein_name)
        self.assertContains(response, "GCF_ALPHA")
        self.assertContains(response, reverse("browser:sequence-detail", args=[matched["sequence"].pk]))
        self.assertContains(response, "Compare branch lengths")
        self.assertContains(response, "Compare branch codon ratios")
        repeatcall_length_query = parse_qs(urlparse(response.context["length_explorer_url"]).query)
        self.assertEqual(repeatcall_length_query["run"], ["run-alpha"])
        self.assertEqual(repeatcall_length_query["branch"], [str(self.alpha["taxon"].pk)])
        self.assertEqual(repeatcall_length_query["q"], ["DETAILGENE"])
        self.assertEqual(repeatcall_length_query["method"], [RepeatCall.Method.THRESHOLD])
        self.assertEqual(repeatcall_length_query["residue"], ["A"])
        repeatcall_codon_query = parse_qs(urlparse(response.context["codon_ratio_explorer_url"]).query)
        self.assertEqual(repeatcall_codon_query["run"], ["run-alpha"])
        self.assertEqual(repeatcall_codon_query["branch"], [str(self.alpha["taxon"].pk)])
        self.assertEqual(repeatcall_codon_query["q"], ["DETAILGENE"])
        self.assertEqual(repeatcall_codon_query["method"], [RepeatCall.Method.THRESHOLD])
        self.assertEqual(repeatcall_codon_query["residue"], ["A"])
        self.assertNotContains(response, "Open run")
