from ._browser_views import BrowserViewTests
from ._suite import build_named_test_suite


TEST_NAMES = [
    "test_codon_usage_list_renders_row_level_profiles",
    "test_codon_usage_route_uses_stable_view_export",
    "test_codon_usage_list_only_shows_calls_with_target_codon_usage",
    "test_codon_usage_list_uses_cursor_pagination_for_default_ordering",
    "test_codon_usage_list_uses_count_derived_percentages",
    "test_codon_usage_list_tsv_export_includes_sequences_and_parseable_counts",
    "test_codon_usage_list_renders_tsv_download_link_with_filters",
    "test_codon_usage_list_virtual_scroll_fragment_returns_profiles",
]


def load_tests(_loader, _tests, _pattern):
    return build_named_test_suite(BrowserViewTests, TEST_NAMES)
