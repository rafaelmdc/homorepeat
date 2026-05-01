from ._import_command import ImportRunCommandTests
from ._suite import build_named_test_suite


TEST_NAMES = [
    "test_import_run_can_process_one_queued_batch_by_id",
    "test_import_run_can_process_next_pending_batch",
    "test_import_run_next_pending_reports_when_queue_is_empty",
]


def load_tests(_loader, _tests, _pattern):
    return build_named_test_suite(ImportRunCommandTests, TEST_NAMES)
