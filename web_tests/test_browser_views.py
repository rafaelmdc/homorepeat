from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.browser.models import (
    AccessionCallCount,
    AccessionStatus,
    AcquisitionBatch,
    DownloadManifestEntry,
    NormalizationWarning,
    Protein,
    RepeatCall,
    RunParameter,
    Sequence,
)
from apps.imports.models import ImportBatch

from .support import create_imported_run_fixture


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

        repeat_count = max(1, min(length, int(round(length * purity))))
        non_repeat_count = max(length - repeat_count, 0)
        filler = "A" if residue != "A" else "Q"
        aa_sequence = (residue * repeat_count) + (filler * non_repeat_count)
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
            repeat_count=repeat_count,
            non_repeat_count=non_repeat_count,
            purity=purity,
            aa_sequence=aa_sequence,
        )
        return {"sequence": sequence, "protein": protein, "repeat_call": repeat_call}

    def test_browser_home_shows_counts_and_recent_runs(self):
        response = self.client.get(reverse("browser:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Imported runs")
        self.assertContains(response, "Operational provenance")
        self.assertContains(response, reverse("browser:accessionstatus-list"))
        self.assertContains(response, reverse("browser:downloadmanifest-list"))
        self.assertContains(response, "run-alpha")
        self.assertContains(response, "run-beta")

    def test_run_list_renders_imported_runs(self):
        response = self.client.get(reverse("browser:run-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "run-alpha")
        self.assertContains(response, "run-beta")
        self.assertContains(response, reverse("browser:run-detail", args=[self.alpha["pipeline_run"].pk]))

    def test_run_list_search_filters_results(self):
        response = self.client.get(reverse("browser:run-list"), {"q": "run-beta"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "run-beta")
        self.assertNotContains(response, "run-alpha")

    def test_run_detail_shows_counts_and_scoped_links(self):
        response = self.client.get(reverse("browser:run-detail", args=[self.alpha["pipeline_run"].pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "run-alpha")
        self.assertContains(response, "Distinct taxa referenced")
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
            phase="loading_fasta",
            heartbeat_at=timezone.now(),
            progress_payload={
                "message": "Loading FASTA payloads.",
                "batch_id": "batch_0002",
                "inserted_sequences": 42,
            },
        )

        response = self.client.get(reverse("browser:run-detail", args=[pipeline_run.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Publish mode: raw")
        self.assertContains(response, "Acquisition publish mode")
        self.assertContains(response, "Heartbeat and row visibility")
        self.assertContains(response, "Loading FASTA payloads.")
        self.assertContains(response, "Inserted sequences")
        self.assertContains(response, "batch_0002")
        self.assertContains(response, "partial_cds")
        self.assertContains(response, "threshold")
        self.assertContains(response, "Latest completed counts")
        self.assertContains(response, "failed")

    def test_run_detail_links_summary_counts_to_filtered_related_views(self):
        response = self.client.get(reverse("browser:run-detail", args=[self.alpha["pipeline_run"].pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{reverse('browser:genome-list')}?run=run-alpha")
        self.assertContains(response, f"{reverse('browser:protein-list')}?run=run-alpha")
        self.assertContains(response, f"{reverse('browser:repeatcall-list')}?run=run-alpha")
        self.assertContains(response, "terminal_status=completed")
        self.assertContains(response, "method=pure")

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

    def test_accession_list_links_summary_counts_to_filtered_related_views(self):
        response = self.client.get(reverse("browser:accession-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{reverse('browser:repeatcall-list')}?mode=merged&amp;accession=GCF_ALPHA&amp;run=run-alpha")
        self.assertContains(response, f"{reverse('browser:protein-list')}?mode=merged&amp;accession=GCF_ALPHA&amp;run=run-alpha")
        self.assertContains(response, "method=pure")
        self.assertContains(response, "accession=GCF_ALPHA")

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

    def test_genome_list_branch_filter_includes_descendant_taxa(self):
        response = self.client.get(reverse("browser:genome-list"), {"branch": str(self.mammalia.pk)})

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

    def test_accession_detail_links_to_source_proteins_and_repeat_calls(self):
        response = self.client.get(reverse("browser:accession-detail", args=["GCF_ALPHA"]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Open source proteins")
        self.assertContains(response, f"{reverse('browser:protein-list')}?accession=GCF_ALPHA")
        self.assertContains(response, f"{reverse('browser:repeatcall-list')}?accession=GCF_ALPHA")

    def test_sequence_list_run_filter_scopes_results(self):
        response = self.client.get(reverse("browser:sequence-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NM_run-alpha")
        self.assertNotContains(response, "NM_run-beta")
        self.assertContains(response, reverse("browser:sequence-detail", args=[self.alpha["sequence"].pk]))

    def test_sequence_detail_shows_linked_records_and_navigation(self):
        response = self.client.get(reverse("browser:sequence-detail", args=[self.alpha["sequence"].pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NM_run-alpha")
        self.assertContains(response, "run-alpha")
        self.assertContains(response, "NP_run-alpha")
        self.assertContains(response, "call_alpha")
        self.assertContains(response, reverse("browser:protein-list"))
        self.assertContains(response, reverse("browser:repeatcall-list"))

    def test_protein_list_run_filter_scopes_results(self):
        response = self.client.get(reverse("browser:protein-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NP_run-alpha")
        self.assertNotContains(response, "NP_run-beta")

    def test_protein_list_defers_large_sequence_payloads(self):
        response = self.client.get(reverse("browser:protein-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        protein = response.context["page_obj"].object_list[0]
        self.assertIn("amino_acid_sequence", protein.get_deferred_fields())

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
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["next_query"], "")

    def test_protein_list_merged_virtual_scroll_fragment_returns_rows(self):
        response = self.client.get(
            reverse("browser:protein-list"),
            {"mode": "merged", "fragment": "virtual-scroll"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("rows_html", payload)
        self.assertIn("GCF_ALPHA", payload["rows_html"])

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

    def test_repeatcall_list_defers_large_sequence_payloads(self):
        response = self.client.get(reverse("browser:repeatcall-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        repeat_call = response.context["page_obj"].object_list[0]
        self.assertIn("aa_sequence", repeat_call.get_deferred_fields())
        self.assertIn("codon_sequence", repeat_call.get_deferred_fields())
        self.assertIn("amino_acid_sequence", repeat_call.protein.get_deferred_fields())

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
        first_ids = [repeat_call.call_id for repeat_call in first_page.object_list]
        self.assertTrue(first_page.cursor_pagination)
        self.assertTrue(first_page.has_next())
        self.assertIn("after=", first_page.next_query)

        next_response = self.client.get(f"{reverse('browser:repeatcall-list')}?{first_page.next_query}")

        self.assertEqual(next_response.status_code, 200)
        second_page = next_response.context["page_obj"]
        second_ids = [repeat_call.call_id for repeat_call in second_page.object_list]
        self.assertTrue(second_page.has_previous())
        self.assertTrue(set(first_ids).isdisjoint(second_ids))

    def test_repeatcall_list_renders_virtual_scroll_hooks_for_raw_results(self):
        response = self.client.get(reverse("browser:repeatcall-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-virtual-scroll-root")
        self.assertContains(response, "data-virtual-scroll-body")

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
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["next_query"], "")

    def test_repeatcall_list_merged_virtual_scroll_fragment_returns_rows(self):
        response = self.client.get(
            reverse("browser:repeatcall-list"),
            {"mode": "merged", "fragment": "virtual-scroll"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("rows_html", payload)
        self.assertIn("GCF_ALPHA", payload["rows_html"])

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
