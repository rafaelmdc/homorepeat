# GUI Pipeline Run Imports Implementation Details

## Current Code Context

Relevant files:

| Concern | File |
|---------|------|
| Import page views | `apps/imports/views.py` |
| Import form | `apps/imports/forms.py` |
| Import URLs | `apps/imports/urls.py` |
| Import models | `apps/imports/models.py` |
| Celery import tasks | `apps/imports/tasks.py` |
| Existing import API | `apps/imports/services/import_run/api.py` |
| Published run inspection | `apps/imports/services/published_run/load.py` |
| Published artifact resolution | `apps/imports/services/published_run/artifacts.py` |
| Import page template | `templates/imports/home.html` |
| Import history template | `templates/imports/history.html` |
| Settings and Compose | `config/settings.py`, `compose.yaml`, `.env.example` |
| Import tests | `web_tests/test_import_views.py`, `web_tests/test_import_tasks.py`, `web_tests/_import_command.py` |

Current import entry points:

- `ImportRunForm` accepts either a detected publish root or a manual publish
  root.
- `ImportsHomeView.form_valid()` calls `enqueue_published_run()` and
  `dispatch_import_batch()`.
- `dispatch_import_batch()` queues `apps.imports.tasks.run_import_batch`.
- `run_import_batch()` calls `process_import_batch()`.
- `process_import_batch()` inspects and imports a publish root.

The new upload flow should feed this existing path rather than replacing it.

## Proposed Data Model

Add a new model in `apps/imports/models.py`:

```python
class UploadedRun(models.Model):
    class Status(models.TextChoices):
        RECEIVING = "receiving", "Receiving"
        RECEIVED = "received", "Received"
        EXTRACTING = "extracting", "Extracting"
        READY = "ready", "Ready"
        QUEUED = "queued", "Queued"
        IMPORTED = "imported", "Imported"
        FAILED = "failed", "Failed"

    original_filename = models.CharField(max_length=255)
    upload_id = models.UUIDField(unique=True, editable=False)
    status = models.CharField(max_length=32, choices=Status.choices, db_index=True)
    size_bytes = models.BigIntegerField(default=0)
    received_bytes = models.BigIntegerField(default=0)
    chunk_size_bytes = models.PositiveIntegerField(default=8 * 1024 * 1024)
    total_chunks = models.PositiveIntegerField(default=0)
    received_chunks = models.JSONField(default=list, blank=True)
    publish_root = models.CharField(max_length=500, blank=True)
    run_id = models.CharField(max_length=200, blank=True, db_index=True)
    error_message = models.TextField(blank=True)
    import_batch = models.ForeignKey(
        "imports.ImportBatch",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="uploaded_runs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

Notes:

- `received_chunks` is enough for an MVP. A separate `UploadedRunChunk` model is
  more normalized but not necessary unless concurrency or audit needs grow.
- `zip_path`, `extracted_root`, and `library_root` should be `@property`
  values derived from `upload_id` and `settings.HOMOREPEAT_IMPORTS_ROOT`, not
  stored fields.
- `publish_root` should be the final app-visible publish directory passed to
  `enqueue_published_run()`.
- Keep `ImportBatch` unchanged at first.

## Settings

Add settings in `config/settings.py`:

```python
HOMOREPEAT_IMPORTS_ROOT = os.getenv("HOMOREPEAT_IMPORTS_ROOT", "/data/imports").strip()
HOMOREPEAT_UPLOAD_MAX_ZIP_BYTES = _env_int("HOMOREPEAT_UPLOAD_MAX_ZIP_BYTES", 5 * 1024 * 1024 * 1024)
HOMOREPEAT_UPLOAD_CHUNK_BYTES = _env_int("HOMOREPEAT_UPLOAD_CHUNK_BYTES", 8 * 1024 * 1024)
HOMOREPEAT_UPLOAD_MAX_EXTRACTED_BYTES = _env_int("HOMOREPEAT_UPLOAD_MAX_EXTRACTED_BYTES", 50 * 1024 * 1024 * 1024)
HOMOREPEAT_UPLOAD_MAX_FILES = _env_int("HOMOREPEAT_UPLOAD_MAX_FILES", 200000)
```

Add `.env.example` entries:

```dotenv
# GUI upload/import storage inside Docker. Usually leave this unchanged.
HOMOREPEAT_IMPORTS_ROOT=/data/imports
HOMOREPEAT_UPLOAD_MAX_ZIP_BYTES=5368709120
```

## Compose Changes

Add a persistent volume:

```yaml
volumes:
  homorepeat_imports:
```

Mount it into services that need upload/import storage:

```yaml
web:
  environment:
    HOMOREPEAT_IMPORTS_ROOT: /data/imports
  volumes:
    - homorepeat_imports:/data/imports

celery-import-worker:
  environment:
    HOMOREPEAT_IMPORTS_ROOT: /data/imports
  volumes:
    - homorepeat_imports:/data/imports
```

The `migrate` service does not need this volume. The `web` service needs it for
chunk writes and listing ready uploaded runs. The `celery-import-worker` needs
it for extraction and import.

## Routes

Extend `apps/imports/urls.py`:

```python
urlpatterns = [
    path("", ImportsHomeView.as_view(), name="home"),
    path("history/", ImportsHistoryView.as_view(), name="history"),
    path("uploads/start/", UploadRunStartView.as_view(), name="upload-start"),
    path("uploads/<uuid:upload_id>/chunk/", UploadRunChunkView.as_view(), name="upload-chunk"),
    path("uploads/<uuid:upload_id>/complete/", UploadRunCompleteView.as_view(), name="upload-complete"),
    path("uploads/<uuid:upload_id>/import/", UploadedRunImportView.as_view(), name="upload-import"),
]
```

Keep these routes behind the existing `StaffOnlyMixin`; no-admin mode will
already bypass staff checks through middleware.

## Services

Create `apps/imports/services/uploads.py` with small, testable functions:

```text
start_upload(filename, size_bytes) -> UploadedRun
store_chunk(uploaded_run, chunk_index, file_obj) -> UploadedRun
assemble_zip(uploaded_run) -> UploadedRun
extract_uploaded_zip(uploaded_run) -> UploadedRun
find_publish_root(extracted_root) -> Path
move_to_library(uploaded_run, publish_root) -> UploadedRun
queue_uploaded_run_import(uploaded_run, replace_existing=False) -> ImportBatch
```

Use `pathlib.Path` and Django settings. Do not embed Compose paths in business
logic.

## Chunk Upload Protocol

MVP custom protocol:

1. `POST /imports/uploads/start/`
   JSON body:

   ```json
   {
     "filename": "run-alpha.zip",
     "size_bytes": 1234567890,
     "total_chunks": 149
   }
   ```

   Response:

   ```json
   {
     "upload_id": "...",
     "chunk_size_bytes": 8388608,
     "received_chunks": []
   }
   ```

2. `POST /imports/uploads/<upload_id>/chunk/`
   Multipart body:

   ```text
   chunk_index=<int>
   chunk=<file>
   ```

   Write to:

   ```text
   /data/imports/uploads/<upload-id>/chunks/<chunk-index>.part
   ```

   Response includes updated received count.

3. `POST /imports/uploads/<upload_id>/complete/`
   Assembles chunks into `source.zip`, marks `received`, and dispatches
   extraction.

This can later be replaced with `tus`/Uppy if we want a standard resumable
protocol. For this codebase, a focused custom protocol keeps dependencies small
because `pyproject.toml` currently has no upload-specific dependency.

## Safe Zip Extraction

Extraction must reject unsafe archives before writing outside the upload area.

Rules:

- Only accept `.zip` files.
- Reject absolute paths.
- Reject `..` path traversal.
- Reject symlinks and special files if present in zip metadata.
- Enforce `HOMOREPEAT_UPLOAD_MAX_EXTRACTED_BYTES`.
- Enforce `HOMOREPEAT_UPLOAD_MAX_FILES`.
- Extract into a fresh directory:

  ```text
  /data/imports/uploads/<upload-id>/extracted/
  ```

- Find exactly one publish root by searching for:

  ```text
  metadata/run_manifest.json
  ```

  where its parent directory is named `publish`.

- Validate with existing published-run code:

  ```python
  inspect_published_run(publish_root)
  ```

Do not import until validation passes.

## Moving Into The Import Library

After validation, move or copy the extracted run into:

```text
/data/imports/library/<run-id>/
```

The final publish root should become:

```text
/data/imports/library/<run-id>/publish
```

Duplicate run ID behavior for MVP:

- If the target library directory exists, mark the upload failed with a friendly
  error.
- Let the user choose `replace_existing` during import only after a later UI
  pass clarifies the data replacement story.

Later option:

- Store duplicates as `/data/imports/library/<run-id>--<upload-id>/` while the
  imported pipeline `run_id` remains unchanged.

## Celery Tasks

Extend `apps/imports/tasks.py`:

```python
@shared_task(bind=True, max_retries=1)
def extract_uploaded_run(self, uploaded_run_id: int) -> None:
    ...

@shared_task
def cleanup_failed_uploads() -> dict[str, int]:
    ...
```

`extract_uploaded_run` should:

1. Mark status `extracting`.
2. Assemble if needed.
3. Extract safely.
4. Validate.
5. Move to library.
6. Mark status `ready`.

Import queueing can stay view-driven at first:

```python
batch = enqueue_published_run(uploaded_run.publish_root)
dispatch_import_batch(batch)
uploaded_run.import_batch = batch
uploaded_run.status = UploadedRun.Status.QUEUED
```

When `batch` completes, the upload row does not need to update immediately for
MVP because import status is visible through `ImportBatch`. Later, a periodic
task can mirror `imported`/`failed` onto `UploadedRun`.

## Import Page Changes

Update `templates/imports/home.html` so the primary page reads as:

1. **Detected pipeline runs**
   - Combine existing mounted runs from `_discover_publish_runs()` with ready
     uploaded runs from `/data/imports/library`.
   - Show Run, Finished, Source, Status, Import action.

2. **Upload zipped pipeline run**
   - File picker for `.zip`.
   - Progress bar.
   - Upload status list.

3. **Advanced path import**
   - Existing manual publish-root input, collapsed in a `<details>` block.

4. **Recent imports**
   - Existing recent import batches.

Change language:

- Prefer "pipeline run" over "publish root".
- Prefer "Import" over "Queue import" in primary buttons.
- Keep technical paths visible in smaller secondary text for troubleshooting.

## View Changes

In `apps/imports/views.py`:

- Keep `ImportsHomeView`.
- Add uploaded-run querysets to context:

  ```python
  context["uploaded_runs"] = UploadedRun.objects.order_by("-created_at")[:10]
  context["ready_uploaded_runs"] = UploadedRun.objects.filter(status=UploadedRun.Status.READY)
  ```

- Add JSON class-based views for upload start/chunk/complete.
- Add a POST view for queueing a ready uploaded run import.

For manual path validation, improve `ImportRunForm.clean()` by checking:

- resolved path exists
- `metadata/run_manifest.json` exists
- `inspect_published_run()` succeeds

Return form errors instead of creating failed background batches for obvious
path mistakes.

## Frontend

Add a small script, for example:

```text
static/js/import_uploads.js
```

Responsibilities:

- Read selected zip.
- Call upload start.
- Slice file into configured chunk sizes.
- Upload chunks sequentially for MVP.
- Show progress percent.
- Retry a failed chunk a small number of times.
- Call complete.
- Refresh the page or update the upload row.

Sequential chunk upload is simpler and adequate for a local app. Parallel chunk
upload can be added later.

## Tests

Add focused tests in `web_tests/test_import_uploads.py`.

Recommended coverage:

- Start upload rejects non-zip filenames.
- Start upload rejects size over `HOMOREPEAT_UPLOAD_MAX_ZIP_BYTES`.
- Chunk upload writes a `.part` file and records received chunk index.
- Complete rejects missing chunks.
- Safe extraction rejects `../evil.txt`.
- Safe extraction rejects archives without `publish/metadata/run_manifest.json`.
- Valid minimal zip becomes `UploadedRun.Status.READY`.
- Ready uploaded run import creates an `ImportBatch`.
- `/imports/` renders upload controls and uploaded run status.
- Existing detected mounted-run tests still pass.

Use `TemporaryDirectory()` plus `override_settings(HOMOREPEAT_IMPORTS_ROOT=...)`
to keep tests isolated.

## Validation Commands

Focused:

```bash
python manage.py test web_tests.test_import_views web_tests.test_import_uploads web_tests.test_import_tasks
```

Containerized:

```bash
docker compose run --rm web python manage.py test \
  web_tests.test_import_views \
  web_tests.test_import_uploads \
  web_tests.test_import_tasks
```

Manual:

1. Start Compose.
2. Open `http://localhost:8000/imports/`.
3. Upload a small valid zipped run.
4. Confirm it reaches Ready.
5. Click Import.
6. Confirm the import batch progresses and the run appears in Browser.

## Known Issues and Implementation Notes

### Issue: Chunk assembly in the web process will hit the gunicorn timeout

Gunicorn runs with `--timeout 120` (`compose.yaml`). The plan puts `assemble_zip()` inside the
`complete` view. Sequentially reading and concatenating 625 × 8 MB chunks into a 5 GB file can
exceed 120 s on a slow volume. Move assembly into `extract_uploaded_run` (step 2 of that task)
and keep the `complete` view responsible only for marking `received` and dispatching the task.

### Issue: Race condition on `received_chunks` JSONField

Gunicorn runs 4 workers. If the browser retries a chunk and the retry lands on a different worker
while the first is still writing, both read the same JSON list, append their index, and one write
silently wins. `store_chunk()` should write each chunk to a temporary file, atomically rename it
into place, then update `received_chunks` in a short `select_for_update()` transaction. Do not
hold a database row lock while streaming a large chunk body.

### Issue: `extract_uploaded_run` would share the `imports` Celery queue with `run_import_batch`

`celery-import-worker` runs with `-c 2`. A 5 GB extraction task can occupy a slot for many
minutes. One extraction and one import can still run together, but two long extractions can occupy
the whole imports pool and delay actual imports. Consider routing `extract_uploaded_run` to a
separate queue (e.g. `uploads`) with an explicit Celery route before the existing
`apps.imports.tasks.*` wildcard, or at minimum document the concurrency trade-off explicitly.

### Issue: No CSRF handling specified for the JS upload API

The chunk upload views are JSON POST endpoints called from `import_uploads.js`. Django's CSRF
middleware rejects them unless the fetch requests include the `X-CSRFToken` header. The plan
doesn't specify this. The JS must read the token from the cookie or a template-injected meta tag
and include it on every POST.

### Issue: Duplicate run-ID library move is not atomic

The plan marks an upload failed if the library directory already exists. Two concurrent uploads
of the same `run_id` can both see no directory and both pass the check. Depending on the exact move
operation, the second upload may fail late, nest files unexpectedly, or leave an inconsistent
library path. Fix with either a DB-level uniqueness guard for active/terminal uploaded runs or a
filesystem-level atomic `Path.mkdir(exist_ok=False)` reservation which raises on collision before
moving files.

### Issue: `received_chunks` DB state can diverge from the filesystem after a crash

If the web process writes a `.part` file but crashes before updating `received_chunks`, the DB
under-counts received chunks and the `complete` view's missing-chunk check blocks a valid upload
forever. `assemble_zip()` should scan the `chunks/` directory with `glob("*.part")` as the
authoritative source and treat the DB field as a fast-path hint only.

### Issue: `cleanup_failed_uploads` task is never scheduled

When `cleanup_failed_uploads` is implemented, `CELERY_BEAT_SCHEDULE` in `config/settings.py` must
also be updated to run it. Add an entry to the beat schedule alongside
`reset_stale_import_batches`.

### Issue: `size_bytes` / `total_chunks` consistency not validated on start

The start request accepts both from the client. The server must verify
`total_chunks == ceil(size_bytes / chunk_size_bytes)`. A mismatch (e.g. `total_chunks=1` for a
4 GB file) would silently produce a corrupt assembly.

---

### Optimization: Refactor `_discover_publish_runs()` to accept a root argument

The view will merge results from `HOMOREPEAT_RUNS_ROOT` and `/data/imports/library/`. The
current function hardcodes `_runs_root()`. Extract to
`_discover_publish_runs_in(root: Path) -> list[DetectedPublishRun]` and call it for each root.
This avoids duplicating the manifest-reading and dedup logic.

### Optimization: Add `select_related("import_batch")` to the uploaded-runs queryset

The template will display `import_batch.status` per row. Without `select_related`, each row
triggers a separate query. The context queryset should be:

```python
UploadedRun.objects.select_related("import_batch").order_by("-created_at")[:10]
```

### Optimization: Catch `ImportContractError` separately in `extract_uploaded_run`

`run_import_batch` already handles `ImportContractError` without retrying (the zip content is
deterministically invalid). `extract_uploaded_run` should do the same: catch
`ImportContractError`, set `status=FAILED` with a readable message, and not retry.

### Optimization: Make the `complete` endpoint idempotent

If the browser retries `complete` after a network drop the server re-assembles or re-dispatches.
Check at the start of the view whether `status` is already `received` or beyond and return `200`
without re-processing.

### Optimization: Make ready-run import queueing idempotent

If the user double-clicks the Import button, or the browser retries the POST after a network drop,
the app can create multiple `ImportBatch` rows for the same `UploadedRun`. Lock the `UploadedRun`
row during import queueing and return the existing linked `import_batch` when the upload is already
`queued` or beyond.

### Optimization: Extend the existing auto-refresh condition to cover uploaded runs

`ImportsHomeView.get_context_data()` already sets `enable_import_auto_refresh` from active
`ImportBatch` rows. Extend the condition to also trigger when any `UploadedRun` is in
`receiving`, `received`, `extracting`, or `queued` — no new polling infrastructure needed.

### Optimization: Derive filesystem paths from `upload_id` at runtime

`zip_path`, `extracted_root`, and `library_root` are deterministic:

```text
{IMPORTS_ROOT}/uploads/{upload_id}/source.zip
{IMPORTS_ROOT}/uploads/{upload_id}/extracted/
{IMPORTS_ROOT}/library/{run_id}/
```

Expose these as `@property` methods on `UploadedRun` derived from `upload_id` + settings.
Only `publish_root` (which is set after the manifest `run_id` is known) truly needs to be stored
as a field. This reduces stored redundancy and removes the risk of stale path fields if settings
change.

---

## Suggested Implementation Slices

### Slice 1 - Storage and model

- Add settings (`HOMOREPEAT_IMPORTS_ROOT`, `HOMOREPEAT_UPLOAD_MAX_ZIP_BYTES`,
  `HOMOREPEAT_UPLOAD_CHUNK_BYTES`, `HOMOREPEAT_UPLOAD_MAX_EXTRACTED_BYTES`,
  `HOMOREPEAT_UPLOAD_MAX_FILES`) in `config/settings.py`.
- Add `.env.example` entries.
- Add Compose persistent volume (`homorepeat_imports`) and mount it into `web`
  and `celery-import-worker`.
- Add `UploadedRun` model and migration.
  - Drop `zip_path`, `extracted_root`, and `library_root` as stored fields;
    expose them as `@property` methods derived from `upload_id` + settings
    (see Optimization: Derive filesystem paths). Only `publish_root` needs to
    be stored because it depends on the manifest `run_id`.
- Add admin registration for troubleshooting.
- Tests: `UploadedRun` can be created with defaults; `@property` paths resolve
  against `HOMOREPEAT_IMPORTS_ROOT`.

### Slice 2 - Upload API

- Decide and implement the `extract_uploaded_run` queue routing before
  writing the task dispatch call (see Issue: shared `imports` queue).
- Add `UploadRunStartView`, `UploadRunChunkView`, `UploadRunCompleteView`.
- Add upload service functions.
  - **`store_chunk()`**: write chunk to a temp file, atomically `rename()` it
    into the `chunks/` directory, then update `received_chunks` inside a
    `select_for_update()` transaction. Do not hold the DB lock while reading
    the request body (see Issue: race condition on `received_chunks`).
  - **`complete` view**: mark `received` and dispatch extraction only. Do not
    assemble the zip in the web process — assembly belongs in the Celery task
    (see Issue: gunicorn timeout).
  - **`complete` view**: check `status` at entry and return `200` without
    re-processing if already `received` or beyond (see Optimization: idempotent
    `complete`).
  - **`start` view**: validate `total_chunks == ceil(size_bytes /
    chunk_size_bytes)` and reject mismatches (see Issue: `size_bytes` /
    `total_chunks` consistency).
- The imports page must render enough CSRF context for `import_uploads.js` to
  send `X-CSRFToken` from the cookie or a template-injected value on every
  upload POST (see Issue: CSRF handling).
- Tests (JS-free):
  - Start rejects non-zip filename.
  - Start rejects size over `HOMOREPEAT_UPLOAD_MAX_ZIP_BYTES`.
  - Start rejects inconsistent `total_chunks` vs `size_bytes`.
  - Chunk write produces a `.part` file and records the chunk index.
  - Complete on a partially received upload returns an error.
  - Complete on a fully received upload marks `received` and dispatches task.
  - Second `complete` call on an already-`received` upload returns `200`
    without re-dispatching.

### Slice 3 - Safe extraction and validation

- Decide Celery queue routing for `extract_uploaded_run` (separate `uploads`
  queue, or accept sharing `imports` with `-c 2`). Update `CELERY_TASK_ROUTES`
  in `config/settings.py` and `compose.yaml` before merging (see Issue: shared
  `imports` queue).
- Add `extract_uploaded_run` Celery task:
  1. Mark `extracting`.
  2. Assemble zip from chunks (moved here from the `complete` view).
  3. Extract safely.
  4. Validate with `inspect_published_run()`.
  5. Move to library with `Path.mkdir(exist_ok=False)` as the atomic collision
     guard (see Issue: duplicate run-ID move not atomic).
  6. Mark `ready` or `failed`.
- Add zip safety checks (path traversal, symlinks, byte/file-count limits).
- `find_publish_root()` must enforce exactly one `publish/metadata/run_manifest.json`;
  raise a clear error if zero or more than one is found.
- `assemble_zip()` must scan `chunks/*.part` as the source of truth rather than
  `received_chunks` (see Issue: DB/filesystem divergence after crash).
- Catch `ImportContractError` explicitly: set `status=FAILED` with the
  validation message and do not retry (see Optimization: `ImportContractError`
  handling).
- Tests:
  - Extraction rejects `../evil.txt` path traversal.
  - Extraction rejects archive over `HOMOREPEAT_UPLOAD_MAX_EXTRACTED_BYTES`.
  - Extraction rejects archive with no `publish/metadata/run_manifest.json`.
  - Extraction rejects archive with multiple `publish/metadata/run_manifest.json`.
  - Extraction with an invalid manifest sets `status=FAILED` with a readable
    message and does not enqueue a retry.
  - Valid minimal zip moves to library and sets `status=READY`.
  - Duplicate `run_id` sets `status=FAILED` with a clear duplicate message.
  - Assembly reads `.part` files from disk, ignoring `received_chunks` count.

### Slice 4 - Imports page UX

- Refactor `_discover_publish_runs()` in `views.py` to
  `_discover_publish_runs_in(root: Path)` and call it for both
  `HOMOREPEAT_RUNS_ROOT` and `/data/imports/library/` (see Optimization:
  refactor `_discover_publish_runs()`).
- Add `uploaded_runs` and `ready_uploaded_runs` to context with
  `select_related("import_batch")` (see Optimization: `select_related`).
- Extend `enable_import_auto_refresh` to also trigger when any `UploadedRun`
  is in `receiving`, `received`, `extracting`, or `queued` (see Optimization:
  auto-refresh extension).
- Redesign `templates/imports/home.html` with the four-section layout
  (detected runs, upload form, advanced path, recent imports).
- Demote manual publish-root input to a `<details>` block.
- Add `static/js/import_uploads.js` with chunk upload, progress bar, retry,
  and `complete` call. Include `X-CSRFToken` header on every POST (see Issue:
  CSRF handling).
- Tests:
  - `/imports/` renders upload controls.
  - `/imports/` lists `UploadedRun` rows with status.
  - Uploaded runs from library root appear alongside mounted-run detections.
  - Existing detected mounted-run tests still pass.

### Slice 5 - Queue import from uploaded run

- Add `UploadedRunImportView` (POST, staff-only) that:
  - Acquires a `select_for_update()` lock on the `UploadedRun` row.
  - Returns the existing linked `import_batch` if already `queued` or beyond
    (idempotent under double-submit).
  - Calls `enqueue_published_run(uploaded_run.publish_root)` and
    `dispatch_import_batch()`.
  - Links `UploadedRun.import_batch` and sets `status=QUEUED`.
- Tests:
  - Import action on a `READY` upload creates an `ImportBatch` and links it.
  - Double-submit returns the existing batch without creating a second one.
  - Import action on a non-`READY` upload returns an error.

### Slice 6 - Polish and cleanup

- Implement `cleanup_failed_uploads` Celery task.
- Add it to `CELERY_BEAT_SCHEDULE` in `config/settings.py` alongside
  `reset_stale_import_batches` (see Issue: `cleanup_failed_uploads` never
  scheduled).
- Add docs in `docs/usage.md` and `docs/configuration.md`.
- Add size/disk-space warnings to the UI.
- Consider automatic import after successful validation.
