# Usage

## Local Setup

Copy the example environment file and start the stack:

```bash
cp .env.example .env
docker compose up --build
```

The `migrate` service runs automatically before `web` starts. The app is available at **http://localhost:8000**.

On subsequent starts:

```bash
docker compose up
```

The Compose stack exposes:

- web app: `http://localhost:8000`
- PostgreSQL: local port `5432`
- Celery workers: import, graph pre-warming, and download generation queues

To run management commands inside the stack:

```bash
docker compose exec web python manage.py <command>
```

## Importing PAASTA Runs

PAARTA ingests PAASTA (Poly-Amino Acid Sequence Tract Analyzer) — [PAASTA](../homorepeat_pipeline) runs the pipeline; PAARTA imports what it publishes. Browser requests read from the database; they do not access pipeline files at request time.

The supported import format is publish contract v2. A v2 `publish/` directory has this layout:

```text
publish/
  calls/
    repeat_calls.tsv
    run_params.tsv
  tables/
    genomes.tsv
    taxonomy.tsv
    matched_sequences.tsv
    matched_proteins.tsv
    repeat_call_codon_usage.tsv
    repeat_context.tsv
    download_manifest.tsv
    normalization_warnings.tsv
    accession_status.tsv
    accession_call_counts.tsv
  summaries/
    status_summary.json
    acquisition_validation.json
  metadata/
    run_manifest.json
```

`metadata/run_manifest.json` must include `publish_contract_version: 2`.

**Manual import:**

```bash
docker compose exec web python manage.py import_run \
  --publish-root /workspace/homorepeat_pipeline/runs/<run-id>/publish
```

**Import queue UI for mounted runs:**

Set `HOMOREPEAT_RUNS_ROOT` in `.env` to the host directory containing run folders. Compose mounts it read-only at `/workspace/homorepeat_pipeline/runs`. Then use **http://localhost:8000/imports/** to queue runs for the worker to process.

**Import queue UI for zipped runs:**

Use **http://localhost:8000/imports/** to upload a zipped pipeline run when the
run is not already mounted under `HOMOREPEAT_RUNS_ROOT`. The upload flow is a
staff-only local-app protocol for zipped PAASTA publish outputs; the default
maximum zip size is 5 GB.

The zip must contain exactly one publish root with:

```text
publish/metadata/run_manifest.json
```

The browser sends the file in chunks to the Django app. The upload worker then
assembles the chunks, safely extracts the zip, validates the publish contract,
and copies the validated run into app-managed storage:

```text
/data/imports/library/<run-id>/publish
```

When the uploaded run reaches **Ready**, it appears in the detected-runs list on
`/imports/`. Select that run and submit the import form to create an import
batch. Import progress is shown on the same page and in `/imports/history/`.

**Upload protocol and integrity:**

1. The browser starts an upload with the filename, byte size, and expected chunk
   count. The server rejects non-zip files, files over the configured size cap,
   over-quota users, and uploads that fail the disk-space preflight.
2. The browser slices the file into `HOMOREPEAT_UPLOAD_CHUNK_BYTES` chunks
   (8 MiB by default). Each chunk is posted with its chunk index and SHA-256.
3. The server writes each chunk to a temporary file, verifies the SHA-256, then
   atomically replaces the final `.part` file. Re-sending the same chunk is
   idempotent when the checksum matches; a conflicting checksum is rejected.
4. Completing the upload verifies that every chunk from `0..total_chunks-1` is
   present and that the received byte count equals the declared file size.
5. The upload worker streams the chunks into `source.zip`, records the assembled
   SHA-256, and optionally compares it with a client-supplied `file_sha256`.
6. Extraction rejects invalid zip files, absolute paths, `..` traversal,
   symlinks, special files, too many entries, and excessive extracted size before
   the run is accepted into the library.

Upload requests use same-origin browser requests with Django CSRF protection.
The protocol is not `tus`, S3 multipart upload, or another external upload
standard; it is designed for trusted staff users operating this app.

**Resume behavior:**

If your browser tab closes mid-upload, refreshing the page resumes from where
the server left off. The status API (`GET /imports/uploads/<id>/status/`) returns
the list of accepted chunks with their hashes; the browser skips chunks already
confirmed by the server and uploads only what is missing. Resume state is tied
to the same browser session and selected file name, size, and modified time.

**Upload cleanup runs from Celery Beat.** Stale incomplete uploads are marked
failed and their working files are removed. Failed upload working files are
removed after the configured retention window. Ready/imported library data is
never removed automatically.

**Recovering a failed upload:**

If extraction fails (e.g. from a transient disk error but the source zip is
intact), use the **Retry** button on the `/imports/` page to re-queue extraction
without re-uploading. If the failure is unrecoverable (e.g. a SHA-256 mismatch),
the Retry button is not shown; use **Clear files** to reclaim disk space and
then re-upload.

**Disk planning for zipped uploads:**

- Keep enough free space for the source zip, chunk files, extracted data, and
  the final library copy during extraction.
- A conservative rule is
  **2 × zip size + 2 × estimated extracted size + 1 GiB headroom**.
- With the default extraction estimate (`zip size × 3`), this is about
  **zip size × 8 + 1 GiB** per upload in flight. Highly compressible data can
  require more; increase `HOMOREPEAT_UPLOAD_EXTRACTION_SPACE_MULTIPLIER` for
  those deployments.
- The disk preflight check is enabled by default. It rejects new uploads and
  extractions that would leave less than `HOMOREPEAT_UPLOAD_MIN_FREE_BYTES` free.
- For very large uncompressed outputs, prefer the mounted-run path through
  `HOMOREPEAT_RUNS_ROOT`.

**Upload queues:**

Zip extraction and import batches run on separate Celery queues so heavy
extractions cannot delay import jobs. The `celery-upload-worker` service handles
the `uploads` queue (chunk assembly, zip extraction, cleanup). The
`celery-import-worker` service handles the `imports` queue (database writes,
canonical catalog sync).

**Upload scope:**

Uploaded zips are validated for path and size safety, but they are not malware
scanned. For internet-facing or untrusted-user deployments, put the app behind a
trusted reverse proxy, enforce quotas, use HTTPS, and add malware scanning or an
external object-store upload path before accepting arbitrary files.

**Process the oldest queued import manually:**

```bash
docker compose exec web python manage.py import_run --next-pending
```

## Routes

| URL | Description |
|-----|-------------|
| `/` | Site home |
| `/healthz/` | JSON healthcheck |
| `/browser/` | Browser directory |
| `/browser/homorepeats/` | Primary homorepeat observation table |
| `/browser/codon-usage/` | Repeat codon-usage profile table |
| `/browser/lengths/` | Repeat-length distributions |
| `/browser/codon-ratios/` | Residue-scoped codon composition |
| `/browser/codon-composition-length/` | Codon composition across length bins |
| `/browser/runs/` | Imported runs and provenance |
| `/browser/accessions/`, `/browser/genomes/`, `/browser/sequences/`, `/browser/proteins/`, `/browser/calls/` | Supporting canonical catalog browsers |
| `/browser/warnings/`, `/browser/accession-status/`, `/browser/accession-call-counts/`, `/browser/download-manifest/` | Operational provenance browsers |
| `/imports/` | Staff-facing import queue |
| `/imports/history/` | Import batch history and progress |

Filtered table downloads use `?download=tsv`. The homorepeat table also supports `?download=aa_fasta` and `?download=dna_fasta`.

## Running Tests

Run all browser tests:

```bash
python3 manage.py test web_tests
```

Run focused test modules:

```bash
python3 manage.py test web_tests.test_browser_stats
python3 manage.py test web_tests.test_browser_lengths
python3 manage.py test web_tests.test_browser_codon_ratios
python3 manage.py test web_tests.test_browser_codon_composition_lengths
```

Check JavaScript syntax:

```bash
node --check static/js/stats-chart-shell.js
node --check static/js/pairwise-overview.js
node --check static/js/taxonomy-gutter.js
node --check static/js/repeat-length-explorer.js
node --check static/js/repeat-codon-ratio-explorer.js
node --check static/js/codon-composition-length-explorer.js
```
