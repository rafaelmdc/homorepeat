from ._browser_views import BrowserViewTests
from ._suite import build_named_test_suite


TEST_NAMES = [
    "test_repeatcall_list_combined_filters_and_branch_scope_work",
    "test_repeatcall_list_all_runs_use_union_of_metadata_facets",
    "test_repeatcall_list_keeps_raw_rows_narrow",
    "test_repeatcall_list_uses_local_ids_and_denormalized_fields_for_links",
    "test_repeatcall_list_default_ordering_matches_optimize_contract",
    "test_repeatcall_list_uses_cursor_pagination_for_raw_results",
    "test_repeatcall_list_alternate_sort_falls_back_to_page_pagination",
    "test_repeatcall_list_renders_virtual_scroll_hooks_for_raw_results",
    "test_repeatcall_list_renders_sort_links_for_all_visible_headers",
    "test_repeatcall_list_virtual_scroll_fragment_returns_rows",
    "test_repeatcall_list_tsv_export_uses_full_filtered_queryset",
    "test_repeatcall_list_renders_tsv_download_link_with_filters",
    "test_repeatcall_detail_shows_linked_parents_and_coordinates",
]


def load_tests(_loader, _tests, _pattern):
    return build_named_test_suite(BrowserViewTests, TEST_NAMES)
