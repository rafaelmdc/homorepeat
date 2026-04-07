from django.test import TestCase
from django.urls import reverse

from apps.browser.models import Genome, PipelineRun, Protein, RepeatCall, Sequence

from .support import ensure_test_taxonomy


class BrowserMergeViewTests(TestCase):
    def setUp(self):
        self.taxa = ensure_test_taxonomy()
        self.human = self.taxa["human"]

    def _create_accession_source(
        self,
        *,
        run_id,
        accession,
        genome_suffix,
        protein_name,
        protein_length,
        call_id,
        method=RepeatCall.Method.PURE,
        residue="Q",
        start=10,
        length=11,
        purity=1.0,
        analyzed_protein_count=20,
        taxon=None,
    ):
        taxon = taxon or self.human
        pipeline_run = PipelineRun.objects.create(
            run_id=run_id,
            status="success",
            profile="docker",
            git_revision="abc123",
            manifest_path=f"/tmp/{run_id}/manifest/run_manifest.json",
            publish_root=f"/tmp/{run_id}/publish",
            manifest_payload={"run_id": run_id},
        )
        genome = Genome.objects.create(
            pipeline_run=pipeline_run,
            genome_id=f"genome_{genome_suffix}",
            source="ncbi_datasets",
            accession=accession,
            genome_name=f"Genome {genome_suffix}",
            assembly_type="haploid",
            taxon=taxon,
            assembly_level="Chromosome",
            species_name=taxon.taxon_name,
            analyzed_protein_count=analyzed_protein_count,
        )
        sequence = Sequence.objects.create(
            pipeline_run=pipeline_run,
            genome=genome,
            taxon=taxon,
            sequence_id=f"seq_{genome_suffix}",
            sequence_name=f"NM_{genome_suffix}",
            sequence_length=900,
            sequence_path=f"/tmp/{genome_suffix}/cds.fna",
            gene_symbol="GENE1",
        )
        protein = Protein.objects.create(
            pipeline_run=pipeline_run,
            genome=genome,
            sequence=sequence,
            taxon=taxon,
            protein_id=f"prot_{genome_suffix}",
            protein_name=protein_name,
            protein_length=protein_length,
            protein_path=f"/tmp/{genome_suffix}/proteins.faa",
            gene_symbol="GENE1",
        )
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
            call_id=call_id,
            method=method,
            start=start,
            end=start + length - 1,
            length=length,
            repeat_residue=residue,
            repeat_count=repeat_count,
            non_repeat_count=non_repeat_count,
            purity=purity,
            aa_sequence=aa_sequence,
        )
        return {
            "pipeline_run": pipeline_run,
            "genome": genome,
            "sequence": sequence,
            "protein": protein,
            "repeat_call": repeat_call,
        }

    def test_accession_list_groups_shared_accessions_across_runs(self):
        self._create_accession_source(
            run_id="run-alpha",
            accession="GCF_SHARED",
            genome_suffix="shared_alpha",
            protein_name="SharedProtein",
            protein_length=300,
            call_id="call_shared_alpha",
        )
        self._create_accession_source(
            run_id="run-beta",
            accession="GCF_SHARED",
            genome_suffix="shared_beta",
            protein_name="SharedProtein",
            protein_length=300,
            call_id="call_shared_beta",
        )
        self._create_accession_source(
            run_id="run-gamma",
            accession="GCF_UNIQUE",
            genome_suffix="unique_gamma",
            protein_name="UniqueProtein",
            protein_length=280,
            call_id="call_unique_gamma",
        )

        response = self.client.get(reverse("browser:accession-list"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "browser/accession_list.html")
        self.assertContains(response, reverse("browser:accession-detail", args=["GCF_SHARED"]))
        self.assertContains(response, reverse("browser:accession-detail", args=["GCF_UNIQUE"]))
        self.assertContains(response, "Merged accession analytics")
        self.assertEqual(response.context["summary"]["accession_groups_count"], 2)
        self.assertEqual(response.context["summary"]["source_repeat_calls_count"], 3)
        self.assertEqual(response.context["summary"]["collapsed_repeat_calls_count"], 2)
        self.assertEqual(response.context["summary"]["duplicate_source_repeat_calls_count"], 1)
        self.assertEqual(response.context["summary"]["merged_repeat_bearing_proteins_count"], 2)
        self.assertEqual(response.context["summary"]["analyzed_proteins_total"], 40)
        self.assertAlmostEqual(response.context["summary"]["repeat_bearing_protein_percentage"], 5.0)
        shared_group = next(
            accession_group
            for accession_group in response.context["accession_groups"]
            if accession_group["accession"] == "GCF_SHARED"
        )
        self.assertEqual(shared_group["source_runs_count"], 2)
        self.assertEqual(shared_group["source_genomes_count"], 2)
        self.assertEqual(shared_group["collapsed_repeat_calls_count"], 1)
        self.assertEqual(shared_group["duplicate_source_repeat_calls_count"], 1)
        self.assertEqual(shared_group["merged_repeat_bearing_proteins_count"], 1)
        self.assertAlmostEqual(shared_group["repeat_bearing_protein_percentage"], 5.0)

    def test_accession_list_summarizes_collapsed_methods_and_safe_denominators(self):
        self._create_accession_source(
            run_id="run-alpha",
            accession="GCF_SHARED",
            genome_suffix="summary_alpha",
            protein_name="SharedProtein",
            protein_length=300,
            call_id="call_summary_alpha",
            analyzed_protein_count=20,
            method=RepeatCall.Method.PURE,
            residue="Q",
        )
        self._create_accession_source(
            run_id="run-beta",
            accession="GCF_SHARED",
            genome_suffix="summary_beta",
            protein_name="SharedProtein",
            protein_length=300,
            call_id="call_summary_beta",
            analyzed_protein_count=20,
            method=RepeatCall.Method.PURE,
            residue="Q",
        )
        self._create_accession_source(
            run_id="run-gamma",
            accession="GCF_ALT",
            genome_suffix="summary_gamma",
            protein_name="AltProtein",
            protein_length=280,
            call_id="call_summary_gamma",
            analyzed_protein_count=10,
            method=RepeatCall.Method.THRESHOLD,
            residue="A",
        )
        self._create_accession_source(
            run_id="run-delta",
            accession="GCF_CONFLICT",
            genome_suffix="summary_delta",
            protein_name="ConflictProtein",
            protein_length=260,
            call_id="call_summary_delta",
            analyzed_protein_count=12,
            method=RepeatCall.Method.PURE,
            residue="Q",
        )
        self._create_accession_source(
            run_id="run-epsilon",
            accession="GCF_CONFLICT",
            genome_suffix="summary_epsilon",
            protein_name="ConflictProtein",
            protein_length=260,
            call_id="call_summary_epsilon",
            analyzed_protein_count=15,
            method=RepeatCall.Method.PURE,
            residue="Q",
        )

        response = self.client.get(reverse("browser:accession-list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summary"]["accession_groups_count"], 3)
        self.assertEqual(response.context["summary"]["collapsed_repeat_calls_count"], 3)
        self.assertEqual(response.context["summary"]["duplicate_source_repeat_calls_count"], 2)
        self.assertEqual(response.context["summary"]["merged_repeat_bearing_proteins_count"], 3)
        self.assertEqual(response.context["summary"]["conflict_accessions_count"], 1)
        self.assertEqual(response.context["summary"]["safe_accessions_count"], 2)
        self.assertEqual(response.context["summary"]["analyzed_proteins_total"], 30)
        self.assertEqual(response.context["summary"]["safe_repeat_bearing_proteins_count"], 2)
        self.assertAlmostEqual(response.context["summary"]["repeat_bearing_protein_percentage"], 6.6666666667)
        self.assertEqual(response.context["summary"]["method_summary"][0], {"label": "pure", "count": 2})
        self.assertEqual(response.context["summary"]["method_summary"][1], {"label": "threshold", "count": 1})
        self.assertEqual(response.context["summary"]["residue_summary"][0], {"label": "Q", "count": 2})
        self.assertEqual(response.context["summary"]["residue_summary"][1], {"label": "A", "count": 1})
        self.assertNotContains(response, "Percentage withheld because no conflict-safe analyzed-protein denominator is available.")

    def test_genome_list_merged_mode_groups_shared_accessions(self):
        self._create_accession_source(
            run_id="run-alpha",
            accession="GCF_SHARED",
            genome_suffix="genome_list_alpha",
            protein_name="SharedProtein",
            protein_length=300,
            call_id="call_genome_list_alpha",
        )
        self._create_accession_source(
            run_id="run-beta",
            accession="GCF_SHARED",
            genome_suffix="genome_list_beta",
            protein_name="SharedProtein",
            protein_length=300,
            call_id="call_genome_list_beta",
        )

        response = self.client.get(reverse("browser:genome-list"), {"mode": "merged"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Merged accession inventory")
        self.assertEqual(response.context["current_mode"], "merged")
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        self.assertContains(response, reverse("browser:accession-detail", args=["GCF_SHARED"]))

    def test_protein_list_merged_mode_groups_proteins_across_runs(self):
        self._create_accession_source(
            run_id="run-alpha",
            accession="GCF_SHARED",
            genome_suffix="protein_list_alpha",
            protein_name="SharedProtein",
            protein_length=300,
            call_id="call_protein_list_alpha",
        )
        self._create_accession_source(
            run_id="run-beta",
            accession="GCF_SHARED",
            genome_suffix="protein_list_beta",
            protein_name="SharedProtein",
            protein_length=300,
            call_id="call_protein_list_beta",
        )

        response = self.client.get(reverse("browser:protein-list"), {"mode": "merged"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_mode"], "merged")
        protein_groups = list(response.context["proteins"])
        self.assertEqual(len(protein_groups), 1)
        self.assertEqual(protein_groups[0]["source_runs_count"], 2)
        self.assertEqual(protein_groups[0]["source_proteins_count"], 2)
        self.assertEqual(protein_groups[0]["collapsed_repeat_calls_count"], 1)

    def test_repeatcall_list_merged_mode_collapses_exact_calls(self):
        self._create_accession_source(
            run_id="run-alpha",
            accession="GCF_SHARED",
            genome_suffix="call_list_alpha",
            protein_name="SharedProtein",
            protein_length=300,
            call_id="call_call_list_alpha",
        )
        self._create_accession_source(
            run_id="run-beta",
            accession="GCF_SHARED",
            genome_suffix="call_list_beta",
            protein_name="SharedProtein",
            protein_length=300,
            call_id="call_call_list_beta",
        )
        self._create_accession_source(
            run_id="run-gamma",
            accession="GCF_SHARED",
            genome_suffix="call_list_gamma",
            protein_name="SharedProtein",
            protein_length=300,
            call_id="call_call_list_gamma",
            purity=0.875,
        )

        response = self.client.get(reverse("browser:repeatcall-list"), {"mode": "merged"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_mode"], "merged")
        collapsed_groups = list(response.context["repeat_calls"])
        self.assertEqual(len(collapsed_groups), 2)
        self.assertEqual(sorted(group["source_count"] for group in collapsed_groups), [1, 2])
        self.assertContains(response, "Merged repeat-call inventory")

    def test_accession_detail_collapses_exact_calls_and_uses_merged_denominator(self):
        alpha = self._create_accession_source(
            run_id="run-alpha",
            accession="GCF_SHARED",
            genome_suffix="shared_alpha",
            protein_name="SharedProtein",
            protein_length=300,
            call_id="call_shared_alpha",
            analyzed_protein_count=20,
        )
        beta = self._create_accession_source(
            run_id="run-beta",
            accession="GCF_SHARED",
            genome_suffix="shared_beta",
            protein_name="SharedProtein",
            protein_length=300,
            call_id="call_shared_beta",
            analyzed_protein_count=20,
        )
        self._create_accession_source(
            run_id="run-gamma",
            accession="GCF_SHARED",
            genome_suffix="shared_gamma",
            protein_name="SharedProtein",
            protein_length=300,
            call_id="call_shared_gamma",
            analyzed_protein_count=20,
            purity=0.875,
        )

        response = self.client.get(reverse("browser:accession-detail", args=["GCF_SHARED"]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "browser/accession_detail.html")
        self.assertEqual(response.context["source_repeat_calls_count"], 3)
        self.assertEqual(response.context["collapsed_repeat_calls_count"], 2)
        self.assertEqual(response.context["duplicate_source_repeat_calls_count"], 1)
        self.assertEqual(response.context["merged_repeat_bearing_proteins_count"], 1)
        self.assertEqual(response.context["merged_analyzed_protein_count"], 20)
        self.assertEqual(response.context["repeat_bearing_protein_percentage"], 5.0)
        self.assertContains(response, f"run-alpha:{alpha['repeat_call'].call_id}")
        self.assertContains(response, f"run-beta:{beta['repeat_call'].call_id}")
        source_counts = sorted(group["source_count"] for group in response.context["collapsed_call_groups"])
        self.assertEqual(source_counts, [1, 2])

    def test_accession_detail_withholds_percentage_when_denominator_conflicts(self):
        self._create_accession_source(
            run_id="run-alpha",
            accession="GCF_CONFLICT",
            genome_suffix="conflict_alpha",
            protein_name="SharedProtein",
            protein_length=300,
            call_id="call_conflict_alpha",
            analyzed_protein_count=20,
        )
        self._create_accession_source(
            run_id="run-beta",
            accession="GCF_CONFLICT",
            genome_suffix="conflict_beta",
            protein_name="SharedProtein",
            protein_length=300,
            call_id="call_conflict_beta",
            analyzed_protein_count=24,
        )

        response = self.client.get(reverse("browser:accession-detail", args=["GCF_CONFLICT"]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["has_analyzed_protein_conflict"])
        self.assertIsNone(response.context["merged_analyzed_protein_count"])
        self.assertIsNone(response.context["repeat_bearing_protein_percentage"])
        self.assertContains(response, "Percentage withheld because the analyzed protein denominator conflicts across runs.")
        self.assertContains(response, "20, 24")

    def test_taxon_detail_merged_mode_uses_merged_branch_counts(self):
        self._create_accession_source(
            run_id="run-alpha",
            accession="GCF_SHARED",
            genome_suffix="taxon_alpha",
            protein_name="SharedProtein",
            protein_length=300,
            call_id="call_taxon_alpha",
        )
        self._create_accession_source(
            run_id="run-beta",
            accession="GCF_SHARED",
            genome_suffix="taxon_beta",
            protein_name="SharedProtein",
            protein_length=300,
            call_id="call_taxon_beta",
        )

        response = self.client.get(
            reverse("browser:taxon-detail", args=[self.human.pk]),
            {"mode": "merged"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_mode"], "merged")
        self.assertEqual(response.context["branch_genomes_count"], 1)
        self.assertEqual(response.context["branch_proteins_count"], 1)
        self.assertEqual(response.context["branch_repeat_calls_count"], 1)
        self.assertContains(response, reverse("browser:genome-list") + f"?branch={self.human.pk}&amp;mode=merged")
        self.assertContains(response, reverse("browser:accession-detail", args=["GCF_SHARED"]))

    def test_genome_detail_links_to_merged_accession_view(self):
        alpha = self._create_accession_source(
            run_id="run-alpha",
            accession="GCF_SHARED",
            genome_suffix="detail_alpha",
            protein_name="SharedProtein",
            protein_length=300,
            call_id="call_detail_alpha",
        )
        self._create_accession_source(
            run_id="run-beta",
            accession="GCF_SHARED",
            genome_suffix="detail_beta",
            protein_name="SharedProtein",
            protein_length=300,
            call_id="call_detail_beta",
        )

        response = self.client.get(reverse("browser:genome-detail", args=[alpha["genome"].pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("browser:accession-detail", args=["GCF_SHARED"]))
        self.assertContains(response, "2 genome rows across imported runs")
