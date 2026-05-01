from ._browser_views import BrowserViewTests
from ._suite import build_named_test_suite


TEST_NAMES = [
    "test_codon_usage_row_route_uses_stable_view_export",
    "test_codon_usage_row_list_renders_supporting_catalog_table",
    "test_codon_usage_row_list_filters_by_codon_and_exports_tsv",
    "test_codon_usage_row_list_virtual_scroll_fragment_returns_rows",
]


def load_tests(_loader, _tests, _pattern):
    return build_named_test_suite(BrowserViewTests, TEST_NAMES)
