from ._browser_views import BrowserViewTests
from ._suite import build_named_test_suite


TEST_NAMES = [
    "test_browser_home_shows_counts_and_recent_runs",
    "test_browser_home_recent_runs_use_browser_metadata_counts",
    "test_run_list_renders_imported_runs",
    "test_run_list_uses_completed_import_batch_count_fallback",
    "test_run_list_leaves_summary_counts_blank_without_metadata_or_import_batch_counts",
    "test_run_list_search_filters_results",
    "test_run_list_imported_counts_do_not_link_to_canonical_views",
    "test_run_detail_shows_counts_and_scoped_links",
    "test_run_detail_shows_batch_provenance_and_import_activity",
    "test_run_detail_links_summary_counts_to_filtered_related_views",
    "test_run_detail_replacement_import_separates_current_and_imported_counts",
    "test_run_detail_uses_browser_metadata_facets",
    "test_sort_headers_render_across_browser_lists",
    "test_primary_browser_tables_render_sort_links_for_previously_plain_headers",
    "test_run_list_sort_header_cycles_desc_asc_clear",
    "test_virtual_scroll_hooks_render_across_browser_lists",
    "test_run_list_virtual_scroll_fragment_returns_rows",
    "test_run_list_tsv_export_uses_full_filtered_queryset",
    "test_run_list_tsv_export_honors_search_filter",
    "test_run_list_tsv_export_honors_status_filter",
    "test_run_list_renders_tsv_download_link_with_filters",
    "test_branch_filter_forms_use_branch_q_text_input_across_hot_pages",
]


def load_tests(loader, tests, pattern):
    return build_named_test_suite(BrowserViewTests, TEST_NAMES)
