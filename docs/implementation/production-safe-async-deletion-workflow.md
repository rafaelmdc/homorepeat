# Production-Safe Async Deletion Workflow

Date: 2026-05-02

## Overview

HomoRepeat needs a safe way for an administrator to remove an imported run or dataset without making the website slow, holding large database locks, serving stale browser/stat/download data, or accidentally deleting shared biological reference data.

The first implementation should be backend-only. An operator should use Django management commands to dry-run, queue, inspect, and retry deletion jobs. The website delete button should come later, after the backend workflow has been proven on local and staging data.

The target deletion unit, based on the current repo structure, should be `browser.PipelineRun`. HomoRepeat does not currently have a separate `Dataset` model. Imported raw data is run-scoped through `PipelineRun`, while canonical browser data and shared taxonomy/reference data need more careful handling.

The intended production flow is:

```text
management command
    -> validate PipelineRun
    -> create/reuse DeletionJob
    -> mark run hidden/deleting
    -> bump catalog cache version
    -> commit transaction
    -> enqueue Celery task with transaction.on_commit()
    -> worker deletes artifacts and rows in durable phases
    -> worker repairs canonical catalog
    -> worker deletes raw rows in chunks
    -> worker runs lightweight ANALYZE
    -> worker marks job done or failed
```

The synchronous part must stay fast:

```text
validate -> hide -> enqueue -> return
```

The asynchronous part performs expensive work:

```text
canonical repair -> cache invalidation -> artifact cleanup -> chunked deletes -> analyze -> finish
```

The normal workflow must not run destructive table-wide maintenance such as `VACUUM FULL`, non-concurrent `REINDEX`, `TRUNCATE`, `DROP CASCADE`, or broad unbounded raw deletes. PostgreSQL autovacuum should handle dead tuple cleanup over time; the default post-delete maintenance should be targeted `ANALYZE` on affected tables.

## Current Architecture Summary

Relevant apps and models:

| Area | Current code |
| --- | --- |
| Imports | `apps.imports`, `ImportBatch`, `UploadedRun`, `UploadedRunChunk`, `CatalogVersion` |
| Imported run identity | `apps.browser.models.runs.PipelineRun` |
| Raw run-owned observations | `AcquisitionBatch`, `Genome`, `Sequence`, `Protein`, `RepeatCall`, `RepeatCallCodonUsage`, `RepeatCallContext`, `RunParameter` |
| Operational run rows | `DownloadManifestEntry`, `NormalizationWarning`, `AccessionStatus`, `AccessionCallCount` |
| Shared taxonomy/reference data | `Taxon`, `TaxonClosure` |
| Canonical browser catalog | `CanonicalGenome`, `CanonicalSequence`, `CanonicalProtein`, `CanonicalRepeatCall`, `CanonicalRepeatCallCodonUsage`, canonical codon summary tables |
| Async payload/download records | `PayloadBuild`, `DownloadBuild` |
| Celery queues | `uploads`, `imports`, `payload_graph`, `downloads` |
| Cache versioning | Existing `imports.CatalogVersion`; stats cache keys already include catalog version through `StatsFilterState.cache_key_data()` |
| Artifact roots | `HOMOREPEAT_IMPORTS_ROOT`, especially `uploads/<uuid>/` and `library/<run-id>/publish/`; `HOMOREPEAT_RUNS_ROOT` is source data and mounted read-only in Compose |

Important repo facts:

- `PipelineRun` is the safest canonical deletion target for MVP.
- Existing import replacement deletes some run-scoped rows synchronously via broad ORM cascades in `apps/imports/services/import_run/entities.py`; the deletion workflow should not reuse that as the production path for large data.
- `Taxon` and `TaxonClosure` are shared/global and must not be deleted as part of run deletion.
- Canonical rows point at `latest_pipeline_run` and `latest_import_batch` with protective relationships, so raw deletion must be preceded by canonical repair or removal.
- Stats payloads and taxonomy gutter payloads are cache-versioned already; deletion needs to bump the catalog version when the run is hidden and likely once more after canonical repair.

## Canonical Target And Ownership

The MVP delete target is:

```text
browser.PipelineRun
```

Supported identifiers:

```text
--run-id <PipelineRun.run_id>
--pipeline-run-id <PipelineRun.pk>
```

Run-owned data:

- `AcquisitionBatch`
- `RunParameter`
- `Genome`
- `Sequence`
- `Protein`
- `RepeatCall`
- `RepeatCallCodonUsage`
- `RepeatCallContext`
- `DownloadManifestEntry`
- `NormalizationWarning`
- `AccessionStatus`
- `AccessionCallCount`

Audit data to keep:

- `PipelineRun` tombstone row
- `ImportBatch`
- `UploadedRun`
- `UploadedRunChunk`

Shared/global data to keep:

- `Taxon`
- `TaxonClosure`
- Canonical rows that can be promoted to another active run
- External source files under `HOMOREPEAT_RUNS_ROOT`

Browser behavior:

- Normal browsing should exclude runs whose lifecycle is `deleting`, `deleted`, or `delete_failed`.
- Direct run URLs for hidden/deleted runs should show a clear status message instead of normal browse links.
- Canonical browser rows should not continue to point at a deleting/deleted run after canonical repair.

## Phase Plan

### Phase 1: Backend-Only Foundation

Goal: add the data model and service boundaries without exposing website delete actions.

Slices:

1. Add run lifecycle fields to `PipelineRun`.
   - Add `lifecycle_status`: `active`, `deleting`, `deleted`, `delete_failed`.
   - Add `deleting_at`, `deleted_at`, `delete_failed_at`, and `deletion_reason`.
   - Add an index for active-run browsing, such as `(lifecycle_status, imported_at, id)`.

2. Add `DeletionJob`.
   - Prefer `apps.imports.models.DeletionJob`, because deletion belongs with import/run operations and audit.
   - Fields: target type, `pipeline_run`, status, phase, requester, reason, timestamps, heartbeat, row counters, artifact counters, error fields, retry count, idempotency key.
   - Status values: `pending`, `running`, `done`, `failed`.
   - Do not add cancellation in MVP.

3. Add duplicate prevention.
   - Add a partial unique constraint so only one `pending` or `running` deletion job can exist per `PipelineRun`.
   - Also use `select_for_update()` on the target/job rows when queueing deletion.
   - Repeated delete requests should return the existing active job.

4. Add active-run query helpers.
   - Centralize “active for browsing” filtering so views, stats, run choices, and metadata do not each reinvent it.
   - Update browser query paths to exclude non-active runs before any UI delete button exists.

Acceptance checks:

- Migrations apply cleanly.
- Existing import/browser tests still pass after active-run default behavior is added.
- A non-active run no longer appears in normal run choices or browser lists.

### Phase 2: Dry-Run Planner

Goal: allow operators to inspect the full deletion impact without mutating data.

Slices:

1. Create `apps/imports/services/deletion/`.
   - `planning.py`: row counts, canonical impact counts, artifact candidates.
   - `safety.py`: target validation and ownership checks.
   - `cache.py`: catalog version helpers.
   - `artifacts.py`: path-safe artifact discovery.
   - `postgres.py`: index/timeout/analyze helpers.

2. Implement dry-run count planning.
   - Count run-owned raw rows per table.
   - Count canonical rows whose `latest_pipeline_run` is the target.
   - Count `ImportBatch` and `UploadedRun` audit links, but mark them as retained.
   - Report shared tables explicitly as “not deleted”.

3. Implement artifact planning.
   - Only consider paths under `HOMOREPEAT_IMPORTS_ROOT/library/<run-id>/`.
   - Treat `HOMOREPEAT_RUNS_ROOT` as external source data and never plan deletion there.
   - Resolve paths and reject anything outside approved roots.

4. Add command:

```text
python manage.py queue_delete_run --run-id <run_id> --dry-run
```

Dry-run output should include:

- target identity and lifecycle status
- duplicate active job status
- row counts by table
- canonical repair impact
- artifact roots planned
- cache/catalog version impact
- large deletion warnings
- missing-index or query-plan warnings where feasible

Acceptance checks:

- Dry-run does not hide or delete anything.
- Dry-run reports expected tables.
- Artifact planner refuses path traversal and outside-root paths.

### Phase 3: Queueing And Job Orchestration

Goal: queue a deletion safely while doing only fast synchronous work.

Slices:

1. Implement `jobs.py`.
   - Validate target.
   - Lock target with `select_for_update()`.
   - Create or reuse active `DeletionJob`.
   - Mark `PipelineRun` as `deleting`.
   - Record reason/requester.
   - Bump `CatalogVersion`.
   - Enqueue Celery task via `transaction.on_commit()`.

2. Extend `queue_delete_run`.
   - Require `--confirm` for actual queueing.
   - Keep `--dry-run` as default behavior.
   - Print job id and suggested status command.

3. Add status command:

```text
python manage.py deletion_status --job-id <id>
```

4. Add retry command:

```text
python manage.py retry_deletion_job --job-id <id> --confirm
```

Retry rules:

- Only failed jobs can be retried.
- Retry reuses the same job.
- Retry increments retry count and re-enqueues through the same Celery path.

Acceptance checks:

- Actual deletion cannot queue without `--confirm`.
- Duplicate request reuses existing job.
- Target is hidden immediately after queueing.
- Cache catalog version bumps when target is hidden.
- Management commands print useful operator output.

### Phase 4: Celery Execution Skeleton

Goal: run deletion as a durable, observable background job.

Slices:

1. Add task:

```text
apps.imports.tasks.delete_pipeline_run_job(job_id)
```

2. Add dedicated queue:

```text
deletions
```

3. Configure routing:

```text
"apps.imports.tasks.delete_pipeline_run_job": {"queue": "deletions"}
```

4. Add a low-concurrency worker in Compose later:

```text
celery -A config.celery worker -Q deletions -c 1 --prefetch-multiplier 1 --loglevel=info
```

5. Implement claim/heartbeat/failure behavior.
   - Atomically claim `pending` job.
   - Exit if already `done`.
   - Update phase and heartbeat regularly.
   - Store safe errors in `error_message`.
   - Store trace/debug metadata in admin-only structured JSON.

Acceptance checks:

- Task can be queued and claimed once.
- Re-running an already done job is a no-op.
- Failed task marks job failed with useful metadata.
- Worker crash can be recovered through retry command.

### Phase 5: Canonical Catalog Repair

Goal: ensure the public canonical browser does not point at deleted raw rows or deleted runs.

Slices:

1. Identify canonical rows impacted by the target run.
   - `CanonicalGenome.latest_pipeline_run`
   - `CanonicalSequence.latest_pipeline_run`
   - `CanonicalProtein.latest_pipeline_run`
   - `CanonicalRepeatCall.latest_pipeline_run`
   - `CanonicalRepeatCall.latest_repeat_call`
   - `CanonicalRepeatCallCodonUsage` through canonical repeat calls

2. Repair strategy.
   - For canonical rows whose latest run is being deleted, promote the newest active predecessor raw row when one exists.
   - Delete canonical rows only when no active predecessor exists.
   - Delete child canonical rows before parents.

3. Rebuild summary rollups.
   - Reuse existing canonical codon rollup rebuild functions.
   - Run this outside the raw delete transaction.
   - Bump catalog version after repair finishes.

Acceptance checks:

- Canonical rows no longer point to deleting/deleted runs.
- Shared canonical data from other active runs remains visible.
- Deleted-run-only canonical rows disappear.
- Rollup tables reflect the repaired canonical catalog.

### Phase 6: Artifact Cleanup

Goal: remove only app-owned generated/import library artifacts safely.

Slices:

1. Delete approved app-managed library paths.
   - `HOMOREPEAT_IMPORTS_ROOT/library/<run-id>/`
   - Matching `UploadedRun.library_root`
   - Matching `PipelineRun.publish_root` only if it resolves inside the approved library root.

2. Do not delete:
   - `HOMOREPEAT_RUNS_ROOT`
   - `DownloadManifestEntry.download_path`
   - `DownloadManifestEntry.rehydrated_path`
   - Arbitrary user-supplied paths
   - Shared cache directories

3. Safety behavior.
   - Resolve every path.
   - Require path to be inside approved root.
   - Treat missing paths as success.
   - Handle symlinks conservatively.
   - Log root-level summaries.

Acceptance checks:

- Missing artifact paths do not fail deletion.
- Outside-root paths are refused.
- Raw source data is never removed.

### Phase 7: Chunked PostgreSQL Deletion

Goal: delete rows without giant transactions or avoidable lock amplification.

Slices:

1. Implement chunk helper for direct run-owned tables:

```sql
WITH victim AS (
  SELECT id
  FROM table
  WHERE pipeline_run_id = %s
  ORDER BY id
  LIMIT %s
)
DELETE FROM table
USING victim
WHERE table.id = victim.id;
```

2. Implement chunk helper for indirect children:

```sql
WITH victim AS (
  SELECT cu.id
  FROM browser_repeatcallcodonusage cu
  JOIN browser_repeatcall rc ON rc.id = cu.repeat_call_id
  WHERE rc.pipeline_run_id = %s
  ORDER BY cu.id
  LIMIT %s
)
DELETE FROM browser_repeatcallcodonusage cu
USING victim
WHERE cu.id = victim.id;
```

3. Use dependency order:
   - `RepeatCallCodonUsage`
   - `RepeatCallContext`
   - `RepeatCall`
   - `DownloadManifestEntry`
   - `NormalizationWarning`
   - `AccessionStatus`
   - `AccessionCallCount`
   - `Protein`
   - `Sequence`
   - `Genome`
   - `RunParameter`
   - `AcquisitionBatch`

4. Use conservative PostgreSQL settings per chunk.
   - `lock_timeout`: 1-3 seconds.
   - `statement_timeout`: 30-120 seconds.
   - initial chunk size: around 5,000 rows, tuned per table on staging.

5. Do not use one huge transaction.
   - Commit each chunk or small phase.
   - Update job counters after chunks.
   - Retry lock timeouts with backoff.

Acceptance checks:

- Deletion does not touch unrelated runs.
- Large tables delete in chunks.
- Job counters update.
- Lock timeout fails/retries instead of blocking indefinitely.
- `EXPLAIN` confirms indexed filters on staging.

### Phase 8: PostgreSQL Maintenance

Goal: update planner statistics without dangerous maintenance.

Slices:

1. Run targeted `ANALYZE` after large deletes and canonical repair.
2. Analyze affected raw and canonical tables.
3. Record analyze phase in the job.

Do not automate:

- `VACUUM FULL`
- non-concurrent `REINDEX`
- `TRUNCATE`
- `DROP CASCADE`

Acceptance checks:

- `ANALYZE` is run or safely skipped on non-PostgreSQL test backends.
- Dangerous maintenance is not part of the normal workflow.

### Phase 9: Backend Tests And Staging Validation

Goal: prove safety before any website integration.

Required tests:

- Dry-run reports expected affected tables.
- Dry-run does not hide or delete.
- Confirm flag is required.
- Command creates exactly one job.
- Duplicate active request returns existing job.
- Target is hidden immediately after queueing.
- Catalog version bumps on hide.
- Canonical repair promotes/removes correctly.
- Shared taxonomy/reference rows are not deleted.
- Missing artifacts do not fail the job.
- Artifact cleanup refuses outside-root paths.
- Retry is safe after partial artifact deletion.
- Retry is safe after partial row deletion.
- Failed job records error state.
- Status command reports progress.
- Chunk deletion preserves unrelated runs.
- `ANALYZE` helper is isolated, mocked, or safely tested.

Performance/staging checks:

- `EXPLAIN` each delete chunk query.
- Measure row deletion throughput by table.
- Observe lock behavior while browser queries run.
- Confirm cache invalidation across web and Celery workers.
- Confirm deletion worker time limits and retry behavior.

### Phase 10: Website Integration Later

Goal: add UI only after backend deletion is proven.

Slices:

1. Add admin-only delete action on run detail pages.
   - Permission protected.
   - CSRF protected.
   - GET confirmation shows dry-run summary.
   - POST requires explicit confirmation.
   - POST calls the same service used by management commands.
   - Request thread only hides/enqueues.

2. Add deletion status UI.
   - Target, status, phase.
   - Rows planned/deleted.
   - Artifacts planned/deleted.
   - Heartbeat and timestamps.
   - Safe error summary.
   - Retry action for failed jobs only.

3. Browser behavior.
   - Deleting/deleted runs disappear from normal browsing.
   - Filter options exclude deleting/deleted runs.
   - Direct URLs show clear deleting/deleted messages.

4. UI tests.
   - Non-admins cannot delete.
   - POST requires CSRF.
   - POST queues a job without heavy deletion.
   - Duplicate POST does not create duplicate jobs.
   - Failed job retry is permission protected.

## Key Risks To Manage

- PostgreSQL lock amplification from large cascades.
- Long transactions from ORM-level delete.
- Table and index bloat after massive deletes.
- Cascade surprises through `PipelineRun`.
- Stale graph/stat/download caches.
- Cache version mismatch between web and Celery workers.
- Deleting shared taxonomy/reference rows.
- Deleting shared canonical proteins or repeat calls that should be promoted from another active run.
- Filesystem path traversal.
- Deleting raw source data accidentally.
- Starving import or payload workers with giant deletion jobs.
- Duplicate deletion jobs for the same run.
- Retries after partial deletion.
- UI showing half-deleted data.
- Dry-run counts differing from actual deletion because data changed between dry-run and execution.

## Rollout Strategy

1. Implement dry-run planner only.
2. Validate dry-run counts against manual SQL/ORM checks.
3. Add missing indexes before enabling queueing.
4. Add backend queueing.
5. Test on small local data.
6. Test on larger staging PostgreSQL data.
7. Tune chunk sizes, timeouts, and deletion worker concurrency.
8. Verify canonical repair.
9. Verify cache invalidation.
10. Verify artifact cleanup safety.
11. Deploy backend-only commands.
12. Run the first real deletion manually during a low-traffic window.
13. Observe PostgreSQL locks, query times, worker logs, Redis cache behavior, and app errors.
14. Add website UI only after successful backend-only production-like deletion.

Failure strategy:

- If failure occurs before destructive phases, an admin may manually restore the run after review.
- If failure occurs after artifact, canonical, or row deletion starts, do not pretend rollback is automatic.
- Inspect the job, fix the cause, and retry.
- Add a separate recovery command later only if a real recovery need emerges.

## Future Optimization: Partitioning

For very large deployments, consider partitioning major run-owned tables by `pipeline_run_id`.

Benefits:

- Whole-run deletion can become partition detach/drop.
- Less dead tuple bloat.
- Faster archival/deletion.
- Clearer ownership boundaries.

Costs:

- More complex migrations.
- More complex imports.
- More careful Django/PostgreSQL integration.
- More query planning and operational complexity.

Partitioning is not required for MVP.
