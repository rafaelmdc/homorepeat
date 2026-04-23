from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.utils import timezone

from apps.browser.catalog import sync_canonical_catalog_for_run
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.browser.stats import (
    apply_stats_filter_context,
    build_ccdf_points,
    build_codon_length_composition_bundle,
    build_codon_length_browse_payload,
    build_codon_length_dominance_overview_payload,
    build_codon_length_preference_overview_payload,
    build_codon_length_shift_overview_payload,
    build_filtered_codon_usage_queryset,
    build_codon_overview_payload,
    build_group_codon_species_call_fraction_queryset,
    build_group_length_counts_queryset,
    build_filtered_repeat_call_queryset,
    build_group_length_values_queryset,
    build_length_inspect_bundle,
    build_length_inspect_payload,
    build_length_profile_vector_bundle,
    build_matching_repeat_calls_with_codon_usage_count,
    build_ranked_codon_composition_summary_bundle,
    build_ranked_length_chart_payload,
    build_ranked_length_summary_bundle,
    build_ranked_taxon_group_queryset,
    build_stats_filter_state,
    build_tail_burden_overview_payload,
    build_tail_pairwise_matrix,
    build_taxonomy_gutter_payload,
    build_typical_length_overview_payload,
    build_wasserstein_pairwise_matrix,
    rebuild_canonical_codon_composition_summaries,
    rebuild_canonical_codon_composition_length_summaries,
    summarize_ranked_codon_composition_groups,
    summarize_ranked_length_groups,
)
from apps.browser.stats.summaries import (
    _compute_l1_tail_distance,
    _compute_tail_feature_vector,
    _compute_wasserstein1_distance,
)
from apps.browser.stats.ordering import order_taxon_rows_by_lineage
from apps.browser.models import (
    CanonicalCodonCompositionSummary,
    CanonicalCodonCompositionLengthSummary,
    CanonicalRepeatCall,
    RepeatCall,
    RepeatCallCodonUsage,
)
from apps.imports.models import CatalogVersion

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

    def _seed_q_codon_usage_for_length_exports(self, *, with_shift=False):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )
        self._set_repeat_call_codon_usages(
            self.beta,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )
        if not with_shift:
            return None

        alpha_shift_call = self._create_repeat_call(
            self.alpha,
            suffix="alpha_length_shift",
            residue="Q",
            codon_metric_name="codon_ratio",
            codon_ratio_value=0.0,
            length=16,
        )
        self._set_repeat_call_codon_usages(
            self.alpha,
            repeat_call=alpha_shift_call,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )
        return alpha_shift_call

    def _seed_a_codon_usage_for_dominance_export(self):
        alpha_call = self._create_repeat_call(
            self.alpha,
            suffix="alpha_dominance",
            residue="A",
            codon_metric_name="alanine_ratio",
            codon_ratio_value=0.7,
            length=11,
        )
        beta_call = self._create_repeat_call(
            self.beta,
            suffix="beta_dominance",
            residue="A",
            codon_metric_name="alanine_ratio",
            codon_ratio_value=0.6,
            length=11,
        )
        self._set_repeat_call_codon_usages(
            self.alpha,
            repeat_call=alpha_call,
            rows=[
                {"amino_acid": "A", "codon": "GCA", "codon_count": 6, "codon_fraction": 0.6},
                {"amino_acid": "A", "codon": "GCC", "codon_count": 3, "codon_fraction": 0.3},
                {"amino_acid": "A", "codon": "GCG", "codon_count": 1, "codon_fraction": 0.1},
            ],
        )
        self._set_repeat_call_codon_usages(
            self.beta,
            repeat_call=beta_call,
            rows=[
                {"amino_acid": "A", "codon": "GCT", "codon_count": 10, "codon_fraction": 1.0},
            ],
        )

    def test_repeat_length_stats_download_rejects_unknown_dataset_key(self):
        response = self.client.get(
            reverse("browser:lengths"),
            {"download": "bogus"},
        )

        self.assertEqual(response.status_code, 404)

    def test_repeat_length_page_renders_section_download_actions(self):
        response = self.client.get(
            reverse("browser:lengths"),
            {"rank": "species", "min_count": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Download Typical TSV")
        self.assertContains(response, "Download Tail TSV")
        self.assertContains(response, "Download Summary TSV")
        self.assertContains(
            response,
            'href="/browser/lengths/?rank=species&amp;min_count=1&amp;download=overview_typical"',
        )
        self.assertContains(
            response,
            'href="/browser/lengths/?rank=species&amp;min_count=1&amp;download=overview_tail"',
        )
        self.assertContains(
            response,
            'href="/browser/lengths/?rank=species&amp;min_count=1&amp;download=summary"',
        )

    def test_repeat_length_inspect_download_returns_header_only_without_branch_scope(self):
        response = self.client.get(
            reverse("browser:lengths"),
            {"download": "inspect", "rank": "class", "method": "pure"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "text/tab-separated-values; charset=utf-8",
        )
        self.assertEqual(
            b"".join(response.streaming_content).decode("utf-8"),
            "Scope\tObservations\tMedian\tQ90\tQ95\tMax\tCCDF length\tCCDF survival fraction\n",
        )

    def test_repeat_length_summary_download_matches_summary_bundle_rows(self):
        response = self.client.get(
            reverse("browser:lengths"),
            {"download": "summary", "rank": "class", "min_count": "1"},
        )

        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertTrue(
            body.startswith(
                "Taxon id\tTaxon\tRank\tObservations\tSpecies\tMin\tQ1\tMedian\tQ3\tMax\n"
            )
        )
        self.assertIn("\tMammalia\tclass\t2\t2\t11\t11\t11\t11\t11\n", body)

    def test_repeat_length_overview_typical_download_exports_long_form_matrix(self):
        response = self.client.get(
            reverse("browser:lengths"),
            {"download": "overview_typical", "rank": "species", "min_count": "1"},
        )

        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertTrue(
            body.startswith("Row taxon\tColumn taxon\tWasserstein-1 distance\n")
        )
        self.assertEqual(len(body.strip().splitlines()), 5)
        self.assertIn(
            f"{self.alpha['taxon'].taxon_name}\t{self.beta['taxon'].taxon_name}\t0.0\n",
            body,
        )
        self.assertIn(
            f"{self.beta['taxon'].taxon_name}\t{self.alpha['taxon'].taxon_name}\t0.0\n",
            body,
        )

    def test_repeat_length_overview_tail_download_exports_long_form_matrix(self):
        response = self.client.get(
            reverse("browser:lengths"),
            {"download": "overview_tail", "rank": "species", "min_count": "1"},
        )

        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertTrue(
            body.startswith("Row taxon\tColumn taxon\tTail-burden distance\n")
        )
        self.assertEqual(len(body.strip().splitlines()), 5)
        self.assertIn(
            f"{self.alpha['taxon'].taxon_name}\t{self.beta['taxon'].taxon_name}\t0.0\n",
            body,
        )

    def test_repeat_length_inspect_download_matches_active_branch_bundle(self):
        response = self.client.get(
            reverse("browser:lengths"),
            {
                "download": "inspect",
                "branch": str(self.alpha["taxa"]["primates"].pk),
                "rank": "species",
                "min_count": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertTrue(
            body.startswith(
                "Scope\tObservations\tMedian\tQ90\tQ95\tMax\tCCDF length\tCCDF survival fraction\n"
            )
        )
        self.assertIn("Order Primates\t1\t11\t11\t11\t11\t11\t1.0\n", body)

    def test_codon_ratio_inspect_download_returns_header_only_without_branch_scope(self):
        response = self.client.get(
            reverse("browser:codon-ratios"),
            {"download": "inspect", "residue": "Q", "method": "pure"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            b"".join(response.streaming_content).decode("utf-8"),
            "Scope\tObservations\tCodon\tShare\n",
        )

    def test_codon_ratio_page_hides_unavailable_overview_and_browse_actions_without_residue(self):
        response = self.client.get(reverse("browser:codon-ratios"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Download Summary TSV")
        self.assertNotContains(response, "Download Overview TSV")
        self.assertNotContains(response, "Download Browse TSV")

    def test_codon_ratio_page_renders_section_download_actions_when_residue_active(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )
        self._set_repeat_call_codon_usages(
            self.beta,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )

        response = self.client.get(
            reverse("browser:codon-ratios"),
            {"rank": "species", "min_count": "1", "residue": "Q"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Download Summary TSV")
        self.assertContains(response, "Download Overview TSV")
        self.assertContains(response, "Download Browse TSV")
        self.assertContains(
            response,
            'href="/browser/codon-ratios/?rank=species&amp;min_count=1&amp;residue=Q&amp;download=overview"',
        )
        self.assertContains(
            response,
            'href="/browser/codon-ratios/?rank=species&amp;min_count=1&amp;residue=Q&amp;download=browse"',
        )

    def test_codon_ratio_summary_download_exports_visible_codon_shares(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )
        self._set_repeat_call_codon_usages(
            self.beta,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )

        response = self.client.get(
            reverse("browser:codon-ratios"),
            {"download": "summary", "rank": "species", "min_count": "1", "residue": "Q"},
        )

        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertTrue(
            body.startswith(
                "Taxon id\tTaxon\tRank\tObservations\tSpecies\tCAA share\tCAG share\n"
            )
        )
        self.assertIn(
            f"\t{self.alpha['taxon'].taxon_name}\tspecies\t1\t1\t1\t0\n",
            body,
        )
        self.assertIn(
            f"\t{self.beta['taxon'].taxon_name}\tspecies\t1\t1\t0\t1\n",
            body,
        )

    def test_codon_ratio_overview_download_exports_long_form_matrix(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )
        self._set_repeat_call_codon_usages(
            self.beta,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )

        response = self.client.get(
            reverse("browser:codon-ratios"),
            {"download": "overview", "rank": "species", "min_count": "1", "residue": "Q"},
        )

        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertTrue(
            body.startswith(
                "Row taxon\tColumn taxon\tMetric\tValue\tRow support\tColumn support\n"
            )
        )
        self.assertEqual(len(body.strip().splitlines()), 5)
        self.assertIn(
            f"{self.alpha['taxon'].taxon_name}\t{self.beta['taxon'].taxon_name}\tsigned_difference\t1.0\t1\t1\n",
            body,
        )
        self.assertIn(
            f"{self.beta['taxon'].taxon_name}\t{self.alpha['taxon'].taxon_name}\tsigned_difference\t1.0\t1\t1\n",
            body,
        )

    def test_codon_ratio_browse_download_matches_summary_rows(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )
        self._set_repeat_call_codon_usages(
            self.beta,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )

        summary_response = self.client.get(
            reverse("browser:codon-ratios"),
            {"download": "summary", "rank": "species", "min_count": "1", "residue": "Q"},
        )
        browse_response = self.client.get(
            reverse("browser:codon-ratios"),
            {"download": "browse", "rank": "species", "min_count": "1", "residue": "Q"},
        )

        self.assertEqual(
            b"".join(summary_response.streaming_content).decode("utf-8"),
            b"".join(browse_response.streaming_content).decode("utf-8"),
        )

    def test_codon_ratio_inspect_download_matches_active_branch_bundle(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )

        response = self.client.get(
            reverse("browser:codon-ratios"),
            {
                "download": "inspect",
                "branch": str(self.alpha["taxa"]["primates"].pk),
                "rank": "species",
                "residue": "Q",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertTrue(body.startswith("Scope\tObservations\tCodon\tShare\n"))
        self.assertIn("Order Primates\t1\tCAA\t1\n", body)

    def test_codon_composition_length_comparison_download_returns_header_only_without_branch_scope(self):
        response = self.client.get(
            reverse("browser:codon-composition-length"),
            {"download": "comparison", "residue": "Q", "method": "pure"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            b"".join(response.streaming_content).decode("utf-8"),
            "Scope\tLength bin\tSupport\tDominant codon\tCodon\tCodon share\tShift from previous\n",
        )

    def test_codon_composition_length_page_renders_explicit_overview_actions(self):
        self._seed_q_codon_usage_for_length_exports(with_shift=True)

        response = self.client.get(
            reverse("browser:codon-composition-length"),
            {"rank": "species", "min_count": "1", "residue": "Q"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Download Summary TSV")
        self.assertContains(response, "Download Preference TSV")
        self.assertContains(response, "Download Shift TSV")
        self.assertContains(response, "Download Similarity TSV")
        self.assertContains(response, "Download Browse TSV")
        self.assertNotContains(response, "Download Dominance TSV")
        self.assertContains(
            response,
            'href="/browser/codon-composition-length/?rank=species&amp;min_count=1&amp;residue=Q&amp;download=preference"',
        )
        self.assertContains(
            response,
            'href="/browser/codon-composition-length/?rank=species&amp;min_count=1&amp;residue=Q&amp;download=similarity"',
        )

    def test_codon_composition_length_page_renders_inspect_and_comparison_actions(self):
        self._seed_q_codon_usage_for_length_exports(with_shift=True)

        response = self.client.get(
            reverse("browser:codon-composition-length"),
            {
                "branch": str(self.alpha["taxon"].pk),
                "rank": "species",
                "residue": "Q",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Download Inspect TSV")
        self.assertContains(response, "Download Comparison TSV")
        self.assertContains(
            response,
            f'href="/browser/codon-composition-length/?branch={self.alpha["taxon"].pk}&amp;rank=species&amp;residue=Q&amp;download=inspect"',
        )
        self.assertContains(
            response,
            f'href="/browser/codon-composition-length/?branch={self.alpha["taxon"].pk}&amp;rank=species&amp;residue=Q&amp;download=comparison"',
        )

    def test_codon_composition_length_summary_download_exports_long_form_rows(self):
        self._seed_q_codon_usage_for_length_exports()

        response = self.client.get(
            reverse("browser:codon-composition-length"),
            {"download": "summary", "rank": "species", "min_count": "1", "residue": "Q"},
        )

        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertTrue(
            body.startswith(
                "Taxon id\tTaxon\tRank\tLength bin\tObservations\tSpecies\tDominant codon\tDominance margin\tCodon\tCodon share\n"
            )
        )
        self.assertEqual(len(body.strip().splitlines()), 5)
        self.assertIn(
            f"\t{self.alpha['taxon'].taxon_name}\tspecies\t10-14\t1\t1\tCAA\t1\tCAA\t1\n",
            body,
        )
        self.assertIn(
            f"\t{self.beta['taxon'].taxon_name}\tspecies\t10-14\t1\t1\tCAG\t1\tCAG\t1\n",
            body,
        )

    def test_codon_composition_length_preference_download_exports_rows(self):
        self._seed_q_codon_usage_for_length_exports()

        response = self.client.get(
            reverse("browser:codon-composition-length"),
            {"download": "preference", "rank": "species", "min_count": "1", "residue": "Q"},
        )

        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertTrue(
            body.startswith(
                "Taxon\tLength bin\tPreference value\tCodon A share\tCodon B share\tSupport\n"
            )
        )
        self.assertIn(
            f"{self.alpha['taxon'].taxon_name}\t10-14\t1\t1\t0\t1\n",
            body,
        )
        self.assertIn(
            f"{self.beta['taxon'].taxon_name}\t10-14\t-1\t0\t1\t1\n",
            body,
        )

    def test_codon_composition_length_dominance_download_exports_rows(self):
        self._seed_a_codon_usage_for_dominance_export()

        response = self.client.get(
            reverse("browser:codon-composition-length"),
            {"download": "dominance", "rank": "species", "min_count": "1", "residue": "A"},
        )

        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertTrue(
            body.startswith(
                "Taxon\tLength bin\tDominant codon\tDominance margin\tCodon share\tSupport\n"
            )
        )
        self.assertIn(
            f"{self.alpha['taxon'].taxon_name}\t10-14\tGCA\t0.3\t0.6\t1\n",
            body,
        )

    def test_codon_composition_length_shift_download_exports_transitions(self):
        self._seed_q_codon_usage_for_length_exports(with_shift=True)

        response = self.client.get(
            reverse("browser:codon-composition-length"),
            {"download": "shift", "rank": "species", "min_count": "1", "residue": "Q"},
        )

        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertTrue(
            body.startswith(
                "Taxon\tPrevious length bin\tNext length bin\tShift value\tPrevious support\tNext support\n"
            )
        )
        self.assertIn(
            f"{self.alpha['taxon'].taxon_name}\t10-14\t15-19\t1\t1\t1\n",
            body,
        )

    def test_codon_composition_length_similarity_download_exports_long_form_matrix(self):
        self._seed_q_codon_usage_for_length_exports()

        response = self.client.get(
            reverse("browser:codon-composition-length"),
            {"download": "similarity", "rank": "species", "min_count": "1", "residue": "Q"},
        )

        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertTrue(
            body.startswith("Row taxon\tColumn taxon\tTrajectory Jensen-Shannon divergence\n")
        )
        self.assertEqual(len(body.strip().splitlines()), 5)
        self.assertIn(
            f"{self.alpha['taxon'].taxon_name}\t{self.beta['taxon'].taxon_name}\t1.0\n",
            body,
        )

    def test_codon_composition_length_browse_download_matches_summary_rows(self):
        self._seed_q_codon_usage_for_length_exports()

        summary_response = self.client.get(
            reverse("browser:codon-composition-length"),
            {"download": "summary", "rank": "species", "min_count": "1", "residue": "Q"},
        )
        browse_response = self.client.get(
            reverse("browser:codon-composition-length"),
            {"download": "browse", "rank": "species", "min_count": "1", "residue": "Q"},
        )

        self.assertEqual(
            b"".join(summary_response.streaming_content).decode("utf-8"),
            b"".join(browse_response.streaming_content).decode("utf-8"),
        )

    def test_codon_composition_length_inspect_and_comparison_downloads_export_rows(self):
        self._seed_q_codon_usage_for_length_exports(with_shift=True)

        inspect_response = self.client.get(
            reverse("browser:codon-composition-length"),
            {
                "download": "inspect",
                "branch": str(self.alpha["taxon"].pk),
                "rank": "species",
                "residue": "Q",
            },
        )
        comparison_response = self.client.get(
            reverse("browser:codon-composition-length"),
            {
                "download": "comparison",
                "branch": str(self.alpha["taxon"].pk),
                "rank": "species",
                "residue": "Q",
            },
        )

        inspect_body = b"".join(inspect_response.streaming_content).decode("utf-8")
        comparison_body = b"".join(comparison_response.streaming_content).decode("utf-8")

        self.assertTrue(
            inspect_body.startswith(
                "Scope\tLength bin\tSupport\tDominant codon\tCodon\tCodon share\tShift from previous\n"
            )
        )
        self.assertIn("Species Homo sapiens\t10-14\t1\tCAA\tCAA\t1\t\n", inspect_body)
        self.assertIn("Species Homo sapiens\t15-19\t1\tCAG\tCAA\t0\t1\n", inspect_body)
        self.assertIn("Species Homo sapiens\t15-19\t1\tCAG\tCAG\t1\t1\n", inspect_body)
        self.assertIn("Order Primates\t15-19\t1\tCAG\tCAG\t1\t1\n", comparison_body)

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
                    "species_count": 2,
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

    def test_group_length_counts_queryset_collapses_duplicate_lengths(self):
        self._create_repeat_call(
            self.alpha,
            suffix="alpha-duplicate-length",
            residue="Q",
            codon_metric_name="codon_ratio",
            codon_ratio_value=0.25,
            length=11,
        )
        request = self.factory.get(
            "/browser/lengths/",
            {
                "rank": "species",
                "min_count": "1",
                "top_n": "10",
            },
        )
        filter_state = build_stats_filter_state(request)
        group_rows = list(build_ranked_taxon_group_queryset(filter_state))

        grouped_length_counts = list(
            build_group_length_counts_queryset(
                filter_state,
                display_taxon_ids=[row["display_taxon_id"] for row in group_rows],
            )
        )

        self.assertEqual(
            grouped_length_counts,
            [
                (self.alpha["taxon"].pk, 11, 2),
                (self.beta["taxon"].pk, 11, 1),
            ],
        )

    def test_codon_length_composition_bundle_groups_visible_taxa_by_bin_and_codon(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )
        beta_long_call = self._create_repeat_call(
            self.beta,
            suffix="beta-long-q",
            residue="Q",
            codon_metric_name="codon_ratio",
            codon_ratio_value=0.75,
            length=17,
        )
        self._set_repeat_call_codon_usages(
            self.beta,
            repeat_call=beta_long_call,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )
        request = self.factory.get(
            "/browser/codon-composition-length/",
            {
                "rank": "class",
                "min_count": "1",
                "top_n": "10",
                "residue": "q",
            },
        )

        bundle = build_codon_length_composition_bundle(build_stats_filter_state(request))

        self.assertEqual(bundle["matching_repeat_calls_count"], 3)
        self.assertEqual(bundle["total_taxa_count"], 1)
        self.assertEqual(bundle["visible_taxa_count"], 1)
        self.assertEqual(bundle["visible_codons"], ["CAA", "CAG"])
        self.assertEqual(
            [row["label"] for row in bundle["visible_bins"]],
            ["10-14", "15-19"],
        )
        self.assertEqual(len(bundle["matrix_rows"]), 1)
        self.assertEqual(bundle["matrix_rows"][0]["taxon_name"], "Mammalia")
        self.assertEqual(
            [
                [share_row["codon"] for share_row in row["codon_shares"]]
                for row in bundle["matrix_rows"][0]["bin_rows"]
            ],
            [
                ["CAA", "CAG"],
                ["CAA", "CAG"],
            ],
        )
        self.assertEqual(
            [
                [share_row["share"] for share_row in row["codon_shares"]]
                for row in bundle["matrix_rows"][0]["bin_rows"]
            ],
            [
                [1, 0],
                [0, 1],
            ],
        )
        self.assertEqual(
            [
                (row["bin"]["label"], row["dominant_codon"], row["observation_count"], row["species_count"])
                for row in bundle["matrix_rows"][0]["bin_rows"]
            ],
            [
                ("10-14", "CAA", 1, 1),
                ("15-19", "CAG", 1, 1),
            ],
        )

    def test_codon_length_composition_bundle_applies_min_count_to_bin_rows(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )
        alpha_second_call = self._create_repeat_call(
            self.alpha,
            suffix="alpha-second-q",
            residue="Q",
            codon_metric_name="codon_ratio",
            codon_ratio_value=0.0,
            length=12,
        )
        self._set_repeat_call_codon_usages(
            self.alpha,
            repeat_call=alpha_second_call,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )
        beta_long_call = self._create_repeat_call(
            self.beta,
            suffix="beta-low-support-long-q",
            residue="Q",
            codon_metric_name="codon_ratio",
            codon_ratio_value=1.0,
            length=17,
        )
        self._set_repeat_call_codon_usages(
            self.beta,
            repeat_call=beta_long_call,
            rows=[
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )
        request = self.factory.get(
            "/browser/codon-composition-length/",
            {
                "rank": "class",
                "min_count": "2",
                "top_n": "10",
                "residue": "q",
            },
        )

        bundle = build_codon_length_composition_bundle(build_stats_filter_state(request))

        self.assertEqual(bundle["visible_taxa_count"], 1)
        self.assertEqual(
            [row["label"] for row in bundle["visible_bins"]],
            ["10-14"],
        )
        self.assertEqual(
            [
                (row["bin"]["label"], row["observation_count"], row["dominant_codon"])
                for row in bundle["matrix_rows"][0]["bin_rows"]
            ],
            [("10-14", 2, "CAA")],
        )

    def test_codon_length_composition_bundle_uses_rollup_on_default_scope(self):
        CanonicalCodonCompositionLengthSummary.objects.bulk_create(
            [
                CanonicalCodonCompositionLengthSummary(
                    repeat_residue="Q",
                    display_rank="class",
                    display_taxon_id=self.alpha["taxa"]["mammalia"].pk,
                    display_taxon_name="Mammalia",
                    length_bin_start=10,
                    observation_count=2,
                    species_count=2,
                    codon="CAA",
                    codon_share=0.625,
                ),
                CanonicalCodonCompositionLengthSummary(
                    repeat_residue="Q",
                    display_rank="class",
                    display_taxon_id=self.alpha["taxa"]["mammalia"].pk,
                    display_taxon_name="Mammalia",
                    length_bin_start=10,
                    observation_count=2,
                    species_count=2,
                    codon="CAG",
                    codon_share=0.375,
                ),
            ]
        )
        CanonicalCodonCompositionSummary.objects.bulk_create(
            [
                CanonicalCodonCompositionSummary(
                    repeat_residue="Q",
                    display_rank="class",
                    display_taxon_id=self.alpha["taxa"]["mammalia"].pk,
                    display_taxon_name="Mammalia",
                    observation_count=2,
                    species_count=2,
                    codon="CAA",
                    codon_share=0.625,
                ),
                CanonicalCodonCompositionSummary(
                    repeat_residue="Q",
                    display_rank="class",
                    display_taxon_id=self.alpha["taxa"]["mammalia"].pk,
                    display_taxon_name="Mammalia",
                    observation_count=2,
                    species_count=2,
                    codon="CAG",
                    codon_share=0.375,
                ),
            ]
        )
        request = self.factory.get(
            "/browser/codon-composition-length/",
            {
                "rank": "class",
                "min_count": "1",
                "top_n": "10",
                "residue": "q",
            },
        )

        with patch(
            "apps.browser.stats.queries._build_codon_length_composition_bundle_live",
            side_effect=AssertionError("live path should not run"),
        ):
            bundle = build_codon_length_composition_bundle(build_stats_filter_state(request))

        self.assertEqual(bundle["visible_taxa_count"], 1)
        self.assertEqual(bundle["visible_codons"], ["CAA", "CAG"])
        self.assertEqual(
            [
                (row["bin"]["label"], row["dominant_codon"], row["observation_count"], row["species_count"])
                for row in bundle["matrix_rows"][0]["bin_rows"]
            ],
            [("10-14", "CAA", 2, 2)],
        )

    def test_codon_length_preference_overview_payload_derives_from_two_codon_bundle(self):
        bundle = {
            "visible_codons": ["CAA", "CAG"],
            "visible_bins": [
                {"start": 10, "end": 14, "label": "10-14"},
                {"start": 15, "end": 19, "label": "15-19"},
            ],
            "matrix_rows": [
                {
                    "taxon_id": 1,
                    "taxon_name": "Mammalia",
                    "rank": "class",
                    "observation_count": 12,
                    "species_count": 2,
                    "bin_rows": [
                        {
                            "bin": {"start": 10, "end": 14, "label": "10-14"},
                            "observation_count": 8,
                            "species_count": 2,
                            "codon_shares": [
                                {"codon": "CAA", "share": 0.75},
                                {"codon": "CAG", "share": 0.25},
                            ],
                            "dominant_codon": "CAA",
                            "dominance_margin": 0.5,
                        },
                        {
                            "bin": {"start": 15, "end": 19, "label": "15-19"},
                            "observation_count": 4,
                            "species_count": 1,
                            "codon_shares": [
                                {"codon": "CAA", "share": 0.2},
                                {"codon": "CAG", "share": 0.8},
                            ],
                            "dominant_codon": "CAG",
                            "dominance_margin": 0.6,
                        },
                    ],
                },
            ],
        }

        payload = build_codon_length_preference_overview_payload(bundle)

        self.assertTrue(payload["available"])
        self.assertEqual(payload["mode"], "preference")
        self.assertEqual(payload["codonA"], "CAA")
        self.assertEqual(payload["codonB"], "CAG")
        self.assertEqual(payload["metricLabel"], "CAA - CAG")
        self.assertEqual(
            [
                (cell["rowIndex"], cell["binIndex"], cell["preference"], cell["supportTier"])
                for cell in payload["cells"]
            ],
            [
                (0, 0, 0.5, "medium"),
                (0, 1, -0.6, "low"),
            ],
        )
        self.assertEqual(payload["cells"][0]["codonShares"][0], {"codon": "CAA", "share": 0.75})

    def test_codon_length_dominance_overview_payload_derives_from_three_codon_bundle(self):
        bundle = {
            "visible_codons": ["AAA", "AAG", "AAC"],
            "visible_bins": [{"start": 10, "end": 14, "label": "10-14"}],
            "matrix_rows": [
                {
                    "taxon_id": 1,
                    "taxon_name": "Mammalia",
                    "rank": "class",
                    "observation_count": 24,
                    "species_count": 3,
                    "bin_rows": [
                        {
                            "bin": {"start": 10, "end": 14, "label": "10-14"},
                            "observation_count": 24,
                            "species_count": 3,
                            "codon_shares": [
                                {"codon": "AAA", "share": 0.15},
                                {"codon": "AAG", "share": 0.65},
                                {"codon": "AAC", "share": 0.2},
                            ],
                            "dominant_codon": "AAG",
                            "dominance_margin": 0.45,
                        },
                    ],
                },
            ],
        }

        payload = build_codon_length_dominance_overview_payload(bundle)

        self.assertTrue(payload["available"])
        self.assertEqual(payload["mode"], "dominance")
        self.assertEqual(payload["metricLabel"], "Dominance margin")
        self.assertEqual(payload["valueMax"], 0.45)
        self.assertEqual(
            payload["cells"][0],
            {
                "rowIndex": 0,
                "binIndex": 0,
                "binStart": 10,
                "binLabel": "10-14",
                "value": 0.45,
                "dominantCodon": "AAG",
                "dominantCodonIndex": 1,
                "dominanceMargin": 0.45,
                "codonShares": [
                    {"codon": "AAA", "share": 0.15},
                    {"codon": "AAG", "share": 0.65},
                    {"codon": "AAC", "share": 0.2},
                ],
                "observationCount": 24,
                "speciesCount": 3,
                "supportTier": "high",
            },
        )

    def test_codon_length_shift_overview_payload_skips_missing_adjacent_bins(self):
        bundle = {
            "visible_codons": ["AAA", "AAG", "AAC"],
            "visible_bins": [
                {"start": 10, "end": 14, "label": "10-14"},
                {"start": 15, "end": 19, "label": "15-19"},
                {"start": 20, "end": 24, "label": "20-24"},
            ],
            "matrix_rows": [
                {
                    "taxon_id": 1,
                    "taxon_name": "Mammalia",
                    "rank": "class",
                    "observation_count": 30,
                    "species_count": 3,
                    "bin_rows": [
                        {
                            "bin": {"start": 10, "end": 14, "label": "10-14"},
                            "observation_count": 20,
                            "species_count": 3,
                            "codon_shares": [
                                {"codon": "AAA", "share": 0.5},
                                {"codon": "AAG", "share": 0.25},
                                {"codon": "AAC", "share": 0.25},
                            ],
                            "dominant_codon": "AAA",
                            "dominance_margin": 0.25,
                        },
                        {
                            "bin": {"start": 15, "end": 19, "label": "15-19"},
                            "observation_count": 10,
                            "species_count": 2,
                            "codon_shares": [
                                {"codon": "AAA", "share": 0.2},
                                {"codon": "AAG", "share": 0.5},
                                {"codon": "AAC", "share": 0.3},
                            ],
                            "dominant_codon": "AAG",
                            "dominance_margin": 0.2,
                        },
                    ],
                },
            ],
        }

        payload = build_codon_length_shift_overview_payload(bundle)

        self.assertTrue(payload["available"])
        self.assertEqual(
            [transition["label"] for transition in payload["transitions"]],
            ["10-14 -> 15-19", "15-19 -> 20-24"],
        )
        self.assertEqual(len(payload["cells"]), 1)
        self.assertEqual(payload["cells"][0]["transitionIndex"], 0)
        self.assertEqual(payload["cells"][0]["shift"], 0.6)
        self.assertEqual(payload["cells"][0]["previousSupport"]["supportTier"], "high")
        self.assertEqual(payload["cells"][0]["nextSupport"]["supportTier"], "medium")

    def test_codon_length_browse_payload_preserves_fixed_bins_and_codon_order(self):
        bundle = {
            "visible_codons": ["CAA", "CAG"],
            "visible_bins": [
                {"start": 10, "end": 14, "label": "10-14"},
                {"start": 15, "end": 19, "label": "15-19"},
            ],
            "matrix_rows": [
                {
                    "taxon_id": 1,
                    "taxon_name": "Mammalia",
                    "rank": "class",
                    "observation_count": 12,
                    "species_count": 2,
                    "bin_rows": [
                        {
                            "bin": {"start": 10, "end": 14, "label": "10-14"},
                            "observation_count": 8,
                            "species_count": 2,
                            "codon_shares": [
                                {"codon": "CAA", "share": 0.75},
                                {"codon": "CAG", "share": 0.25},
                            ],
                            "dominant_codon": "CAA",
                            "dominance_margin": 0.5,
                        },
                    ],
                },
            ],
        }

        payload = build_codon_length_browse_payload(bundle)

        self.assertTrue(payload["available"])
        self.assertEqual(payload["mode"], "two_codon_area")
        self.assertEqual(payload["visibleCodons"], ["CAA", "CAG"])
        self.assertEqual(payload["shownTaxaCount"], 1)
        self.assertEqual(payload["windowSize"], 12)
        self.assertEqual(
            [
                (
                    bin_row["bin"]["label"],
                    bin_row["occupied"],
                    bin_row["codonShares"],
                    bin_row["supportTier"],
                )
                for bin_row in payload["panels"][0]["bins"]
            ],
            [
                (
                    "10-14",
                    True,
                    [{"codon": "CAA", "share": 0.75}, {"codon": "CAG", "share": 0.25}],
                    "medium",
                ),
                (
                    "15-19",
                    False,
                    [{"codon": "CAA", "share": None}, {"codon": "CAG", "share": None}],
                    "missing",
                ),
            ],
        )

    def test_codon_length_composition_bundle_skips_rollup_for_filtered_scope(self):
        request = self.factory.get(
            "/browser/codon-composition-length/",
            {
                "rank": "class",
                "min_count": "1",
                "top_n": "10",
                "residue": "q",
                "length_max": "12",
            },
        )

        with patch(
            "apps.browser.stats.queries._build_codon_length_composition_bundle_from_rollup",
            side_effect=AssertionError("rollup path should not run"),
        ), patch(
            "apps.browser.stats.queries._build_codon_length_composition_bundle_live",
            return_value=(0, [], [], []),
        ) as live_mock:
            bundle = build_codon_length_composition_bundle(build_stats_filter_state(request))

        self.assertEqual(bundle["matrix_rows"], [])
        self.assertEqual(bundle["visible_codons"], [])
        live_mock.assert_called_once()

    def test_codon_length_composition_rollup_matches_live_bundle_for_default_scope(self):
        self._set_repeat_call_codon_usages(
            self.alpha,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 8, "codon_fraction": 1.0},
            ],
        )
        beta_long_call = self._create_repeat_call(
            self.beta,
            suffix="beta-long-q-rollup-parity",
            residue="Q",
            codon_metric_name="codon_ratio",
            codon_ratio_value=0.75,
            length=17,
        )
        self._set_repeat_call_codon_usages(
            self.beta,
            repeat_call=beta_long_call,
            rows=[
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 2, "codon_fraction": 0.25},
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 6, "codon_fraction": 0.75},
            ],
        )
        request = self.factory.get(
            "/browser/codon-composition-length/",
            {
                "rank": "class",
                "min_count": "1",
                "top_n": "10",
                "residue": "q",
            },
        )
        filter_state = build_stats_filter_state(request)

        with patch(
            "apps.browser.stats.queries._can_use_codon_composition_length_summary_rollup",
            return_value=False,
        ):
            live_bundle = build_codon_length_composition_bundle(filter_state)

        cache.clear()
        rebuild_canonical_codon_composition_summaries()
        rebuild_canonical_codon_composition_length_summaries()
        cache.clear()
        rollup_bundle = build_codon_length_composition_bundle(filter_state)

        self.assertEqual(rollup_bundle["matching_repeat_calls_count"], live_bundle["matching_repeat_calls_count"])
        self.assertEqual(rollup_bundle["total_taxa_count"], live_bundle["total_taxa_count"])
        self.assertEqual(rollup_bundle["visible_taxa_count"], live_bundle["visible_taxa_count"])
        self.assertEqual(rollup_bundle["visible_codons"], live_bundle["visible_codons"])
        self.assertEqual(
            [row["label"] for row in rollup_bundle["visible_bins"]],
            [row["label"] for row in live_bundle["visible_bins"]],
        )
        self.assertEqual(
            self._flatten_codon_length_bundle(rollup_bundle),
            self._flatten_codon_length_bundle(live_bundle),
        )

    def _flatten_codon_length_bundle(self, bundle):
        return [
            (
                matrix_row["taxon_name"],
                bin_row["bin"]["label"],
                bin_row["observation_count"],
                bin_row["species_count"],
                bin_row["dominant_codon"],
                bin_row["dominance_margin"],
                tuple(
                    (share_row["codon"], share_row["share"])
                    for share_row in bin_row["codon_shares"]
                ),
            )
            for matrix_row in bundle["matrix_rows"]
            for bin_row in matrix_row["bin_rows"]
        ]

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

    def test_length_profile_vector_bundle_reuses_visible_taxa_and_shared_length_bins(self):
        self._create_repeat_call(
            self.alpha,
            suffix="alpha-extra",
            residue="Q",
            codon_metric_name="codon_ratio",
            codon_ratio_value=0.25,
            length=17,
        )
        self._create_repeat_call(
            self.beta,
            suffix="beta-extra",
            residue="Q",
            codon_metric_name="codon_ratio",
            codon_ratio_value=0.75,
            length=27,
        )
        request = self.factory.get(
            "/browser/lengths/",
            {
                "rank": "species",
                "min_count": "1",
                "top_n": "10",
            },
        )
        filter_state = build_stats_filter_state(request)

        bundle = build_length_profile_vector_bundle(filter_state)

        self.assertEqual(bundle["matching_repeat_calls_count"], 4)
        self.assertEqual(bundle["visible_taxa_count"], 2)
        self.assertEqual(
            [length_bin["label"] for length_bin in bundle["visible_bins"]],
            ["10-14", "15-19", "20-24", "25-29"],
        )
        self.assertEqual(
            [
                (
                    row["taxon_name"],
                    row["observation_count"],
                    row["species_count"],
                    row["length_profile"],
                )
                for row in bundle["profile_rows"]
            ],
            [
                ("Homo sapiens", 2, 1, [0.5, 0.5, 0.0, 0.0]),
                ("Mus musculus", 2, 1, [0.5, 0.0, 0.0, 0.5]),
            ],
        )
        self.assertEqual(
            [
                [bin_row["count"] for bin_row in row["bin_counts"]]
                for row in bundle["profile_rows"]
            ],
            [
                [1, 1, 0, 0],
                [1, 0, 0, 1],
            ],
        )
        self.assertEqual(
            bundle["profile_rows"][0]["length_counts"],
            [
                {"length": 11, "count": 1},
                {"length": 17, "count": 1},
            ],
        )

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
            payload["divergenceMatrix"],
            [
                [0.0, 0.295807],
                [0.295807, 0.0],
            ],
        )

    def test_build_codon_overview_payload_uses_similarity_mode_for_multi_codon_residue(self):
        payload = build_codon_overview_payload(
            [
                {
                    "taxon_id": 1,
                    "taxon_name": "Taxon A",
                    "rank": "class",
                    "observation_count": 3,
                    "species_count": 2,
                    "codon_shares": [
                        {"codon": "AAA", "share": 1.0},
                        {"codon": "AAG", "share": 0.0},
                        {"codon": "AAC", "share": 0.0},
                    ],
                },
                {
                    "taxon_id": 2,
                    "taxon_name": "Taxon B",
                    "rank": "class",
                    "observation_count": 4,
                    "species_count": 3,
                    "codon_shares": [
                        {"codon": "AAA", "share": 0.0},
                        {"codon": "AAG", "share": 1.0},
                        {"codon": "AAC", "share": 0.0},
                    ],
                },
            ],
            visible_codons=["AAA", "AAG", "AAC"],
        )

        self.assertEqual(payload["mode"], "pairwise_similarity_matrix")
        self.assertEqual(payload["displayMetric"], "similarity")
        self.assertEqual(payload["visibleCodons"], ["AAA", "AAG", "AAC"])
        self.assertEqual(payload["visibleTaxaCount"], 2)
        self.assertEqual(payload["maxObservationCount"], 4)
        self.assertEqual(payload["maxSpeciesCount"], 3)
        self.assertEqual(payload["valueMin"], 0)
        self.assertEqual(payload["valueMax"], 1)
        self.assertEqual(
            payload["taxa"],
            [
                {
                    "taxonId": 1,
                    "taxonName": "Taxon A",
                    "rank": "class",
                    "observationCount": 3,
                    "speciesCount": 2,
                    "rowIndex": 0,
                    "columnIndex": 0,
                },
                {
                    "taxonId": 2,
                    "taxonName": "Taxon B",
                    "rank": "class",
                    "observationCount": 4,
                    "speciesCount": 3,
                    "rowIndex": 1,
                    "columnIndex": 1,
                },
            ],
        )
        self.assertEqual(
            payload["divergenceMatrix"],
            [
                [0.0, 1.0],
                [1.0, 0.0],
            ],
        )

    def test_build_typical_length_overview_payload_uses_divergence_mode(self):
        rows = [
            {
                "taxon_id": 1,
                "taxon_name": "Taxon A",
                "rank": "class",
                "observation_count": 3,
                "species_count": 2,
                "length_profile": [1.0, 0.0, 0.0],
                "raw_lengths": [5, 10, 15],
            },
            {
                "taxon_id": 2,
                "taxon_name": "Taxon B",
                "rank": "class",
                "observation_count": 4,
                "species_count": 3,
                "length_profile": [0.0, 1.0, 0.0],
                "raw_lengths": [20, 25, 30, 35],
            },
        ]
        payload = build_typical_length_overview_payload(rows)

        self.assertEqual(payload["mode"], "pairwise_similarity_matrix")
        self.assertEqual(payload["displayMetric"], "divergence")
        self.assertEqual(payload["visibleTaxaCount"], 2)
        self.assertEqual(payload["maxObservationCount"], 4)
        self.assertEqual(payload["maxSpeciesCount"], 3)
        taxa = payload["taxa"]
        self.assertEqual(taxa[0]["taxonId"], 1)
        self.assertEqual(taxa[0]["rowIndex"], 0)
        self.assertEqual(taxa[0]["columnIndex"], 0)
        self.assertEqual(taxa[1]["rowIndex"], 1)
        self.assertEqual(taxa[1]["columnIndex"], 1)
        matrix = payload["divergenceMatrix"]
        self.assertEqual(matrix[0][0], 0.0)
        self.assertEqual(matrix[1][1], 0.0)
        self.assertAlmostEqual(matrix[0][1], matrix[1][0], places=6)
        self.assertGreater(matrix[0][1], 0.0)

    def test_order_taxon_rows_by_lineage_uses_curated_metazoa_order_for_root_linked_phyla(self):
        ordered_rows = order_taxon_rows_by_lineage(
            [
                {
                    "taxon_id": self.alpha["taxa"]["chordata"].pk,
                    "taxon_name": "Chordata",
                    "rank": "phylum",
                },
                {
                    "taxon_id": self.alpha["taxa"]["cnidaria"].pk,
                    "taxon_name": "Cnidaria",
                    "rank": "phylum",
                },
                {
                    "taxon_id": self.alpha["taxa"]["arthropoda"].pk,
                    "taxon_name": "Arthropoda",
                    "rank": "phylum",
                },
            ]
        )

        self.assertEqual(
            [row["taxon_name"] for row in ordered_rows],
            ["Cnidaria", "Arthropoda", "Chordata"],
        )

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

    def test_ranked_codon_composition_summary_bundle_cache_key_tracks_catalog_version(self):
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
        build_ranked_codon_composition_summary_bundle(filter_state)
        CatalogVersion.increment()

        with patch(
            "apps.browser.stats.queries.build_filtered_repeat_call_queryset",
            side_effect=AssertionError("expected versioned cache miss"),
        ):
            with self.assertRaises(AssertionError):
                build_ranked_codon_composition_summary_bundle(filter_state)

    def test_taxonomy_gutter_payload_cache_key_tracks_catalog_version(self):
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
        build_taxonomy_gutter_payload(
            summary_rows,
            filter_state=filter_state,
            collapse_rank=filter_state.rank,
        )
        CatalogVersion.increment()

        with patch(
            "apps.browser.stats.taxonomy_gutter._build_scope_descendant_counts_by_taxon",
            side_effect=AssertionError("expected versioned taxonomy gutter cache miss"),
        ):
            with self.assertRaises(AssertionError):
                build_taxonomy_gutter_payload(
                    summary_rows,
                    filter_state=filter_state,
                    collapse_rank=filter_state.rank,
                )

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

    def test_build_ccdf_points_builds_step_function_from_sorted_lengths(self):
        points = build_ccdf_points([5, 10, 10, 20])

        self.assertEqual(points, [
            {"x": 5, "y": 1.0},
            {"x": 10, "y": 0.75},
            {"x": 20, "y": 0.25},
        ])

    def test_build_ccdf_points_returns_empty_for_empty_input(self):
        self.assertEqual(build_ccdf_points([]), [])

    def test_build_ccdf_points_always_includes_first_and_last_when_downsampling(self):
        lengths = list(range(1, 1002))
        points = build_ccdf_points(lengths, max_points=10)

        self.assertLessEqual(len(points), 10)
        self.assertEqual(points[0]["x"], 1)
        self.assertEqual(points[0]["y"], 1.0)
        self.assertEqual(points[-1]["x"], 1001)
        self.assertAlmostEqual(points[-1]["y"], 1 / 1001, places=5)

    def test_build_length_inspect_bundle_returns_empty_for_no_matching_calls(self):
        filter_state = build_stats_filter_state(
            self.factory.get("/browser/lengths/", {"q": "NOMATCH_XXXXXX"})
        )

        bundle = build_length_inspect_bundle(filter_state)

        self.assertEqual(bundle["observation_count"], 0)
        self.assertEqual(bundle["ccdf_points"], [])
        self.assertIsNone(bundle["median"])
        self.assertIsNone(bundle["max"])

    def test_build_length_inspect_bundle_returns_ccdf_and_quantiles_for_branch_scope(self):
        self._create_repeat_call(
            self.alpha,
            suffix="inspect-len-a",
            residue="Q",
            codon_metric_name="codon_ratio",
            codon_ratio_value=0.5,
            length=15,
        )
        self._create_repeat_call(
            self.alpha,
            suffix="inspect-len-b",
            residue="Q",
            codon_metric_name="codon_ratio",
            codon_ratio_value=0.5,
            length=20,
        )
        filter_state = build_stats_filter_state(
            self.factory.get(
                "/browser/lengths/",
                {
                    "branch": str(self.alpha["taxa"]["primates"].pk),
                    "min_count": "1",
                },
            )
        )

        bundle = build_length_inspect_bundle(filter_state)

        self.assertEqual(bundle["observation_count"], 3)
        self.assertEqual(bundle["ccdf_points"], [
            {"x": 11, "y": 1.0},
            {"x": 15, "y": round(2 / 3, 6)},
            {"x": 20, "y": round(1 / 3, 6)},
        ])
        self.assertEqual(bundle["median"], 15)
        self.assertEqual(bundle["max"], 20)

    def test_build_length_inspect_payload_shapes_bundle_for_frontend(self):
        bundle = {
            "observation_count": 5,
            "ccdf_points": [{"x": 10, "y": 1.0}, {"x": 20, "y": 0.4}],
            "median": 15,
            "q90": 19,
            "q95": 20,
            "max": 20,
        }

        payload = build_length_inspect_payload(bundle, scope_label="Primates")

        self.assertEqual(payload["scopeLabel"], "Primates")
        self.assertEqual(payload["observationCount"], 5)
        self.assertEqual(payload["ccdfPoints"], bundle["ccdf_points"])
        self.assertEqual(payload["median"], 15)
        self.assertEqual(payload["q90"], 19)
        self.assertEqual(payload["q95"], 20)
        self.assertEqual(payload["max"], 20)

    def test_build_length_inspect_payload_returns_empty_shape_for_empty_bundle(self):
        payload = build_length_inspect_payload(
            {"observation_count": 0, "ccdf_points": [], "median": None, "q90": None, "q95": None, "max": None},
            scope_label="Empty branch",
        )

        self.assertEqual(payload["observationCount"], 0)
        self.assertEqual(payload["ccdfPoints"], [])
        self.assertIsNone(payload["median"])


class LengthOverviewMetricsTests(TestCase):
    # ---- Wasserstein-1 distance ----

    def test_wasserstein1_zero_for_identical_inputs(self):
        self.assertEqual(_compute_wasserstein1_distance([5, 10, 15], [5, 10, 15]), 0.0)

    def test_wasserstein1_symmetry(self):
        a = [5, 10, 15]
        b = [20, 30, 40]
        self.assertAlmostEqual(
            _compute_wasserstein1_distance(a, b),
            _compute_wasserstein1_distance(b, a),
            places=6,
        )

    def test_wasserstein1_completely_separated_distributions(self):
        # a all at 1, b all at 50 (at l_cap); integral of |CDF_a - CDF_b| from 1→50 = 49, /50 = 0.98
        result = _compute_wasserstein1_distance([1, 1, 1], [50, 50, 50])
        self.assertAlmostEqual(result, 0.98, places=4)

    def test_wasserstein1_outlier_clamped_not_filtered(self):
        # 500 gets clamped to 50, not removed — creates a detectable shift
        result_with_outlier = _compute_wasserstein1_distance([5, 5, 5, 500], [5, 5, 5, 5])
        self.assertGreater(result_with_outlier, 0.0)
        self.assertLessEqual(result_with_outlier, 1.0)

    def test_wasserstein1_returns_zero_for_empty_inputs(self):
        self.assertEqual(_compute_wasserstein1_distance([], []), 0.0)
        self.assertEqual(_compute_wasserstein1_distance([], [10, 20]), 0.0)

    def test_wasserstein1_result_in_unit_interval(self):
        result = _compute_wasserstein1_distance([5, 10, 15], [20, 30, 40])
        self.assertGreaterEqual(result, 0.0)
        self.assertLessEqual(result, 1.0)

    def test_wasserstein1_concrete_value(self):
        # a=[5,10,15] b=[20,30,40] l_cap=50 → W1=20 → normalized=0.4 (verified analytically)
        result = _compute_wasserstein1_distance([5, 10, 15], [20, 30, 40])
        self.assertAlmostEqual(result, 0.4, places=5)

    # ---- Tail feature vector ----

    def test_tail_feature_all_short_lengths(self):
        vec = _compute_tail_feature_vector([5, 10, 15, 20])
        self.assertEqual(vec[0], 0.0)  # p(L>20)
        self.assertEqual(vec[1], 0.0)  # p(L>30)
        self.assertEqual(vec[2], 0.0)  # p(L>50)

    def test_tail_feature_threshold_boundaries_strict(self):
        # strict >: 20 is NOT > 20, 21,30,31,50,51 are → 5/6
        # 30 is NOT > 30, 31,50,51 are → 3/6
        # 50 is NOT > 50, 51 is → 1/6
        vec = _compute_tail_feature_vector([20, 21, 30, 31, 50, 51])
        self.assertAlmostEqual(vec[0], 5 / 6, places=5)  # p(L>20)
        self.assertAlmostEqual(vec[1], 3 / 6, places=5)  # p(L>30)
        self.assertAlmostEqual(vec[2], 1 / 6, places=5)  # p(L>50)

    def test_tail_feature_empty_list(self):
        self.assertEqual(_compute_tail_feature_vector([]), [0.0, 0.0, 0.0, 0.0])

    def test_tail_feature_q95_capped_at_one(self):
        # q95 >> l_cap=50, normalized should cap at 1.0
        vec = _compute_tail_feature_vector([300, 300, 300, 300, 300])
        self.assertEqual(vec[3], 1.0)

    def test_tail_feature_q95_normalized_by_l_cap(self):
        # All lengths = 25; q95 = 25; 25/50 = 0.5
        vec = _compute_tail_feature_vector([25] * 10)
        self.assertAlmostEqual(vec[3], 0.5, places=5)

    # ---- L1 tail distance ----

    def test_l1_tail_distance_zero_for_identical(self):
        self.assertEqual(_compute_l1_tail_distance([0.3, 0.2, 0.1, 0.4], [0.3, 0.2, 0.1, 0.4]), 0.0)

    def test_l1_tail_distance_symmetry(self):
        a = [0.8, 0.5, 0.2, 0.9]
        b = [0.1, 0.3, 0.0, 0.4]
        self.assertAlmostEqual(
            _compute_l1_tail_distance(a, b),
            _compute_l1_tail_distance(b, a),
            places=6,
        )

    def test_l1_tail_distance_max_value(self):
        # all-ones vs all-zeros → sum = 4, /4 = 1.0
        self.assertAlmostEqual(
            _compute_l1_tail_distance([1.0, 1.0, 1.0, 1.0], [0.0, 0.0, 0.0, 0.0]),
            1.0,
            places=6,
        )

    # ---- Pairwise matrix builders ----

    def _make_rows(self, lengths_list):
        return [
            {"raw_lengths": lengths, "taxon_id": i, "taxon_name": f"T{i}",
             "rank": "class", "observation_count": len(lengths), "species_count": 1,
             "length_profile": []}
            for i, lengths in enumerate(lengths_list)
        ]

    def test_wasserstein_matrix_zero_diagonal(self):
        rows = self._make_rows([[5, 10, 15], [20, 25, 30], [35, 40, 45]])
        matrix = build_wasserstein_pairwise_matrix(rows)
        for i in range(3):
            self.assertEqual(matrix[i][i], 0.0)

    def test_wasserstein_matrix_symmetric(self):
        rows = self._make_rows([[5, 10, 15], [20, 25, 30], [35, 40, 45]])
        matrix = build_wasserstein_pairwise_matrix(rows)
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(matrix[i][j], matrix[j][i], places=6)

    def test_tail_matrix_zero_diagonal(self):
        rows = self._make_rows([[5, 10, 15], [20, 25, 30]])
        matrix = build_tail_pairwise_matrix(rows)
        for i in range(2):
            self.assertEqual(matrix[i][i], 0.0)

    def test_tail_matrix_symmetric(self):
        rows = self._make_rows([[5, 10, 15], [20, 25, 60], [100, 200, 300]])
        matrix = build_tail_pairwise_matrix(rows)
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(matrix[i][j], matrix[j][i], places=6)

    # ---- Payload shapes ----

    def test_build_typical_length_overview_payload_shape(self):
        rows = self._make_rows([[5, 10, 15], [20, 30, 40]])
        payload = build_typical_length_overview_payload(rows)
        self.assertEqual(payload["mode"], "pairwise_similarity_matrix")
        self.assertEqual(payload["displayMetric"], "divergence")
        self.assertEqual(payload["visibleTaxaCount"], 2)
        matrix = payload["divergenceMatrix"]
        self.assertEqual(matrix[0][0], 0.0)
        self.assertEqual(matrix[1][1], 0.0)
        self.assertAlmostEqual(matrix[0][1], matrix[1][0], places=6)
        taxa = payload["taxa"]
        self.assertIn("rowIndex", taxa[0])
        self.assertIn("columnIndex", taxa[0])

    def test_build_tail_burden_overview_payload_shape(self):
        rows = self._make_rows([[5, 10, 15], [100, 200, 300]])
        payload = build_tail_burden_overview_payload(rows)
        self.assertEqual(payload["mode"], "pairwise_similarity_matrix")
        self.assertEqual(payload["displayMetric"], "divergence")
        matrix = payload["divergenceMatrix"]
        self.assertEqual(matrix[0][0], 0.0)
        self.assertEqual(matrix[1][1], 0.0)
        self.assertAlmostEqual(matrix[0][1], matrix[1][0], places=6)
        self.assertGreater(matrix[0][1], 0.0)

    def test_both_overview_payloads_return_empty_shape_for_empty_rows(self):
        for builder in (build_typical_length_overview_payload, build_tail_burden_overview_payload):
            payload = builder([])
            self.assertEqual(payload["mode"], "pairwise_similarity_matrix")
            self.assertEqual(payload["displayMetric"], "divergence")
            self.assertEqual(payload["divergenceMatrix"], [])
            self.assertEqual(payload["visibleTaxaCount"], 0)

    def test_typical_and_tail_payloads_produce_different_matrices(self):
        # Same central lengths, but one taxon has a very long tail → matrices differ
        rows = self._make_rows([[10, 12, 14, 16], [10, 12, 14, 200]])
        typical_matrix = build_typical_length_overview_payload(rows)["divergenceMatrix"]
        tail_matrix = build_tail_burden_overview_payload(rows)["divergenceMatrix"]
        # The off-diagonal value should differ between the two metrics
        self.assertNotAlmostEqual(typical_matrix[0][1], tail_matrix[0][1], places=3)
