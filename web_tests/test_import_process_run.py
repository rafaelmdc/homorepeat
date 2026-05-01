from ._import_command import ImportRunCommandTests
from ._suite import build_named_test_suite


TEST_NAMES = [
    "test_import_run_persists_browser_metadata",
    "test_import_run_keeps_only_repeat_linked_sequences_and_proteins",
    "test_import_run_keeps_matched_sequences_and_proteins_but_counts_all_batch_proteins",
    "test_import_run_fails_without_replace_for_existing_run",
    "test_import_run_replace_existing_reloads_run_scoped_rows",
    "test_import_run_keeps_raw_rows_when_canonical_sync_fails",
    "test_import_run_replace_existing_removes_stale_canonical_repeat_entities",
    "test_import_run_canonical_catalog_latest_run_wins_across_runs",
    "test_import_run_rolls_back_on_broken_references",
    "test_import_run_fails_when_codon_usage_references_missing_call",
    "test_import_run_fails_when_repeat_call_references_missing_matched_protein",
    "test_import_run_fails_on_duplicate_v2_entity_keys",
    "test_import_run_fails_when_taxonomy_parent_is_missing",
    "test_import_run_still_validates_unreferenced_inventory_rows",
    "test_import_run_preserves_full_taxonomy_before_storing_closure",
    "test_import_run_stores_residue_scoped_run_params",
    "test_import_run_reports_progress_during_transactional_import_phase",
    "test_import_run_triggers_post_load_analyze_hook",
]


def load_tests(_loader, _tests, _pattern):
    return build_named_test_suite(ImportRunCommandTests, TEST_NAMES)
