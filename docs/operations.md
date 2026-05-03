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

**Import a published run:**

```bash
python3 manage.py import_run --publish-root /absolute/path/to/<run>/publish
```

The manifest at `metadata/run_manifest.json` must include `publish_contract_version: 2`. Required v2 files are `calls/repeat_calls.tsv`, `calls/run_params.tsv`, the TSVs under `tables/`, summaries under `summaries/`, and the manifest under `metadata/`.

**Process the oldest queued import:**

```bash
python3 manage.py import_run --next-pending
```

**Rebuild canonical catalog metadata:**

```bash
python3 manage.py backfill_canonical_catalog
python3 manage.py backfill_browser_metadata
```

**Rebuild codon rollups:**

```bash
python3 manage.py backfill_codon_composition_summaries
python3 manage.py backfill_codon_composition_length_summaries
```

## Import and Rollup Maintenance

The canonical catalog sync rebuilds codon composition summaries, codon composition by length summaries, and canonical protein repeat-call counts.

If codon share values in an unfiltered view do not match a filtered/branch view, rebuild the relevant rollup table and compare against live aggregation. Unfiltered views are the most likely to use rollups.

For codon-by-length summaries, shares for a complete residue codon set should sum to 1 within each taxon/bin (within rounding). If they do not, check for:

- stale rollup rows
- denominator bugs that count codon-usage rows instead of distinct repeat calls
- incomplete or invalid imported codon fractions

## Cache Behaviour

Stats bundles and taxonomy gutter payloads are cached using a hash of the validated filter state. TTL is controlled by `HOMOREPEAT_BROWSER_STATS_CACHE_TTL` (default: 60 seconds).

Taxonomy gutter payloads also carry a local version constant in `apps/browser/stats/taxonomy_gutter.py`. Bump it when changing payload shape or alignment semantics.

## Upload and Import Operator Checklist

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

For a failed upload shown in `/imports/`:

1. Check the error detail shown under the Failed badge — it will say whether the failure was a checksum mismatch, a disk preflight rejection, a zip validation error, or a publish-contract error.
2. If the failure is **transient** (disk temporarily full, worker crashed mid-extraction, zip valid and checksum not failed): click **Retry** to re-queue extraction without re-uploading.
3. If the failure is **permanent** (SHA-256 checksum mismatch, corrupt zip, invalid publish contract): click **Clear files** to reclaim disk space, then re-upload a corrected zip.
4. If neither button appears, working files are already gone — the database row is kept for audit purposes.

### Clearing Old Failed Working Files

The cleanup task runs hourly via Celery Beat and removes working directories for uploads that have been in a failed state longer than `HOMOREPEAT_UPLOAD_FAILED_RETENTION_HOURS` (default: 7 days).

To clear failed working files immediately:

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

Library data (`library/<run-id>/`) is never touched by cleanup — only the `uploads/<upload-id>/` working directory is removed.

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

Deleting a pipeline run is irreversible once row deletion begins. Follow this checklist in order.

### Overview

The deletion workflow is asynchronous and designed to be safe for a live production database. It never holds long locks that would stall other queries, and it never touches taxonomy or reference data shared with other runs. The run is hidden from browsing immediately when the job is queued; all other runs continue to serve normally throughout.

**Deletion is slow by design.** A large run (tens of millions of rows) can take several minutes to over an hour depending on hardware. The reasons:

- **Canonical repair** rebuilds the browser's derived catalog by re-pointing rows to the best available predecessor run for each accession. This involves complex SQL across many tables and a full codon rollup rebuild.
- **Row deletion uses small chunks** (a few thousand rows at a time) rather than a single bulk `DELETE`. This avoids long-held table locks, keeps autovacuum from falling behind, and lets other queries proceed between chunks.
- **Each chunk updates indexes.** PostgreSQL must update every B-tree index on the table for every deleted row. A heavily-indexed table like `browser_repeatcall` takes proportionally longer per row than a simple table.
- **`ANALYZE` runs at the end** on all affected tables so the query planner has accurate statistics immediately after deletion, rather than waiting for autovacuum to catch up.

Phases in order:

1. **canonical_repair** — browser catalog rows pointing at this run are promoted to the most recent active predecessor run (if one exists for the same accession) or deleted if none exists. DB-level `ON DELETE CASCADE` propagates removals through the canonical hierarchy automatically. Codon composition rollups are fully rebuilt.
2. **artifact_cleanup** — files under `HOMOREPEAT_IMPORTS_ROOT/library/<run-id>/` are removed. Paths outside approved roots are skipped safely.
3. **row_deletion** — run-owned rows are deleted in dependency order using chunked queries. Each chunk acquires only a short row-level lock, leaving the table available to concurrent reads throughout.
4. **analyze** — `ANALYZE` is run on all affected tables to refresh query planner statistics.
5. **finished** — the `PipelineRun` row is marked `lifecycle_status = deleted` (tombstone). Import batch and upload audit rows are retained for audit. Taxonomy and reference data are never touched.

### Step 1 — Dry-run: review the impact

```bash
python manage.py queue_delete_run --run-id <run-id>
```

Prints the full impact plan: row counts per table, canonical rows affected, artifact roots, and any warnings (e.g. unexpectedly large tables). Nothing is modified.

If an active deletion job already exists (status `pending` or `running`), the plan shows its job ID. Do not queue a second job — monitor the existing one with `deletion_status`.

### Step 2 — Queue the deletion job

```bash
python manage.py queue_delete_run --run-id <run-id> --confirm
```

Pass `--reason "..."` to record why the run is being deleted (stored on the job and shown in the UI).

What happens synchronously before the command returns:

- The run is locked and validated (`active` or `deleting` only; `deleted` and `delete_failed` are rejected).
- A `DeletionJob` is created with `status = pending`.
- `lifecycle_status` is set to `deleting` — the run is immediately hidden from normal browsing and its cache entries are invalidated.
- The Celery task is dispatched on commit.

The command prints the job ID — note it for monitoring.

```
Deletion job queued (id=42, status=pending).
  Check progress : python manage.py deletion_status --job-id 42
```

### Step 3 — Monitor progress

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

If `deletion_status` shows `status: failed`, the error and a retry hint are printed:

```
--- Error ---
  IntegrityError: ...

  To retry: python manage.py retry_deletion_job --job-id 42 --confirm
```

Check the error before retrying. Transient failures (worker OOM, network blip, PostgreSQL restart) are safe to retry. Schema or data integrity errors are not — fix the underlying cause first or they will reproduce.

**Dry-run (prints state, no changes):**

```bash
python manage.py retry_deletion_job --job-id <job-id>
```

**Re-enqueue:**

```bash
python manage.py retry_deletion_job --job-id <job-id> --confirm
```

This resets the job to `pending`, increments `retry_count`, clears error fields, resets the run lifecycle to `deleting`, and dispatches a new Celery task. Retry always restarts from phase 1. Every phase is idempotent: canonical repair re-checks current state, artifact deletion skips missing paths, and chunk deletion is a no-op for rows already gone.

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
