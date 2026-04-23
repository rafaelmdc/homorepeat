# Redis + Celery Refactor: Overview

## 1. Executive Overview

This migration is needed because the current Django application still owns too
much heavy work directly in the request/response path, while the only background
execution model is a database-polled import worker. That is workable for a
small local MVP, but it is the wrong foundation for responsive async imports,
reusable payload builds, and future horizontal worker scaling.

The first-stage target architecture keeps Django, PostgreSQL, and Docker Compose
as the core runtime, but adds Redis and Celery as the standard async boundary.
The immediate goal is not full pipeline automation. The immediate goal is to:

- enqueue imports cleanly through Redis-backed Celery queues
- move only the right heavy payload work out of the web path
- keep cheap payloads synchronous when worker overhead would be worse
- separate import orchestration, graph payload generation, and download payload
  generation into clearer service boundaries
- replace ad hoc worker polling with persistent worker pools

Problems this solves:

- less request-path contention inside Django
- lower queueing latency than DB polling
- fewer cases where heavy graph/export work competes with page rendering
- cleaner status tracking for long-running imports and artifact builds
- a simpler path toward later queue specialization and Kubernetes workers

Out of scope for this MVP:

- full pipeline launch/orchestration automation
- Kubernetes-specific deployment mechanics
- introducing Kafka or other heavier infrastructure
- moving every payload into background workers by default
- redesigning the scientific pipeline contract

## 2. Current-State Assessment

### Current architecture

The current Compose stack has four services:

- `web`: Django app, browser UI, stats views, payload creation, and download
  generation
- `postgres`: application database
- `migrate`: schema gate before web start
- `worker`: `python manage.py import_worker --poll-interval 2`

Within the app:

- `apps/imports` already has a durable DB-backed queue record: `ImportBatch`
- `apps/browser/views/stats/*` build graph payloads inside Django views
- `apps/browser/exports.py` serves download payloads directly from the web app
- graph payload building currently sits very close to template rendering

### Tight coupling points

- Stats views both gather data and build chart payload JSON in the same web
  request.
- Download generation is triggered directly from views and HTTP responses.
- Import enqueueing is durable in the database, but execution still depends on a
  polling management command rather than a real broker.
- Payload invalidation is implicit and local rather than modeled as a first
  class concern.

### What the stats service layer already provides

`apps/browser/stats/` already contains distinct service modules that views call
rather than building payloads inline:

- `filters.py` / `params.py` parse query parameters into `StatsFilterState`
- `queries.py` contains all bundle builders; they already use Django's cache
  framework with a configurable TTL (default 60 s) keyed by
  `filter_state.cache_key()` (SHA1 of filter parameters)
- `payloads.py` contains all payload serializers
- `summaries.py` contains statistical computation
- `taxonomy_gutter.py` builds the cladogram payload with its own caching

Similarly, `BrowserTSVExportMixin` and `StatsTSVExportMixin` in
`apps/browser/exports.py` already separate export assembly from view rendering
for small and medium table downloads.

The remaining coupling is at the view-orchestration level: views still
coordinate multiple bundle and payload builder calls and hold the payload
classification policy implicitly. The primary structural gaps are:

- cache keys do not incorporate a catalog version, so new imports do not
  invalidate cached payloads naturally
- the cache backend is Django locmem (per-process); cache entries are not
  shared across web workers, so hit rates drop under multi-process deployment
- payload classification policy (sync vs cached vs async) is not formalized;
  it lives implicitly inside each view class

### Responsibilities in the wrong place

- View classes currently act as request parsers, query orchestrators, payload
  assemblers, and response renderers.
- Download generation currently lives too close to the web response boundary,
  even for payloads that may later deserve artifact persistence or retries.
- The worker model is import-specific and does not provide a general async
  boundary for reusable background work.

### Likely bottlenecks

- heavy stats page requests compete with normal web traffic for CPU, DB time,
  and serialization time
- stats bundle caching uses Django locmem (per-process) today; under multiple
  web workers each process maintains its own cache and cold-miss rates are
  higher than a shared Redis cache would produce
- large downloads tie up web workers and long-lived HTTP responses
- DB polling adds latency and does not provide queue-level backpressure

### Risks of graph payload generation living in Django

- request latency grows with payload complexity and cache misses
- concurrent users can trigger repeated expensive recomputation
- web capacity and graph-build capacity cannot be scaled independently
- interactive views become harder to reason about because business logic,
  aggregation, and rendering stay entangled

### Risks of download payload generation living in Django

- large exports occupy web workers for work that is not latency-sensitive
- retries, resumability, and failure visibility are weak
- repeated requests for the same export can duplicate expensive work
- artifact retention and invalidation remain implicit instead of modeled

### Limitations of the current worker model

- it is DB-polled, so queue latency is tied to poll interval
- it is import-only, not a general async execution substrate
- it does not separate workload classes by queue or concurrency
- it does not reduce spawn overhead for many small specialized workers because
  the model is still a single long-running command with one responsibility
- it does not give a clean future path for graph/download worker pools

## 3. Payload Classification And Decision Framework

This is the critical decision point of the migration. The correct answer is not
"move all payloads to Celery." That would worsen UX for cheap or interactive
payloads and would add queue latency where none is needed.

### Primary classification approach

Use this decision order for this codebase:

1. Keep a payload synchronous in Django if it is needed immediately for page
   render or interaction and usually completes cheaply from already-materialized
   tables.
2. Add caching before adding workers if the payload is deterministic and reused
   often across the same filter scope.
3. Use async Celery builds only when the payload is heavy enough that request
   latency becomes unacceptable, or when the output is a reusable artifact.
4. Persist generated output only when the payload is expensive enough to justify
   reuse across requests, or when the output is a downloadable file the user may
   fetch later.
5. Precompute or materialize only when the result is reused broadly across many
   requests and invalidates on import boundaries rather than on every ad hoc
   filter combination.

### Decision criteria

Classify each payload against these engineering criteria:

- latency tolerance: must the user see it inline in one page load?
- generation cost: CPU, DB, memory, serialization time
- frequency: how often is the same payload scope requested?
- size: small JSON object vs large JSON matrix vs downloadable file
- determinism: is it purely derived from canonical state + filter state?
- cacheability: can a stable cache key safely represent it?
- reuse: is the output likely to be reused by many requests?
- concurrency pressure: does it harm web responsiveness under concurrent access?
- artifact value: does it produce a file or reusable persisted object?
- worker overhead: would enqueue + broker + status polling cost more than inline
  execution?

### Concrete recommendations for this codebase

#### Graph / visualization payloads

Not all graph payloads should become worker jobs.

Primary recommendation:

- Keep most interactive graph payload generation synchronous, but move it out of
  views into shared payload services.
- Cache deterministic graph payloads in Redis when they are reused often.
- Reserve Celery only for heavy, reusable graph builds that exceed acceptable
  request latency after query optimization and caching.

Reasoning:

- interactive stats pages need low latency; adding queue round-trips to every
  filter change would make the app feel worse
- many current graph payloads are derived from summary bundles that already come
  from canonical rollup tables, so worker overhead may exceed compute cost
- the biggest architectural problem is not only "payloads are synchronous"; it
  is that payload creation is tightly coupled to views and invalidation is not
  modeled cleanly

Recommended graph classification:

- `synchronous + cached`:
  common overview payloads, browse payloads, taxonomy gutter payloads, ranked
  chart payloads, and most inspect payloads when they are derived from existing
  summary tables and complete within a modest request budget
- `async + persisted`:
  any future graph payload that is expensive, highly reusable, and not required
  for the first HTML response, such as large pairwise matrices or derived
  comparison bundles that regularly breach the latency budget
- `precomputed/materialized on invalidation`:
  only highly reused derived datasets whose natural invalidation point is "new
  canonical snapshot imported", not arbitrary user filter changes

#### Download payloads

Not all download payloads should become worker jobs either.

Primary recommendation:

- Keep small and medium tabular exports synchronous and streamed from Django.
- Move only large, slow, or artifact-like downloads to Celery-backed build jobs.
- Persist async download outputs as files or artifact records, not as giant JSON
  blobs in cache.

Reasoning:

- current table TSV downloads are a good example of work that often belongs in
  the web app: deterministic, straightforward, and user-triggered
- worker overhead would be worse than inline generation for small exports
- the real async use case is large exports that users can wait for, retry, and
  download later

Recommended download classification:

- `synchronous in Django`:
  list page TSVs, stats TSVs, and other exports that stream quickly and do not
  need artifact retention
- `async + persisted artifact`:
  large cross-scope exports, zipped multi-file downloads, or exports that would
  otherwise hold a web worker for too long
- `cached read only`:
  rarely useful for downloads unless repeated identical requests are common; for
  downloads, persisted artifacts are usually a better fit than Redis-only cache

### Explicit answers

Should all graph payloads become worker jobs?

- No. Most should become shared service calls plus caching, not Celery tasks.

Should all download payloads become worker jobs?

- No. Small and medium streamed exports should remain synchronous.

Are there payloads that should remain synchronous because worker overhead would
be worse than inline generation?

- Yes. Most current stats page payloads and current TSV table exports are in
  that category unless profiling proves otherwise.

Are there payloads that should become cached reads instead of worker tasks?

- Yes. Deterministic graph payloads keyed by filter scope and catalog version
  are strong Redis-cache candidates.

Are there payloads that should become background builds only when invalidated?

- Yes. Expensive reusable graph bundles or heavy export artifacts tied to a
  canonical snapshot should build on demand and rebuild only after the relevant
  snapshot changes.

### Recommended decision thresholds

Use these practical thresholds for the first-stage refactor:

- stay synchronous if typical generation is sub-second and request-path impact is
  acceptable
- prefer caching before Celery when a deterministic payload is repeatedly
  requested and generation cost is moderate
- use async Celery when the payload regularly crosses a multi-second latency
  threshold, risks web contention, or creates a reusable artifact
- precompute only when the payload is broadly reused and invalidates naturally
  on import completion

## 4. Target Architecture Overview

### Main services

- `web`: Django app for HTTP, page rendering, status endpoints, lightweight
  payload reads, synchronous cheap exports, and task enqueueing
- `postgres`: system of record for domain data, import job records, and durable
  async build metadata
- `redis`: Celery broker, result/status cache, and shared payload cache
- `celery-import-worker`: import orchestration and canonical sync execution
- `celery-payload-worker`: async graph build tasks and async download build tasks
  for the subset of payloads that deserve it
- `migrate`: schema gate before app start

Optional later:

- `celery-beat`: required once import tasks go through Celery — a watchdog
  periodic task must detect RUNNING batches with stale heartbeats and reset
  them to PENDING (see Phase 3 risks in the implementation plan); also needed
  later for artifact expiry and rebuild backfills
- `flower`: Celery task monitoring UI served inside the Django admin zone; run
  Flower internally in Compose with no exposed host port, then proxy it through
  a `@staff_member_required` Django view registered at `/admin/flower/` — staff
  get task visibility through the existing Django auth without a separate login
  or exposed port

### Responsibilities by service

#### Django web

- parse and validate requests
- read domain data and cheap synchronous payloads
- call shared payload services for inline payload generation
- enqueue import jobs and heavy payload/download jobs
- expose job/build status endpoints
- serve ready persisted artifacts or signed download references

#### Import worker

- execute import orchestration
- update `ImportBatch` state
- run canonical sync
- bump catalog version or snapshot marker on success
- trigger targeted invalidation or follow-up materialization tasks only when
  justified

#### Payload worker

- build only classified heavy graph payloads
- build async download artifacts
- persist build status and output references
- avoid web-tier involvement in long-running payload work

### Role of Redis

- Celery broker for fast enqueue and low-latency handoff
- fast shared cache for deterministic graph payloads, shared across all web
  workers (replacing the current per-process locmem cache); switching is a
  settings change only — `queries.py` and `taxonomy_gutter.py` already use
  Django's cache API and require no code changes
- requires `django-redis` as the Django `CACHES` backend adapter
- optional short-lived status/result cache, with durable truth stored in
  PostgreSQL for user-visible jobs

Use separate Redis logical databases for broker and cache:

- `redis://redis:6379/0` — Celery broker; configure with AOF persistence so
  queued tasks survive a Redis restart
- `redis://redis:6379/1` — Django cache; use `maxmemory-policy volatile-lru`
  so Redis can evict stale cache entries under memory pressure without touching
  broker queue data

Mixing both into one database means a single eviction policy must serve both
concerns, and a cache flood can silently drop pending tasks.

### Role of Celery

- replace DB polling with a brokered task queue
- provide persistent worker pools instead of ad hoc spawned workers
- separate workload classes by queue and worker service
- handle retries and basic failure isolation for imports and heavy payload work

### Role of Django after the refactor

Django remains the control plane and read API. It should still own request
validation, permissions, response formatting, and cheap data reads. It should no
longer be the default place for long-running import orchestration or heavy
artifact generation.

### What belongs where

#### Web

- request parsing and filter normalization
- synchronous cheap payload generation through shared services
- cache lookups
- status polling endpoints
- artifact download handoff

#### Shared application/service code

- payload builders
- cache-key generation
- payload classification policy
- build invalidation rules
- import orchestration services

#### Import workers

- import task wrappers around existing import service code
- durable state updates
- optional post-import invalidation/materialization triggers

#### Payload workers

- heavy reusable graph builds
- heavy persisted download builds

### Should graph and download payloads share a worker pool?

They should use distinct queues even if they initially share the same image and
some implementation modules.

Reason:

- graph builds and download artifacts have different latency goals, memory
  profiles, and retry behavior
- distinct queues make later scaling and concurrency tuning much simpler

### Request flow

1. Browser request reaches Django.
2. Django parses filters and determines payload classification.
3. If payload is synchronous:
   - check Redis cache
   - compute via shared service if needed
   - return immediately
4. If payload is async:
   - look for ready persisted build
   - if missing/stale, create build record and enqueue Celery task
   - return status envelope for frontend polling

### Import flow

1. User requests import.
2. Django validates request and creates/updates `ImportBatch`.
3. Django enqueues Celery import task with batch ID.
4. Import worker processes the batch and updates status as it runs.
5. On success, canonical sync completes and catalog version is advanced.
6. Relevant caches/builds are invalidated or scheduled for rebuild if needed.

### Graph payload flow

1. Django computes cache key from filter state + catalog version.
2. If inline-classified:
   - return cached payload or compute synchronously
3. If async-classified:
   - check durable build record
   - enqueue build only when needed
   - frontend polls until ready

### Download payload flow

1. Django classifies the requested export.
2. If inline-classified:
   - stream directly from Django
3. If artifact-classified:
   - create `DownloadBuild`
   - enqueue Celery task
   - return status page or polling token
4. Worker builds artifact, stores location/metadata, marks build ready.

## 5. Queue And Worker Model

### Recommended MVP queues

- `imports`
- `payload_graph`
- `downloads`
- `pipeline` later, not now

Declare queue routing in `CELERY_TASK_ROUTES` in `config/settings.py` rather
than hardcoding queue names in task call sites. This keeps routing centralized
and allows reassigning tasks to different queues without touching task code.

### Why separate queues are useful

- imports are long-running and DB-heavy; they should not block payload work
- graph builds may be CPU-heavy but usually smaller and more parallelizable
- downloads may be I/O-heavy and can involve large artifact writes
- queue separation gives predictable latency and prevents one workload from
  starving another

### Worker pool recommendation

For the MVP:

- one `celery-import-worker` service bound to `imports`
- one `celery-payload-worker` service bound to both `payload_graph` and
  `downloads`, or two services from the same image if you want cleaner
  concurrency control from day one

Recommended direction:

- keep graph and download queues distinct immediately
- it is acceptable for the first Compose version to run them from the same image
- prefer separate services once payload traffic becomes non-trivial

### Concurrency guidance

- import workers: low concurrency (1–2), because imports are DB-heavy and can
  contend on canonical writes; use the default prefork pool
- graph payload workers: moderate concurrency; prefork is appropriate since
  payload building is CPU and DB bound; `--autoscale=<max>,<min>` in the
  Compose command allows elastic scaling without configuration changes
- download workers: lower, controlled concurrency with a hard ceiling, because
  artifact generation can be memory or disk heavy; prefork is safest

Use the prefork pool (Celery default) for all worker services in this codebase.
Gevent/eventlet pools suit high-volume I/O-bound work and require async-safe
ORM usage; they are not appropriate here.

Set `CELERY_WORKER_PREFETCH_MULTIPLIER = 1` globally, and override per worker
via `--prefetch-multiplier 1` in the import worker command. The default of 4
means each worker process reserves 4 tasks from the queue even when it can only
run one at a time — for long-running import tasks this silently starves other
workers waiting for a slot.

### How this reduces overhead

Compared to the current model:

- broker enqueue is lower-latency than DB polling
- persistent Celery worker pools remove repeated process-spawn costs
- separate queues avoid import work interfering with graph/download work
- web no longer needs to hold heavy tasks in process when async is justified

### Which payload types should not use queues

- cheap chart payloads used directly in interactive page renders
- small and medium streamed table downloads
- lightweight request-scoped transformations with little reuse value

## 6. Service Boundary Recommendations

### What should remain in Django/web

- HTTP routing, forms, validation, permissions
- filter parsing and request shaping
- synchronous cheap payload reads/builds
- current-style small TSV streaming endpoints
- status endpoints and build lookup logic

### What should move into shared service code

- graph payload builders currently embedded in stats views
- download payload assembly logic currently coupled to views
- cache-key generation keyed by filter scope + catalog version
- classification policy deciding sync vs cached vs async vs artifact

### What should move into Celery tasks

- import execution entrypoints
- heavy graph builds that have been explicitly classified as async
- heavy download artifact generation
- optional post-import invalidation/materialization orchestration

### What should stay synchronous

- cheap graph payloads needed for normal interactive browsing
- lightweight export streams
- request validation and result lookup

### Should graph payload generation be fully detached from views?

Yes, as shared application/service code. No, not every graph payload should be
forced into a worker. The view should decide policy and rendering, not own the
builder internals.

### Should download payload generation be fully detached from views?

Yes. Views should decide whether a download is inline or async, then call a
service layer. For inline downloads the web response still streams the result,
but the generation logic should not stay buried in view classes.

### Should imports become orchestration tasks plus internal service calls?

Yes. The Celery task should become a thin orchestration shell that calls the
existing import service code. That keeps business logic testable and avoids
turning Celery tasks into monoliths.

## 7. Docker Compose Implications

### Recommended Compose evolution

Add:

- `redis`
- `celery-import-worker`
- `celery-payload-worker` or separate `celery-graph-worker` and
  `celery-download-worker`
- `flower` (no host port exposed; accessed through Django admin proxy)

Keep:

- `web`
- `postgres`
- `migrate`

Remove or simplify:

- replace the current `worker` service running `manage.py import_worker`

### Flower in the Django admin zone

Flower should not be exposed on a host port. Instead:

1. Run the `flower` Compose service with no `ports:` entry so it is only
   reachable inside the Docker network:
   ```yaml
   flower:
     image: homorepeat-web:dev
     command: celery -A config.celery flower --port=5555 --url_prefix=admin/flower
     # no ports: — internal only
   ```
   The `--url_prefix=admin/flower` flag tells Flower to prefix all its internal
   asset and API URLs with that path so they resolve correctly through the proxy.

2. Add a proxy view in Django protected by `@staff_member_required`:
   ```python
   # apps/imports/views/flower.py
   import httpx
   from django.contrib.admin.views.decorators import staff_member_required
   from django.http import HttpResponse

   FLOWER_INTERNAL_URL = "http://flower:5555"

   @staff_member_required
   def flower_proxy(request, path=""):
       url = f"{FLOWER_INTERNAL_URL}/admin/flower/{path}"
       if request.META.get("QUERY_STRING"):
           url += f"?{request.META['QUERY_STRING']}"
       resp = httpx.request(
           method=request.method,
           url=url,
           content=request.body,
           headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
           follow_redirects=False,
       )
       return HttpResponse(
           resp.content,
           status=resp.status_code,
           content_type=resp.headers.get("content-type", "text/html"),
       )
   ```

3. Register the proxy in `config/urls.py` before the `admin/` catch-all:
   ```python
   path("admin/flower/", flower_proxy),
   path("admin/flower/<path:path>", flower_proxy),
   path("admin/", admin.site.urls),
   ```

Staff users visit `/admin/flower/` in the browser and are gated by Django's
existing session auth. No extra auth layer, no exposed port.

**Known limitation**: Flower uses WebSocket for real-time task-stream updates.
The Django HTTP proxy cannot upgrade connections to WebSocket. Flower detects
this and falls back to periodic HTTP polling; the dashboard still shows task
state, queue depth, and runtimes, but without a live stream. This is acceptable
for an admin monitoring UI. If full real-time streaming is needed later, an
nginx `proxy_pass` with `proxy_http_version 1.1` and the appropriate Upgrade
headers can replace the Django proxy.

**Dependency note**: the proxy view above uses `httpx`. Add it to requirements
if it is not already present. `requests` is an equally valid substitute for a
simple synchronous proxy.

### Image recommendation

- keep one base application image for `web`, `migrate`, and Celery workers
- use separate Compose services with different commands and queue bindings

This is simpler than maintaining separate Dockerfiles now, while still mapping
cleanly to later Kubernetes Deployments.

### Web server: switch runserver to Gunicorn

The current Compose `web` service runs `python manage.py runserver`, which is
single-process. The entire point of switching from per-process locmem to shared
Redis cache is to benefit multiple web workers — which requires a real WSGI
server. Replace `manage.py runserver` in Compose with:

```
gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 4
```

Without this, the cache backend change has no effect on cache hit rates in
development or production-like Compose runs.

### Should graph and download workers share an image?

Yes. Share the image; separate the services and queues.

### Environment and config implications

Add configuration for:

- Redis URL
- Celery broker/result settings
- queue names
- worker concurrency per service
- payload cache TTLs
- artifact storage root for async downloads
- build expiry/cleanup settings

### Broker connectivity implications

- web and workers both need Redis connectivity
- Redis becomes a critical dependency for enqueue and cache
- durable user-visible state should still be mirrored in PostgreSQL, not left
  only in Redis

## 8. Future Compatibility

This MVP remains compatible with later growth because it introduces the right
boundaries without overcommitting:

- a future `pipeline` queue can be added without disturbing imports or payloads
- resource-specific workers can be introduced by splitting queue bindings
- Redis/Celery queue semantics map cleanly onto Kubernetes Deployments and
  HorizontalPodAutoscaler patterns
- the shared service layer keeps business logic portable across web, worker, and
  later orchestration entrypoints
- catalog-version-based cache keys make later distributed invalidation easier

## 9. Recommended Deliverables

Recommended docs/files for this refactor:

- `docs/implementation/redis_celery_refactor/overview.md`
- `docs/implementation/redis_celery_refactor/implementation_plan.md`
- `docs/architecture.md`
  Update after the refactor lands so the architecture doc reflects Redis,
  Celery, queue boundaries, and payload classification.
- `docs/operations.md`
  Add worker start-up, queue ownership, retry expectations, and artifact cleanup
  notes once implementation starts.

Avoid creating more design docs than that for the MVP. The plan should stay in
one place and the main architecture/operations docs should be updated after the
implementation proves out.

## Recommended Target Architecture Summary

Primary recommendation:

- keep Django as the control plane and read layer
- add Redis + Celery as the async substrate
- move imports to Celery first
- detach graph/download generation from views into shared services
- keep most graph payloads synchronous plus cached
- keep small/medium downloads synchronous plus streamed
- use separate `payload_graph` and `downloads` queues for the subset of heavy
  payload work that genuinely benefits from async execution

This is the simplest architecture that fixes the current boundaries without
blindly turning every payload into a background job.
