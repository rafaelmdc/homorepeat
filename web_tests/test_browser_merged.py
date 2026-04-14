import unittest

from ._browser_merge_views import BrowserMergeViewTests
from ._browser_views import BrowserViewTests
from ._merged_helpers import MergedHelperTests
from ._suite import build_named_test_suite


BROWSER_VIEW_MERGED_TESTS = [
    "test_protein_list_merged_virtual_scroll_fragment_returns_rows",
    "test_protein_list_merged_branch_q_name_prefix_scopes_groups",
    "test_protein_list_merged_branch_q_without_matches_returns_empty_result_set",
    "test_repeatcall_list_merged_renders_sort_links_for_all_visible_headers",
    "test_repeatcall_list_merged_virtual_scroll_fragment_returns_rows",
]

MERGED_VIEW_TESTS = [
    "test_accession_list_groups_shared_accessions_across_runs",
    "test_accession_list_summarizes_collapsed_methods_and_safe_denominators",
    "test_accession_list_counts_distinct_residues_separately_within_one_protein",
    "test_accession_list_counts_distinct_methods_separately_within_one_protein",
    "test_genome_list_merged_mode_groups_shared_accessions",
    "test_protein_list_merged_mode_groups_proteins_across_runs",
    "test_protein_list_merged_mode_keeps_distinct_protein_ids_separate",
    "test_protein_list_merged_mode_keeps_distinct_methods_separate",
    "test_protein_list_merged_mode_surfaces_provenance_backlinks",
    "test_protein_list_merged_mode_filters_by_matching_evidence",
    "test_repeatcall_list_merged_mode_groups_by_protein_id_and_residue",
    "test_repeatcall_list_merged_mode_keeps_distinct_residues_separate",
    "test_repeatcall_list_merged_mode_keeps_distinct_methods_separate",
    "test_repeatcall_list_merged_mode_surfaces_provenance_backlinks",
    "test_repeatcall_list_merged_mode_filters_by_matching_evidence",
    "test_accession_detail_groups_by_protein_id_and_residue_and_uses_merged_denominator",
    "test_accession_detail_reports_excluded_rows_separately_from_duplicates",
    "test_accession_detail_withholds_percentage_when_denominator_conflicts",
    "test_taxon_detail_merged_mode_uses_merged_branch_counts",
    "test_genome_detail_links_to_merged_accession_view",
]

MERGED_HELPER_TESTS = [
    "test_protein_identity_groups_collapse_on_accession_and_protein_id",
    "test_residue_identity_groups_split_same_protein_by_residue",
    "test_identity_groups_split_same_protein_by_method",
    "test_identity_helpers_exclude_rows_without_trustworthy_keys",
    "test_representative_row_prefers_more_complete_row_before_newer_run",
    "test_representative_row_uses_newer_run_as_final_tiebreaker",
    "test_merged_group_helpers_do_not_issue_n_plus_one_queries",
    "test_summary_rebuild_global_queries_do_not_order_repeat_calls",
    "test_rebuild_merged_summaries_streams_repeat_call_reads_by_accession",
    "test_filter_inclusion_operates_on_matching_evidence_not_identity_keys",
]


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(
        [
            build_named_test_suite(BrowserViewTests, BROWSER_VIEW_MERGED_TESTS),
            build_named_test_suite(BrowserMergeViewTests, MERGED_VIEW_TESTS),
            build_named_test_suite(MergedHelperTests, MERGED_HELPER_TESTS),
        ]
    )
