# Industry-Standard Upload Refactor Overview

## Purpose

The current GUI upload/import path is a strong local MVP: it supports chunked
zip upload, background extraction, safe zip validation, app-managed storage,
cleanup, and import progress through `ImportBatch`. The next refactor should
raise that path to a web-production standard while preserving the product
direction that already works for PAARTA:

- keep mounted run-folder imports for very large local outputs
- keep app-managed persistent storage for GUI uploads
- keep the existing published PAASTA v2 contract
- keep the existing `ImportBatch` import execution path
- harden the custom upload protocol instead of replacing it with `tus`, S3
  multipart upload, or object storage in this refactor

## Target Standard

The target is web-production hardening for authenticated staff or authorized
users. This is broader than a trusted single-user workstation, but it is not a
cloud-object-storage redesign.

The refactored upload path should provide:

- upload integrity guarantees through SHA-256 checksums
- resumable upload reconciliation from server-side state
- disk-space preflight before accepting or extracting large uploads
- explicit upload ownership and audit metadata
- quota and rate-limit hooks
- extraction queue isolation from import execution
- clear recovery actions for failed or interrupted uploads
- operationally safe cleanup that never deletes validated library data unless a
  future explicit delete feature does so

## Current State

The current implementation uses:

- custom chunked upload endpoints under `/imports/uploads/`
- sequential browser chunk upload in `static/js/import_uploads.js`
- filesystem-backed chunks under
  `/data/imports/uploads/<upload-id>/chunks/`
- Celery extraction through `extract_uploaded_run`
- safe zip checks for traversal, symlinks/special files, extracted byte limits,
  and file-count limits
- final validated library placement under
  `/data/imports/library/<run-id>/publish`
- import queueing through `enqueue_published_run()` and `dispatch_import_batch()`
- cleanup through `cleanup_stale_uploaded_runs`

Known gaps:

- no per-chunk checksum verification
- no full-file checksum verification
- no dedicated resume/status endpoint
- no disk-space preflight
- extraction shares the `imports` Celery queue with import batches
- limited user/audit metadata
- no quota/rate-limit policy layer
- the UI does not expose all recovery actions a production operator expects

## Refactor Direction

### Keep the custom upload protocol

The custom protocol stays because the app is local-first, has no object-storage
dependency, and already owns the web and worker stack. The refactor should make
the protocol robust rather than switch protocols.

Required protocol hardening:

- the browser computes SHA-256 per chunk
- the browser can provide a full-file SHA-256 before upload completion
- the server verifies chunk hashes before accepting `.part` files
- the worker verifies the assembled file hash before extraction
- the server exposes received chunk state for resume
- repeated chunk upload is idempotent when content/hash match and rejected when
  they conflict

### Add upload state reconciliation

The filesystem remains authoritative for chunk presence and sizes. The database
records fast-path metadata and audit state. A status endpoint reconciles both:

```text
GET /imports/uploads/<upload-id>/status/
```

This endpoint lets the browser resume after refresh, network drop, or a web
worker restart.

### Add disk preflight

The system should reject uploads or extraction when configured storage has too
little free space. The check should be conservative because the temporary disk
footprint can include:

```text
chunk files + assembled zip + extracted files + final library copy
```

Mounted-run import remains the preferred workflow for very large uncompressed
outputs.

### Isolate extraction work

Zip extraction is disk and CPU heavy. Import execution is database heavy and
user-visible. They should not compete for the same `imports` worker pool after
this refactor.

The target routing is:

```text
extract_uploaded_run          -> uploads queue
cleanup_stale_uploaded_runs   -> uploads queue
run_import_batch              -> imports queue
reset_stale_import_batches    -> imports queue
```

Compose should add a `celery-upload-worker` service with the same
`homorepeat_imports:/data/imports` volume mount as `web` and
`celery-import-worker`.

## Security and Operations Boundaries

This refactor must not:

- give the Django app access to the Docker socket
- mount arbitrary host paths from the website
- change the PAASTA publish contract
- require object storage
- delete ready/imported library data during cleanup

This refactor should prepare for, but does not have to fully implement:

- user-specific quotas
- malware scanning integration
- organization-level access control
- externally stored upload objects

Those can be layered later once ownership/audit and upload policy hooks exist.

## Success Criteria

- A browser can resume an interrupted upload from server-reported state.
- Corrupt chunks and corrupt assembled zips are rejected before extraction.
- A low-disk condition fails early with a clear user-facing error.
- Extraction cannot starve import batches because it runs on a separate queue.
- Upload records carry enough user/audit metadata for operators to understand
  who uploaded what and when.
- Cleanup removes stale working files without touching validated library data.
- The existing mounted-run and manual import paths continue to work.
