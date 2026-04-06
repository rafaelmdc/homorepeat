from django.test import TestCase
from django.urls import reverse

from apps.browser.models import Protein, RepeatCall, Sequence

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
                sequence_path=f"/tmp/{suffix}/cds.fna",
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
                protein_path=f"/tmp/{suffix}/proteins.faa",
                gene_symbol=gene_symbol,
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
        self.assertContains(response, "Method: pure")

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

    def test_protein_list_run_filter_scopes_results(self):
        response = self.client.get(reverse("browser:protein-list"), {"run": "run-alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NP_run-alpha")
        self.assertNotContains(response, "NP_run-beta")

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
