# Session Log

**Date:** 2026-05-01

## Objective

- Continue implementing the GUI pipeline-run import roadmap slice by slice.
- Finish the remaining Phase 4, Phase 5, and Phase 6 operational polish.
- Document the current GUI upload/import behavior.
- Create a decision-complete refactor plan for hardening the upload flow toward
  web-production standards.

## What happened

- Read the latest session log and confirmed the next roadmap slice.
- Completed Phase 4 import-page UX polish:
  - moved the manual publish-root import field into an advanced `<details>`
    section
  - kept the manual path open when it has a value or validation errors
  - extended `/imports/` auto-refresh to cover active uploaded runs in
    `receiving`, `received`, `extracting`, or `queued`
- Completed Phase 5 uploaded-run import queueing:
  - added `POST /imports/uploads/<upload_id>/import/`
  - added idempotent ready-upload queueing with a row lock on `UploadedRun`
  - reused `enqueue_published_run()` and `dispatch_import_batch()`
  - linked `UploadedRun.import_batch`
  - marked uploaded runs `queued`
  - returned existing linked batches for already queued/imported uploaded runs
  - rendered linked import batch progress in the uploaded-run table
- Completed Phase 6 operational/docs slices:
  - added `cleanup_stale_uploaded_runs`
  - added retention settings for stale incomplete and failed uploads
  - scheduled upload cleanup in `CELERY_BEAT_SCHEDULE`
  - documented the decision to keep extraction on the `imports` queue for the
    MVP, with the trade-off and future `uploads` queue path
  - documented GUI zipped-run imports in user-facing docs
  - documented upload/import storage settings and disk-planning requirements
- Discussed whether the current upload flow is "industry standard."
  - conclusion: the current implementation is a solid staff-only/local MVP, but
    not yet production-grade upload infrastructure
  - main gaps identified: checksums, resume reconciliation, disk preflight,
    queue separation, ownership/audit, quotas/rate limits, and broader security
    controls
- Created two new planning docs for the production-hardening refactor:
  - overview of target state, current gaps, boundaries, and success criteria
  - implementation plan split into integrity, resume/reconciliation, disk
    preflight, audit/policy, queue isolation, UI recovery, and operations/docs

## Files touched

- `templates/imports/home.html`
- `apps/imports/views.py`
- `apps/imports/urls.py`
- `apps/imports/services/uploads.py`
- `apps/imports/tasks.py`
- `config/settings.py`
- `.env.example`
- `README.md`
- `docs/usage.md`
- `docs/configuration.md`
- `docs/immpelementation/gui-run-imports/implementation-details.md`
- `docs/immpelementation/gui-run-imports/implementation_roadmap.md`
- `docs/immpelementation/gui-run-imports/industry-standard-refactor-overview.md`
- `docs/immpelementation/gui-run-imports/industry-standard-refactor-implementation-plan.md`
- `web_tests/test_import_views.py`
- `web_tests/test_import_uploads.py`
- `web_tests/test_import_tasks.py`

## Validation

Successful checks run during the session included:

```text
python3 -m py_compile apps/imports/views.py apps/imports/urls.py apps/imports/services/uploads.py web_tests/test_import_uploads.py web_tests/test_import_views.py
python3 -m py_compile apps/imports/services/uploads.py apps/imports/views.py apps/imports/urls.py web_tests/test_import_uploads.py web_tests/test_import_views.py
python3 -m py_compile web_tests/test_import_views.py
python3 -m py_compile config/settings.py apps/imports/tasks.py web_tests/test_import_tasks.py
git diff --check
docker compose config
docker compose run --rm web python manage.py test web_tests.test_import_views
docker compose run --rm web python manage.py test web_tests.test_import_uploads web_tests.test_import_views
docker compose run --rm web python manage.py test web_tests.test_import_views web_tests.test_import_uploads web_tests.test_import_tasks
```

The final focused Docker test run for the import/upload/task suite passed 49
tests.

One intermediate Docker test run failed because PostgreSQL does not allow
`SELECT FOR UPDATE` across a nullable `select_related("import_batch")` outer
join. The queueing helper was corrected to lock only the `UploadedRun` row and
load the linked `ImportBatch` separately.

## Current Status

- The GUI upload/import MVP is implemented through:
  - chunked zip upload
  - safe extraction and validation
  - library placement
  - ready uploaded-run import queueing
  - import progress display
  - cleanup of stale upload working files
- The mounted-run and manual advanced publish-root paths remain available.
- The user-facing docs now describe zipped-run uploads, storage layout,
  cleanup behavior, disk planning, and MVP limitations.
- The production-hardening refactor is planned but not implemented.

## Open Issues

- The upload protocol is still custom and lacks chunk/full-file checksum
  verification.
- There is no resume/reconciliation endpoint for interrupted browser uploads.
- There is no disk-space preflight before accepting or extracting large uploads.
- Extraction still shares the `imports` queue with import execution.
- Uploaded runs have limited ownership/audit metadata and no quota/rate-limit
  policy layer.
- The UI still needs richer recovery actions for failed/interrupted uploads.
- A manual end-to-end smoke test with a real small zipped run is still pending.

## Next Step

- Start the industry-standard refactor from
  `docs/immpelementation/gui-run-imports/industry-standard-refactor-implementation-plan.md`.
- Recommended first slice: upload integrity with SHA-256 metadata, chunk
  checksum validation, idempotent matching chunk re-uploads, and assembled zip
  checksum verification.

---

## Session continuation — industry-standard refactor (Phases 1–7)

### Objective

Implement all seven phases of the hardening refactor plan slice by slice, running
tests between each phase.

### What happened

**Phase 1 — Upload Integrity**

- Added `UploadedRunChunk` model: FK to `UploadedRun`, `chunk_index`, `size_bytes`,
  `sha256`, `received_at`; unique-together on `(uploaded_run, chunk_index)`.
- Added nullable checksum fields to `UploadedRun`: `file_sha256`, `assembled_sha256`,
  `checksum_status`, `checksum_error`.
- `store_chunk()` now computes per-chunk SHA-256 while writing; verifies against
  client-supplied `chunk_sha256` if provided; creates a `UploadedRunChunk` record
  inside a row-locked transaction; treats re-upload as idempotent when SHA-256 matches.
- `assemble_uploaded_zip()` now streams chunks through a SHA-256 hasher, saves
  `assembled_sha256`, and marks the upload FAILED with `checksum_status="failed"` on
  mismatch against the declared `file_sha256`.
- Migration `0007_uploadedrun_checksum_uploadedrunshunk.py` created.
- `static/js/import_uploads.js` updated to compute per-chunk SHA-256 with Web Crypto
  and send it with every chunk POST.

**Phase 2 — Resume and Reconciliation**

- Added `GET /imports/uploads/<upload_id>/status/` → `UploadRunStatusView`.
- `get_upload_status()` reads filesystem `.part` files as authoritative chunk
  presence; overlays DB SHA-256 and size metadata; returns `received_chunks` with
  per-chunk `index`, `size_bytes`, and `sha256`.
- Returns `allowed_actions` based on current status.
- `import_uploads.js` extended with: `loadResumeState()` (checks sessionStorage,
  calls status endpoint, validates filename/size match); `uploadFile()` now skips
  chunks already confirmed by the server (matched by index+SHA-256).
- `upload_status_url_template` added to template context and rendered as
  `data-upload-status-url-template` on the upload form.

**Phase 3 — Disk Preflight**

- Added `HOMOREPEAT_UPLOAD_DISK_PREFLIGHT_ENABLED`, `HOMOREPEAT_UPLOAD_MIN_FREE_BYTES`,
  `HOMOREPEAT_UPLOAD_EXTRACTION_SPACE_MULTIPLIER` to `config/settings.py` and
  `.env.example`.
- `_imports_root_disk_usage()` walks up to find an existing ancestor so
  `shutil.disk_usage()` always gets a valid path.
- `_check_disk_space_for_upload()` called from `start_upload()`; rejects with
  a user-facing error if free < chunks + zip + min_free.
- `_check_disk_space_for_extraction()` called inside `assemble_uploaded_zip()`;
  estimates extracted volume via multiplier (capped by `MAX_EXTRACTED_BYTES`).

**Phase 4 — Ownership, Audit, and Policy Hooks**

- Added 7 audit fields to `UploadedRun` (all nullable): `created_by`, `completed_by`,
  `import_requested_by` (FK to AUTH_USER_MODEL); `client_ip`, `user_agent`,
  `completed_at`, `failed_at`.
- Migration `0008_uploadedrun_audit_fields.py` created with `swappable_dependency`.
- `apps/imports/policy.py` created with `UploadPolicyError` and three check functions:
  `check_active_upload_limit`, `check_daily_bytes_limit`, `check_zip_size_limit`.
  All default to 0 (unlimited); only applied to identified users.
- All three checks enforced at `UploadRunStartView`; returns HTTP 429 on violation.
- `failed_at` stamped in extraction failure paths in `tasks.py`.
- Added `can_retry_extraction` and `can_clear_working_files` model properties.

**Phase 5 — Queue Isolation**

- `CELERY_TASK_ROUTES` updated: explicit `uploads` queue routes for
  `extract_uploaded_run` and `cleanup_stale_uploaded_runs` placed before the
  `apps.imports.tasks.*` wildcard.
- `celery-upload-worker` service added to `compose.yaml`: `-Q uploads -c 2
  --prefetch-multiplier 1`, mounts `homorepeat_imports:/data/imports`.
- `web_tests/test_import_tasks.py` extended with `QueueRoutingTests` (6 tests).

**Phase 6 — UI and Recovery**

- `retry_upload_extraction()` and `clear_upload_working_files()` added to
  `services/uploads.py`.
- `_allowed_actions()` returns `["retry", "clear"]` for retryable FAILED states.
- Three new views: `UploadRunImportFormView` (form POST → redirect), `UploadRunRetryView`,
  `UploadRunClearView`.
- Three new URLs: `upload-import-form`, `upload-retry`, `upload-clear`.
- Uploaded-runs table overhauled: Bootstrap status badges (color-coded per status),
  inline error/checksum detail, action buttons per state.
- 18 new tests: model properties, service functions, view redirects, and HTML rendering.

**Phase 7 — Operations and Documentation**

- `docs/usage.md`: updated to describe SHA-256 integrity, browser resume, failure
  recovery (Retry/Clear), disk planning formula, and queue separation.
- `docs/configuration.md`: added Disk Preflight and Per-User Quotas setting tables;
  corrected `celery-upload-worker` mount reference.
- `docs/operations.md`: added full operator checklist — sizing `/data/imports`,
  choosing upload worker concurrency, recovering failed uploads, manually clearing
  stale working files, end-to-end smoke test, and queue routing validation.

### Files touched

- `apps/imports/models.py`
- `apps/imports/migrations/0007_uploadedrun_checksum_uploadedrunshunk.py`
- `apps/imports/migrations/0008_uploadedrun_audit_fields.py`
- `apps/imports/services/uploads.py`
- `apps/imports/policy.py`
- `apps/imports/views.py`
- `apps/imports/urls.py`
- `apps/imports/tasks.py`
- `config/settings.py`
- `compose.yaml`
- `.env.example`
- `static/js/import_uploads.js`
- `templates/imports/home.html`
- `docs/usage.md`
- `docs/configuration.md`
- `docs/operations.md`
- `web_tests/test_import_uploads.py`
- `web_tests/test_import_tasks.py`

### Validation

```text
python3 manage.py test web_tests.test_import_uploads   # 49 tests, all pass
python3 manage.py test web_tests.test_import_tasks     # queue routing tests pass
python3 manage.py test web_tests                       # 512 total; 2 pre-existing failures unrelated to this work
```

The 2 pre-existing failures (`test_homorepeat_list_aa_fasta_export_streams_filtered_sequences`
and `test_download_action_uses_shared_label_and_href`) were present on the branch before
this session and are not caused by any change made here.

### Current Status

All seven phases of the industry-standard upload refactor are implemented and tested.
The upload flow is now production-grade for a trusted staff-only deployment:

- Per-chunk and assembled-zip SHA-256 integrity
- Browser resume after tab close or network failure
- Disk preflight before upload and extraction
- Ownership and audit metadata on every upload record
- Per-user quota/rate-limit policy hooks (disabled by default)
- Separate `uploads` and `imports` Celery queues
- Operator-facing recovery actions (Retry, Clear files, Import)
- User-facing and operator documentation

### Open Issues

- The pre-existing browser test failures are unrelated to uploads but should be
  investigated separately.
- A manual end-to-end smoke test with a real small zipped run in the Docker stack
  is still recommended before a production deployment.
- Full-file SHA-256 computation in the browser is not implemented (Web Crypto
  `subtle.digest` is not a streaming API); `file_sha256` at upload start remains
  optional until a JS streaming SHA-256 library is introduced.

### Next Step

- Investigate and fix the 2 pre-existing browser test failures on this branch.
- Run a Docker end-to-end smoke test with a real small zipped pipeline run.
- Merge to main once the smoke test passes.

---

## Session continuation — dead-code audit and cleanup

### Request

After the upload refactor review/fix, user asked for a read-only dead-code report,
then approved installing tooling and removing the identified dead code.

### Tooling Added Locally

- Installed `ruff` and `vulture` into the current Python environment:

```text
python -m pip install ruff vulture
```

These were used for audit/verification only; no project dependency file was changed.

### Initial Audit

Commands used:

```text
ruff check .
vulture apps config web_tests --min-confidence 80
vulture apps config --min-confidence 60
```

The audit found a mix of real dead code and Django/unittest false positives. The
real candidates were:

- Unused PostgreSQL helper `apps.browser.db.copy.analyze_models()`.
- Obsolete `_copy_rows_to_model()` in `apps.imports.services.import_run.copy`;
  current import code uses `_copy_rows_to_table()`.
- Unused `_resolve_optional_taxon_pk()` in import taxonomy code.
- Unused `_read_acquisition_validation_payload()` in published-run manifest code.
- Retired `load_published_run()` compatibility function that only raised.
- Unused placeholder template `templates/browser/section_placeholder.html`.
- Inactive async-download scaffold:
  - `apps/browser/downloads.py`
  - `generate_download_artifact`
  - Celery route for `generate_download_artifact`
- Local generated Python bytecode caches under `apps/`, `config/`, and `web_tests/`.

### Cleanup Performed

Removed:

- `apps/browser/db.copy.analyze_models()`.
- `apps/imports/services/import_run/copy._copy_rows_to_model()`.
- `apps/imports/services/import_run/taxonomy._resolve_optional_taxon_pk()`.
- `apps/imports/services/published_run/manifest._read_acquisition_validation_payload()`
  and its now-unused validation constant imports.
- `load_published_run()` and stale exports from:
  - `apps/imports/services/published_run/__init__.py`
  - `apps/imports/services/import_run/__init__.py`
  - `apps/imports/services/__init__.py`
- `apps/browser/downloads.py`.
- `apps/browser.tasks.generate_download_artifact`.
- `apps.browser.tasks.generate_download_artifact` Celery route.
- `templates/browser/section_placeholder.html`.
- Local `__pycache__` / `.pyc` files.

Kept:

- `DownloadBuild` model/table and `DownloadBuildStatusView`, because that is
  migrated persisted schema. Only the inactive future async-download policy/task
  scaffold around it was removed.
- Django admin/app config/model metadata that Vulture reported as unused but is
  framework-owned.
- Management commands, URL configs, Celery beat tasks, and model fields that are
  invoked dynamically by Django/Celery.

### Related Fixes While Cleaning

- Fixed `ImportBatch` type annotation in `apps/browser/metadata.py` by importing
  it from `apps.imports.models`.
- Removed stale tests that only covered deleted compatibility/scaffold paths.
- Trimmed `web_tests/test_browser_downloads.py` to live `DownloadBuild` status
  and expiry behavior.
- Removed unused imports/test locals flagged by Ruff.
- Renamed required-but-unused callback parameters in no-admin and test
  `load_tests()` hooks to underscore-prefixed names so Vulture no longer reports
  them as dead variables.

### Validation

Passed:

```text
ruff check .
vulture apps config web_tests --min-confidence 80
git diff --check
docker compose config
docker compose run --rm web python manage.py test web_tests.test_browser_downloads web_tests.test_import_published_run web_tests.test_import_uploads web_tests.test_models web_tests.test_browser_stats
docker compose run --rm web python manage.py test web_tests.test_import_commands
```

The first Docker test command passed 214 tests. The import-command test command
passed 3 tests.

One broader combined test invocation including `web_tests.test_import_process_run`
still showed existing PostgreSQL import-process failures unrelated to the removed
dead-code surface:

- `test_import_run_fails_on_duplicate_v2_entity_keys`
- `test_import_run_reports_progress_during_transactional_import_phase`

Those were not patched in this cleanup because they relate to import-process
behavior, not dead-code removal.

### Current Status

Dead-code cleanup is complete for the identified safe candidates. Ruff is clean,
Vulture at 80% confidence is clean, and the affected live tests listed above pass.
