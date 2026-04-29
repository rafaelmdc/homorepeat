# GUI Pipeline Run Imports Overview

## Problem

HomoRepeat is intended to be usable by biologists through the website. The
current import workflow still assumes an operator can configure a Docker mount
or run a management command:

```bash
docker compose exec web python manage.py import_run \
  --publish-root /workspace/homorepeat_pipeline/runs/<run-id>/publish
```

That works for developers and power users, but it is not a good primary path
for a website-first local tool. Users should be able to add pipeline output from
the GUI, queue an import, and watch progress without editing `.env` or
understanding host paths versus container paths.

Pipeline output can be large. Uncompressed runs may be 2-40 GB; zipped runs are
expected to be closer to 5 GB max. This rules out a naive single-request Django
upload, but it makes a resumable/chunked zip-upload workflow practical.

## Goals

- Keep mounted run-folder imports for large local data and advanced users.
- Add a website-first import path for zipped pipeline runs.
- Avoid requiring a site restart when adding another run.
- Avoid requiring users to edit `.env`.
- Store uploaded runs in an app-managed persistent import area.
- Extract, validate, and import runs in background workers.
- Reuse the existing `ImportBatch` and Celery import execution path wherever
  possible.
- Show friendly status and validation errors in `/imports/`.

## Non-Goals

- Do not give the Django container access to the Docker socket or host root.
- Do not try to mount arbitrary host folders from inside the web app.
- Do not make browser upload the only path for 40 GB uncompressed run folders.
- Do not replace the existing `import_run` management command.
- Do not change the published TSV contract.

## Recommended Product Shape

The imports page should become a biologist-facing workflow with two sources:

1. **Detected runs**
   Runs already present in the configured import library are listed with an
   obvious Import button. This path is fastest and avoids copying large data.

2. **Upload zipped run**
   Users upload a `.zip` through the website. The upload is resumable/chunked,
   assembled in persistent storage, extracted by Celery, validated, then queued
   for import.

Both sources should end in the same existing import mechanism:

```text
publish root -> ImportBatch -> run_import_batch Celery task -> canonical browser catalog
```

## Storage Model

Add an app-owned persistent import directory, separate from the optional
read-only pipeline mount:

```text
/data/imports/
  library/
    <run-id>/
      publish/
        metadata/run_manifest.json
        ...
  uploads/
    <upload-id>/
      chunks/
      source.zip
      extracted/
```

In Docker Compose this should be a persistent volume by default:

```yaml
volumes:
  homorepeat_imports:

services:
  web:
    volumes:
      - homorepeat_imports:/data/imports
  celery-import-worker:
    volumes:
      - homorepeat_imports:/data/imports
```

The existing read-only `HOMOREPEAT_RUNS_ROOT` mount can remain for users who
already have local pipeline output folders:

```text
/workspace/homorepeat_pipeline/runs
```

## User-Facing Behavior

### First Use

The user opens `/imports/` and sees:

- Detected runs, if any are already in the import library or mounted runs root.
- Upload zipped run.
- Recent import progress.

No `.env` instructions are needed for the primary GUI path.

### Upload Flow

1. User chooses a pipeline output `.zip`.
2. Browser uploads in chunks with a progress bar.
3. Server records the upload as `receiving`.
4. When upload completes, server queues extraction.
5. Worker extracts safely into `/data/imports/uploads/<upload-id>/extracted/`.
6. Worker finds and validates one `publish/metadata/run_manifest.json`.
7. Worker copies or moves the extracted run into `/data/imports/library/<run-id>/`.
8. The run appears in Detected runs as ready to import, or import starts
   automatically if that option is enabled.

### Import Flow

The user clicks Import. The app creates an existing `ImportBatch` with the
validated publish root and dispatches `run_import_batch`.

Progress continues to use the existing import batch status table.

## Why Not Runtime Mounts From The Website?

Docker bind mounts are configured when a container starts. A Django view running
inside the container cannot safely ask Docker to mount an arbitrary host folder
without privileged access to the Docker daemon. Giving a local web app Docker
socket access would let it control containers and host mounts, which is too much
privilege for this feature.

The safer pattern is:

- persistent app-owned import storage for GUI uploads
- optional read-only host mount for advanced large-data workflows
- no Docker socket access

## Main Risks

- **Large upload reliability:** 5 GB uploads need chunking, progress, and
  resume support.
- **Disk use:** zipped upload plus extraction can temporarily require more than
  2x the zip size.
- **Unsafe zip contents:** extraction must block path traversal, symlinks, huge
  inflated output, and excessive file counts.
- **Duplicate run IDs:** the app must decide whether to reject, replace, or
  version a run already in the import library.
- **Worker availability:** extraction and import should clearly show queued
  versus running states if Celery is not active.
- **Cross-platform Docker volumes:** the app-managed volume is portable, but
  host-mounted advanced paths still depend on Docker Desktop/Linux permissions.

## Success Criteria

- A user can upload a valid zipped run through `/imports/` and import it without
  editing `.env` or running a shell command.
- Adding another run does not require restarting the site.
- Existing mounted-run detection still works.
- Invalid zip files produce friendly validation errors.
- Existing `ImportBatch` progress remains the single import status surface.
- Focused tests cover upload assembly, safe extraction, validation, import
  queueing, and page rendering.
