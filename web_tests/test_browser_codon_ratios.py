from urllib.parse import parse_qs, urlparse

from django.core.cache import cache
from django.test import TestCase
from django.urls import resolve, reverse
from django.utils import timezone

from apps.browser.catalog import sync_canonical_catalog_for_run
from apps.browser.models import RepeatCallCodonUsage
from apps.browser.views import CodonRatioExplorerView

from .support import create_imported_run_fixture


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

    def _sync_run(self, run_data):
        sync_canonical_catalog_for_run(
            run_data["pipeline_run"],
            import_batch=run_data["import_batch"],
            last_seen_at=timezone.now(),
            replace_all_repeat_call_methods=True,
        )
        cache.clear()

    def _set_repeat_call_codon_usages(self, run_data, *, rows):
        RepeatCallCodonUsage.objects.filter(repeat_call=run_data["repeat_call"]).delete()
        RepeatCallCodonUsage.objects.bulk_create(
            [
                RepeatCallCodonUsage(
                    repeat_call=run_data["repeat_call"],
                    amino_acid=row["amino_acid"],
                    codon=row["codon"],
                    codon_count=row["codon_count"],
                    codon_fraction=row["codon_fraction"],
                )
                for row in rows
            ]
        )
        self._sync_run(run_data)

    def test_codon_ratio_route_uses_stable_view_export(self):
        match = resolve(reverse("browser:codon-ratios"))

        self.assertIs(match.func.view_class, CodonRatioExplorerView)

    def test_codon_ratio_explorer_renders_with_default_scope(self):
        response = self.client.get(reverse("browser:codon-ratios"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "browser/codon_ratio_explorer.html")
        self.assertContains(response, "Residue-scoped codon composition across the current catalog.")
        self.assertEqual(response.context["current_rank"], "class")
        self.assertEqual(response.context["current_top_n"], 1000)
        self.assertEqual(response.context["current_min_count"], 3)
        self.assertEqual(response.context["matching_repeat_calls_count"], 2)
        self.assertEqual(response.context["matching_repeat_calls_with_codon_usage_count"], 0)
        self.assertEqual(response.context["total_taxa_count"], 0)
        self.assertEqual(response.context["visible_taxa_count"], 0)
        self.assertEqual(response.context["summary_rows"], [])
        self.assertEqual(response.context["visible_codons"], [])
        self.assertEqual(response.context["overview_payload"]["taxa"], [])
        self.assertEqual(response.context["overview_payload"]["codons"], [])
        self.assertEqual(response.context["chart_payload"]["rows"], [])
        self.assertIsNone(response.context["overview_taxonomy_gutter_payload"]["root"])
        self.assertEqual(response.context["overview_taxonomy_gutter_payload"]["nodes"], [])
        self.assertEqual(response.context["overview_taxonomy_gutter_payload"]["leaves"], [])
        self.assertIsNone(response.context["chart_taxonomy_gutter_payload"]["root"])
        self.assertEqual(response.context["chart_taxonomy_gutter_payload"]["nodes"], [])
        self.assertEqual(response.context["chart_taxonomy_gutter_payload"]["leaves"], [])
        self.assertFalse(response.context["inspect_scope_active"])
        self.assertNotContains(response, 'id="id_codon_metric_name"')
        self.assertNotContains(response, "All numeric metrics")
        self.assertContains(response, 'id="codon-composition-overview-payload"')
        self.assertContains(response, 'id="codon-composition-overview-taxonomy-gutter-payload"')
        self.assertContains(response, 'id="codon-composition-overview"')
        self.assertContains(response, 'id="codon-composition-chart-payload"')
        self.assertContains(response, 'id="codon-composition-chart-taxonomy-gutter-payload"')
        self.assertContains(response, 'id="codon-composition-chart"')
        self.assertContains(response, "Taxon x codon overview")
        self.assertContains(response, "Stacked codon composition for the visible taxa")
        self.assertContains(response, "Select a residue to browse codon composition.")
        self.assertContains(response, "taxonomy-gutter.js")
        self.assertContains(response, "repeat-codon-ratio-explorer.js")
        self.assertContains(response, "echarts.min.js")

    def test_codon_ratio_explorer_renders_grouped_taxon_summary_rows(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "D", "codon": "GAC", "codon_count": 1, "codon_fraction": 1.0},
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )
        self._set_repeat_call_codon_usages(
            self.beta,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 1, "codon_fraction": 0.25},
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 3, "codon_fraction": 0.75},
            ],
        )

        response = self.client.get(
            reverse("browser:codon-ratios"),
            {
                "rank": "class",
                "min_count": "1",
                "top_n": "10",
                "residue": "q",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_taxa_count"], 1)
        self.assertEqual(response.context["visible_taxa_count"], 1)
        self.assertEqual(response.context["matching_repeat_calls_with_codon_usage_count"], 2)
        self.assertEqual(response.context["visible_codons"], ["CAA", "CAG"])
        self.assertContains(response, "Grouped taxa")
        self.assertContains(response, "Mammalia")
        self.assertContains(response, "Open branch")
        self.assertContains(response, "0.625")
        self.assertContains(response, "0.375")

        summary_rows = response.context["summary_rows"]
        self.assertEqual(len(summary_rows), 1)
        self.assertEqual(summary_rows[0]["taxon_name"], "Mammalia")
        self.assertEqual(summary_rows[0]["rank"], "class")
        self.assertEqual(summary_rows[0]["observation_count"], 2)
        self.assertEqual(
            summary_rows[0]["codon_shares"],
            [
                {"codon": "CAA", "share": 0.625},
                {"codon": "CAG", "share": 0.375},
            ],
        )

    def test_codon_ratio_explorer_browse_payload_uses_lineage_order_for_visible_taxa(self):
        gamma = create_imported_run_fixture(
            run_id="run-gamma",
            genome_id="genome_gamma",
            sequence_id="seq_gamma",
            protein_id="prot_gamma",
            call_id="call_gamma",
            accession="GCF_GAMMA",
            taxon_key="fruit_fly",
            genome_name="Fruit fly reference genome",
        )
        delta = create_imported_run_fixture(
            run_id="run-delta",
            genome_id="genome_delta",
            sequence_id="seq_delta",
            protein_id="prot_delta",
            call_id="call_delta",
            accession="GCF_DELTA",
            taxon_key="house_spider",
            genome_name="Spider reference genome",
        )

        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 2, "codon_fraction": 1.0},
            ],
        )
        self._set_repeat_call_codon_usages(
            self.beta,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 2, "codon_fraction": 1.0},
            ],
        )
        self._set_repeat_call_codon_usages(
            gamma,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 2, "codon_fraction": 1.0},
            ],
        )
        self._set_repeat_call_codon_usages(
            delta,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 2, "codon_fraction": 1.0},
            ],
        )

        response = self.client.get(
            reverse("browser:codon-ratios"),
            {
                "rank": "class",
                "min_count": "1",
                "top_n": "10",
                "residue": "q",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["taxon_name"] for row in response.context["summary_rows"]],
            ["Arachnida", "Insecta", "Mammalia"],
        )
        self.assertEqual(
            [row["observation_count"] for row in response.context["summary_rows"]],
            [1, 1, 2],
        )
        self.assertEqual(
            [row["taxonName"] for row in response.context["chart_payload"]["rows"]],
            ["Arachnida", "Insecta", "Mammalia"],
        )
        self.assertEqual(
            [row["taxonName"] for row in response.context["overview_payload"]["taxa"]],
            ["Arachnida", "Insecta", "Mammalia"],
        )

    def test_codon_ratio_explorer_renders_overview_heatmap_payload(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 2, "codon_fraction": 0.5},
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 2, "codon_fraction": 0.5},
            ],
        )
        self._set_repeat_call_codon_usages(
            self.beta,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 4, "codon_fraction": 1.0},
            ],
        )

        response = self.client.get(
            reverse("browser:codon-ratios"),
            {
                "rank": "species",
                "min_count": "1",
                "top_n": "10",
                "residue": "q",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.context["overview_payload"]
        self.assertEqual(payload["visibleTaxaCount"], 2)
        self.assertEqual(payload["visibleCodonCount"], 2)
        self.assertEqual(
            [taxon["taxonName"] for taxon in payload["taxa"]],
            ["Homo sapiens", "Mus musculus"],
        )
        self.assertEqual(
            [codon["codon"] for codon in payload["codons"]],
            ["CAA", "CAG"],
        )
        self.assertEqual(
            payload["seriesData"],
            [
                [0, 0, 0.5],
                [1, 0, 0.5],
                [0, 1, 0],
                [1, 1, 1],
            ],
        )
        gutter_payload = response.context["overview_taxonomy_gutter_payload"]
        self.assertEqual(
            gutter_payload["root"],
            {
                "nodeId": f"taxon-{self.alpha['taxa']['mammalia'].pk}",
                "taxonId": self.alpha["taxa"]["mammalia"].pk,
                "taxonName": "Mammalia",
                "rank": "class",
                "depth": 0,
            },
        )
        self.assertEqual(gutter_payload["maxDepth"], 2)
        self.assertEqual(
            [node["taxonName"] for node in gutter_payload["nodes"]],
            ["Mammalia", "Primates", "Homo sapiens", "Mus musculus"],
        )
        self.assertEqual(
            gutter_payload["edges"],
            [
                {
                    "parentNodeId": f"taxon-{self.alpha['taxa']['mammalia'].pk}",
                    "childNodeId": f"taxon-{self.alpha['taxa']['primates'].pk}",
                },
                {
                    "parentNodeId": f"taxon-{self.alpha['taxa']['primates'].pk}",
                    "childNodeId": f"taxon-{self.alpha['taxa']['human'].pk}",
                },
                {
                    "parentNodeId": f"taxon-{self.alpha['taxa']['mammalia'].pk}",
                    "childNodeId": f"taxon-{self.beta['taxa']['mouse'].pk}",
                },
            ],
        )
        self.assertEqual(
            [leaf["taxonName"] for leaf in gutter_payload["leaves"]],
            ["Homo sapiens", "Mus musculus"],
        )
        self.assertEqual(
            [leaf["braceLabel"] for leaf in gutter_payload["leaves"]],
            ["", ""],
        )
        self.assertNotIn("columns", gutter_payload)
        self.assertNotIn("segments", gutter_payload)
        self.assertNotIn("rows", gutter_payload)
        self.assertNotIn("terminals", gutter_payload)

    def test_codon_ratio_explorer_renders_branch_scoped_inspect_section(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 3, "codon_fraction": 0.3},
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 7, "codon_fraction": 0.7},
            ],
        )

        response = self.client.get(
            reverse("browser:codon-ratios"),
            {
                "run": "run-alpha",
                "branch": str(self.alpha["taxa"]["primates"].pk),
                "rank": "species",
                "residue": "q",
                "min_count": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["inspect_scope_active"])
        self.assertContains(response, "Inspect layer")
        self.assertContains(response, "Codon composition for Primates")
        self.assertContains(response, 'id="codon-composition-inspect-payload"')
        self.assertContains(response, 'id="codon-composition-inspect-chart"')
        self.assertEqual(
            response.context["inspect_payload"],
            {
                "scopeLabel": "Order Primates",
                "observationCount": 1,
                "visibleCodons": ["CAA", "CAG"],
                "codonShares": [
                    {"codon": "CAA", "share": 0.3},
                    {"codon": "CAG", "share": 0.7},
                ],
                "maxShare": 0.7,
            },
        )

    def test_codon_ratio_explorer_branch_link_preserves_relevant_filter_state(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 11, "codon_fraction": 1.0},
            ],
        )

        response = self.client.get(
            reverse("browser:codon-ratios"),
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
        self.assertNotIn("codon_metric_name", branch_query)
        self.assertEqual(
            response.context["chart_payload"]["rows"][0]["branchExplorerUrl"],
            row["branch_explorer_url"],
        )

    def test_codon_ratio_explorer_explains_when_scope_has_calls_but_no_residue_codon_usage(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "D", "codon": "GAC", "codon_count": 1, "codon_fraction": 1.0},
            ],
        )

        response = self.client.get(
            reverse("browser:codon-ratios"),
            {
                "run": "run-alpha",
                "residue": "q",
                "min_count": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["matching_repeat_calls_with_codon_usage_count"], 0)
        self.assertEqual(response.context["visible_taxa_count"], 0)
        self.assertContains(
            response,
            "Canonical repeat calls matched these filters, but no codon-usage rows were available for the selected residue.",
        )

    def test_codon_ratio_chart_assets_are_page_local(self):
        response = self.client.get(reverse("browser:home"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "repeat-codon-ratio-explorer.js")
        self.assertNotContains(response, "echarts.min.js")
