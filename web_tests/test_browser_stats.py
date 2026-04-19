from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.utils import timezone

from apps.browser.catalog import sync_canonical_catalog_for_run
from django.core.cache import cache
from django.test import RequestFactory, TestCase

from apps.browser.stats import (
    apply_stats_filter_context,
    build_filtered_codon_usage_queryset,
    build_codon_overview_payload,
    build_group_codon_species_call_fraction_queryset,
    build_filtered_repeat_call_queryset,
    build_group_length_values_queryset,
    build_matching_repeat_calls_with_codon_usage_count,
    build_ranked_codon_composition_summary_bundle,
    build_ranked_length_chart_payload,
    build_ranked_length_summary_bundle,
    build_ranked_taxon_group_queryset,
    build_stats_filter_state,
    build_taxonomy_gutter_payload,
    summarize_ranked_codon_composition_groups,
    summarize_ranked_length_groups,
)
from apps.browser.models import (
    CanonicalCodonCompositionSummary,
    CanonicalRepeatCall,
    RepeatCall,
    RepeatCallCodonUsage,
)

from .support import build_test_repeat_call_values, create_imported_run_fixture


class BrowserStatsTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
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
        length=11,
        method=RepeatCall.Method.PURE,
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
            codon_metric_name=codon_metric_name,
            codon_metric_value=repeat_call_values["codon_metric_value"],
            codon_ratio_value=repeat_call_values["codon_ratio_value"],
        )
        sync_canonical_catalog_for_run(
            run_data["pipeline_run"],
            import_batch=run_data["import_batch"],
            last_seen_at=timezone.now(),
            replace_all_repeat_call_methods=True,
        )
        return repeat_call

    def _sync_run(self, run_data):
        sync_canonical_catalog_for_run(
            run_data["pipeline_run"],
            import_batch=run_data["import_batch"],
            last_seen_at=timezone.now(),
            replace_all_repeat_call_methods=True,
        )

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

    def test_stats_filter_state_defaults_without_branch_scope(self):
        request = self.factory.get("/browser/lengths/")

        filter_state = build_stats_filter_state(request)

        self.assertEqual(filter_state.current_run_id, "")
        self.assertFalse(filter_state.branch_scope_active)
        self.assertEqual(filter_state.rank, "class")
        self.assertEqual(filter_state.top_n, 1000)
        self.assertEqual(filter_state.min_count, 3)
        self.assertEqual(filter_state.cache_key_data()["rank"], "class")

    def test_stats_filter_state_clamps_and_uses_branch_defaults(self):
        primates = self.alpha["taxa"]["primates"]
        request = self.factory.get(
            "/browser/lengths/",
            {
                "branch": str(primates.pk),
                "rank": "bogus",
                "q": "GENE",
                "method": "pure",
                "residue": "q",
                "length_min": "7",
                "length_max": "12",
                "purity_min": "0.8",
                "purity_max": "1.0",
                "min_count": "0",
                "top_n": "9999",
            },
        )

        filter_state = build_stats_filter_state(request)

        self.assertTrue(filter_state.branch_scope_active)
        self.assertEqual(filter_state.rank, "species")
        self.assertEqual(filter_state.current_branch, str(primates.pk))
        self.assertEqual(filter_state.current_branch_input, str(primates.taxon_id))
        self.assertEqual(filter_state.q, "GENE")
        self.assertEqual(filter_state.method, "pure")
        self.assertEqual(filter_state.residue, "Q")
        self.assertEqual(filter_state.length_min, 7)
        self.assertEqual(filter_state.length_max, 12)
        self.assertEqual(filter_state.purity_min, 0.8)
        self.assertEqual(filter_state.purity_max, 1.0)
        self.assertEqual(filter_state.min_count, 1)
        self.assertEqual(filter_state.top_n, 2000)

        context = apply_stats_filter_context({}, filter_state)
        self.assertEqual(context["current_method"], "pure")
        self.assertEqual(context["current_residue"], "Q")

    def test_ranked_taxon_group_query_rolls_up_and_summarizes_lengths(self):
        request = self.factory.get(
            "/browser/lengths/",
            {
                "rank": "class",
                "min_count": "1",
                "top_n": "10",
            },
        )
        filter_state = build_stats_filter_state(request)

        group_rows = list(build_ranked_taxon_group_queryset(filter_state))

        self.assertEqual(len(group_rows), 1)
        self.assertEqual(group_rows[0]["display_taxon_name"], "Mammalia")
        self.assertEqual(group_rows[0]["display_taxon_rank"], "class")
        self.assertEqual(group_rows[0]["observation_count"], 2)

        grouped_lengths = list(
            build_group_length_values_queryset(
                filter_state,
                display_taxon_ids=[group_rows[0]["display_taxon_id"]],
            )
        )
        summary_rows = summarize_ranked_length_groups(group_rows, grouped_lengths)
        payload = build_ranked_length_chart_payload(summary_rows)

        self.assertEqual(
            summary_rows,
            [
                {
                    "taxon_id": group_rows[0]["display_taxon_id"],
                    "taxon_name": "Mammalia",
                    "rank": "class",
                    "observation_count": 2,
                    "min_length": 11,
                    "q1": 11,
                    "median": 11,
                    "q3": 11,
                    "max_length": 11,
                }
            ],
        )
        self.assertEqual(payload["x_min"], 11)
        self.assertEqual(payload["x_max"], 11)
        self.assertEqual(payload["max_observation_count"], 2)

    def test_ranked_taxon_group_query_respects_branch_scope_default_rank(self):
        primates = self.alpha["taxa"]["primates"]
        request = self.factory.get(
            "/browser/lengths/",
            {
                "branch": str(primates.pk),
                "min_count": "1",
            },
        )
        filter_state = build_stats_filter_state(request)

        group_rows = list(build_ranked_taxon_group_queryset(filter_state))

        self.assertEqual(filter_state.rank, "species")
        self.assertEqual(len(group_rows), 1)
        self.assertEqual(group_rows[0]["display_taxon_name"], "Homo sapiens")
        self.assertEqual(group_rows[0]["observation_count"], 1)

    def test_ranked_length_summary_bundle_caches_visible_results(self):
        request = self.factory.get(
            "/browser/lengths/",
            {
                "rank": "class",
                "min_count": "1",
                "top_n": "10",
            },
        )
        filter_state = build_stats_filter_state(request)

        first_bundle = build_ranked_length_summary_bundle(filter_state)

        self.assertEqual(first_bundle["matching_repeat_calls_count"], 2)
        self.assertEqual(first_bundle["total_taxa_count"], 1)
        self.assertEqual(first_bundle["visible_taxa_count"], 1)
        self.assertEqual(first_bundle["summary_rows"][0]["taxon_name"], "Mammalia")

        with patch(
            "apps.browser.stats.queries.build_filtered_repeat_call_queryset",
            side_effect=AssertionError("expected cached summary bundle"),
        ):
            second_bundle = build_ranked_length_summary_bundle(filter_state)

        self.assertEqual(second_bundle, first_bundle)

    def test_imported_run_fixture_populates_residue_specific_codon_defaults(self):
        gamma = create_imported_run_fixture(
            run_id="run-gamma",
            genome_id="genome_gamma",
            sequence_id="seq_gamma",
            protein_id="prot_gamma",
            call_id="call_gamma",
            accession="GCF_GAMMA",
            taxon_key="human",
            repeat_residue="A",
        )

        repeat_call = gamma["repeat_call"]
        canonical_repeat_call = CanonicalRepeatCall.objects.get(latest_repeat_call=repeat_call)

        self.assertEqual(gamma["run_parameter"].repeat_residue, "A")
        self.assertEqual(gamma["accession_call_count"].repeat_residue, "A")
        self.assertEqual(repeat_call.repeat_residue, "A")
        self.assertEqual(repeat_call.codon_metric_name, "codon_ratio")
        self.assertEqual(repeat_call.codon_metric_value, "0.75")
        self.assertEqual(repeat_call.codon_ratio_value, 0.75)
        self.assertEqual(repeat_call.codon_sequence, "GCT" * 11)
        self.assertEqual(canonical_repeat_call.repeat_residue, "A")
        self.assertEqual(canonical_repeat_call.codon_ratio_value, 0.75)

    def test_codon_composition_requires_residue_scope(self):
        filter_state = build_stats_filter_state(
            self.factory.get(
                "/browser/codon-ratios/",
            )
        )

        self.assertEqual(build_filtered_codon_usage_queryset(filter_state).count(), 0)
        self.assertEqual(build_ranked_codon_composition_summary_bundle(filter_state)["summary_rows"], [])

    def test_filtered_codon_usage_queryset_only_includes_selected_residue_codons(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "D", "codon": "GAC", "codon_count": 1, "codon_fraction": 1.0},
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 3, "codon_fraction": 0.3},
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 7, "codon_fraction": 0.7},
            ],
        )

        filter_state = build_stats_filter_state(
            self.factory.get(
                "/browser/codon-ratios/",
                {
                    "run": "run-alpha",
                    "branch": str(self.alpha["taxa"]["primates"].pk),
                    "residue": "q",
                },
            )
        )

        self.assertEqual(
            list(build_filtered_codon_usage_queryset(filter_state).values_list("amino_acid", "codon")),
            [("Q", "CAA"), ("Q", "CAG")],
        )

    def test_ranked_codon_composition_summary_bundle_rolls_up_two_codon_residue(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
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

        filter_state = build_stats_filter_state(
            self.factory.get(
                "/browser/codon-ratios/",
                {
                    "rank": "class",
                    "min_count": "1",
                    "top_n": "10",
                    "residue": "q",
                },
            )
        )

        bundle = build_ranked_codon_composition_summary_bundle(filter_state)

        self.assertEqual(bundle["matching_repeat_calls_count"], 2)
        self.assertEqual(bundle["total_taxa_count"], 1)
        self.assertEqual(bundle["visible_taxa_count"], 1)
        self.assertEqual(bundle["visible_codons"], ["CAA", "CAG"])
        self.assertEqual(
            bundle["summary_rows"],
            [
                {
                    "taxon_id": self.alpha["taxa"]["mammalia"].pk,
                    "taxon_name": "Mammalia",
                    "rank": "class",
                    "observation_count": 2,
                    "species_count": 2,
                    "codon_shares": [
                        {"codon": "CAA", "share": 0.625},
                        {"codon": "CAG", "share": 0.375},
                    ],
                }
            ],
        )

    def test_ranked_codon_composition_summary_bundle_supports_four_codon_residue(self):
        alpha_alanine = self._create_repeat_call(
            self.alpha,
            suffix="alpha_alanine_composition",
            residue="A",
            codon_metric_name="alanine_ratio",
            codon_ratio_value=0.7,
        )
        beta_alanine = self._create_repeat_call(
            self.beta,
            suffix="beta_alanine_composition",
            residue="A",
            codon_metric_name="alanine_ratio",
            codon_ratio_value=0.6,
        )
        self._set_repeat_call_codon_usages(
            self.alpha,
            repeat_call=alpha_alanine,
            rows=[
                {"amino_acid": "A", "codon": "GCA", "codon_count": 2, "codon_fraction": 0.5},
                {"amino_acid": "A", "codon": "GCC", "codon_count": 2, "codon_fraction": 0.5},
            ],
        )
        self._set_repeat_call_codon_usages(
            self.beta,
            repeat_call=beta_alanine,
            rows=[
                {"amino_acid": "A", "codon": "GCG", "codon_count": 2, "codon_fraction": 0.5},
                {"amino_acid": "A", "codon": "GCT", "codon_count": 2, "codon_fraction": 0.5},
            ],
        )

        filter_state = build_stats_filter_state(
            self.factory.get(
                "/browser/codon-ratios/",
                {
                    "rank": "class",
                    "min_count": "1",
                    "top_n": "10",
                    "residue": "a",
                },
            )
        )

        bundle = build_ranked_codon_composition_summary_bundle(filter_state)

        self.assertEqual(bundle["visible_codons"], ["GCA", "GCC", "GCG", "GCT"])
        self.assertEqual(
            bundle["summary_rows"],
            [
                {
                    "taxon_id": self.alpha["taxa"]["mammalia"].pk,
                    "taxon_name": "Mammalia",
                    "rank": "class",
                    "observation_count": 2,
                    "species_count": 2,
                    "codon_shares": [
                        {"codon": "GCA", "share": 0.25},
                        {"codon": "GCC", "share": 0.25},
                        {"codon": "GCG", "share": 0.25},
                        {"codon": "GCT", "share": 0.25},
                    ],
                }
            ],
        )

    def test_ranked_codon_composition_summary_bundle_uses_equal_species_weight(self):
        alpha_extra = self._create_repeat_call(
            self.alpha,
            suffix="alpha_species_weight",
            residue="Q",
            codon_metric_name="codon_ratio",
            codon_ratio_value=0.0,
        )
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 12, "codon_fraction": 1.0},
            ],
        )
        self._set_repeat_call_codon_usages(
            self.alpha,
            repeat_call=alpha_extra,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 12, "codon_fraction": 1.0},
            ],
        )
        self._set_repeat_call_codon_usages(
            self.beta,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 2, "codon_fraction": 1.0},
            ],
        )

        filter_state = build_stats_filter_state(
            self.factory.get(
                "/browser/codon-ratios/",
                {
                    "rank": "class",
                    "min_count": "1",
                    "residue": "q",
                },
            )
        )

        bundle = build_ranked_codon_composition_summary_bundle(filter_state)

        self.assertEqual(bundle["summary_rows"][0]["observation_count"], 3)
        self.assertEqual(bundle["summary_rows"][0]["species_count"], 2)
        self.assertEqual(
            bundle["summary_rows"][0]["codon_shares"],
            [
                {"codon": "CAA", "share": 0.25},
                {"codon": "CAG", "share": 0.75},
            ],
        )

    def test_matching_repeat_calls_with_codon_usage_count_respects_selected_residue(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 4, "codon_fraction": 1.0},
            ],
        )
        self._set_repeat_call_codon_usages(
            self.beta,
            rows=[
                {"amino_acid": "D", "codon": "GAC", "codon_count": 4, "codon_fraction": 1.0},
            ],
        )

        filter_state = build_stats_filter_state(
            self.factory.get(
                "/browser/codon-ratios/",
                {
                    "rank": "class",
                    "min_count": "1",
                    "residue": "q",
                },
            )
        )

        self.assertEqual(build_matching_repeat_calls_with_codon_usage_count(filter_state), 1)

    def test_canonical_codon_composition_summaries_are_rebuilt_during_sync(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
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

        mammalia_rows = list(
            CanonicalCodonCompositionSummary.objects.filter(
                repeat_residue="Q",
                display_rank="class",
                display_taxon=self.alpha["taxa"]["mammalia"],
            )
            .order_by("codon")
            .values(
                "display_taxon_name",
                "observation_count",
                "species_count",
                "codon",
                "codon_share",
            )
        )
        human_rows = list(
            CanonicalCodonCompositionSummary.objects.filter(
                repeat_residue="Q",
                display_rank="species",
                display_taxon=self.alpha["taxa"]["human"],
            )
            .order_by("codon")
            .values("codon", "codon_share")
        )

        self.assertEqual(
            mammalia_rows,
            [
                {
                    "display_taxon_name": "Mammalia",
                    "observation_count": 2,
                    "species_count": 2,
                    "codon": "CAA",
                    "codon_share": 0.625,
                },
                {
                    "display_taxon_name": "Mammalia",
                    "observation_count": 2,
                    "species_count": 2,
                    "codon": "CAG",
                    "codon_share": 0.375,
                },
            ],
        )
        self.assertEqual(
            human_rows,
            [
                {"codon": "CAA", "codon_share": 1.0},
                {"codon": "CAG", "codon_share": 0.0},
            ],
        )

    def test_backfill_codon_composition_summaries_command_rebuilds_rows(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )

        CanonicalCodonCompositionSummary.objects.all().delete()
        stdout = StringIO()

        call_command("backfill_codon_composition_summaries", stdout=stdout)

        self.assertGreater(CanonicalCodonCompositionSummary.objects.count(), 0)
        self.assertIn("Rebuilt codon composition summaries", stdout.getvalue())

    def test_ranked_codon_composition_summary_bundle_uses_postgresql_fast_path(self):
        filter_state = build_stats_filter_state(
            self.factory.get(
                "/browser/codon-ratios/",
                {
                    "rank": "class",
                    "min_count": "1",
                    "residue": "q",
                },
            )
        )

        expected_summary_rows = [
            {
                "taxon_id": self.alpha["taxa"]["mammalia"].pk,
                "taxon_name": "Mammalia",
                "rank": "class",
                "observation_count": 2,
                "species_count": 2,
                "codon_shares": [
                    {"codon": "CAA", "share": 0.5},
                    {"codon": "CAG", "share": 0.5},
                ],
            }
        ]

        with (
            patch("apps.browser.stats.queries.connection") as mocked_connection,
            patch(
                "apps.browser.stats.queries._build_ranked_codon_composition_summary_bundle_postgresql",
                return_value=(1, expected_summary_rows, ["CAA", "CAG"]),
            ) as mocked_fast_path,
        ):
            mocked_connection.vendor = "postgresql"
            bundle = build_ranked_codon_composition_summary_bundle(filter_state)

        mocked_fast_path.assert_called_once()
        self.assertEqual(bundle["matching_repeat_calls_count"], 2)
        self.assertEqual(bundle["total_taxa_count"], 1)
        self.assertEqual(bundle["visible_taxa_count"], 1)
        self.assertEqual(bundle["visible_codons"], ["CAA", "CAG"])
        self.assertEqual(bundle["summary_rows"], expected_summary_rows)

    def test_ranked_codon_composition_summary_bundle_prefers_rollup_for_broad_scope(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
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

        filter_state = build_stats_filter_state(
            self.factory.get(
                "/browser/codon-ratios/",
                {
                    "rank": "class",
                    "min_count": "1",
                    "residue": "q",
                },
            )
        )

        with patch(
            "apps.browser.stats.queries._build_ranked_codon_composition_summary_bundle_live",
            side_effect=AssertionError("expected rollup summary path"),
        ):
            bundle = build_ranked_codon_composition_summary_bundle(filter_state)

        self.assertEqual(bundle["matching_repeat_calls_count"], 2)
        self.assertEqual(bundle["total_taxa_count"], 1)
        self.assertEqual(bundle["visible_codons"], ["CAA", "CAG"])
        self.assertEqual(
            bundle["summary_rows"],
            [
                {
                    "taxon_id": self.alpha["taxa"]["mammalia"].pk,
                    "taxon_name": "Mammalia",
                    "rank": "class",
                    "observation_count": 2,
                    "species_count": 2,
                    "codon_shares": [
                        {"codon": "CAA", "share": 0.625},
                        {"codon": "CAG", "share": 0.375},
                    ],
                }
            ],
        )

    def test_build_codon_overview_payload_uses_signed_preference_mode_for_two_codon_residue(self):
        payload = build_codon_overview_payload(
            [
                {
                    "taxon_id": 1,
                    "taxon_name": "Taxon A",
                    "rank": "class",
                    "observation_count": 3,
                    "species_count": 2,
                    "codon_shares": [
                        {"codon": "CAA", "share": 0.7},
                        {"codon": "CAG", "share": 0.3},
                    ],
                },
                {
                    "taxon_id": 2,
                    "taxon_name": "Taxon B",
                    "rank": "class",
                    "observation_count": 4,
                    "species_count": 3,
                    "codon_shares": [
                        {"codon": "CAA", "share": 0.1},
                        {"codon": "CAG", "share": 0.9},
                    ],
                },
            ],
            visible_codons=["CAA", "CAG"],
        )

        self.assertEqual(payload["mode"], "signed_preference_map")
        self.assertEqual(payload["scoreLabel"], "CAG - CAA")
        self.assertEqual(payload["displayMetric"], "signed_difference")
        self.assertEqual(payload["valueMin"], -1.2)
        self.assertEqual(payload["valueMax"], 1.2)
        self.assertEqual(
            [(taxon["taxonName"], taxon["score"]) for taxon in payload["taxa"]],
            [("Taxon A", -0.4), ("Taxon B", 0.8)],
        )
        self.assertEqual(
            [
                (
                    cell["rowIndex"],
                    cell["columnIndex"],
                    cell["signedDifference"],
                )
                for cell in payload["cells"]
            ],
            [
                (0, 0, 0.0),
                (0, 1, -1.2),
                (1, 0, 1.2),
                (1, 1, 0.0),
            ],
        )
        self.assertEqual(payload["pairwiseJsdMatrix"]["displayMetric"], "divergence")
        self.assertEqual(payload["pairwiseJsdMatrix"]["visibleTaxaCount"], 2)

    def test_taxonomy_gutter_payload_builds_rooted_visible_tree_and_scope_aware_braces(self):
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

        filter_state = build_stats_filter_state(
            self.factory.get(
                "/browser/codon-ratios/",
                {
                    "rank": "class",
                    "min_count": "1",
                    "top_n": "10",
                    "residue": "q",
                },
            )
        )

        bundle = build_ranked_codon_composition_summary_bundle(filter_state)
        payload = build_taxonomy_gutter_payload(
            bundle["summary_rows"],
            filter_state=filter_state,
            collapse_rank=filter_state.rank,
        )

        self.assertEqual(payload["collapseRank"], "class")
        self.assertEqual(payload["collapsedChildRank"], "order")
        self.assertEqual(
            payload["root"],
            {
                "nodeId": f"taxon-{self.alpha['taxa']['root'].pk}",
                "taxonId": self.alpha["taxa"]["root"].pk,
                "taxonName": "root",
                "rank": "no rank",
                "depth": 0,
            },
        )
        self.assertEqual(payload["maxDepth"], 2)
        self.assertEqual(
            [node["taxonName"] for node in payload["nodes"]],
            ["root", "Arthropoda", "Arachnida", "Insecta", "Chordata", "Mammalia"],
        )
        self.assertEqual(
            [node["depth"] for node in payload["nodes"]],
            [0, 1, 2, 2, 1, 2],
        )
        self.assertEqual(
            [leaf["taxonName"] for leaf in payload["leaves"]],
            ["Arachnida", "Insecta", "Mammalia"],
        )
        self.assertEqual(
            [leaf["braceLabel"] for leaf in payload["leaves"]],
            ["1 order", "1 order", "1 order"],
        )
        self.assertEqual(
            payload["edges"],
            [
                {
                    "parentNodeId": f"taxon-{self.alpha['taxa']['root'].pk}",
                    "childNodeId": f"taxon-{self.alpha['taxa']['arthropoda'].pk}",
                },
                {
                    "parentNodeId": f"taxon-{self.alpha['taxa']['arthropoda'].pk}",
                    "childNodeId": f"taxon-{self.alpha['taxa']['arachnida'].pk}",
                },
                {
                    "parentNodeId": f"taxon-{self.alpha['taxa']['arthropoda'].pk}",
                    "childNodeId": f"taxon-{self.alpha['taxa']['insecta'].pk}",
                },
                {
                    "parentNodeId": f"taxon-{self.alpha['taxa']['root'].pk}",
                    "childNodeId": f"taxon-{self.alpha['taxa']['chordata'].pk}",
                },
                {
                    "parentNodeId": f"taxon-{self.alpha['taxa']['chordata'].pk}",
                    "childNodeId": f"taxon-{self.alpha['taxa']['mammalia'].pk}",
                },
            ],
        )
        self.assertNotIn("columns", payload)
        self.assertNotIn("segments", payload)
        self.assertNotIn("rows", payload)
        self.assertNotIn("terminals", payload)

    def test_taxonomy_gutter_payload_uses_visible_lca_for_single_phylum_subset(self):
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

        filter_state = build_stats_filter_state(
            self.factory.get(
                "/browser/codon-ratios/",
                {
                    "rank": "species",
                    "min_count": "1",
                    "top_n": "10",
                    "residue": "q",
                },
            )
        )

        bundle = build_ranked_codon_composition_summary_bundle(filter_state)
        payload = build_taxonomy_gutter_payload(
            bundle["summary_rows"],
            filter_state=filter_state,
            collapse_rank=filter_state.rank,
        )

        self.assertEqual(
            payload["root"],
            {
                "nodeId": f"taxon-{self.alpha['taxa']['mammalia'].pk}",
                "taxonId": self.alpha["taxa"]["mammalia"].pk,
                "taxonName": "Mammalia",
                "rank": "class",
                "depth": 0,
            },
        )
        self.assertEqual(
            [node["taxonName"] for node in payload["nodes"]],
            ["Mammalia", "Primates", "Homo sapiens", "Mus musculus"],
        )
        self.assertEqual(
            payload["edges"],
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
                    "childNodeId": f"taxon-{self.alpha['taxa']['mouse'].pk}",
                },
            ],
        )
        self.assertEqual([leaf["braceLabel"] for leaf in payload["leaves"]], ["", ""])

    def test_taxonomy_gutter_payload_projects_tree_to_browser_ranks_only(self):
        from apps.browser.models import Taxon, TaxonClosure

        theria = Taxon.objects.create(
            taxon_id=32525,
            taxon_name="Theria",
            rank="clade",
            parent_taxon=self.alpha["taxa"]["mammalia"],
        )
        primates = self.alpha["taxa"]["primates"]
        primates.parent_taxon = theria
        primates.save()

        def rebuild_closure(taxon):
            TaxonClosure.objects.filter(descendant=taxon).delete()
            ancestor = taxon
            depth = 0
            while ancestor is not None:
                TaxonClosure.objects.create(
                    ancestor=ancestor,
                    descendant=taxon,
                    depth=depth,
                )
                ancestor = ancestor.parent_taxon
                depth += 1

        rebuild_closure(primates)
        rebuild_closure(self.alpha["taxa"]["human"])

        filter_state = build_stats_filter_state(
            self.factory.get(
                "/browser/codon-ratios/",
                {
                    "rank": "species",
                    "min_count": "1",
                    "residue": "q",
                },
            )
        )

        payload = build_taxonomy_gutter_payload(
            [
                {
                    "taxon_id": self.alpha["taxa"]["human"].pk,
                    "taxon_name": "Homo sapiens",
                    "rank": "species",
                },
                {
                    "taxon_id": self.alpha["taxa"]["mouse"].pk,
                    "taxon_name": "Mus musculus",
                    "rank": "species",
                },
            ],
            filter_state=filter_state,
            collapse_rank=filter_state.rank,
        )

        self.assertEqual(
            [node["taxonName"] for node in payload["nodes"]],
            ["Mammalia", "Primates", "Homo sapiens", "Mus musculus"],
        )
        self.assertNotIn("Theria", [node["taxonName"] for node in payload["nodes"]])
        self.assertNotIn("clade", [node["rank"] for node in payload["nodes"]])

    def test_taxonomy_gutter_payload_uses_cache_for_same_visible_scope(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 2, "codon_fraction": 1.0},
            ],
        )

        filter_state = build_stats_filter_state(
            self.factory.get(
                "/browser/codon-ratios/",
                {
                    "rank": "class",
                    "min_count": "1",
                    "top_n": "10",
                    "residue": "q",
                },
            )
        )
        summary_rows = build_ranked_codon_composition_summary_bundle(filter_state)["summary_rows"]

        first_payload = build_taxonomy_gutter_payload(
            summary_rows,
            filter_state=filter_state,
            collapse_rank=filter_state.rank,
        )

        with patch(
            "apps.browser.stats.taxonomy_gutter._build_scope_descendant_counts_by_taxon",
            side_effect=AssertionError("expected cached taxonomy gutter payload"),
        ):
            second_payload = build_taxonomy_gutter_payload(
                summary_rows,
                filter_state=filter_state,
                collapse_rank=filter_state.rank,
            )

        self.assertEqual(second_payload, first_payload)

    def test_ranked_codon_composition_summary_bundle_respects_run_branch_method_and_residue_filters(self):
        alpha_alanine = self._create_repeat_call(
            self.alpha,
            suffix="alpha_threshold_alanine",
            residue="A",
            codon_metric_name="alanine_ratio",
            codon_ratio_value=0.7,
            method=RepeatCall.Method.THRESHOLD,
        )
        beta_alanine = self._create_repeat_call(
            self.beta,
            suffix="beta_threshold_alanine",
            residue="A",
            codon_metric_name="alanine_ratio",
            codon_ratio_value=0.6,
            method=RepeatCall.Method.THRESHOLD,
        )
        self._set_repeat_call_codon_usages(
            self.alpha,
            repeat_call=alpha_alanine,
            rows=[
                {"amino_acid": "A", "codon": "GCA", "codon_count": 4, "codon_fraction": 1.0},
            ],
        )
        self._set_repeat_call_codon_usages(
            self.beta,
            repeat_call=beta_alanine,
            rows=[
                {"amino_acid": "A", "codon": "GCC", "codon_count": 4, "codon_fraction": 1.0},
            ],
        )

        filter_state = build_stats_filter_state(
            self.factory.get(
                "/browser/codon-ratios/",
                {
                    "run": "run-alpha",
                    "branch": str(self.alpha["taxa"]["primates"].pk),
                    "rank": "species",
                    "method": RepeatCall.Method.THRESHOLD,
                    "residue": "a",
                    "min_count": "1",
                },
            )
        )

        group_rows = list(build_ranked_taxon_group_queryset(filter_state))
        grouped_species_call_codon_fractions = list(
            build_group_codon_species_call_fraction_queryset(
                filter_state,
                display_taxon_ids=[group_rows[0]["display_taxon_id"]],
            )
        )
        summary_rows = summarize_ranked_codon_composition_groups(
            group_rows,
            grouped_species_call_codon_fractions,
            visible_codons=["GCA"],
        )

        bundle = build_ranked_codon_composition_summary_bundle(filter_state)
        self.assertEqual(bundle["matching_repeat_calls_count"], 1)
        self.assertEqual(bundle["total_taxa_count"], 1)
        self.assertEqual(bundle["visible_codons"], ["GCA"])
        self.assertEqual(
            summary_rows,
            [
                {
                    "taxon_id": self.alpha["taxon"].pk,
                    "taxon_name": "Homo sapiens",
                    "rank": "species",
                    "observation_count": 1,
                    "species_count": 1,
                    "codon_shares": [
                        {"codon": "GCA", "share": 1},
                    ],
                }
            ],
        )
        self.assertEqual(bundle["summary_rows"], summary_rows)
