# Redis + Celery Refactor: Implementation Plan

## Likely Root Cause

The main architectural problem is not merely that the app lacks Celery. The
deeper problem is that heavy work is split incorrectly:

- imports are durable but executed through DB polling instead of a real broker
- graph payload building is coupled to web views
- download generation is coupled to request/response even when some outputs
  should become durable artifacts
- payload invalidation and reuse are not modeled explicitly

The migration should fix those boundaries first, then move only the right work
into async queues.

## Migration Strategy

## Phase 1. Architecture Audit And Payload Inventory

### Goal

Establish an explicit inventory of import steps, graph payload families, and
download payload families before moving runtime boundaries.

### What is already done

- stats service layer: `apps/browser/stats/queries.py`, `payloads.py`,
  `summaries.py`, `filters.py`, and `taxonomy_gutter.py` are already separate
  modules; views call them rather than building payloads inline
- bundle builders already cache using `filter_state.cache_key()` (SHA1 of
  filter parameters) with a 60-second TTL via Django's cache framework
- download export logic: `BrowserTSVExportMixin` and `StatsTSVExportMixin` in
  `apps/browser/exports.py` already separate export assembly from view rendering
- import state machine: `apps/imports/services/import_run/state.py` already
  implements atomic claim (`_claim_import_batch`) and idempotent status
  transitions that are safe to call from a Celery task

### What is not yet done

- cache keys do not include a catalog version, so new imports do not invalidate
  stale cached payloads
- the CACHES backend is locmem (per-process); no shared cross-worker cache exists
- no async task substrate (broker, worker services, task definitions)
- payload classification policy lives implicitly inside view classes

### Concrete changes

- document current import entrypoints, queue points, and status updates
- inventory graph payload families by view, bundle builder, cost profile, and
  user interaction pattern; note which are already in separate modules
- inventory download payload families by size, latency, and artifact value
- add basic timing instrumentation around bundle builders to establish cost
  baselines before making async promotion decisions
- define catalog-version as the basis for cache invalidation: what it is, where
  it lives, and when it increments (see Section 8 for recommended model)

### Expected benefits

- stops the migration from becoming a blind "Celery everywhere" rewrite
- identifies which payloads are worth caching vs persisting vs leaving inline
- gives a bounded initial scope for the first async move

### Risks

- underestimating payload cost without basic timing data
- spending too long cataloging instead of moving a first slice

### Exit criteria

- payload inventory exists with explicit classifications:
  `sync`, `sync+cache`, `async+persisted`, or `defer`
- import flow and current worker responsibilities are documented
- catalog-version concept is defined and agreed (what it is, where it lives,
  when it increments)
- initial cache-key composition (filter_state hash + catalog_version) is agreed

## Phase 2. Introduce Redis And Celery Skeleton

### Goal

Add the runtime substrate without changing core business behavior yet.

### Concrete changes

- add `redis:7-alpine` service to Compose with a healthcheck (`redis-cli ping`);
  make `web` and all Celery worker services depend on it being healthy
- add `django-redis` to requirements; update `CACHES` in `config/settings.py`
  to use Redis as the default backend — the existing `cache.get/set` calls in
  `queries.py` and `taxonomy_gutter.py` require no code changes
- create `config/celery.py`:
  ```python
  from celery import Celery
  app = Celery('homorepeat')
  app.config_from_object('django.conf:settings', namespace='CELERY')
  app.autodiscover_tasks()
  ```
  import it in `config/__init__.py` (`from .celery import app as celery_app`)
  so Django loads the Celery app at startup
- add Celery settings in `config/settings.py`:
  - `CELERY_BROKER_URL = 'redis://redis:6379/0'` — logical db 0 for broker
  - `CACHES = {'default': {'BACKEND': '...', 'LOCATION': 'redis://redis:6379/1'}}`
    — logical db 1 for cache; different db allows different eviction policies
    (broker needs AOF persistence; cache can use `volatile-lru` eviction)
  - `CELERY_TASK_IGNORE_RESULT = True` — tasks write their own state to
    `ImportBatch`/`PayloadBuild`/`DownloadBuild`; the result backend is not
    the source of truth
  - `CELERY_TASK_SERIALIZER = 'json'`
  - `CELERY_WORKER_PREFETCH_MULTIPLIER = 1` — prevent worker processes from
    reserving multiple long-running tasks and silently starving the queue; the
    default of 4 is wrong for import-class tasks
  - `CELERY_BROKER_TRANSPORT_OPTIONS = {'visibility_timeout': 43200}` — Redis
    default visibility timeout is 1 hour; an import running longer than that
    will be re-queued mid-flight by the broker even if the worker is alive;
    43200 seconds (12 hours) is a safe ceiling for this workload
  - `CELERY_TASK_ROUTES` for centralized queue assignment, e.g.:
    ```python
    CELERY_TASK_ROUTES = {
        'apps.imports.tasks.*': {'queue': 'imports'},
        'apps.browser.tasks.*': {'queue': 'payload_graph'},
    }
    ```
  - `CELERY_TASK_ALWAYS_EAGER = True` in test settings so tasks execute
    synchronously without a broker
- add Compose services with healthchecks:
  - `celery-import-worker`: `celery -A config.celery worker -Q imports -c 2 --prefetch-multiplier 1 --loglevel=info`
    healthcheck: `celery -A config.celery inspect ping -d celery@$$HOSTNAME`
  - `celery-payload-worker`: `celery -A config.celery worker -Q payload_graph,downloads -c 4 --loglevel=info`
    healthcheck: same pattern
  - `flower`: run with `--url_prefix=admin/flower` and no `ports:` entry;
    accessed via the Django admin proxy (see below), not directly on the host
- add a `flower_proxy` view and register it in `config/urls.py` so that staff
  users can reach Flower at `/admin/flower/` through Django's session auth
  (see the Compose implications section in the overview for the full wiring)
- keep the existing DB-polled `worker` service temporarily as a fallback

### Expected benefits

- creates the async boundary with minimal business risk
- makes enqueue latency independent of DB polling
- allows incremental migration task by task

### Risks

- configuration drift between web and workers
- premature expansion into too many queues before workload evidence exists

### Exit criteria

- web can enqueue a no-op Celery task successfully
- worker services consume from Redis-backed queues locally in Compose
- configuration is stable enough for real task migration

## Phase 3. Refactor Import Execution To Celery

### Goal

Replace the polled management-command worker with Celery while preserving the
existing import service logic and `ImportBatch` durability.

### Concrete changes

- create `apps/imports/tasks.py` with the import task:
  ```python
  @shared_task(bind=True, max_retries=3)
  def run_import_batch(self, batch_id: int) -> None:
      try:
          process_import_batch(batch_id)
      except ImportContractError:
          raise  # contract errors are permanent; do not retry
      except Exception as exc:
          raise self.retry(exc=exc, countdown=30)
  ```
  `process_import_batch()` is the existing function in
  `apps/imports/services/import_run/api.py`; it already calls
  `_claim_import_batch()` which atomically transitions PENDING → RUNNING via
  a DB transaction — this makes the task safe to re-enqueue without duplicate
  execution risk
- add `celery_task_id = models.CharField(max_length=64, null=True, blank=True)`
  to `ImportBatch` so the web layer can store the task ID for operational lookup;
  `ImportBatch.status` and `phase` fields remain the authoritative state
- update the web enqueueing path: after creating `ImportBatch`, call
  `result = run_import_batch.delay(batch.id)` and store `result.id` in
  `batch.celery_task_id`
- the `manage.py import_run` management command must remain functional as a
  direct synchronous path; it calls `process_import_batch()` or
  `import_published_run()` directly, bypassing Celery — do not remove it
- retire the `manage.py import_worker` polling loop once Celery import
  execution is stable in local Compose usage

### Expected benefits

- faster enqueue
- less operational awkwardness than polling
- a durable task model that still preserves current import state reporting

### Risks

- duplicate execution if idempotent claim behavior is not preserved
- race conditions during the transition if both worker paths remain active
- **worker crash leaves batch stuck in RUNNING**: `_claim_import_batch()` in
  `state.py` raises `ImportContractError` if `batch.status != PENDING`. If a
  Celery worker crashes mid-import, the batch status stays RUNNING. Because
  `ImportContractError` is treated as a permanent error (not retried), a re-
  queued task will fail immediately when it tries to claim the same batch —
  leaving the batch stuck in RUNNING forever with no visible error.

  Fix: add a Beat watchdog task that runs on a short interval (e.g. every 5
  minutes) and resets stale RUNNING batches:
  ```python
  @shared_task
  def reset_stale_import_batches():
      stale_cutoff = timezone.now() - timedelta(minutes=10)
      ImportBatch.objects.filter(
          status=ImportBatch.Status.RUNNING,
          heartbeat_at__lt=stale_cutoff,
      ).update(
          status=ImportBatch.Status.PENDING,
          phase=ImportPhase.QUEUED,
          heartbeat_at=timezone.now(),
      )
  ```
  The batch's `heartbeat_at` is already updated every 2 seconds by
  `_ImportBatchStateReporter`, so a 10-minute threshold safely distinguishes
  a crashed worker from a legitimately slow one. Re-setting to PENDING allows
  the normal enqueueing path to re-dispatch the batch. This means `celery-beat`
  should be considered required for import correctness, not optional later.

### Exit criteria

- imports run only through Celery in normal local usage
- `ImportBatch` status, heartbeat, and failure behavior remain intact
- the old `import_worker` path is marked deprecated or removed

## Phase 4. Catalog Version And Cache Key Formalization

### Goal

Introduce a catalog version so that new imports naturally invalidate stale
cached payloads, and formalize the payload classification policy. The stats
service layer is already extracted; this phase closes the remaining structural
gaps.

### What is already done

- `apps/browser/stats/queries.py`, `payloads.py`, `summaries.py`, `filters.py`,
  and `taxonomy_gutter.py` are already separate modules
- bundle builders already cache via Django's cache API; switching the backend
  to Redis (Phase 2) means these calls already benefit from shared cross-worker
  caching without further code changes

### Remaining work

- define and implement `catalog_version` (see Data And Task Flow Design section):
  a monotonically increasing integer stored in a lightweight model, incremented
  by `_mark_batch_completed()` after each successful canonical sync
- update `StatsFilterState.cache_key()` to include the current catalog version
  so new imports automatically invalidate stale cache entries; **do not call
  `CatalogVersion.current()` (a DB query) on every request** — instead cache
  the version value in Redis with a short TTL:
  ```python
  def get_catalog_version() -> int:
      v = cache.get('catalog_version')
      if v is None:
          v = CatalogVersion.current()
          cache.set('catalog_version', v, timeout=10)
      return v
  ```
  This limits catalog version DB reads to at most one per 10 seconds across all
  web workers, rather than one per request. After an import completes, call
  `cache.delete('catalog_version')` so the next request picks up the new
  version immediately rather than waiting for the 10-second TTL.
- **cache stampede on import completion**: when the catalog version changes, all
  existing cache keys become stale simultaneously. A traffic burst right after
  an import will cause every concurrent request to miss cache and rebuild its
  payload from the DB at the same time. Mitigation: old keys do not need
  explicit deletion — they become unreachable (different version in key) and
  expire via TTL. Keep the cache TTL moderate (e.g. 10–15 minutes) so stale
  keys reclaim memory eventually without active purge overhead.
- add per-bundle timing instrumentation to establish actual payload cost
  baselines; use these measurements to validate or revise Phase 1 classifications
  before making any async promotion decisions
- formalize payload classification policy: replace the implicit per-view
  decisions with a shared function that maps (filter state, payload type) to
  `sync`, `sync+cache`, or `async+persisted`; this makes the policy testable
  and keeps it in one place
- verify that `payloads.py` and `queries.py` functions have no view-layer
  imports so they can be called from Celery workers without pulling in HTTP
  request context

### Expected benefits

- new imports automatically invalidate stale chart payloads via cache-key change
- shared Redis cache improves hit rates under multi-worker deployment
- timing data guides async promotion decisions in Phase 6
- classification policy is explicit and testable

### Risks

- over-engineering catalog_version before the cache invalidation problem is
  actually observed
- timing data may show most payloads are fast enough to stay synchronous,
  making Phase 6 smaller than expected (that is a good outcome, not a problem)

### Exit criteria

- `catalog_version` is defined, stored, and updated on import completion
- cache keys in `queries.py` and `taxonomy_gutter.py` include `catalog_version`
- at least one representative payload family has timing data from production-
  like filter scopes
- no graph families have been promoted to async without timing evidence

## Phase 5. Extract Download Generation Policy From Views

### Goal

Create a clear download service boundary that can support both inline streaming
and async artifact builds.

### What is already done

- `BrowserTSVExportMixin` and `StatsTSVExportMixin` in
  `apps/browser/exports.py` already separate export assembly from view
  rendering; the TSV streaming path is already a service boundary and requires
  no changes for the MVP

### Remaining work

- add `DownloadBuild` model (see Section 9 for recommended fields) for the
  async artifact path
- add a classification function (in `apps/browser/exports.py` or a new
  `apps/browser/downloads.py`) that routes a download request to the inline
  streaming path or the async artifact path based on export type and size
- add status/readiness endpoints for async download builds
- the inline streaming paths (`BrowserTSVExportMixin`,
  `StatsTSVExportMixin`) remain untouched for the MVP

### Expected benefits

- download logic stops being a web-only concern
- the app gains a clean path for larger exports later
- small exports stay fast and simple

### Risks

- overbuilding async download machinery before a real heavy export needs it
- prematurely converting useful streaming downloads into queued jobs

### Exit criteria

- current streamed downloads still work through the new service boundary
- one representative async artifact flow is designed and ready for later
  implementation
- download classification rules are documented and enforced in one place

## Phase 6. Introduce Payload Queues Selectively

### Goal

Use Celery for the subset of graph/download work that genuinely benefits from
background execution.

### Concrete changes

- create `payload_graph` and `downloads` queues
- implement one or two explicitly heavy async build paths, not a blanket move
- store durable build records for async payloads/artifacts
- add frontend polling/status behavior only where async is actually used

### Expected benefits

- web responsiveness improves where heavy payload contention existed
- reuse of expensive build outputs becomes possible
- the queue model is proven without overcommitting the app

### Risks

- user experience regression if async is used for payloads that should stay
  inline
- build record sprawl if every payload gets durable rows

### Exit criteria

- at least one heavy graph or export use case runs through the new payload queue
- the majority of interactive payloads remain inline
- async payload builds have explicit status, retry, and invalidation behavior

## Phase 7. Split Worker Pools And Tune Concurrency

### Goal

Prevent imports, graph builds, and download builds from interfering with each
other.

### Concrete changes

- run separate worker services or queue bindings for:
  - imports
  - graph payloads
  - downloads
- tune concurrency independently per worker type
- define queue ownership and operational expectations in docs

### Expected benefits

- predictable latency per workload class
- better local resource use
- cleaner future path to independent horizontal scaling

### Risks

- premature queue/service sprawl if traffic remains tiny
- too much concurrency for DB-heavy imports

### Exit criteria

- imports cannot starve graph/download workers
- concurrency settings exist per worker class
- local Compose startup remains understandable

## Phase 8. Cleanup, Invalidation, And Operational Hardening

### Goal

Remove the old pathways and stabilize the new architecture.

### Concrete changes

- remove the DB-polled worker path
- remove obsolete view-coupled payload code
- finalize catalog-version invalidation behavior
- add basic cleanup for expired async download artifacts
- document worker restart, retry, and failure expectations

### Expected benefits

- fewer parallel code paths
- clearer ownership of sync vs async work
- lower operational ambiguity

### Risks

- deleting fallback paths too early
- missing artifact cleanup leading to storage drift

### Exit criteria

- old worker path is gone
- invalidation behavior is explicit and tested
- the architecture is documented as the new default

## Data And Task Flow Design

## Catalog version model

A catalog version is a monotonically increasing integer that identifies the
current state of the canonical catalog. It advances exactly once per successful
canonical sync.

Recommended implementation:

- add a `CatalogVersion` model in `apps/imports/models.py`:
  ```python
  class CatalogVersion(models.Model):
      version = models.PositiveIntegerField(default=0)
      updated_at = models.DateTimeField(auto_now=True)

      class Meta:
          # enforce a single row
          constraints = [models.CheckConstraint(check=models.Q(pk=1), name='singleton')]

      @classmethod
      def current(cls) -> int:
          obj, _ = cls.objects.get_or_create(pk=1)
          return obj.version

      @classmethod
      def increment(cls) -> int:
          cls.objects.filter(pk=1).update(version=models.F('version') + 1)
          return cls.current()
  ```
- call `CatalogVersion.increment()` inside `_mark_batch_completed()` in
  `apps/imports/services/import_run/state.py` after the canonical sync
  completes successfully
- cache keys incorporate the version: `f"{filter_state.cache_key()}:{CatalogVersion.current()}"`
- no explicit cache invalidation calls are needed: the key changes when the
  version changes, and old entries expire via TTL

This is intentionally simple. Per-taxon or per-entity versioning is not
warranted until key-space cardinality becomes a problem.

## Import request lifecycle

### What the web app does

- validates the import request
- creates or updates `ImportBatch`
- sets initial status/phase
- enqueues Celery task with batch ID

### What gets written to the database

- durable `ImportBatch` row
- later, `pipeline_run` linkage and progress updates as today
- catalog-version update after successful canonical sync

### What gets queued

- one import task on the `imports` queue

### What the worker does

- claims the batch idempotently
- runs existing import service code
- updates phase/progress/heartbeat/failure
- runs canonical sync
- advances catalog version on success
- triggers targeted invalidation or follow-up materialization only if needed

### How completion/status/errors should be tracked

- `ImportBatch` remains the source of truth
- Celery task state is secondary operational metadata, not the user-facing model

### What the frontend should read from

- import status endpoints backed by `ImportBatch`

### Whether results should be cached, persisted, or regenerated

- import status persists in PostgreSQL
- import outputs remain the canonical/raw domain tables already used by the app

## Graph payload generation lifecycle

### What the web app does

- parses filter state
- computes payload type and cache/build key using catalog version
- decides `sync`, `sync+cache`, or `async+persisted`

### What gets written to the database

- nothing for normal synchronous cached reads
- optional `PayloadBuild` record only for async graph builds

### What gets queued

- nothing for inline graph payloads
- one `payload_graph` task for async-classified graph builds

### What the worker does

- loads canonical state for the requested scope
- builds payload through shared service code
- persists result reference and status

### How completion/status/errors should be tracked

- cache hit/miss metrics for synchronous paths
- `PayloadBuild` record for async paths with status, timestamps, and error text

### What the frontend should read from

- direct payload response for synchronous paths
- status endpoint plus ready payload endpoint for async paths

### Whether results should be cached, persisted, or regenerated

- synchronous deterministic graph payloads should usually be cached in Redis
- async graph builds should persist only when they are genuinely reusable
- graph payloads should be keyed by catalog version so new imports invalidate
  old results naturally

## Download payload generation lifecycle

### What the web app does

- classifies the requested export
- either streams immediately or creates a `DownloadBuild`
- enqueues background task only for artifact-class exports

### What gets written to the database

- nothing new for inline streamed downloads
- `DownloadBuild` row for async artifact downloads

### What gets queued

- nothing for inline streamed downloads
- one `downloads` task for async artifact generation

### What the worker does

- builds export content via shared download service code
- writes artifact to configured storage location
- records artifact path, size, checksum, and completion state

### How completion/status/errors should be tracked

- `DownloadBuild` is the durable truth
- worker retries are allowed for transient failures
- terminal failures should retain error details for UI display

### What the frontend should read from

- immediate response for inline downloads
- build-status endpoint for async downloads, followed by ready artifact link

### Whether results should be cached, persisted, or regenerated

- inline downloads should be regenerated on demand
- async download artifacts should be persisted for a bounded retention period

## State, Status, And Observability Model

### Durable state recommendation

#### Import jobs

- keep `ImportBatch`
- extend it with `celery_task_id` (CharField, nullable) to store the Celery
  task ID for operational lookup; `status` and `phase` fields remain authoritative
- optionally add `attempt_count` (PositiveSmallIntegerField, default=0) if
  retry tracking becomes needed
- do not replace `ImportBatch` with ephemeral Celery result backend state

#### Graph payload builds

- do not create DB rows for every graph request
- create a durable `PayloadBuild` model only for async graph families
- synchronous graph payloads should rely on cache plus deterministic rebuild

#### Download payload builds

- create a durable `DownloadBuild` model for async artifact downloads
- store file location, status, error, expiry, and catalog version

### Recommended state fields

For async build records, keep the model minimal:

- `build_type`
- `scope_key`
- `catalog_version`
- `status`
- `requested_by`
- `created_at`
- `started_at`
- `finished_at`
- `error_message`
- `artifact_path` or payload reference
- `checksum` and `size_bytes` where relevant

### Status exposure to the web layer

- import pages read from `ImportBatch`
- async graph payload polling reads from `PayloadBuild`
- async download polling reads from `DownloadBuild`
- the web layer should never need to inspect Celery internals to render user
  status

### Failure and retry model

- imports: retry cautiously and explicitly, because side effects are heavier
- graph builds: safe automatic retry only if the build is idempotent
- downloads: retry transient storage/DB issues automatically, keep terminal
  failures visible

### Minimal observability for the MVP

- structured logs from web and worker processes with queue name included
- DB-backed job/build status views for user-visible tasks (`ImportBatch`,
  `PayloadBuild`, `DownloadBuild`)
- Flower served inside the Django admin zone at `/admin/flower/`; staff see
  queue depth, task state, retries, and runtimes through the existing session
  auth without a separate login or exposed port — implement using the proxy
  view described in Phase 2 and the overview's Compose implications section
- basic timing metrics; collect these in Phase 4 by wrapping bundle builders:
  - import enqueue-to-start latency
  - import runtime
  - per-bundle synchronous payload generation time
  - async payload/download build time
  - cache hit/miss ratio for graph payloads (add a simple logging wrapper
    around `cache.get` calls in `queries.py`; Django does not expose this
    automatically with the default backends)

Do not over-engineer monitoring at this stage. The MVP needs enough visibility
to tune queue decisions and catch stuck jobs.

## Recommended Phased Migration Summary

Primary sequence:

1. inventory and classify payloads
2. add Redis + Celery skeleton
3. migrate imports to Celery
4. extract graph payload services and add caching
5. extract download services while keeping small exports synchronous
6. move only explicitly heavy graph/download work to payload queues
7. split worker pools and tune concurrency
8. remove old paths and harden operations

This sequence keeps the most important architectural win first: imports move to
a real broker, while payload work is classified before it is pushed into async.

## First Implementation Milestone Suggestion

The first implementation milestone should be:

### Milestone 1: Redis/Celery bootstrap plus import-task migration

Deliver:

- Redis service in Compose
- Celery app/runtime wiring
- `imports` queue and `celery-import-worker`
- web enqueue path that creates `ImportBatch` then dispatches Celery task
- import execution moved from `manage.py import_worker` polling to Celery task
- no graph/download async migration yet

Why this first:

- it solves the clearest current architectural mismatch
- it provides the async substrate needed for later payload decisions
- it preserves the current product behavior while changing the execution model
- it avoids prematurely queueing graph/download work before classification and
  service extraction are done
