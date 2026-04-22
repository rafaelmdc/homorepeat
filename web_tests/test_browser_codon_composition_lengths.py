from django.core.cache import cache
from django.test import TestCase
from django.urls import resolve, reverse
from django.utils import timezone

from apps.browser.catalog import sync_canonical_catalog_for_run
from apps.browser.models import RepeatCall, RepeatCallCodonUsage
from apps.browser.views import CodonCompositionLengthExplorerView

from .support import build_test_repeat_call_values, create_imported_run_fixture


class BrowserCodonCompositionLengthExplorerTests(TestCase):
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
    ):
        repeat_call_values = build_test_repeat_call_values(
            residue=residue,
            length=length,
            purity=purity,
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
        self._sync_run(run_data)
        return repeat_call

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
        self._sync_run(run_data)
        return target_repeat_call

    def test_codon_composition_length_route_uses_stable_view_export(self):
        match = resolve(reverse("browser:codon-composition-length"))

        self.assertIs(match.func.view_class, CodonCompositionLengthExplorerView)

    def test_codon_composition_length_explorer_renders_default_shell(self):
        response = self.client.get(reverse("browser:codon-composition-length"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "browser/codon_composition_length_explorer.html")
        self.assertContains(response, "Residue-scoped codon composition across repeat length bins.")
        self.assertEqual(response.context["current_rank"], "class")
        self.assertEqual(response.context["current_top_n"], 1000)
        self.assertEqual(response.context["current_min_count"], 3)
        self.assertEqual(response.context["matching_repeat_calls_count"], 2)
        self.assertEqual(response.context["total_taxa_count"], 0)
        self.assertEqual(response.context["visible_taxa_count"], 0)
        self.assertEqual(response.context["summary_rows"], [])
        self.assertEqual(response.context["overview_default_mode"], "preference")
        self.assertFalse(response.context["overview_preference_payload"]["available"])
        self.assertFalse(response.context["overview_dominance_payload"]["available"])
        self.assertFalse(response.context["overview_shift_payload"]["available"])
        self.assertFalse(response.context["browse_payload"]["available"])
        self.assertContains(response, "Select a residue to summarize codon composition by length.")
        self.assertContains(response, "Codon preference and transition summaries")
        self.assertContains(response, "Per-taxon composition trajectories")
        self.assertContains(response, "No-JS fallback for the overview and browse layers")
        self.assertContains(response, "codon-composition-length-explorer.js")
        self.assertContains(response, "codon-composition-length-preference-overview-payload")
        self.assertContains(response, "codon-composition-length-browse-payload")

    def test_codon_composition_length_explorer_normalizes_filters(self):
        response = self.client.get(
            reverse("browser:codon-composition-length"),
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
        self.assertContains(
            response,
            "no codon-usage rows were available for the selected residue",
        )

    def test_codon_composition_length_explorer_renders_grouped_taxon_bin_rows(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )
        beta_long_call = self._create_repeat_call(
            self.beta,
            suffix="beta-long-q",
            method=RepeatCall.Method.PURE,
            residue="Q",
            length=17,
            purity=1.0,
        )
        self._set_repeat_call_codon_usages(
            self.beta,
            repeat_call=beta_long_call,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )

        response = self.client.get(
            reverse("browser:codon-composition-length"),
            {
                "rank": "class",
                "min_count": "1",
                "top_n": "10",
                "residue": "q",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["matching_repeat_calls_count"], 3)
        self.assertEqual(response.context["matching_repeat_calls_with_codon_usage_count"], 2)
        self.assertEqual(response.context["total_taxa_count"], 1)
        self.assertEqual(response.context["visible_taxa_count"], 1)
        self.assertEqual(response.context["visible_codons"], ["CAA", "CAG"])
        self.assertEqual(len(response.context["summary_rows"]), 2)
        self.assertEqual(response.context["overview_default_mode"], "preference")
        self.assertTrue(response.context["overview_preference_payload"]["available"])
        self.assertFalse(response.context["overview_dominance_payload"]["available"])
        self.assertTrue(response.context["overview_shift_payload"]["available"])
        self.assertTrue(response.context["browse_payload"]["available"])
        self.assertEqual(response.context["browse_payload"]["shownTaxaCount"], 1)
        self.assertEqual(
            [
                (cell["binLabel"], cell["preference"])
                for cell in response.context["overview_preference_payload"]["cells"]
            ],
            [
                ("10-14", 1),
                ("15-19", -1),
            ],
        )
        self.assertContains(response, "Mammalia")
        self.assertContains(response, "10-14")
        self.assertContains(response, "15-19")
        self.assertContains(response, "CAA 1")
        self.assertContains(response, "CAG 1")

    def test_codon_composition_length_inspect_not_shown_without_branch_scope(self):
        response = self.client.get(
            reverse("browser:codon-composition-length"),
            {"residue": "q"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["inspect_scope_active"])
        self.assertNotContains(response, "Inspect layer")

    def test_codon_composition_length_inspect_shown_with_branch_scope_and_data(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )
        beta_long_call = self._create_repeat_call(
            self.beta,
            suffix="beta-long-q-inspect",
            method="pure",
            residue="Q",
            length=17,
            purity=1.0,
        )
        self._set_repeat_call_codon_usages(
            self.beta,
            repeat_call=beta_long_call,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )

        response = self.client.get(
            reverse("browser:codon-composition-length"),
            {"residue": "q", "min_count": "1", "branch_q": "Mammalia"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["inspect_scope_active"])
        self.assertIn("inspect_observation_count", response.context)
        self.assertGreater(response.context["inspect_observation_count"], 0)
        self.assertIn("inspect_bin_rows", response.context)
        self.assertGreater(len(response.context["inspect_bin_rows"]), 0)
        self.assertTrue(response.context["inspect_payload"]["available"])
        self.assertContains(response, "Inspect layer")
        self.assertContains(response, "codon-composition-length-inspect-payload")
        self.assertContains(response, "Shift from previous")

    def test_codon_composition_length_inspect_empty_without_residue(self):
        response = self.client.get(
            reverse("browser:codon-composition-length"),
            {"branch_q": "Mammalia"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["inspect_scope_active"])
        self.assertEqual(response.context["inspect_observation_count"], 0)
        self.assertFalse(response.context["inspect_payload"]["available"])
        self.assertContains(response, "Inspect layer")
        self.assertContains(response, "codon-usage rows")

    def test_codon_composition_length_inspect_comparison_shown_via_branch_q_single_match(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )

        response = self.client.get(
            reverse("browser:codon-composition-length"),
            {"residue": "q", "min_count": "1", "branch_q": "Mammalia"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["inspect_scope_active"])
        self.assertTrue(response.context["inspect_has_comparison"])
        self.assertIn("Chordata", response.context.get("inspect_comparison_scope_label", ""))

    def test_codon_composition_length_inspect_no_comparison_when_branch_q_unresolved(self):
        response = self.client.get(
            reverse("browser:codon-composition-length"),
            {"residue": "q", "branch_q": "nonexistent-taxon-xyz"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["inspect_scope_active"])
        self.assertFalse(response.context["inspect_has_comparison"])
        self.assertEqual(response.context["inspect_comparison_bin_rows"], [])

    def test_codon_composition_length_inspect_comparison_shown_with_selected_taxon(self):
        from apps.browser.models import Taxon

        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )
        beta_long_call = self._create_repeat_call(
            self.beta,
            suffix="beta-long-q-comp",
            method="pure",
            residue="Q",
            length=17,
            purity=1.0,
        )
        self._set_repeat_call_codon_usages(
            self.beta,
            repeat_call=beta_long_call,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )
        primates_taxon = Taxon.objects.filter(taxon_name="Primates").first()
        if primates_taxon is None:
            return

        response = self.client.get(
            reverse("browser:codon-composition-length"),
            {"residue": "q", "min_count": "1", "branch": str(primates_taxon.pk)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["inspect_scope_active"])
        self.assertIn("inspect_comparison_scope_label", response.context)
        self.assertIn("Mammalia", response.context.get("inspect_comparison_scope_label", ""))
        payload = response.context["inspect_payload"]
        self.assertIn("comparisonBinRows", payload)
        self.assertGreater(len(payload["comparisonBinRows"]), 0)
        self.assertContains(response, "Comparison")
        self.assertContains(response, "Mammalia")

    def test_codon_composition_length_inspect_payload_bin_rows_and_delta(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )
        beta_long_call = self._create_repeat_call(
            self.beta,
            suffix="beta-long-q-delta",
            method="pure",
            residue="Q",
            length=17,
            purity=1.0,
        )
        self._set_repeat_call_codon_usages(
            self.beta,
            repeat_call=beta_long_call,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 6, "codon_fraction": 0.75},
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 2, "codon_fraction": 0.25},
            ],
        )

        response = self.client.get(
            reverse("browser:codon-composition-length"),
            {"residue": "q", "min_count": "1", "branch_q": "Mammalia"},
        )

        self.assertEqual(response.status_code, 200)
        bin_rows = response.context["inspect_bin_rows"]
        self.assertGreater(len(bin_rows), 0)
        self.assertIsNone(bin_rows[0]["delta"])
        if len(bin_rows) > 1:
            self.assertIsNotNone(bin_rows[1]["delta"])

    def test_codon_composition_length_pairwise_payload_structure(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )
        beta_long_call = self._create_repeat_call(
            self.beta,
            suffix="beta-long-q-pairwise",
            method="pure",
            residue="Q",
            length=17,
            purity=1.0,
        )
        self._set_repeat_call_codon_usages(
            self.beta,
            repeat_call=beta_long_call,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )

        response = self.client.get(
            reverse("browser:codon-composition-length"),
            {"residue": "q", "min_count": "1", "rank": "species"},
        )

        self.assertEqual(response.status_code, 200)
        pairwise = response.context["overview_pairwise_payload"]
        self.assertEqual(pairwise["mode"], "pairwise_similarity_matrix")
        self.assertTrue(pairwise["available"])
        self.assertEqual(pairwise["displayMetric"], "divergence")
        n = pairwise["visibleTaxaCount"]
        self.assertGreaterEqual(n, 2)
        self.assertEqual(len(pairwise["divergenceMatrix"]), n)
        self.assertEqual(len(pairwise["divergenceMatrix"][0]), n)
        self.assertEqual(pairwise["divergenceMatrix"][0][0], 0.0)
        self.assertContains(response, "codon-composition-length-pairwise-overview-payload")
