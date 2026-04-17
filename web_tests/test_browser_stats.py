from unittest.mock import patch

from django.utils import timezone

from apps.browser.catalog import sync_canonical_catalog_for_run
from django.core.cache import cache
from django.test import RequestFactory, TestCase

from apps.browser.stats import (
    apply_stats_filter_context,
    build_available_codon_metric_names,
    build_codon_heatmap_payload,
    build_codon_heatmap_summary_bundle,
    build_codon_inspect_bundle,
    build_codon_inspect_payload,
    build_group_codon_heatmap_values_queryset,
    build_group_codon_ratio_values_queryset,
    build_filtered_repeat_call_queryset,
    build_group_length_values_queryset,
    build_ranked_codon_summary_bundle,
    build_ranked_length_chart_payload,
    build_ranked_length_summary_bundle,
    build_ranked_taxon_group_queryset,
    build_stats_filter_state,
    summarize_codon_heatmap_groups,
    summarize_ranked_codon_ratio_groups,
    summarize_ranked_length_groups,
)
from apps.browser.models import CanonicalRepeatCall, RepeatCall

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

    def _create_null_codon_repeat_call(
        self,
        run_data,
        *,
        suffix,
        residue,
        codon_metric_name,
        codon_metric_value,
    ):
        repeat_call_values = build_test_repeat_call_values(
            residue=residue,
            length=11,
            purity=1.0,
        )
        repeat_call = RepeatCall.objects.create(
            pipeline_run=run_data["pipeline_run"],
            genome=run_data["genome"],
            sequence=run_data["sequence"],
            protein=run_data["protein"],
            taxon=run_data["taxon"],
            call_id=f"call_{suffix}",
            method=RepeatCall.Method.PURE,
            accession=run_data["genome"].accession,
            gene_symbol=run_data["protein"].gene_symbol or run_data["sequence"].gene_symbol,
            protein_name=run_data["protein"].protein_name,
            protein_length=run_data["protein"].protein_length,
            start=30 + (len(suffix) * 20),
            end=40 + (len(suffix) * 20),
            length=11,
            repeat_residue=residue,
            repeat_count=repeat_call_values["repeat_count"],
            non_repeat_count=repeat_call_values["non_repeat_count"],
            purity=1.0,
            aa_sequence=repeat_call_values["aa_sequence"],
            codon_sequence=repeat_call_values["codon_sequence"],
            codon_metric_name=codon_metric_name,
            codon_metric_value=codon_metric_value,
            codon_ratio_value=None,
        )
        sync_canonical_catalog_for_run(
            run_data["pipeline_run"],
            import_batch=run_data["import_batch"],
            last_seen_at=timezone.now(),
            replace_all_repeat_call_methods=True,
        )
        return repeat_call

    def test_stats_filter_state_defaults_without_branch_scope(self):
        request = self.factory.get("/browser/lengths/")

        filter_state = build_stats_filter_state(request)

        self.assertEqual(filter_state.current_run_id, "")
        self.assertFalse(filter_state.branch_scope_active)
        self.assertEqual(filter_state.rank, "class")
        self.assertEqual(filter_state.top_n, 1000)
        self.assertEqual(filter_state.min_count, 3)
        self.assertEqual(filter_state.codon_metric_name, "")
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
                "codon_metric_name": "alt_ratio",
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
        self.assertEqual(filter_state.codon_metric_name, "alt_ratio")
        self.assertEqual(filter_state.length_min, 7)
        self.assertEqual(filter_state.length_max, 12)
        self.assertEqual(filter_state.purity_min, 0.8)
        self.assertEqual(filter_state.purity_max, 1.0)
        self.assertEqual(filter_state.min_count, 1)
        self.assertEqual(filter_state.top_n, 2000)
        self.assertEqual(filter_state.cache_key_data()["codon_metric_name"], "alt_ratio")

        context = apply_stats_filter_context({}, filter_state)
        self.assertEqual(context["current_codon_metric_name"], "alt_ratio")

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

    def test_available_codon_metric_names_are_residue_scoped_and_ignore_null_rows(self):
        self._create_repeat_call(
            self.alpha,
            suffix="alt_ratio_q",
            residue="Q",
            codon_metric_name="alt_ratio",
            codon_ratio_value=0.9,
        )
        self._create_null_codon_repeat_call(
            self.alpha,
            suffix="null_ratio_q",
            residue="Q",
            codon_metric_name="null_ratio",
            codon_metric_value="not-a-number",
        )
        self._create_repeat_call(
            self.alpha,
            suffix="alanine_ratio_a",
            residue="A",
            codon_metric_name="alanine_ratio",
            codon_ratio_value=0.7,
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
            build_available_codon_metric_names(filter_state),
            ["alt_ratio", "codon_ratio"],
        )

    def test_filtered_repeat_call_queryset_for_codon_applies_metric_selector_and_excludes_nulls(self):
        self._create_repeat_call(
            self.alpha,
            suffix="alt_ratio_selected",
            residue="Q",
            codon_metric_name="alt_ratio",
            codon_ratio_value=1.6,
        )
        self._create_null_codon_repeat_call(
            self.alpha,
            suffix="alt_ratio_null",
            residue="Q",
            codon_metric_name="alt_ratio",
            codon_metric_value="bad",
        )

        filter_state = build_stats_filter_state(
            self.factory.get(
                "/browser/codon-ratios/",
                {
                    "run": "run-alpha",
                    "branch": str(self.alpha["taxa"]["primates"].pk),
                    "residue": "q",
                    "codon_metric_name": "alt_ratio",
                },
            )
        )

        queryset = build_filtered_repeat_call_queryset(
            filter_state,
            require_codon_ratio=True,
        )

        self.assertEqual(queryset.count(), 1)
        self.assertEqual(
            list(queryset.values_list("codon_metric_name", "codon_ratio_value")),
            [("alt_ratio", 1.6)],
        )

    def test_ranked_codon_summary_bundle_rolls_up_and_summarizes_codon_ratios(self):
        self._create_repeat_call(
            self.beta,
            suffix="beta_low_ratio",
            residue="Q",
            codon_metric_name="codon_ratio",
            codon_ratio_value=0.8,
        )

        filter_state = build_stats_filter_state(
            self.factory.get(
                "/browser/codon-ratios/",
                {
                    "rank": "class",
                    "min_count": "1",
                    "top_n": "10",
                    "residue": "q",
                    "codon_metric_name": "codon_ratio",
                },
            )
        )

        bundle = build_ranked_codon_summary_bundle(filter_state)

        self.assertEqual(bundle["matching_repeat_calls_count"], 3)
        self.assertEqual(bundle["total_taxa_count"], 1)
        self.assertEqual(bundle["visible_taxa_count"], 1)
        self.assertEqual(
            bundle["summary_rows"],
            [
                {
                    "taxon_id": self.alpha["taxa"]["mammalia"].pk,
                    "taxon_name": "Mammalia",
                    "rank": "class",
                    "observation_count": 3,
                    "min_codon_ratio": 0.8,
                    "q1": 1.025,
                    "median": 1.25,
                    "q3": 1.25,
                    "max_codon_ratio": 1.25,
                }
            ],
        )

    def test_ranked_codon_summary_bundle_respects_run_branch_method_and_residue_filters(self):
        self._create_repeat_call(
            self.alpha,
            suffix="alpha_threshold_a",
            residue="A",
            codon_metric_name="alanine_ratio",
            codon_ratio_value=0.7,
        )
        self._create_repeat_call(
            self.beta,
            suffix="beta_threshold_a",
            residue="A",
            codon_metric_name="alanine_ratio",
            codon_ratio_value=0.6,
        )

        RepeatCall.objects.filter(call_id="call_alpha_threshold_a").update(method=RepeatCall.Method.THRESHOLD)
        RepeatCall.objects.filter(call_id="call_beta_threshold_a").update(method=RepeatCall.Method.THRESHOLD)
        sync_canonical_catalog_for_run(
            self.alpha["pipeline_run"],
            import_batch=self.alpha["import_batch"],
            last_seen_at=timezone.now(),
            replace_all_repeat_call_methods=True,
        )
        sync_canonical_catalog_for_run(
            self.beta["pipeline_run"],
            import_batch=self.beta["import_batch"],
            last_seen_at=timezone.now(),
            replace_all_repeat_call_methods=True,
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
                    "codon_metric_name": "alanine_ratio",
                    "min_count": "1",
                },
            )
        )

        bundle = build_ranked_codon_summary_bundle(filter_state)

        self.assertEqual(bundle["matching_repeat_calls_count"], 1)
        self.assertEqual(bundle["total_taxa_count"], 1)
        self.assertEqual(bundle["visible_taxa_count"], 1)
        self.assertEqual(
            bundle["summary_rows"],
            [
                {
                    "taxon_id": self.alpha["taxon"].pk,
                    "taxon_name": "Homo sapiens",
                    "rank": "species",
                    "observation_count": 1,
                    "min_codon_ratio": 0.7,
                    "q1": 0.7,
                    "median": 0.7,
                    "q3": 0.7,
                    "max_codon_ratio": 0.7,
                }
            ],
        )

    def test_grouped_codon_ratio_values_support_sqlite_summary_fallback(self):
        self._create_repeat_call(
            self.beta,
            suffix="beta_mid_ratio",
            residue="Q",
            codon_metric_name="codon_ratio",
            codon_ratio_value=1.0,
        )

        filter_state = build_stats_filter_state(
            self.factory.get(
                "/browser/codon-ratios/",
                {
                    "rank": "class",
                    "min_count": "1",
                    "residue": "q",
                    "codon_metric_name": "codon_ratio",
                },
            )
        )

        group_rows = list(build_ranked_taxon_group_queryset(filter_state, require_codon_ratio=True))
        grouped_codon_ratios = list(
            build_group_codon_ratio_values_queryset(
                filter_state,
                display_taxon_ids=[group_rows[0]["display_taxon_id"]],
            )
        )

        self.assertEqual(grouped_codon_ratios, [(group_rows[0]["display_taxon_id"], 1.0), (group_rows[0]["display_taxon_id"], 1.25), (group_rows[0]["display_taxon_id"], 1.25)])
        self.assertEqual(
            summarize_ranked_codon_ratio_groups(group_rows, grouped_codon_ratios),
            [
                {
                    "taxon_id": group_rows[0]["display_taxon_id"],
                    "taxon_name": "Mammalia",
                    "rank": "class",
                    "observation_count": 3,
                    "min_codon_ratio": 1,
                    "q1": 1.125,
                    "median": 1.25,
                    "q3": 1.25,
                    "max_codon_ratio": 1.25,
                }
            ],
        )

    def test_codon_heatmap_summary_bundle_groups_codon_ratios_by_taxon_and_length_bin(self):
        self._create_repeat_call(
            self.beta,
            suffix="beta_long_ratio",
            residue="Q",
            codon_metric_name="codon_ratio",
            codon_ratio_value=0.8,
            length=22,
        )

        filter_state = build_stats_filter_state(
            self.factory.get(
                "/browser/codon-ratios/",
                {
                    "rank": "species",
                    "min_count": "1",
                    "top_n": "10",
                    "residue": "q",
                    "codon_metric_name": "codon_ratio",
                },
            )
        )

        bundle = build_codon_heatmap_summary_bundle(filter_state)

        self.assertEqual(bundle["matching_repeat_calls_count"], 3)
        self.assertEqual(bundle["total_taxa_count"], 2)
        self.assertEqual(bundle["visible_taxa_count"], 2)
        self.assertEqual(
            bundle["summary_rows"],
            [
                {
                    "taxon_id": self.alpha["taxon"].pk,
                    "taxon_name": "Homo sapiens",
                    "rank": "species",
                    "taxon_observation_count": 1,
                    "length_bin_start": 10,
                    "length_bin_end": 14,
                    "length_bin_key": "10-14",
                    "length_bin_label": "10-14",
                    "observation_count": 1,
                    "min_codon_ratio": 1.25,
                    "q1": 1.25,
                    "median": 1.25,
                    "q3": 1.25,
                    "max_codon_ratio": 1.25,
                },
                {
                    "taxon_id": self.beta["taxon"].pk,
                    "taxon_name": "Mus musculus",
                    "rank": "species",
                    "taxon_observation_count": 2,
                    "length_bin_start": 10,
                    "length_bin_end": 14,
                    "length_bin_key": "10-14",
                    "length_bin_label": "10-14",
                    "observation_count": 1,
                    "min_codon_ratio": 1.25,
                    "q1": 1.25,
                    "median": 1.25,
                    "q3": 1.25,
                    "max_codon_ratio": 1.25,
                },
                {
                    "taxon_id": self.beta["taxon"].pk,
                    "taxon_name": "Mus musculus",
                    "rank": "species",
                    "taxon_observation_count": 2,
                    "length_bin_start": 20,
                    "length_bin_end": 24,
                    "length_bin_key": "20-24",
                    "length_bin_label": "20-24",
                    "observation_count": 1,
                    "min_codon_ratio": 0.8,
                    "q1": 0.8,
                    "median": 0.8,
                    "q3": 0.8,
                    "max_codon_ratio": 0.8,
                },
            ],
        )

    def test_codon_heatmap_summary_bundle_respects_branch_scope_and_filters(self):
        self._create_repeat_call(
            self.alpha,
            suffix="alpha_mid_ratio",
            residue="Q",
            codon_metric_name="codon_ratio",
            codon_ratio_value=0.9,
            length=16,
        )
        self._create_repeat_call(
            self.alpha,
            suffix="alpha_filtered_out_a",
            residue="A",
            codon_metric_name="alanine_ratio",
            codon_ratio_value=0.7,
            length=21,
        )

        filter_state = build_stats_filter_state(
            self.factory.get(
                "/browser/codon-ratios/",
                {
                    "run": "run-alpha",
                    "branch": str(self.alpha["taxa"]["primates"].pk),
                    "rank": "species",
                    "residue": "q",
                    "codon_metric_name": "codon_ratio",
                    "min_count": "1",
                },
            )
        )

        group_rows = list(build_ranked_taxon_group_queryset(filter_state, require_codon_ratio=True))
        grouped_length_codon_ratio_values = list(
            build_group_codon_heatmap_values_queryset(
                filter_state,
                display_taxon_ids=[group_rows[0]["display_taxon_id"]],
            )
        )

        self.assertEqual(
            grouped_length_codon_ratio_values,
            [
                (group_rows[0]["display_taxon_id"], 11, 1.25),
                (group_rows[0]["display_taxon_id"], 16, 0.9),
            ],
        )
        self.assertEqual(
            summarize_codon_heatmap_groups(group_rows, grouped_length_codon_ratio_values),
            [
                {
                    "taxon_id": self.alpha["taxon"].pk,
                    "taxon_name": "Homo sapiens",
                    "rank": "species",
                    "taxon_observation_count": 2,
                    "length_bin_start": 10,
                    "length_bin_end": 14,
                    "length_bin_key": "10-14",
                    "length_bin_label": "10-14",
                    "observation_count": 1,
                    "min_codon_ratio": 1.25,
                    "q1": 1.25,
                    "median": 1.25,
                    "q3": 1.25,
                    "max_codon_ratio": 1.25,
                },
                {
                    "taxon_id": self.alpha["taxon"].pk,
                    "taxon_name": "Homo sapiens",
                    "rank": "species",
                    "taxon_observation_count": 2,
                    "length_bin_start": 15,
                    "length_bin_end": 19,
                    "length_bin_key": "15-19",
                    "length_bin_label": "15-19",
                    "observation_count": 1,
                    "min_codon_ratio": 0.9,
                    "q1": 0.9,
                    "median": 0.9,
                    "q3": 0.9,
                    "max_codon_ratio": 0.9,
                },
            ],
        )

    def test_codon_heatmap_payload_shapes_lineage_ordered_taxa_and_visible_bins(self):
        self._create_repeat_call(
            self.beta,
            suffix="beta_long_ratio_payload",
            residue="Q",
            codon_metric_name="codon_ratio",
            codon_ratio_value=0.8,
            length=22,
        )

        bundle = build_codon_heatmap_summary_bundle(
            build_stats_filter_state(
                self.factory.get(
                    "/browser/codon-ratios/",
                    {
                        "rank": "species",
                        "min_count": "1",
                        "top_n": "10",
                        "residue": "q",
                        "codon_metric_name": "codon_ratio",
                    },
                )
            )
        )

        payload = build_codon_heatmap_payload(bundle["summary_rows"])

        self.assertEqual(payload["visibleTaxaCount"], 2)
        self.assertEqual(payload["visibleBinCount"], 3)
        self.assertEqual(payload["maxObservationCount"], 1)
        self.assertEqual(payload["valueMin"], 0.8)
        self.assertEqual(payload["valueMax"], 1.25)
        self.assertEqual(
            [taxon["taxonName"] for taxon in payload["taxa"]],
            ["Homo sapiens", "Mus musculus"],
        )
        self.assertEqual(
            [length_bin["label"] for length_bin in payload["bins"]],
            ["10-14", "15-19", "20-24"],
        )
        self.assertEqual(
            payload["cells"],
            [
                {
                    "taxonId": self.alpha["taxon"].pk,
                    "taxonName": "Homo sapiens",
                    "rank": "species",
                    "taxonIndex": 0,
                    "binKey": "10-14",
                    "binLabel": "10-14",
                    "binStart": 10,
                    "binEnd": 14,
                    "binIndex": 0,
                    "observationCount": 1,
                    "min": 1.25,
                    "q1": 1.25,
                    "median": 1.25,
                    "q3": 1.25,
                    "max": 1.25,
                    "value": 1.25,
                },
                {
                    "taxonId": self.beta["taxon"].pk,
                    "taxonName": "Mus musculus",
                    "rank": "species",
                    "taxonIndex": 1,
                    "binKey": "10-14",
                    "binLabel": "10-14",
                    "binStart": 10,
                    "binEnd": 14,
                    "binIndex": 0,
                    "observationCount": 1,
                    "min": 1.25,
                    "q1": 1.25,
                    "median": 1.25,
                    "q3": 1.25,
                    "max": 1.25,
                    "value": 1.25,
                },
                {
                    "taxonId": self.beta["taxon"].pk,
                    "taxonName": "Mus musculus",
                    "rank": "species",
                    "taxonIndex": 1,
                    "binKey": "20-24",
                    "binLabel": "20-24",
                    "binStart": 20,
                    "binEnd": 24,
                    "binIndex": 2,
                    "observationCount": 1,
                    "min": 0.8,
                    "q1": 0.8,
                    "median": 0.8,
                    "q3": 0.8,
                    "max": 0.8,
                    "value": 0.8,
                },
            ],
        )
        self.assertEqual(
            payload["seriesData"],
            [
                [0, 0, 1.25],
                [0, 1, 1.25],
                [2, 1, 0.8],
            ],
        )

    def test_codon_inspect_bundle_summarizes_branch_scoped_codon_distribution(self):
        self._create_repeat_call(
            self.alpha,
            suffix="alpha_mid_ratio_inspect",
            residue="Q",
            codon_metric_name="codon_ratio",
            codon_ratio_value=0.9,
            length=16,
        )

        bundle = build_codon_inspect_bundle(
            build_stats_filter_state(
                self.factory.get(
                    "/browser/codon-ratios/",
                    {
                        "run": "run-alpha",
                        "branch": str(self.alpha["taxa"]["primates"].pk),
                        "rank": "species",
                        "residue": "q",
                        "codon_metric_name": "codon_ratio",
                        "min_count": "1",
                    },
                )
            )
        )

        self.assertEqual(bundle["observation_count"], 2)
        self.assertEqual(
            bundle["summary"],
            {
                "min_codon_ratio": 0.9,
                "q1": 0.988,
                "median": 1.075,
                "q3": 1.163,
                "max_codon_ratio": 1.25,
            },
        )
        self.assertEqual(
            bundle["histogram_bins"],
            [
                {
                    "start": 0.9,
                    "end": 1.075,
                    "label": "0.9-1.075",
                    "count": 1,
                    "midpoint": 0.988,
                },
                {
                    "start": 1.075,
                    "end": 1.25,
                    "label": "1.075-1.25",
                    "count": 1,
                    "midpoint": 1.163,
                },
            ],
        )

    def test_codon_inspect_payload_shapes_histogram_and_box_summary(self):
        payload = build_codon_inspect_payload(
            {
                "observation_count": 2,
                "summary": {
                    "min_codon_ratio": 0.9,
                    "q1": 0.988,
                    "median": 1.075,
                    "q3": 1.163,
                    "max_codon_ratio": 1.25,
                },
                "histogram_bins": [
                    {
                        "start": 0.9,
                        "end": 1.075,
                        "label": "0.9-1.075",
                        "count": 1,
                        "midpoint": 0.988,
                    },
                    {
                        "start": 1.075,
                        "end": 1.25,
                        "label": "1.075-1.25",
                        "count": 1,
                        "midpoint": 1.163,
                    },
                ],
            },
            scope_label="Order Primates",
        )

        self.assertEqual(
            payload,
            {
                "scopeLabel": "Order Primates",
                "observationCount": 2,
                "summary": {
                    "min": 0.9,
                    "q1": 0.988,
                    "median": 1.075,
                    "q3": 1.163,
                    "max": 1.25,
                },
                "histogramBins": [
                    {
                        "label": "0.9-1.075",
                        "start": 0.9,
                        "end": 1.075,
                        "count": 1,
                        "midpoint": 0.988,
                    },
                    {
                        "label": "1.075-1.25",
                        "start": 1.075,
                        "end": 1.25,
                        "count": 1,
                        "midpoint": 1.163,
                    },
                ],
                "xMin": 0.9,
                "xMax": 1.25,
                "maxBinCount": 1,
            },
        )
