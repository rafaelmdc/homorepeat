from urllib.parse import parse_qs, urlparse

from django.core.cache import cache
from django.test import TestCase
from django.urls import resolve, reverse
from django.utils import timezone

from apps.browser.catalog import sync_canonical_catalog_for_run
from apps.browser.models import RepeatCall
from apps.browser.views import CodonRatioExplorerView

from .support import build_test_repeat_call_values, create_imported_run_fixture


class BrowserCodonRatioExplorerTests(TestCase):
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
        residue,
        codon_metric_name,
        codon_ratio_value,
        method=RepeatCall.Method.PURE,
        length=11,
    ):
        repeat_call_values = build_test_repeat_call_values(
            residue=residue,
            length=length,
            purity=1.0,
            codon_metric_name=codon_metric_name,
            codon_ratio_value=codon_ratio_value,
        )
        repeat_call = RepeatCall.objects.create(
            pipeline_run=run_data["pipeline_run"],
            genome=run_data["genome"],
            sequence=run_data["sequence"],
            protein=run_data["protein"],
            taxon=run_data["taxon"],
            call_id=f"call_{suffix}",
            method=method,
            accession=run_data["genome"].accession,
            gene_symbol=run_data["protein"].gene_symbol or run_data["sequence"].gene_symbol,
            protein_name=run_data["protein"].protein_name,
            protein_length=run_data["protein"].protein_length,
            start=30 + (len(suffix) * 20),
            end=(30 + (len(suffix) * 20)) + length - 1,
            length=length,
            repeat_residue=residue,
            repeat_count=repeat_call_values["repeat_count"],
            non_repeat_count=repeat_call_values["non_repeat_count"],
            purity=1.0,
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

    def _clear_run_codon_ratio_values(self, run_data):
        RepeatCall.objects.filter(pipeline_run=run_data["pipeline_run"]).update(
            codon_metric_name="codon_ratio",
            codon_metric_value="not-a-number",
            codon_ratio_value=None,
        )
        sync_canonical_catalog_for_run(
            run_data["pipeline_run"],
            import_batch=run_data["import_batch"],
            last_seen_at=timezone.now(),
            replace_all_repeat_call_methods=True,
        )
        cache.clear()

    def test_codon_ratio_route_uses_stable_view_export(self):
        match = resolve(reverse("browser:codon-ratios"))

        self.assertIs(match.func.view_class, CodonRatioExplorerView)

    def test_codon_ratio_explorer_renders_with_default_scope(self):
        response = self.client.get(reverse("browser:codon-ratios"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "browser/codon_ratio_explorer.html")
        self.assertContains(response, "Residue-aware codon-ratio browsing over the current catalog.")
        self.assertEqual(response.context["current_rank"], "class")
        self.assertEqual(response.context["current_top_n"], 1000)
        self.assertEqual(response.context["current_min_count"], 3)
        self.assertEqual(response.context["matching_repeat_calls_count"], 2)
        self.assertEqual(response.context["matching_repeat_calls_without_codon_count"], 2)
        self.assertEqual(response.context["total_taxa_count"], 0)
        self.assertEqual(response.context["visible_taxa_count"], 0)
        self.assertEqual(response.context["summary_rows"], [])
        self.assertEqual(response.context["heatmap_payload"]["taxa"], [])
        self.assertEqual(response.context["heatmap_payload"]["bins"], [])
        self.assertEqual(response.context["heatmap_payload"]["cells"], [])
        self.assertEqual(response.context["heatmap_payload"]["visibleTaxaCount"], 0)
        self.assertEqual(response.context["heatmap_payload"]["visibleBinCount"], 0)
        self.assertEqual(response.context["chart_payload"]["rows"], [])
        self.assertEqual(response.context["chart_payload"]["visibleTaxaCount"], 0)
        self.assertEqual(response.context["available_codon_metric_names"], ["codon_ratio"])
        self.assertFalse(response.context["show_codon_metric_selector"])
        self.assertNotContains(response, 'id="id_codon_metric_name"')
        self.assertContains(response, 'id="codon-ratio-heatmap-payload"')
        self.assertContains(response, 'id="codon-ratio-heatmap"')
        self.assertContains(response, 'id="codon-ratio-chart-payload"')
        self.assertContains(response, 'id="codon-ratio-chart"')
        self.assertContains(response, "repeat-codon-ratio-explorer.js")
        self.assertContains(response, "echarts.min.js")
        self.assertContains(response, "Taxon x length-bin codon overview")
        self.assertContains(response, "Ranked codon-ratio distributions for the visible taxa")
        self.assertContains(response, 'data-chart-mode-switch')
        self.assertContains(response, 'data-chart-mode-button')
        self.assertContains(response, 'data-chart-mode="focused"')
        self.assertContains(response, 'data-chart-mode="full-range"')
        self.assertContains(
            response,
            "No taxa reached the current display rank and minimum observation threshold.",
        )

    def test_codon_ratio_explorer_renders_grouped_taxon_summary_rows(self):
        response = self.client.get(
            reverse("browser:codon-ratios"),
            {
                "rank": "class",
                "min_count": "1",
                "top_n": "10",
                "residue": "q",
                "codon_metric_name": "codon_ratio",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_taxa_count"], 1)
        self.assertEqual(response.context["visible_taxa_count"], 1)
        self.assertContains(response, "Grouped taxa")
        self.assertContains(response, "Mammalia")
        self.assertContains(response, "Open branch")
        self.assertContains(response, "Showing 1 of 1 taxa at rank class.")

        summary_rows = response.context["summary_rows"]
        self.assertEqual(len(summary_rows), 1)
        self.assertEqual(summary_rows[0]["taxon_name"], "Mammalia")
        self.assertEqual(summary_rows[0]["rank"], "class")
        self.assertEqual(summary_rows[0]["observation_count"], 2)
        self.assertEqual(summary_rows[0]["min_codon_ratio"], 1.25)
        self.assertEqual(summary_rows[0]["median"], 1.25)
        self.assertEqual(summary_rows[0]["max_codon_ratio"], 1.25)
        heatmap_payload = response.context["heatmap_payload"]
        self.assertEqual(heatmap_payload["visibleTaxaCount"], 1)
        self.assertEqual(heatmap_payload["visibleBinCount"], 1)
        self.assertEqual(heatmap_payload["taxa"][0]["taxonName"], "Mammalia")
        self.assertEqual(heatmap_payload["bins"][0]["label"], "10-14")
        self.assertEqual(heatmap_payload["cells"][0]["value"], 1.25)
        chart_payload = response.context["chart_payload"]
        self.assertEqual(chart_payload["visibleTaxaCount"], 1)
        self.assertEqual(chart_payload["x_min"], 1.25)
        self.assertEqual(chart_payload["x_max"], 1.25)
        self.assertEqual(chart_payload["rows"][0]["taxonName"], "Mammalia")
        self.assertIn("branchExplorerUrl", chart_payload["rows"][0])
        self.assertIn("taxonDetailUrl", chart_payload["rows"][0])

    def test_codon_ratio_explorer_renders_overview_heatmap_payload(self):
        self._create_repeat_call(
            self.beta,
            suffix="beta_long_ratio",
            residue="Q",
            codon_metric_name="codon_ratio",
            codon_ratio_value=0.8,
            length=22,
        )

        response = self.client.get(
            reverse("browser:codon-ratios"),
            {
                "rank": "species",
                "min_count": "1",
                "top_n": "10",
                "residue": "q",
                "codon_metric_name": "codon_ratio",
            },
        )

        self.assertEqual(response.status_code, 200)
        heatmap_payload = response.context["heatmap_payload"]
        self.assertEqual(heatmap_payload["visibleTaxaCount"], 2)
        self.assertEqual(heatmap_payload["visibleBinCount"], 3)
        self.assertEqual(
            [taxon["taxonName"] for taxon in heatmap_payload["taxa"]],
            ["Homo sapiens", "Mus musculus"],
        )
        self.assertEqual(
            [length_bin["label"] for length_bin in heatmap_payload["bins"]],
            ["10-14", "15-19", "20-24"],
        )
        self.assertEqual(
            heatmap_payload["seriesData"],
            [
                [0, 0, 1.25],
                [0, 1, 1.25],
                [2, 1, 0.8],
            ],
        )

    def test_codon_ratio_explorer_branch_link_preserves_relevant_filter_state(self):
        response = self.client.get(
            reverse("browser:codon-ratios"),
            {
                "run": "run-alpha",
                "rank": "class",
                "q": "GENE",
                "method": "pure",
                "residue": "q",
                "codon_metric_name": "codon_ratio",
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
        self.assertEqual(branch_query["codon_metric_name"], ["codon_ratio"])
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

    def test_codon_ratio_explorer_shows_metric_selector_only_when_scope_has_multiple_metrics(self):
        self._create_repeat_call(
            self.alpha,
            suffix="alpha_alt_ratio",
            residue="Q",
            codon_metric_name="alt_ratio",
            codon_ratio_value=0.9,
        )

        response = self.client.get(
            reverse("browser:codon-ratios"),
            {
                "run": "run-alpha",
                "branch": str(self.alpha["taxa"]["primates"].pk),
                "residue": "q",
                "min_count": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["show_codon_metric_selector"])
        self.assertEqual(response.context["available_codon_metric_names"], ["alt_ratio", "codon_ratio"])
        self.assertContains(response, 'id="id_codon_metric_name"')
        self.assertContains(response, '<option value="">All numeric metrics</option>', html=True)
        self.assertContains(response, '<option value="alt_ratio">alt_ratio</option>', html=True)
        self.assertContains(response, '<option value="codon_ratio">codon_ratio</option>', html=True)

    def test_codon_ratio_explorer_explains_when_scope_has_calls_but_no_numeric_codon_data(self):
        gamma = create_imported_run_fixture(
            run_id="run-gamma",
            genome_id="genome_gamma",
            sequence_id="seq_gamma",
            protein_id="prot_gamma",
            call_id="call_gamma",
            accession="GCF_GAMMA",
            taxon_key="human",
            genome_name="Gamma genome",
        )
        self._clear_run_codon_ratio_values(gamma)

        response = self.client.get(
            reverse("browser:codon-ratios"),
            {
                "run": "run-gamma",
                "min_count": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["matching_repeat_calls_without_codon_count"], 1)
        self.assertEqual(response.context["matching_repeat_calls_count"], 0)
        self.assertEqual(response.context["visible_taxa_count"], 0)
        self.assertContains(
            response,
            "Canonical repeat calls matched these filters, but none carried numeric codon ratios.",
        )

    def test_codon_ratio_chart_assets_are_page_local(self):
        response = self.client.get(reverse("browser:home"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "repeat-codon-ratio-explorer.js")
        self.assertNotContains(response, "echarts.min.js")
