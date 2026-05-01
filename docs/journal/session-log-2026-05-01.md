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
