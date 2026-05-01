from ._browser_views import BrowserViewTests
from ._suite import build_named_test_suite


TEST_NAMES = [
    "test_protein_list_run_filter_scopes_results",
    "test_protein_list_default_ordering_matches_optimize_contract",
    "test_protein_list_run_filter_uses_run_metadata_facets",
    "test_protein_list_keeps_raw_rows_narrow",
    "test_protein_list_uses_local_ids_and_denormalized_fields_for_links",
    "test_protein_list_uses_cursor_pagination_for_raw_results",
    "test_protein_list_alternate_sort_falls_back_to_page_pagination",
    "test_protein_list_renders_virtual_scroll_hooks_for_raw_results",
    "test_protein_list_virtual_scroll_fragment_returns_rows",
    "test_protein_list_raw_virtual_scroll_fragment_skips_page_chrome_context",
    "test_protein_list_tsv_export_uses_full_filtered_queryset",
    "test_protein_list_renders_tsv_download_link_with_filters",
    "test_protein_list_combined_call_filters_match_same_linked_call",
    "test_protein_detail_shows_call_summary_and_navigation",
]


def load_tests(_loader, _tests, _pattern):
    return build_named_test_suite(BrowserViewTests, TEST_NAMES)
