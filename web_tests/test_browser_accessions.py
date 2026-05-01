from ._browser_views import BrowserViewTests
from ._suite import build_named_test_suite


TEST_NAMES = [
    "test_accession_list_links_summary_counts_to_filtered_related_views",
    "test_accession_list_virtual_scroll_fragment_returns_rows",
    "test_accession_list_tsv_export_honors_search_filter",
    "test_catalog_list_download_links_preserve_filters",
    "test_accession_detail_links_to_source_proteins_and_repeat_calls",
    "test_accession_list_branch_q_scopes_analytics_and_links",
]


def load_tests(_loader, _tests, _pattern):
    return build_named_test_suite(BrowserViewTests, TEST_NAMES)
