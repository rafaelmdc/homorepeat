# Operations

## Management Commands

All commands can be run directly or inside the Compose stack:

```bash
# Direct
python3 manage.py <command>

# Inside Compose
docker compose exec web python manage.py <command>
```

**Migrate:**

```bash
python3 manage.py migrate
```

**Import a published run (server-side path):**

> **Normal path:** Upload a zipped run via the web UI at `/imports/`. The UI handles chunked upload, extraction, and import automatically. The command below is only needed when the publish root is already on the server (e.g. pipeline output written directly to the host).

```bash
python3 manage.py import_run --publish-root /absolute/path/to/<run>/publish
```

The manifest at `metadata/run_manifest.json` must include `publish_contract_version: 2`. Required v2 files are `calls/repeat_calls.tsv`, `calls/run_params.tsv`, the TSVs under `tables/`, summaries under `summaries/`, and the manifest under `metadata/`.

**Rebuild canonical catalog metadata:**

> These run automatically after every successful import and after every deletion job. Only needed manually after a schema change, a failed rollup, or a data correction.

```bash
python3 manage.py backfill_canonical_catalog
python3 manage.py backfill_browser_metadata
```

**Rebuild codon rollups:**

> Also run automatically after every import and deletion. Only needed manually to recover from a failed rebuild or after a rollup logic change.

```bash
python3 manage.py backfill_codon_composition_summaries
python3 manage.py backfill_codon_composition_length_summaries
```

## Import and Rollup Maintenance

The canonical catalog sync and all codon rollups run automatically after every successful import and after every deletion job — no manual intervention is needed in normal operation. This section covers how to diagnose and fix a rollup if it ends up in a bad state.

If codon share values in an unfiltered view do not match a filtered/branch view, rebuild the relevant rollup table and compare against live aggregation. Unfiltered views are the most likely to use rollups.

For codon-by-length summaries, shares for a complete residue codon set should sum to 1 within each taxon/bin (within rounding). If they do not, check for:

- stale rollup rows
- denominator bugs that count codon-usage rows instead of distinct repeat calls
- incomplete or invalid imported codon fractions

## Cache Behaviour

Stats bundles and taxonomy gutter payloads are cached using a hash of the validated filter state. TTL is controlled by `HOMOREPEAT_BROWSER_STATS_CACHE_TTL` (default: 60 seconds).

Taxonomy gutter payloads also carry a local version constant in `apps/browser/stats/taxonomy_gutter.py`. Bump it when changing payload shape or alignment semantics.

## Upload and Import Operator Checklist

### What the backend does

**When you upload a zip at `/imports/`:**

1. The browser splits the file into chunks and uploads each one. The server writes each chunk to disk and verifies its SHA-256 checksum before accepting it.
2. When the last chunk arrives, the server assembles the full zip and dispatches an extraction task to the `uploads` Celery queue.
3. The extraction worker validates the zip (rejects path traversal, symlinks, excessive size, invalid structure), extracts it to a scratch directory, and moves the validated publish root to `library/<run-id>/publish/` on the imports volume.
4. The run appears as **Ready** with an **Import** button. Nothing has been written to the database yet.

**When you click Import:**

1. The server creates an `ImportBatch` record and dispatches an import task to the `imports` Celery queue.
2. The import worker streams each TSV from the publish root into PostgreSQL staging tables using `COPY`, then joins them into the permanent browser tables in a single transaction.
3. After row insertion, the worker syncs the canonical catalog (promoting or creating canonical genome/sequence/protein/repeat-call entries), rebuilds codon composition summaries, and updates browser metadata.
4. The batch is marked **Completed** and the run is visible in the browser immediately.

**When you retry a failed upload:**

The server re-dispatches the extraction task using the already-uploaded chunks — no re-upload needed. Only valid if the zip bytes are intact (checksum not failed).

**When you click Clear files:**

The server removes the working directory (`uploads/<upload-id>/`) from the imports volume. Library data (`library/<run-id>/`) is never removed by this action.

---

### Sizing `/data/imports`

The `homorepeat_imports` Docker volume holds three categories of data:

- **Working files** — chunk `.part` files, assembled `source.zip`, extracted scratch dir. These are cleaned up automatically after the retention window.
- **Library** — `library/<run-id>/publish/` — the validated, extracted run used by the importer. Retained until removed manually.

A safe capacity formula per upload in flight is:

```text
2 × zip_size + 2 × estimated_extracted_size + 1 GiB
```

The first `2 × zip_size` covers chunk files plus the assembled `source.zip`.
The extracted data can temporarily exist twice: once in the extraction scratch
directory and once in the final `library/<run-id>/publish/` copy. With the
default extraction estimate of `zip_size × 3`, plan for about
`zip_size × 8 + 1 GiB` per upload in flight.

Example: 10 concurrent 5 GB uploads → at least **410 GB** free.

For large deployments, increase the extraction space multiplier and confirm the disk preflight settings reflect the actual available capacity.

### Upload Protocol Safety

The browser upload path is intended for authenticated staff users. It is safer
than a raw file drop, but it is not a general-purpose public upload service.

- Requests are same-origin and CSRF-protected.
- Upload start validates filename extension, declared size, chunk count, global
  size cap, optional per-user quotas, and disk preflight.
- Chunks are verified with SHA-256 before acceptance and are committed with an
  atomic replace from a temporary file.
- Re-uploading an already accepted chunk is idempotent when the checksum
  matches; conflicting content is rejected.
- Completion requires every expected chunk and the exact declared byte total.
- Extraction rejects invalid zips, absolute paths, path traversal, symlinks,
  special files, excessive entry counts, and excessive extracted size.
- Ready/imported library data is never removed by stale-upload cleanup.

For untrusted or internet-facing deployments, use HTTPS, strict reverse-proxy
header handling, non-zero per-user quotas, monitoring, and malware scanning.
Consider an external object-store multipart protocol if uploads need to be
public, very large, or independently resumable across browsers.

### Choosing Upload Worker Concurrency

The `celery-upload-worker` service runs on the `uploads` queue with `-c 2` by default. Each upload task is I/O-bound but can hold significant memory during zip extraction. Recommendations:

- **2 workers** is safe for a host with 4+ GB RAM and typical 5 GB uploads.
- Increase to 4 if you have 16+ GB RAM and expect concurrent uploads from multiple users.
- Monitor peak RSS during extraction: `docker stats celery-upload-worker`.

The `celery-import-worker` handles only database writes (the `imports` queue) and does not hold upload files in memory. Its concurrency can be tuned independently.

### Recovering Failed Uploads

The UI at `/imports/` handles recovery directly — no commands needed. Open the failed upload and use the buttons shown under the Failed badge:

- **Retry** — re-queues extraction without re-uploading. Use for transient failures: disk temporarily full, worker crashed mid-extraction, checksum not failed.
- **Clear files** — removes working files to reclaim disk space. Use for permanent failures: SHA-256 checksum mismatch, corrupt zip, invalid publish contract. Re-upload a corrected zip afterwards.

If neither button appears, working files are already gone — the database row is kept for audit purposes.

### Clearing Old Failed Working Files

Cleanup is automatic. Celery Beat runs the cleanup task hourly and removes working directories for uploads that have been failed longer than `HOMOREPEAT_UPLOAD_FAILED_RETENTION_HOURS` (default: 7 days). Library data (`library/<run-id>/`) is never touched — only the `uploads/<upload-id>/` working directory is removed.

To clear failed working files immediately (e.g. disk is critically full):

```bash
docker compose exec web python manage.py shell -c "
from apps.imports.models import UploadedRun
for run in UploadedRun.objects.filter(status='failed'):
    if run.can_clear_working_files:
        import shutil
        shutil.rmtree(run.upload_root, ignore_errors=True)
        print(f'Cleared {run.upload_id}')
"
```

### End-to-End Upload/Import Smoke Test

After deploying, verify the full upload path with a small valid zipped run:

1. Create a minimal zipped run:
   ```bash
   cd /tmp && mkdir -p smoke/publish/metadata
   echo '{"run_id": "smoke-test", "publish_contract_version": 2}' \
     > smoke/publish/metadata/run_manifest.json
   zip -r smoke-test.zip smoke/
   ```
2. Open `http://localhost:8000/imports/` and upload `smoke-test.zip`.
3. Confirm the upload progresses through: **Receiving → Received → Extracting → Ready**.
4. Click **Import** and confirm: **Queued → (import batch completes)**.
5. Check `/imports/history/` for a completed batch with `success_count > 0`.

### Validating Worker Queue Routing

Confirm that tasks land on the correct workers:

```bash
docker compose exec web python manage.py shell -c "
from config.settings import CELERY_TASK_ROUTES
print(CELERY_TASK_ROUTES)
"
```

Expected routes:
- `apps.imports.tasks.extract_uploaded_run` → `uploads`
- `apps.imports.tasks.cleanup_stale_uploaded_runs` → `uploads`
- `apps.imports.tasks.*` (wildcard) → `imports`
- `imports.delete_pipeline_run_job` → `deletions`

---

## Run Deletion Operator Checklist

> **Normal path:** Staff users can delete a run directly from the run detail page in the browser. Click **Delete run…**, review the impact plan, enter an optional reason, and confirm. The UI handles everything — queueing, progress display, and retry — automatically. The management commands below are for scripted workflows, bulk operations, or diagnosing a stuck job from the server.

Deleting a pipeline run is irreversible once row deletion begins.

### What the backend does

**When you click Delete run…:**

The server reads the current database state and returns a preview: how many rows will be deleted per table, which canonical entries are affected, which artifact roots will be removed, and any warnings. Nothing is modified.

**When you confirm:**

1. The run is locked and validated. Its `lifecycle_status` is set to `deleting` and the browser cache version is bumped — the run disappears from browsing immediately and cache entries are invalidated across all users.
2. A `DeletionJob` record is created and the Celery task is dispatched to the `deletions` queue on commit.
3. All other runs continue to serve normally from this point on.

**The Celery worker then runs five phases in order:**

1. **canonical_repair** — For every canonical genome/sequence/protein/repeat-call that was pointing at this run, the worker finds the most recent other active run that contains the same accession. If one exists, the canonical row is re-pointed to it (promoted). If none exists, the canonical row is deleted — and because all FK constraints in the canonical hierarchy use `ON DELETE CASCADE`, removing a canonical genome automatically removes its sequences, proteins, repeat calls, and codon usages in one DB operation. Finally, codon composition rollups are fully rebuilt.
2. **artifact_cleanup** — The worker removes `library/<run-id>/` from the imports volume. Any path that falls outside the approved imports root is skipped safely rather than erroring.
3. **row_deletion** — Run-owned rows (repeat calls, genomes, sequences, proteins, acquisition batches, etc.) are deleted in dependency order in small chunks. Each chunk holds only a short row-level lock so concurrent reads on other runs are never blocked. The heartbeat is updated after each table.
4. **analyze** — `ANALYZE` is run on every affected table so the query planner has fresh statistics immediately, without waiting for autovacuum.
5. **finished** — The `PipelineRun` row is tombstoned (`lifecycle_status = deleted`). Import batch and upload audit rows are retained with their FK set to NULL. Taxonomy and reference data are never touched.

**Deletion is slow by design.** A large run (tens of millions of rows) can take several minutes to over an hour. Each chunk deletion must update every B-tree index on the table for every deleted row — a heavily-indexed table like `browser_repeatcall` takes proportionally longer per row. The chunked approach is intentional: it keeps lock times short and lets autovacuum keep pace.

**When you click Retry on a failed job:**

The job is reset to `pending`, the run lifecycle is reset to `deleting`, and the Celery task is re-dispatched. The worker restarts from phase 1. Every phase is idempotent — canonical repair re-checks current state, artifact deletion skips missing paths, and chunk deletion is a no-op for rows already gone.

### Step 1 — Dry-run: review the impact

> **UI:** Clicking **Delete run…** on the run detail page automatically shows the full impact plan before you confirm. You only need the command below for scripted or automated workflows.

```bash
python manage.py queue_delete_run --run-id <run-id>
```

Prints the full impact plan: row counts per table, canonical rows affected, artifact roots, and any warnings (e.g. unexpectedly large tables). Nothing is modified.

If an active deletion job already exists (status `pending` or `running`), the plan shows its job ID. Do not queue a second job — monitor the existing one with `deletion_status`.

### Step 2 — Queue the deletion job

> **UI:** Confirming on the impact plan page queues the job automatically. The command below is for scripted workflows or server-side imports.

```bash
python manage.py queue_delete_run --run-id <run-id> --confirm
```

Pass `--reason "..."` to record why the run is being deleted (stored on the job and shown in the UI). The command prints the job ID — note it for monitoring.

```
Deletion job queued (id=42, status=pending).
  Check progress : python manage.py deletion_status --job-id 42
```

### Step 3 — Monitor progress

> **UI:** The run detail page shows a live status panel with the current phase, row counters, and heartbeat. Refresh the page to update. Use the command below only when diagnosing a stuck job from the server.

```bash
python manage.py deletion_status --job-id <job-id>
```

Prints phase, timestamps, row counters, artifact count, heartbeat age, and any error. Expected lifecycle:

```
pending → running → canonical_repair → artifact_cleanup → row_deletion → analyze → finished → done
```

Heartbeat is updated at each phase boundary and after each table during `row_deletion`. A heartbeat older than a few minutes while status is `running` means the worker may have crashed — restart the `celery-deletion-worker` container and re-check.

If the task message was lost before the worker picked it up (worker was down when the job was queued), re-enqueue manually:

```bash
python manage.py retry_deletion_job --job-id <job-id> --confirm
```

### Step 4 — Handling failure

> **UI:** If the job fails, the run detail page shows an error summary and a **Retry** button. Click it to re-enqueue without any commands. Use the commands below only to inspect the raw error or retry from the server.

Check the error before retrying. Transient failures (worker OOM, network blip, PostgreSQL restart) are safe to retry. Schema or data integrity errors are not — fix the underlying cause first or they will reproduce.

**Dry-run (prints current state and error, no changes):**

```bash
python manage.py retry_deletion_job --job-id <job-id>
```

**Re-enqueue:**

```bash
python manage.py retry_deletion_job --job-id <job-id> --confirm
```

### Irreversibility

> **Warning:** Once `row_deletion` begins, deleted rows cannot be recovered from within the application. Restore from a database backup if you need to roll back.

- **Partial deletion is a valid intermediate state.** A crash mid-`row_deletion` leaves some tables cleared and others untouched. Retrying is safe (idempotent), but recovering to the pre-deletion state requires a database backup.
- **Canonical repair is permanent for promoted rows.** Rows re-pointed to a predecessor run stay there. If the predecessor is later deleted, those rows are processed again at that time.
- **Artifact deletion is permanent.** Once `library/<run-id>/` is removed, the source files are gone. Restore from filesystem backup if needed.
- **The tombstone is kept.** The `PipelineRun` row is retained with `lifecycle_status = deleted`. Import batch and upload audit rows are retained for audit.

### PostgreSQL Maintenance After Large Deletions

`ANALYZE` runs automatically at the end of every deletion job. `VACUUM` does not — autovacuum handles it, but may lag significantly after a bulk delete of tens of millions of rows.

To reclaim dead tuple space immediately:

```sql
VACUUM browser_repeatcall, browser_repeatcallcodonusage,
       browser_repeatcallcontext, browser_genome,
       browser_sequence, browser_protein;
```

After vacuuming, check for index bloat on the high-traffic tables (`browser_repeatcall`, `browser_canonicalrepeatcall`). If `pg_stat_user_tables` shows a large `n_dead_tup` or index scans are slower than expected, run:

```sql
REINDEX TABLE CONCURRENTLY browser_repeatcall;
```

`CONCURRENTLY` rebuilds the index without blocking reads or writes.

### Validation

After modifying the deletion workflow, run:

```bash
python manage.py test web_tests.test_deletion
```

---

## Validation Checklist

Before merging statistical or chart changes:

```bash
python3 manage.py test web_tests.test_browser_stats
python3 manage.py test web_tests.test_browser_lengths
python3 manage.py test web_tests.test_browser_codon_ratios
python3 manage.py test web_tests.test_browser_codon_composition_lengths
```

Before merging upload or import changes:

```bash
python3 manage.py test web_tests.test_import_uploads
python3 manage.py test web_tests.test_import_tasks
```

Before merging deletion workflow changes:

```bash
python3 manage.py test web_tests.test_deletion
```

For frontend chart changes:

```bash
node --check static/js/stats-chart-shell.js
node --check static/js/taxonomy-gutter.js
node --check static/js/pairwise-overview.js
node --check static/js/repeat-length-explorer.js
node --check static/js/repeat-codon-ratio-explorer.js
node --check static/js/codon-composition-length-explorer.js
```

Manual browser checks should cover:

- unfiltered and branch-scoped routes
- two-codon and multi-codon residues
- y-axis wheel pan and Shift+wheel zoom
- horizontal x-axis sliders where present
- taxonomy gutter alignment after zoom
- no-JS fallback tables where relevant

## Database Notes

PostgreSQL is the production-like path. Large v2 imports stream run-level TSVs into temporary tables with `COPY` and join in SQL. SQLite is a lightweight fallback for compact fixtures and parser checks; it does not exercise the PostgreSQL staging path or SQL rollup rebuilds.

When changing raw SQL rollups, validate both the PostgreSQL rebuild command in the Compose stack and the Django tests using the Python/live fallback.

For a real v2 import validation:

```bash
docker compose exec web python manage.py import_run \
  --publish-root /workspace/homorepeat_pipeline/runs/<run-id>/publish
```

Then compare source table row counts against imported raw counts for repeat calls, matched sequences, matched proteins, repeat-call codon usage, repeat context, and operational tables. Confirm canonical sequence/protein bodies are populated after sync and codon rollups rebuild successfully.
