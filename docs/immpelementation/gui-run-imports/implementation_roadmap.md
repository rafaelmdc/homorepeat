# GUI Pipeline Run Imports Implementation Roadmap

This roadmap breaks the GUI upload/import work into small implementation phases.
Each phase should leave the app in a reviewable state and keep the existing
mounted/manual import path working.

## Phase 0 - Baseline Safety

Goal: tighten the current import page behavior before adding upload storage.

Slices:

1. Improve manual path validation.
   - Resolve the submitted publish root.
   - Require `metadata/run_manifest.json`.
   - Call `inspect_published_run()` during form validation.
   - Return form errors instead of queueing obviously invalid paths.

2. Refactor detected-run discovery.
   - Extract `_discover_publish_runs_in(root: Path)`.
   - Keep `_discover_publish_runs()` as the mounted-runs wrapper.
   - Preserve the current display and sort behavior.

Validation:

```bash
python manage.py test web_tests.test_import_views web_tests.test_import_tasks
```

## Phase 1 - Storage And Model

Goal: add app-owned persistent storage and database tracking without changing
the visible upload UI yet.

Slices:

1. Add settings.
   - `HOMOREPEAT_IMPORTS_ROOT`
   - `HOMOREPEAT_UPLOAD_MAX_ZIP_BYTES`
   - `HOMOREPEAT_UPLOAD_CHUNK_BYTES`
   - `HOMOREPEAT_UPLOAD_MAX_EXTRACTED_BYTES`
   - `HOMOREPEAT_UPLOAD_MAX_FILES`

2. Add Docker Compose storage.
   - Create the `homorepeat_imports` volume.
   - Mount it at `/data/imports` in `web` and `celery-import-worker`.
   - Pass `HOMOREPEAT_IMPORTS_ROOT=/data/imports` to both services.

3. Add `UploadedRun`.
   - Track filename, `upload_id`, status, sizes, chunk metadata, `run_id`,
     `publish_root`, errors, and optional `ImportBatch`.
   - Derive deterministic upload/extraction paths from `upload_id` and settings.
   - Register the model in admin for troubleshooting.

Validation:

```bash
python manage.py makemigrations --check --dry-run
python manage.py test web_tests.test_import_views
```

## Phase 2 - Upload API

Goal: support resumable zip upload through server-side endpoints, without
extracting or importing yet.

Slices:

1. Add upload routes and views.
   - `POST /imports/uploads/start/`
   - `POST /imports/uploads/<uuid:upload_id>/chunk/`
   - `POST /imports/uploads/<uuid:upload_id>/complete/`

2. Add upload service functions.
   - Validate `.zip` filename and max upload size.
   - Validate `total_chunks == ceil(size_bytes / chunk_size_bytes)`.
   - Validate chunk indexes and chunk size bounds.
   - Write chunk bodies to temporary files and atomically rename into place.
   - Update `received_chunks` in a short row-locked transaction.

3. Make `complete` idempotent.
   - Treat filesystem chunks as authoritative during completion.
   - Reject missing chunks with a friendly JSON error.
   - Mark status `received`.
   - Do not assemble the zip in the web request.

4. Add CSRF-aware upload JavaScript scaffolding.
   - Include `X-CSRFToken` on every POST.
   - Upload chunks sequentially for MVP.
   - Show upload progress and retry failed chunks a small number of times.

Validation:

```bash
python manage.py test web_tests.test_import_views web_tests.test_import_uploads
```

## Phase 3 - Extraction And Validation Worker

Goal: assemble, safely extract, validate, and move uploaded runs into the import
library in the background.

Slices:

1. Add `extract_uploaded_run`.
   - Dispatch it from `complete`.
   - Mark status `extracting`.
   - Assemble `source.zip` from chunk files in the Celery task.
   - Make the task idempotent for already-received or ready uploads.

2. Implement safe zip extraction.
   - Reject non-zip input.
   - Reject absolute paths and `..` traversal.
   - Reject symlinks and special files in zip metadata.
   - Enforce extracted-byte and file-count limits.
   - Extract into a fresh upload-specific directory.

3. Find and validate the publish root.
   - Require exactly one `publish/metadata/run_manifest.json`.
   - Call `inspect_published_run()`.
   - Catch `ImportContractError` separately and mark the upload failed without
     retrying.

4. Move into the app import library.
   - Reserve `/data/imports/library/<run-id>/` atomically with
     `Path.mkdir(exist_ok=False)`.
   - Move or copy the validated run into the reserved directory.
   - Store the final `publish_root`.
   - Mark status `ready`.

Validation:

```bash
python manage.py test web_tests.test_import_uploads web_tests.test_import_tasks
```

## Phase 4 - Imports Page UX

Goal: expose uploaded runs and detected library runs on `/imports/`.

Slices:

1. Show detected pipeline runs.
   - Merge mounted runs from `HOMOREPEAT_RUNS_ROOT`.
   - Include ready uploaded runs from the app import library.
   - Keep run ID, finished time, source, status, and import action visible.

2. Add upload status UI.
   - File picker for `.zip`.
   - Progress bar.
   - Recent uploaded-run status list.
   - Friendly error messages for failed validation or extraction.

3. Demote manual path import.
   - Keep the existing manual publish-root path.
   - Move it into an advanced `<details>` section.

4. Extend auto-refresh.
   - Refresh while import batches are active.
   - Also refresh while uploaded runs are `receiving`, `received`,
     `extracting`, or `queued`.

Validation:

```bash
python manage.py test web_tests.test_import_views web_tests.test_import_uploads
```

## Phase 5 - Queue Import From Uploaded Runs

Goal: connect ready uploaded runs to the existing `ImportBatch` import path.

Slices:

1. Add import POST endpoint.
   - Only allow imports for `ready` uploads.
   - Lock the `UploadedRun` row during queueing.
   - Return the existing linked `import_batch` if the upload is already queued
     or imported.

2. Reuse existing import services.
   - Call `enqueue_published_run(uploaded_run.publish_root)`.
   - Call `dispatch_import_batch(batch)`.
   - Link `UploadedRun.import_batch`.
   - Mark status `queued`.

3. Display linked import progress.
   - Use `select_related("import_batch")` for uploaded-run querysets.
   - Show the linked batch status and progress on `/imports/`.

Validation:

```bash
python manage.py test web_tests.test_import_views web_tests.test_import_uploads web_tests.test_import_tasks
```

## Phase 6 - Cleanup And Operational Polish

Goal: handle stale uploads, disk use, and worker operations after the core path
works.

Slices:

1. Add upload cleanup.
   - Remove stale incomplete upload directories.
   - Remove failed upload directories after a retention window.
   - Keep ready/imported library data.
   - Schedule cleanup in `CELERY_BEAT_SCHEDULE`.

2. Decide extraction queue routing.
   - Either keep extraction on the `imports` queue and document the concurrency
     trade-off, or add a separate `uploads` queue and worker.
   - If adding a queue, add an explicit Celery task route before the
     `apps.imports.tasks.*` wildcard.

3. Add docs.
   - Update `docs/usage.md`.
   - Update `.env.example`.
   - Mention disk requirements for zip plus extracted data.

4. Manual smoke test.
   - Upload a small valid zipped run.
   - Confirm it reaches Ready.
   - Import it.
   - Confirm the batch completes and the run appears in Browser.

Validation:

```bash
python manage.py test web_tests.test_import_views web_tests.test_import_uploads web_tests.test_import_tasks
docker compose config
```

## Recommended Review Order

1. Phase 0
2. Phase 1
3. Phase 2 without JavaScript polish
4. Phase 3
5. Phase 4 UI polish
6. Phase 5
7. Phase 6

Avoid starting Phase 4 before Phase 2 and Phase 3 have API coverage. The page
can be polished quickly once upload and extraction behavior is proven in tests.
