from ._browser_views import BrowserViewTests
from ._suite import build_named_test_suite


TEST_NAMES = [
    "test_taxon_list_run_filter_keeps_ancestor_path",
    "test_taxon_list_branch_filter_includes_descendants",
    "test_taxon_list_branch_q_name_prefix_filter_includes_descendants",
    "test_taxon_list_tsv_export_uses_full_filtered_queryset_and_remains_distinct",
    "test_taxon_list_renders_tsv_download_link_with_filters",
    "test_taxon_detail_shows_lineage_and_branch_genomes",
    "test_genome_list_branch_filter_includes_descendant_taxa",
    "test_genome_list_branch_q_numeric_taxon_id_filters_descendants",
    "test_genome_list_accession_filter_works",
    "test_genome_list_tsv_export_honors_accession_filter",
    "test_genome_detail_shows_run_provenance_and_related_records",
]


def load_tests(loader, tests, pattern):
    return build_named_test_suite(BrowserViewTests, TEST_NAMES)
