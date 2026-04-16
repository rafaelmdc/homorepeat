from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, TestCase

from apps.browser.stats import (
    build_group_length_values_queryset,
    build_ranked_length_chart_payload,
    build_ranked_length_summary_bundle,
    build_ranked_taxon_group_queryset,
    build_stats_filter_state,
    summarize_ranked_length_groups,
)

from .support import create_imported_run_fixture


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

    def test_stats_filter_state_defaults_without_branch_scope(self):
        request = self.factory.get("/browser/lengths/")

        filter_state = build_stats_filter_state(request)

        self.assertEqual(filter_state.current_run_id, "")
        self.assertFalse(filter_state.branch_scope_active)
        self.assertEqual(filter_state.rank, "class")
        self.assertEqual(filter_state.top_n, 25)
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
                "top_n": "999",
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
        self.assertEqual(filter_state.top_n, 100)

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
