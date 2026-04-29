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
    zip_path = models.CharField(max_length=500, blank=True)
    extracted_root = models.CharField(max_length=500, blank=True)
    library_root = models.CharField(max_length=500, blank=True)
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

## Suggested Implementation Slices

### Slice 1 - Storage and model

- Add settings.
- Add Compose persistent volume.
- Add `UploadedRun` model and migration.
- Add admin registration for troubleshooting.
- Add basic tests.

### Slice 2 - Upload API

- Add start/chunk/complete views.
- Add upload service functions.
- Add JS-free API tests for chunk assembly.

### Slice 3 - Safe extraction and validation

- Add extraction task.
- Add zip safety checks.
- Reuse `inspect_published_run()`.
- Mark uploads ready or failed.

### Slice 4 - Imports page UX

- Redesign `/imports/` around detected runs and upload status.
- Demote manual path import to advanced.
- Add upload JavaScript and progress UI.

### Slice 5 - Queue import from uploaded run

- Add import action for ready uploaded runs.
- Link `UploadedRun` to `ImportBatch`.
- Extend tests around queueing and recent status.

### Slice 6 - Polish and cleanup

- Add cleanup task for stale incomplete uploads.
- Add docs in `docs/usage.md` and `docs/configuration.md`.
- Add size/disk-space warnings.
- Consider automatic import after successful validation.
