import unittest

from ._merged_helpers import MergedHelperTests
from ._suite import build_named_test_suite


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
            build_named_test_suite(MergedHelperTests, MERGED_HELPER_TESTS),
        ]
    )
