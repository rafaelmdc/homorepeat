from ._browser_views import BrowserViewTests
from ._suite import build_named_test_suite


TEST_NAMES = [
    "test_accession_status_list_filters_by_run_batch_and_status",
    "test_accession_status_list_tsv_export_honors_filters_and_full_queryset",
    "test_accession_call_count_list_filters_by_run_batch_method_and_residue",
    "test_accession_call_count_list_tsv_export_honors_filters_and_full_queryset",
    "test_download_manifest_list_filters_by_run_batch_and_status",
    "test_download_manifest_list_tsv_export_honors_filters_and_full_queryset",
    "test_normalization_warning_list_filters_by_run_batch_and_accession",
    "test_normalization_warning_list_tsv_export_honors_filters_and_full_queryset",
    "test_operational_list_download_links_preserve_filters",
]


def load_tests(_loader, _tests, _pattern):
    return build_named_test_suite(BrowserViewTests, TEST_NAMES)
