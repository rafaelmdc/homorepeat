from ._import_command import ImportRunCommandTests
from ._suite import build_named_test_suite


TEST_NAMES = [
    "test_import_run_can_process_one_queued_batch_by_id",
    "test_import_run_can_process_next_pending_batch",
    "test_import_run_next_pending_reports_when_queue_is_empty",
    "test_import_worker_once_processes_next_pending_batch",
    "test_import_worker_once_reports_when_queue_is_empty",
    "test_import_worker_logs_unexpected_batch_failure_and_keeps_running",
    "test_import_worker_once_raises_unexpected_batch_failure",
]


def load_tests(loader, tests, pattern):
    return build_named_test_suite(ImportRunCommandTests, TEST_NAMES)
