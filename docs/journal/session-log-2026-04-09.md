# Session Log

**Date:** 2026-04-09

## Objective

- Refactor `homorepeat` to consume the current `raw` pipeline contract from
  `../homorepeat_pipeline/`
- keep raw imported truth canonical
- finish the import/backend slices before moving into browser work

## What happened

- Inspected the real pipeline outputs and aligned the importer to:
  - `publish/metadata/run_manifest.json`
  - batch-scoped acquisition files under
    `publish/acquisition/batches/<batch_id>/`
  - run-level `repeat_calls.tsv`, `run_params.tsv`,
    `accession_status.tsv`, and `accession_call_counts.tsv`
- Completed slices `1.1` through `3.5`
- Added canonical provenance models for acquisition batches, download
  manifests, normalization warnings, accession status rows, and accession call
  count rows
- Removed legacy schema/runtime assumptions tied to deleted path fields
- Added `repeat_residue`-scoped run parameters and `seed_extend` support
- Moved the importer to a streamed Postgres-first path:
  - queued/background execution via `ImportBatch`
  - out-of-band heartbeat/progress reporting
  - PostgreSQL bulk load for the largest tables
  - post-load `ANALYZE`
- Validated the real small and large runs in Docker + Postgres
- Confirmed the large real run imports `pure`, `threshold`, and `seed_extend`

## Files touched

- [docs/django/implementation.md](/home/rafael/Documents/GitHub/homorepeat/docs/django/implementation.md)
  Updated architecture/status notes to match the implemented raw import stack.
- [docs/django/phases.md](/home/rafael/Documents/GitHub/homorepeat/docs/django/phases.md)
  Updated implementation status and current next slice.
- [apps/imports/services/published_run.py](/home/rafael/Documents/GitHub/homorepeat/apps/imports/services/published_run.py)
  Refactored raw contract discovery, batch parsing, iterators, and side-artifact
  parsing.
- [apps/imports/services/import_run.py](/home/rafael/Documents/GitHub/homorepeat/apps/imports/services/import_run.py)
  Implemented queued import execution, streamed import preparation,
  transactional import, Postgres heartbeat/progress reporting, `COPY` loading,
  and throughput cleanup.
- [apps/imports/views.py](/home/rafael/Documents/GitHub/homorepeat/apps/imports/views.py)
  Queues imports instead of blocking on full import execution.
- [apps/imports/management/commands/import_run.py](/home/rafael/Documents/GitHub/homorepeat/apps/imports/management/commands/import_run.py)
  Added queued-batch processing options and unified service-layer execution.
- [apps/browser/models.py](/home/rafael/Documents/GitHub/homorepeat/apps/browser/models.py)
  Added raw provenance models and denormalized browse fields; removed obsolete
  runtime fields.
- [apps/imports/models.py](/home/rafael/Documents/GitHub/homorepeat/apps/imports/models.py)
  Added import phase, heartbeat, and progress payload support.
- [apps/browser/views.py](/home/rafael/Documents/GitHub/homorepeat/apps/browser/views.py)
  Updated existing run/protein/repeat-call pages to the corrected raw schema and
  narrowed list-page projections.
- [templates/browser/run_detail.html](/home/rafael/Documents/GitHub/homorepeat/templates/browser/run_detail.html)
- [templates/browser/protein_detail.html](/home/rafael/Documents/GitHub/homorepeat/templates/browser/protein_detail.html)
- [templates/browser/repeatcall_detail.html](/home/rafael/Documents/GitHub/homorepeat/templates/browser/repeatcall_detail.html)
  Updated provenance display to use imported DB state instead of file-path
  assumptions.
- [web_tests/support.py](/home/rafael/Documents/GitHub/homorepeat/web_tests/support.py)
- [web_tests/test_import_services.py](/home/rafael/Documents/GitHub/homorepeat/web_tests/test_import_services.py)
- [web_tests/test_import_command.py](/home/rafael/Documents/GitHub/homorepeat/web_tests/test_import_command.py)
- [web_tests/test_browser_views.py](/home/rafael/Documents/GitHub/homorepeat/web_tests/test_browser_views.py)
- [web_tests/test_models.py](/home/rafael/Documents/GitHub/homorepeat/web_tests/test_models.py)
  Added and updated coverage for the raw contract, queued imports, schema
  behavior, and hot-path projections.

## Validation

- `python3 manage.py test web_tests.test_import_services`
- `python3 manage.py test web_tests.test_models`
- `python3 manage.py test web_tests.test_browser_views`
- `python3 manage.py test web_tests.test_import_views web_tests.test_import_command`
- `python3 manage.py test web_tests.test_import_command`
- Docker + Postgres real-run validation:
  - small run `live_raw_effective_params_2026_04_09`
  - large run `chr_all3_raw_2026_04_09`
- Small real Docker/Postgres import time:
  - `real 4.22`

## Current status

- Done for slices `1.1` through `3.5`
- Browser work is next

## Open issues

- Slice `4.1` is not implemented yet:
  - run detail needs a fuller provenance presentation
  - batch list/detail pages still need to be added
- Side-artifact browsing pages from `4.2` are still pending
- Large-scale optimization is MVP-level only; no parallelism or deeper query
  profiling has been added yet

## Next step

- Implement slice `4.1`: run and batch provenance pages, using imported
  database state only
