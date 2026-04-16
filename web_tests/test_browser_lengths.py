from django.test import TestCase
from django.urls import reverse

from .support import create_imported_run_fixture


class BrowserLengthExplorerTests(TestCase):
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

    def test_length_explorer_renders_with_default_scope(self):
        response = self.client.get(reverse("browser:lengths"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "browser/repeat_length_explorer.html")
        self.assertContains(response, "Lineage-aware repeat length exploration over the current catalog.")
        self.assertEqual(response.context["current_rank"], "class")
        self.assertEqual(response.context["current_top_n"], 25)
        self.assertEqual(response.context["current_min_count"], 3)
        self.assertEqual(response.context["matching_repeat_calls_count"], 2)
        self.assertEqual(response.context["visible_taxa_count"], 0)
        self.assertEqual(response.context["summary_rows"], [])
        self.assertEqual(response.context["chart_payload"]["rows"], [])
        self.assertEqual(response.context["chart_payload"]["visibleTaxaCount"], 0)
        self.assertContains(response, 'id="repeat-length-chart-payload"')
        self.assertContains(response, 'id="repeat-length-chart"')
        self.assertContains(response, "repeat-length-explorer.js")
        self.assertContains(response, "echarts.min.js")
        self.assertContains(response, "Ranked length distributions for the visible taxa")
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
                "top_n": "999",
                "min_count": "0",
                "length_min": "bad",
                "length_max": "12",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_run_id"], "run-beta")
        self.assertEqual(response.context["current_residue"], "Q")
        self.assertEqual(response.context["current_top_n"], 100)
        self.assertEqual(response.context["current_min_count"], 1)
        self.assertIsNone(response.context["current_length_min"])
        self.assertEqual(response.context["current_length_max"], 12)
        self.assertEqual(response.context["matching_repeat_calls_count"], 1)

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
        self.assertEqual(response.context["visible_taxa_count"], 1)
        self.assertContains(response, "Grouped taxa")
        self.assertContains(response, "Mammalia")
        self.assertContains(response, "Open branch")

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
        chart_payload = response.context["chart_payload"]
        self.assertEqual(chart_payload["visibleTaxaCount"], 1)
        self.assertEqual(chart_payload["x_min"], 11)
        self.assertEqual(chart_payload["x_max"], 11)
        self.assertEqual(chart_payload["rows"][0]["taxonName"], "Mammalia")
        self.assertIn("branchExplorerUrl", chart_payload["rows"][0])
        self.assertIn("taxonDetailUrl", chart_payload["rows"][0])

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
        self.assertNotContains(response, "repeat-length-explorer.js")
        self.assertNotContains(response, "echarts.min.js")
