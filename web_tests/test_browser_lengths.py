from urllib.parse import parse_qs, urlparse

from django.core.cache import cache
from django.test import TestCase
from django.urls import resolve, reverse
from django.utils import timezone

from apps.browser.catalog import sync_canonical_catalog_for_run
from apps.browser.models import RepeatCall
from apps.browser.views import RepeatLengthExplorerView

from .support import build_test_repeat_call_values, create_imported_run_fixture


class BrowserLengthExplorerTests(TestCase):
    def setUp(self):
        cache.clear()
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

    def _create_repeat_call(
        self,
        run_data,
        *,
        suffix,
        method,
        residue,
        length,
        purity,
        start=30,
        gene_symbol=None,
    ):
        protein = run_data["protein"]
        sequence = run_data["sequence"]
        genome = run_data["genome"]
        repeat_call_values = build_test_repeat_call_values(
            residue=residue,
            length=length,
            purity=purity,
        )

        repeat_call = RepeatCall.objects.create(
            pipeline_run=run_data["pipeline_run"],
            genome=genome,
            sequence=sequence,
            protein=protein,
            taxon=run_data["taxon"],
            call_id=f"call_{suffix}",
            method=method,
            accession=genome.accession,
            gene_symbol=gene_symbol or protein.gene_symbol or sequence.gene_symbol,
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
            run_data["pipeline_run"],
            import_batch=run_data["import_batch"],
            last_seen_at=timezone.now(),
            replace_all_repeat_call_methods=True,
        )
        cache.clear()
        return repeat_call

    def test_length_explorer_route_uses_stable_view_export(self):
        match = resolve(reverse("browser:lengths"))

        self.assertIs(match.func.view_class, RepeatLengthExplorerView)

    def test_length_explorer_renders_with_default_scope(self):
        response = self.client.get(reverse("browser:lengths"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "browser/repeat_length_explorer.html")
        self.assertContains(response, "Lineage-aware repeat length exploration over the current catalog.")
        self.assertEqual(response.context["current_rank"], "class")
        self.assertEqual(response.context["current_top_n"], 1000)
        self.assertEqual(response.context["current_min_count"], 3)
        self.assertEqual(response.context["matching_repeat_calls_count"], 2)
        self.assertEqual(response.context["total_taxa_count"], 0)
        self.assertEqual(response.context["visible_taxa_count"], 0)
        self.assertEqual(response.context["summary_rows"], [])
        self.assertEqual(response.context["chart_payload"]["rows"], [])
        self.assertEqual(response.context["chart_payload"]["visibleTaxaCount"], 0)
        self.assertContains(response, 'id="repeat-length-chart-payload"')
        self.assertContains(response, 'id="repeat-length-chart"')
        self.assertContains(response, "repeat-length-explorer.js")
        self.assertContains(response, "echarts.min.js")
        self.assertContains(response, "Ranked length distributions for the visible taxa")
        self.assertContains(response, 'data-chart-mode-switch')
        self.assertContains(response, 'data-chart-mode-button')
        self.assertContains(response, 'data-chart-mode="focused"')
        self.assertContains(response, 'data-chart-mode="full-range"')
        self.assertContains(response, "Focused")
        self.assertContains(response, "Full range")
        self.assertContains(
            response,
            "No taxa reached the current display rank and minimum observation threshold.",
        )

    def test_length_explorer_normalizes_run_and_numeric_filters(self):
        response = self.client.get(
            reverse("browser:lengths"),
            {
                "run": "run-beta",
                "residue": "q",
                "top_n": "9999",
                "min_count": "0",
                "length_min": "bad",
                "length_max": "12",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_run_id"], "run-beta")
        self.assertEqual(response.context["current_residue"], "Q")
        self.assertEqual(response.context["current_top_n"], 2000)
        self.assertEqual(response.context["current_min_count"], 1)
        self.assertIsNone(response.context["current_length_min"])
        self.assertEqual(response.context["current_length_max"], 12)
        self.assertEqual(response.context["matching_repeat_calls_count"], 1)

    def test_length_explorer_method_and_residue_filters_limit_matching_calls(self):
        self._create_repeat_call(
            self.alpha,
            suffix="threshold_a",
            method=RepeatCall.Method.THRESHOLD,
            residue="A",
            length=9,
            purity=0.78,
        )

        response = self.client.get(
            reverse("browser:lengths"),
            {
                "run": "run-alpha",
                "branch_q": "Prim",
                "method": RepeatCall.Method.THRESHOLD,
                "residue": "a",
                "min_count": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["matching_repeat_calls_count"], 1)
        self.assertEqual(response.context["visible_taxa_count"], 1)
        self.assertEqual(response.context["summary_rows"][0]["taxon_name"], "Homo sapiens")
        self.assertEqual(response.context["summary_rows"][0]["observation_count"], 1)
        self.assertEqual(response.context["summary_rows"][0]["min_length"], 9)
        self.assertEqual(response.context["summary_rows"][0]["max_length"], 9)

    def test_length_explorer_length_range_filter_limits_matching_calls(self):
        self._create_repeat_call(
            self.alpha,
            suffix="short_threshold_a",
            method=RepeatCall.Method.THRESHOLD,
            residue="A",
            length=9,
            purity=0.78,
        )

        response = self.client.get(
            reverse("browser:lengths"),
            {
                "run": "run-alpha",
                "branch_q": "Prim",
                "length_max": "10",
                "min_count": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["matching_repeat_calls_count"], 1)
        self.assertEqual(response.context["visible_taxa_count"], 1)
        self.assertEqual(response.context["summary_rows"][0]["taxon_name"], "Homo sapiens")
        self.assertEqual(response.context["summary_rows"][0]["min_length"], 9)
        self.assertEqual(response.context["summary_rows"][0]["median"], 9)
        self.assertEqual(response.context["summary_rows"][0]["max_length"], 9)

    def test_length_explorer_renders_grouped_taxon_summary_rows(self):
        response = self.client.get(
            reverse("browser:lengths"),
            {
                "rank": "class",
                "min_count": "1",
                "top_n": "10",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_taxa_count"], 1)
        self.assertEqual(response.context["visible_taxa_count"], 1)
        self.assertContains(response, "Grouped taxa")
        self.assertContains(response, "Mammalia")
        self.assertContains(response, "Open branch")
        self.assertContains(response, "Showing 1 of 1 taxa at rank class.")
        self.assertContains(response, 'data-summary-section')
        self.assertContains(response, 'data-summary-page-size="25"')
        self.assertContains(response, 'data-summary-table-body')
        self.assertContains(response, 'data-summary-row')
        self.assertContains(response, 'data-summary-pagination')
        self.assertContains(response, 'data-chart-mode-switch')
        self.assertContains(response, 'data-preserve-scroll-link')

        summary_rows = response.context["summary_rows"]
        self.assertEqual(len(summary_rows), 1)
        self.assertEqual(summary_rows[0]["taxon_name"], "Mammalia")
        self.assertEqual(summary_rows[0]["rank"], "class")
        self.assertEqual(summary_rows[0]["observation_count"], 2)
        self.assertEqual(summary_rows[0]["min_length"], 11)
        self.assertEqual(summary_rows[0]["median"], 11)
        self.assertEqual(summary_rows[0]["max_length"], 11)
        self.assertIn(reverse("browser:taxon-detail", args=[summary_rows[0]["taxon_id"]]), summary_rows[0]["taxon_detail_url"])
        self.assertIn(f"branch={summary_rows[0]['taxon_id']}", summary_rows[0]["branch_explorer_url"])
        self.assertIn("rank=order", summary_rows[0]["branch_explorer_url"])
        chart_payload = response.context["chart_payload"]
        self.assertEqual(chart_payload["visibleTaxaCount"], 1)
        self.assertEqual(chart_payload["x_min"], 11)
        self.assertEqual(chart_payload["x_max"], 11)
        self.assertEqual(chart_payload["rows"][0]["taxonName"], "Mammalia")
        self.assertIn("branchExplorerUrl", chart_payload["rows"][0])
        self.assertIn("taxonDetailUrl", chart_payload["rows"][0])

    def test_length_explorer_branch_link_preserves_relevant_filter_state(self):
        response = self.client.get(
            reverse("browser:lengths"),
            {
                "run": "run-alpha",
                "rank": "class",
                "q": "GENE",
                "method": "pure",
                "residue": "q",
                "length_min": "10",
                "length_max": "12",
                "purity_min": "0.9",
                "purity_max": "1.0",
                "min_count": "1",
                "top_n": "10",
            },
        )

        self.assertEqual(response.status_code, 200)

        row = response.context["summary_rows"][0]
        branch_query = parse_qs(urlparse(row["branch_explorer_url"]).query)

        self.assertEqual(branch_query["run"], ["run-alpha"])
        self.assertEqual(branch_query["branch"], [str(row["taxon_id"])])
        self.assertEqual(branch_query["q"], ["GENE"])
        self.assertEqual(branch_query["method"], ["pure"])
        self.assertEqual(branch_query["residue"], ["Q"])
        self.assertEqual(branch_query["length_min"], ["10"])
        self.assertEqual(branch_query["length_max"], ["12"])
        self.assertEqual(branch_query["purity_min"], ["0.9"])
        self.assertEqual(branch_query["purity_max"], ["1.0"])
        self.assertEqual(branch_query["min_count"], ["1"])
        self.assertEqual(branch_query["top_n"], ["10"])
        self.assertEqual(branch_query["rank"], ["order"])
        self.assertEqual(
            response.context["chart_payload"]["rows"][0]["branchExplorerUrl"],
            row["branch_explorer_url"],
        )

    def test_length_explorer_branch_link_steps_to_next_lower_rank(self):
        response = self.client.get(
            reverse("browser:lengths"),
            {
                "rank": "phylum",
                "min_count": "1",
                "top_n": "10",
            },
        )

        self.assertEqual(response.status_code, 200)
        row = response.context["summary_rows"][0]
        branch_query = parse_qs(urlparse(row["branch_explorer_url"]).query)

        self.assertEqual(row["rank"], "phylum")
        self.assertEqual(row["taxon_name"], "Chordata")
        self.assertEqual(branch_query["rank"], ["class"])

    def test_length_explorer_branch_scope_defaults_rank_to_species(self):
        response = self.client.get(
            reverse("browser:lengths"),
            {
                "branch_q": "Prim",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["branch_scope_active"])
        self.assertEqual(response.context["current_branch_q"], "Prim")
        self.assertEqual(response.context["current_rank"], "species")
        self.assertEqual(response.context["matching_repeat_calls_count"], 1)

    def test_length_explorer_branch_scope_can_render_species_summary_rows(self):
        response = self.client.get(
            reverse("browser:lengths"),
            {
                "branch_q": "Prim",
                "min_count": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_rank"], "species")
        self.assertEqual(response.context["visible_taxa_count"], 1)
        self.assertEqual(response.context["summary_rows"][0]["taxon_name"], "Homo sapiens")
        self.assertEqual(response.context["summary_rows"][0]["observation_count"], 1)

    def test_length_explorer_top_n_limits_visible_taxa_but_preserves_total_taxa_count(self):
        self._create_repeat_call(
            self.alpha,
            suffix="human_extra",
            method=RepeatCall.Method.PURE,
            residue="Q",
            length=12,
            purity=1.0,
        )

        response = self.client.get(
            reverse("browser:lengths"),
            {
                "rank": "species",
                "min_count": "1",
                "top_n": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_taxa_count"], 2)
        self.assertEqual(response.context["visible_taxa_count"], 1)
        self.assertEqual(response.context["summary_rows"][0]["taxon_name"], "Homo sapiens")
        self.assertEqual(response.context["summary_rows"][0]["observation_count"], 2)
        self.assertEqual(response.context["chart_payload"]["visibleTaxaCount"], 1)
        self.assertContains(response, "Showing 1 of 2 taxa at rank species.")

    def test_length_explorer_explains_when_matches_exist_but_no_taxa_survive_threshold(self):
        response = self.client.get(
            reverse("browser:lengths"),
            {
                "branch_q": "Prim",
                "min_count": "2",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["matching_repeat_calls_count"], 1)
        self.assertEqual(response.context["visible_taxa_count"], 0)
        self.assertEqual(response.context["summary_rows"], [])
        self.assertContains(
            response,
            "No taxa reached the current display rank and minimum observation threshold.",
        )

    def test_length_chart_assets_are_page_local(self):
        response = self.client.get(reverse("browser:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("browser:lengths"))
        self.assertContains(response, "Repeat lengths")
        self.assertNotContains(response, "repeat-length-explorer.js")
        self.assertNotContains(response, "echarts.min.js")
