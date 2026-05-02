# Async Run Deletion Implementation Plan

Date: 2026-05-02

This plan breaks the production-safe deletion workflow into implementation phases and reviewable slices. It is intentionally backend-first. Website integration comes only after the command-driven workflow is tested against realistic PostgreSQL data.

## Goal

Build a safe asynchronous deletion workflow for an imported HomoRepeat run.

The MVP deletion target is `browser.PipelineRun`, because the current schema does not have a separate `Dataset` model and the imported raw data is run-scoped through `pipeline_run` foreign keys.

The workflow should:

- hide the run from normal browsing quickly
- queue heavy cleanup through Celery
- repair canonical browser data before raw row deletion
- delete run-owned database rows in dependency order
- use chunked PostgreSQL deletes with indexed filters
- avoid large single transactions
- invalidate Redis/Django caches through `CatalogVersion`
- clean only app-owned artifacts under approved roots
- expose job progress, failure state, and retry
- keep shared taxonomy/reference data and audit rows

## Optimization Rules

Performance is part of correctness for this feature. A deletion path that is safe only for small fixtures is not acceptable.

Hard rules:

- Do no heavy work in the request thread or management command queueing path.
- Prefer set-based SQL and queryset-level operations over row-by-row Python loops.
- Never load large model instances just to delete rows.
- Never use `OFFSET` pagination for delete batches; it gets slower as the table changes.
- Delete by indexed `pipeline_run_id`, indexed FK, or indexed canonical key only.
- Keep transactions small and commit between chunks.
- Keep job heartbeat/counter writes bounded; update on phase boundaries and every few seconds, not for every row.
- Use cache version bumps instead of chasing individual Redis keys.
- Do not eagerly recompute expensive browser/stat payloads during deletion unless a later measured need justifies it.
- Verify delete query plans on PostgreSQL before enabling confirmed deletion on real data.

Default performance settings for MVP:

| Setting | Initial value | Reason |
| --- | ---: | --- |
| Raw delete chunk size | 5,000 rows | Large enough for throughput, small enough to limit locks/WAL spikes |
| Very large child-table chunk size | 2,000-5,000 rows | Tune after staging `EXPLAIN ANALYZE` |
| Job heartbeat write interval | 5-15 seconds | Observable without excessive DB writes |
| `lock_timeout` per chunk | 1-3 seconds | Avoid blocking normal traffic |
| `statement_timeout` per chunk | 30-120 seconds | Bound failed plans/chunks |
| Deletion worker concurrency | 1 initially | Protect PostgreSQL and avoid worker starvation |

## Phase 0: Preflight And Baseline

Purpose: make sure the implementation starts from a known schema and avoids hidden assumptions.

### Slice 0.1: Confirm Model Graph

Review and document:

- `PipelineRun`
- raw run-owned tables
- canonical tables
- import audit tables
- shared taxonomy tables
- existing indexes on run/deletion filters and canonical repair filters

Acceptance:

- The implementation notes identify each table as `delete`, `repair`, `retain`, or `never touch`.
- The delete target is confirmed as `PipelineRun`.
- Every planned large-table delete has an indexed filter or an explicit migration prerequisite.

### Slice 0.2: Query Plan Preflight

For PostgreSQL, prepare representative `EXPLAIN` checks for:

- raw row deletion by `pipeline_run_id`
- `RepeatCallCodonUsage` deletion through `RepeatCall`
- `RepeatCallContext` deletion by direct `pipeline_run_id`
- canonical rows by `latest_pipeline_run_id`
- canonical repair predecessor lookups

Acceptance:

- Confirmed deletion remains disabled until staging query plans avoid sequential scans on large tables.
- Missing indexes are added before the destructive workflow is enabled.

### Slice 0.3: Confirm Cache And Artifact Paths

Review:

- `CatalogVersion`
- stats cache keys
- `PayloadBuild`
- `DownloadBuild`
- `HOMOREPEAT_IMPORTS_ROOT`
- `HOMOREPEAT_RUNS_ROOT`

Acceptance:

- Cache invalidation points are identified.
- Artifact roots are classified as app-owned or external/source.
- No plan depends on scanning broad cache or artifact directories.

## Phase 1: Schema Foundation

Purpose: add durable state for target lifecycle and deletion jobs.

### Slice 1.1: Add `PipelineRun` Lifecycle Fields

Add fields:

- `lifecycle_status`
  - `active`
  - `deleting`
  - `deleted`
  - `delete_failed`
- `deleting_at`
- `deleted_at`
- `delete_failed_at`
- `deletion_reason`

Add index:

- `(lifecycle_status, imported_at, id)` or equivalent active-run browse index

Acceptance:

- Existing runs default to `active`.
- Normal imports continue to create active runs.
- Migrations apply without rewriting large data unexpectedly.
- Active-run filtering stays index-backed on run list and selector queries.

### Slice 1.2: Add `DeletionJob`

Add `DeletionJob` in `apps.imports`.

Fields:

- `target_type`
- `pipeline_run`
- `status`
- `phase`
- `requested_by`
- `requested_by_label`
- `reason`
- `created_at`
- `started_at`
- `finished_at`
- `last_heartbeat_at`
- `last_error_at`
- `error_message`
- `error_debug`
- `rows_planned`
- `rows_deleted`
- `artifacts_planned`
- `artifacts_deleted`
- `catalog_versions`
- `current_table`
- `current_chunk_size`
- `retry_count`
- `idempotency_key`

Status values:

- `pending`
- `running`
- `done`
- `failed`

Do not implement cancellation in MVP.

Acceptance:

- One job can represent one run deletion end to end.
- Job rows are useful for audit and operator status.

### Slice 1.3: Prevent Duplicate Active Jobs

Add a partial uniqueness rule:

```text
one active DeletionJob per PipelineRun where status in pending/running
```

Also use transactional row locking when queueing.

Acceptance:

- Duplicate queue attempts return the existing active job.
- Race conditions cannot create two active jobs for the same run.

## Phase 2: Active-Run Visibility

Purpose: once deletion is queued, the website should stop serving the run through normal browse paths.

### Slice 2.1: Add Active-Run Query Helpers

Add a central helper/queryset for:

```text
PipelineRun.lifecycle_status = active
```

Use it from browser views instead of scattering lifecycle filters manually.

Acceptance:

- There is one preferred helper for “runs visible to browsing”.
- The helper can be reused in subqueries without forcing model-instance evaluation.

### Slice 2.2: Apply Active Filtering To Browser Lists And Choices

Update:

- run list
- run choices in explorer/stat views
- current run resolver
- metadata/facet builders
- operational browser filters

Acceptance:

- `deleting`, `deleted`, and `delete_failed` runs disappear from normal browsing.
- A direct `?run=<deleted-run>` does not silently use deleted data.

### Slice 2.3: Apply Active Filtering To Canonical Query Paths

Update canonical browser helpers so canonical rows whose `latest_pipeline_run` is not active are excluded until repair finishes.

Acceptance:

- The UI does not show half-deleted canonical rows.
- Existing active-run browsing behavior is unchanged.

## Phase 3: Dry-Run Planner

Purpose: let operators inspect deletion impact before queueing destructive work.

### Slice 3.1: Create Deletion Service Package

Create:

```text
apps/imports/services/deletion/
```

Suggested modules:

- `planning.py`
- `jobs.py`
- `canonical.py`
- `chunks.py`
- `artifacts.py`
- `cache.py`
- `postgres.py`
- `safety.py`

Acceptance:

- Management commands and Celery tasks call the service layer.
- Core deletion logic is not embedded in commands, views, or tasks.

### Slice 3.2: Implement Row Impact Planning

Count:

- run-owned raw rows
- operational rows
- canonical rows pointing at the target run
- audit rows that will be retained

Classify each table:

- delete
- repair
- retain
- never touch

Use exact `COUNT(*)` for small tables. For large tables, support a fast planning mode that uses import metadata or PostgreSQL estimates where exact counts would be expensive. The final Celery task should recalculate actual delete counters as chunks execute.

Acceptance:

- Dry-run output explains exactly what will and will not be deleted.
- Shared taxonomy/reference data is explicitly marked retained.
- Dry-run remains fast enough to run interactively on production-like data.
- Output labels estimated counts clearly when they are not exact.

### Slice 3.3: Implement Artifact Planning

Plan only approved paths:

- `HOMOREPEAT_IMPORTS_ROOT/library/<run-id>/`
- matching uploaded library root
- matching `PipelineRun.publish_root` only if inside the app-managed library root

Never plan:

- `HOMOREPEAT_RUNS_ROOT`
- arbitrary command-provided paths
- `DownloadManifestEntry.download_path`
- `DownloadManifestEntry.rehydrated_path`

Acceptance:

- Missing paths are reported as non-fatal.
- Outside-root paths are refused.
- Planning checks only known per-run paths and never scans unrelated directories.

### Slice 3.4: Add Dry-Run Command

Add:

```text
python manage.py queue_delete_run --run-id <run-id> --dry-run
```

Dry-run is the default when `--confirm` is absent.

Output:

- target identity
- lifecycle state
- duplicate active job state
- row counts by table
- canonical repair impact
- artifact candidates
- cache version impact
- large-count warnings
- index/query-plan warnings

Acceptance:

- Dry-run does not mutate database rows.
- Dry-run does not remove artifacts.
- Dry-run remains read-only except for harmless database metadata reads.

## Phase 4: Queueing Workflow

Purpose: implement the fast synchronous path.

### Slice 4.1: Implement Job Creation Service

In one transaction:

1. lock `PipelineRun`
2. check active duplicate `DeletionJob`
3. create/reuse job
4. mark run `deleting`
5. set `deleting_at`
6. copy reason/requester
7. bump `CatalogVersion`
8. enqueue Celery task with `transaction.on_commit()`

Keep this transaction narrow. It should lock only the target `PipelineRun` and relevant `DeletionJob` rows, not raw data tables.

Acceptance:

- Queueing does not run heavy deletion.
- Target is hidden immediately after commit.
- Cache version changes immediately after hiding.
- Queueing latency is bounded and independent of run size.

### Slice 4.2: Add Confirmed Queue Command

Extend:

```text
python manage.py queue_delete_run --run-id <run-id> --confirm --reason "..."
```

Acceptance:

- Command refuses actual deletion without `--confirm`.
- Command prints job id and status command.

### Slice 4.3: Add Status Command

Add:

```text
python manage.py deletion_status --job-id <id>
```

Output:

- target
- status
- phase
- timestamps
- rows planned/deleted
- artifacts planned/deleted
- current table
- heartbeat
- error summary

Acceptance:

- Operators can inspect progress without using Django admin.

### Slice 4.4: Add Retry Command

Add:

```text
python manage.py retry_deletion_job --job-id <id> --confirm
```

Rules:

- only failed jobs can be retried
- retry reuses the same job
- retry increments retry count
- retry re-enqueues through the same service

Acceptance:

- Retry does not create duplicate jobs.
- Retry can resume after partial cleanup.

## Phase 5: Celery Task And Queue Isolation

Purpose: isolate deletion work from imports, uploads, payload graph work, and downloads.

### Slice 5.1: Add Deletion Task

Add:

```text
apps.imports.tasks.delete_pipeline_run_job(job_id)
```

Task behavior:

1. atomically claim pending job
2. exit if already done
3. validate target
4. update status/phase/heartbeat
5. execute durable phases
6. mark done or failed

The task should execute a deterministic phase list and update the job row on phase boundaries plus timed heartbeats. Avoid writing progress after every chunk when chunks are small; aggregate counters in memory and flush periodically.

Acceptance:

- One worker can claim a job once.
- Re-running a completed task is a no-op.
- Job progress is observable without creating avoidable write load.

### Slice 5.2: Add Dedicated Queue

Route:

```text
"apps.imports.tasks.delete_pipeline_run_job": {"queue": "deletions"}
```

Add a low-concurrency worker in Compose after the task exists:

```text
celery -A config.celery worker -Q deletions -c 1 --prefetch-multiplier 1 --loglevel=info
```

Acceptance:

- Deletion jobs cannot starve imports or payload graph workers.
- Only one large deletion runs by default until staging proves higher concurrency is safe.

### Slice 5.3: Add Failure Handling

On error:

- set job `failed`
- set run `delete_failed`
- store safe `error_message`
- store debug details in `error_debug`
- keep partial counters

Acceptance:

- Failed jobs are inspectable and retryable.
- Raw tracebacks are not exposed to normal users.

## Phase 6: Canonical Catalog Repair

Purpose: prevent canonical browser data from pointing at a run being deleted.

### Slice 6.1: Identify Impacted Canonical Rows

Find canonical rows where:

- `latest_pipeline_run = target`
- `latest_repeat_call` points to target raw repeat calls

Build a small impacted-key working set before repair. Use accession, sequence id, protein id, method/residue/start/end, and raw call ids from the target run so canonical repair does not scan the full canonical catalog unnecessarily.

Acceptance:

- Planner and task agree on the canonical impact.
- Impact discovery uses indexed target-run filters.

### Slice 6.2: Promote Active Predecessors

For canonical entities touched by the deleting run:

- find newest active predecessor raw rows
- update canonical row to point to that active run/import batch
- update `latest_repeat_call` where applicable

Use set-based SQL where possible:

- select candidate predecessor rows with `DISTINCT ON (...)` or window functions ordered by active run recency
- bulk update canonical rows from the candidate set
- avoid per-canonical-row Python lookups

Acceptance:

- Data present in another active run remains browsable.
- Repair runtime scales with impacted keys, not total database size.

### Slice 6.3: Remove Canonical Orphans

Delete canonical rows that have no active predecessor.

Delete child rows first:

- `CanonicalRepeatCallCodonUsage`
- `CanonicalRepeatCall`
- `CanonicalProtein`
- `CanonicalSequence`
- `CanonicalGenome`

Acceptance:

- Deleted-run-only canonical data disappears.
- Shared canonical data is not removed accidentally.
- Orphan deletion uses chunked or bounded set-based deletes when result sets are large.

### Slice 6.4: Rebuild Rollups

Rebuild:

- `CanonicalCodonCompositionSummary`
- `CanonicalCodonCompositionLengthSummary`

Then bump `CatalogVersion` again.

MVP can reuse the existing full rollup rebuild functions for correctness. Before enabling deletion for very large production data, measure rebuild time on staging. If full rebuild is too slow, split this into a follow-up optimization using impacted residue/taxon scopes.

Acceptance:

- Unscoped/global stats reflect the repaired catalog.
- Rollup rebuild time is measured and documented before production use.

## Phase 7: Artifact Cleanup

Purpose: remove app-owned files safely and separately from database cleanup.

### Slice 7.1: Implement Safe Path Utilities

Rules:

- resolve candidate path
- verify approved root
- reject traversal
- handle symlinks conservatively
- missing path is success

Acceptance:

- Tests cover missing paths, traversal, symlinks, and outside-root paths.
- Artifact deletion does not walk broad shared roots.

### Slice 7.2: Delete App-Owned Run Library

Delete:

- approved `HOMOREPEAT_IMPORTS_ROOT/library/<run-id>/`

Retain:

- external source data
- upload audit rows
- download manifest paths

Acceptance:

- Only app-owned library data is deleted.

## Phase 8: Chunked Raw Row Deletion

Purpose: physically remove run-owned database rows without large transactions.

### Slice 8.1: Implement Chunk Delete Helpers

Use PostgreSQL CTE delete batches.

Always batch by primary key selected through an indexed predicate. Do not use Django model `delete()` for large tables because it may collect cascades and hold a large transaction.

Direct run-owned tables:

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

Indirect child tables:

```sql
WITH victim AS (
  SELECT child.id
  FROM child
  JOIN parent ON parent.id = child.parent_id
  WHERE parent.pipeline_run_id = %s
  ORDER BY child.id
  LIMIT %s
)
DELETE FROM child
USING victim
WHERE child.id = victim.id;
```

Acceptance:

- No model instances are loaded for large deletes.
- Each chunk returns row count.
- No chunk query requires materializing a huge Python list of primary keys.
- No chunk query uses `OFFSET`.

### Slice 8.2: Add Lock And Statement Timeouts

Use per-chunk transaction settings:

- short `lock_timeout`
- bounded `statement_timeout`
- retry/backoff on lock timeout
- adaptive chunk sizing after repeated timeouts

Acceptance:

- A locked row/table causes retry or failure, not indefinite blocking.
- Repeated timeouts reduce chunk size before failing the whole job.

### Slice 8.3: Delete In Dependency Order

Order:

1. `RepeatCallCodonUsage`
2. `RepeatCallContext`
3. `RepeatCall`
4. `DownloadManifestEntry`
5. `NormalizationWarning`
6. `AccessionStatus`
7. `AccessionCallCount`
8. `Protein`
9. `Sequence`
10. `Genome`
11. `RunParameter`
12. `AcquisitionBatch`

Acceptance:

- Protected batch/taxon relationships do not block deletion.
- Unrelated runs are untouched.
- Largest child tables are deleted with the most direct indexed filter available.

### Slice 8.4: Minimize WAL And Lock Pressure

Use:

- small transactions per chunk
- short sleeps or Celery retry backoff after lock timeouts
- lower chunk sizes for very wide rows or high-WAL tables
- periodic counter flushes instead of one job update per chunk if chunks are very small

Acceptance:

- Normal read traffic remains responsive during staging deletion tests.
- WAL growth and replication lag, if applicable, stay within operator-defined limits.

## Phase 9: PostgreSQL Analyze And Finish

Purpose: update planner stats and mark final state.

### Slice 9.1: Analyze Affected Tables

Run targeted `ANALYZE` on affected raw and canonical tables.

Only analyze tables whose row count changed meaningfully. Record skipped tables in the job debug metadata so operators can see why maintenance was lightweight.

Do not run:

- `VACUUM FULL`
- non-concurrent `REINDEX`
- `TRUNCATE`
- `DROP CASCADE`

Acceptance:

- `ANALYZE` runs only on PostgreSQL.
- Non-PostgreSQL tests safely skip or mock it.
- Analyze work stays proportional to affected tables, not the whole database.

### Slice 9.2: Mark Job Done

Set:

- job `done`
- phase `finished`
- run `deleted`
- `deleted_at`
- final counters

Acceptance:

- Completed job is idempotent.
- Re-running task exits cleanly.

## Phase 10: Tests And Validation

Purpose: prove safety before website integration.

### Slice 10.1: Unit Tests

Cover:

- dry-run counts
- no mutation during dry-run
- duplicate job prevention
- artifact path safety
- cache version bump helper
- retry eligibility
- status formatting

### Slice 10.2: Integration Tests

Cover:

- queue hides target immediately
- task deletes in dependency order
- unrelated runs remain
- taxonomy/reference rows remain
- canonical rows promote or delete correctly
- missing artifacts are non-fatal
- partial deletion retry succeeds
- failed job records error

### Slice 10.3: PostgreSQL/Staging Tests

Cover:

- `EXPLAIN` delete chunk queries
- `EXPLAIN` canonical predecessor selection and orphan deletion
- deletion throughput
- lock timeout behavior
- worker time limits
- cache invalidation across web and Celery workers
- table/index bloat observation after delete
- WAL growth and database load during deletion

Acceptance:

- Backend-only deletion is safe enough to operate manually.
- Website integration remains blocked until this phase passes.
- Chunk sizes and timeout defaults are chosen from measured staging data, not guesses.

## Phase 11: Operator Documentation

Purpose: make backend deletion usable without source-code knowledge.

Update `docs/operations.md` with:

- dry-run command
- queue command
- status command
- retry command
- expected phases
- failure handling
- warnings about irreversible partial deletion
- explicit note that heavy PostgreSQL maintenance is manual/admin-only

Acceptance:

- An admin can run the backend deletion workflow from the docs.

## Phase 12: Website Integration Later

Purpose: expose the proven workflow through admin-only UI.

### Slice 12.1: Confirmation UI

Add admin-only delete action:

- GET shows dry-run summary
- POST requires CSRF and confirmation
- POST calls same queueing service

### Slice 12.2: Status UI

Show:

- job status
- phase
- counters
- heartbeat
- safe error
- retry button for failed jobs

### Slice 12.3: Direct URL Behavior

Show clear messages for:

- deleting run
- deleted run
- delete failed run

Acceptance:

- UI does not introduce a second deletion pathway.
- Heavy deletion never runs in a request thread.

## Non-Goals For MVP

- Website delete button before backend proof.
- User-facing deletion for non-admins.
- Cancellation of already-running destructive jobs.
- Full rollback after partial physical deletion.
- Kafka or Kubernetes-specific orchestration.
- Automatic bloat repair.
- Automatic `VACUUM FULL`.
- Automatic `REINDEX`.
- Required table partitioning.
