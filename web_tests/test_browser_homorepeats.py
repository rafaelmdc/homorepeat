from ._browser_views import BrowserViewTests
from ._suite import build_named_test_suite


TEST_NAMES = [
    "test_homorepeat_list_renders_biology_first_table",
    "test_homorepeat_list_combined_filters_work",
    "test_homorepeat_list_loads_pattern_fields_without_codon_sequence",
    "test_homorepeat_list_uses_cursor_pagination_for_default_ordering",
    "test_homorepeat_list_virtual_scroll_fragment_returns_rows",
    "test_homorepeat_list_tsv_export_includes_full_sequences",
    "test_homorepeat_list_renders_tsv_download_link_with_filters",
    "test_homorepeat_list_aa_fasta_export_streams_filtered_sequences",
    "test_homorepeat_list_dna_fasta_export_streams_full_nucleotide_sequences",
    "test_homorepeat_fasta_querysets_only_load_needed_sequence_fields_and_stream_by_pk",
    "test_homorepeat_list_dna_fasta_skips_blank_nucleotide_sequences",
]


def load_tests(_loader, _tests, _pattern):
    return build_named_test_suite(BrowserViewTests, TEST_NAMES)
