from ._browser_views import BrowserViewTests
from ._suite import build_named_test_suite


TEST_NAMES = [
    "test_sequence_list_run_filter_scopes_results",
    "test_sequence_list_default_ordering_matches_optimize_contract",
    "test_sequence_list_keeps_raw_rows_narrow",
    "test_sequence_list_uses_local_ids_and_denormalized_fields_for_links",
    "test_sequence_list_uses_cursor_pagination_for_default_raw_order",
    "test_sequence_list_alternate_sort_falls_back_to_page_pagination",
    "test_sequence_list_tsv_export_uses_full_filtered_queryset",
    "test_sequence_detail_shows_linked_records_and_navigation",
    "test_sequence_list_virtual_scroll_fragment_returns_rows_without_count",
]


def load_tests(loader, tests, pattern):
    return build_named_test_suite(BrowserViewTests, TEST_NAMES)
