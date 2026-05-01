# Industry-Standard Upload Refactor Implementation Plan

This plan upgrades the current GUI zipped-run upload path from local MVP to a
web-production hardened workflow while keeping the custom chunk protocol and
app-managed storage.

## Phase 1 - Upload Integrity

Goal: make accepted upload bytes verifiable and repeatable.

Changes:

- Extend `UploadedRun` with checksum metadata (all fields nullable, defaulting
  to NULL for pre-refactor records):
  - `file_sha256`
  - `assembled_sha256`
  - `checksum_status`
  - `checksum_error`
- Add a `UploadedRunChunk` DB model (one row per accepted chunk) that records:
  - FK to `UploadedRun`
  - chunk index
  - size bytes
  - SHA-256
  - received timestamp
  - a database uniqueness constraint on `(uploaded_run, chunk_index)`

  The DB model is the authoritative manifest for fast-path status queries.
  The filesystem `.part` files remain the authoritative byte store. Phase 2
  status reconciliation reads both and treats filesystem presence as truth when
  the two diverge.

- Extend `POST /imports/uploads/start/` to accept an optional `file_sha256`.
- Extend `POST /imports/uploads/<upload_id>/chunk/` to accept an optional
  `chunk_sha256`. When provided, the server verifies the chunk before writing
  the `.part` file. When omitted, the chunk is accepted without verification
  (backward-compatible until Phase 2 ships the JS update).
- Update `static/js/import_uploads.js` to compute per-chunk SHA-256 using
  Web Crypto (`crypto.subtle.digest`) and send it as `chunk_sha256` on every
  chunk upload. Only chunk hashing is added here; full resume logic comes in
  Phase 2.
- Treat re-upload of the same chunk as idempotent only when size and SHA-256
  match the previously accepted `UploadedRunChunk` row.
- Reject conflicting re-uploads with a clear JSON error.
- During `assemble_uploaded_zip`, compute `assembled_sha256` while streaming
  chunks into `source.zip`.
- Reject completion/extraction if `assembled_sha256` does not match
  `file_sha256` (when `file_sha256` was provided at start).
- Phase 1 is compatibility mode: checksum fields are optional so older clients
  still work during deployment. Phase 2 makes `chunk_sha256` required for the
  browser upload path after the JS has shipped. Phase 3 or the final hardening
  pass makes `file_sha256` required for GUI uploads.

Tests:

- start accepts valid full-file SHA-256
- start rejects malformed full-file SHA-256
- chunk upload accepts matching `chunk_sha256`
- chunk upload rejects checksum mismatch
- re-upload of identical chunk is idempotent
- re-upload of same chunk index with different content is rejected
- assembled zip checksum mismatch marks upload failed before extraction

## Phase 2 - Resume and Reconciliation

Goal: let the browser resume from server-authoritative state after refresh,
network failure, or worker restart.

Changes:

- Add `GET /imports/uploads/<upload_id>/status/`.
- Return:
  - `upload_id`
  - status
  - filename
  - size bytes
  - chunk size bytes
  - total chunks
  - received chunks with size and SHA-256
  - received bytes
  - file SHA-256
  - checksum status
  - linked import batch summary when present
  - allowed next actions
- Reconcile status response from filesystem first, then database metadata.
- Update `static/js/import_uploads.js` to complete the full resume flow:
  - compute per-chunk SHA-256 with Web Crypto (already added in Phase 1)
  - compute full-file SHA-256 over the raw file bytes, not by hashing or
    concatenating per-chunk digests
  - use a real incremental SHA-256 implementation for browser-side full-file
    hashing, or defer full-file hash calculation to the server until such a
    client-side implementation is introduced
  - do not load the entire file into memory at once; process the file
    slice-by-slice to stay within browser memory limits for 5 GB-class zips
  - call status when resuming an existing upload
  - skip chunks already accepted by the server (matched by index + SHA-256)
  - upload only missing chunks
  - surface checksum conflicts as terminal errors
- Keep sequential chunk upload for MVP simplicity.

Tests:

- status reports filesystem-present chunks even if DB metadata is stale
- status reports missing chunks after partial upload
- browser helper skips server-reported received chunks
- complete remains idempotent after a retry
- complete rejects when status reconciliation finds missing chunks

## Phase 3 - Disk Preflight

Goal: fail early when upload or extraction would exceed available storage.

Changes:

- Add settings:
  - `HOMOREPEAT_UPLOAD_MIN_FREE_BYTES`
  - `HOMOREPEAT_UPLOAD_EXTRACTION_SPACE_MULTIPLIER`
  - `HOMOREPEAT_UPLOAD_DISK_PREFLIGHT_ENABLED`
- At upload start, require free space for:
  - incoming chunks
  - assembled zip
  - configured minimum free bytes
- Before extraction, require free space for:
  - existing zip/chunks
  - expected extracted limit or multiplier estimate
  - final library copy estimate
  - configured minimum free bytes
- Use `shutil.disk_usage(settings.HOMOREPEAT_IMPORTS_ROOT)`.
- Return user-facing validation errors rather than starting doomed uploads.

Tests:

- start rejects when free space is below required threshold
- extraction rejects when free space drops before extraction
- disk preflight can be disabled for constrained tests/dev setups
- error message includes required and available byte counts

## Phase 4 - Ownership, Audit, and Policy Hooks

Goal: make uploads attributable and enforceable in a multi-user web context.

Changes:

- Extend `UploadedRun` with audit fields (all nullable, defaulting to NULL for
  pre-refactor records):
  - `created_by` (FK to `auth.User`, nullable)
  - `completed_by` (FK to `auth.User`, nullable)
  - `import_requested_by` (FK to `auth.User`, nullable)
  - `client_ip` (text, nullable)
  - `user_agent` (text, nullable)
  - `actor_label` (text, nullable)
  - `completed_at` (datetime, nullable)
  - `failed_at` (datetime, nullable)
- Populate user fields from `request.user` on authenticated requests. When the
  app runs without Django auth (staff-only/local mode), leave user FKs NULL and
  record the actor in `actor_label`. Do not overload `client_ip` with non-IP
  actor labels.
- Add policy helper functions in a new `apps/imports/policy.py` module:
  - `check_active_upload_limit(user)` — raises `UploadPolicyError` when the
    user already has too many active uploads
  - `check_daily_bytes_limit(user, new_bytes)` — raises `UploadPolicyError`
    when the daily byte quota would be exceeded
  - `check_zip_size_limit(user, zip_bytes)` — raises `UploadPolicyError` when
    the zip is above the per-role size cap
- Enforce policy at the view layer: call the relevant helpers at upload start
  and at chunk upload before accepting bytes. Return HTTP 429 with a JSON error
  body on `UploadPolicyError`. Do not enforce in the Celery worker.
- Keep all default limits permissive (effectively unlimited) so current
  staff-only behavior is unchanged without configuration.

Tests:

- authenticated upload records user metadata
- no-admin upload remains usable and auditable
- policy helper rejects when active upload count is exceeded
- policy helper rejects when daily bytes are exceeded
- admin troubleshooting page shows audit fields

## Phase 5 - Queue Isolation

Goal: keep heavy zip extraction from delaying database import execution.

Changes:

- Add explicit Celery routes before the `apps.imports.tasks.*` wildcard:
  - `apps.imports.tasks.extract_uploaded_run` -> `uploads`
  - `apps.imports.tasks.cleanup_stale_uploaded_runs` -> `uploads`
  - `apps.imports.tasks.run_import_batch` -> `imports`
  - `apps.imports.tasks.reset_stale_import_batches` -> `imports`
- Add `celery-upload-worker` to `compose.yaml`.
- Mount `homorepeat_imports:/data/imports` into the upload worker.
- Keep `celery-import-worker` focused on import batches.
- Update docs to describe the two queues and sizing knobs.

Tests:

- Celery route table sends extraction to `uploads`
- import batches still route to `imports`
- Compose config includes upload worker with `/data/imports` volume
- cleanup task remains scheduled and routes to `uploads`

## Phase 6 - UI and Recovery

Goal: expose production-ready upload state and operator actions.

Changes:

- Add explicit uploaded-run actions in `/imports/`:
  - resume upload
  - retry extraction for failed transient states
  - import ready upload
  - clear failed working files
- Display separate statuses for:
  - upload receiving
  - checksum verification
  - received
  - extracting
  - ready
  - queued/importing
  - imported
  - failed
- Show actionable error messages from checksum, disk, zip, and publish-contract
  failures.
- Keep manual publish-root import in the advanced section.
- Keep mounted/library detected runs visible.

Tests:

- ready uploaded run renders Import action
- failed upload renders clear failed-working-files action when applicable
- checksum failure renders checksum-specific message
- disk failure renders disk-specific message
- linked import progress still renders for queued uploads

## Phase 7 - Operations and Documentation

Goal: make the hardened flow maintainable by an operator.

Changes:

- Update `docs/usage.md` with resume, checksum, recovery, and queue behavior.
- Update `docs/configuration.md` with new disk, quota, checksum, and queue
  settings.
- Update `.env.example` with safe defaults.
- Add an operator checklist for:
  - sizing `/data/imports`
  - choosing upload worker concurrency
  - recovering failed uploads
  - clearing old failed working files
  - validating end-to-end upload/import after deployment

Tests:

- `git diff --check`
- `docker compose config`
- focused Django tests for imports/uploads/tasks
- manual smoke test with a small valid zipped run

## Acceptance Criteria

- A 5 GB-class zip upload can resume after browser refresh without re-uploading
  accepted chunks.
- Chunk corruption and assembled-file corruption are rejected before extraction.
- Low disk space is detected before accepting or extracting a large upload.
- Extraction runs on the `uploads` queue and cannot occupy import worker slots.
- Uploaded-run records include user/audit metadata.
- Cleanup remains idempotent and does not delete ready/imported library data.
- Existing mounted-run imports, manual path imports, and `import_run` command
  behavior remain compatible.
