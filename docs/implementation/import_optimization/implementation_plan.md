# Import Pipeline Optimisation: Implementation Plan

## Tier 1 — PostgreSQL `work_mem` in compose.yaml

### File

`compose.yaml`

### Change

Added to `services.postgres.command`, consistent with the existing env-var
pattern for all other PG tunables:

```yaml
- -c
- work_mem=${POSTGRES_WORK_MEM:-64MB}
- -c
- maintenance_work_mem=${POSTGRES_MAINTENANCE_WORK_MEM:-256MB}
```

### Why

Default `work_mem` is 4 MB. The summary-rebuild queries do massive GROUP BY
aggregations; every hash-aggregate node spills to disk at 4 MB. At 64 MB,
small-to-medium imports complete in memory. The per-query `SET LOCAL` in Tier 2a
provides a higher limit for the specific heavy queries.

`maintenance_work_mem` (256 MB) improves VACUUM and `CREATE INDEX` performance
for the large canonical tables; it does not affect query execution.

---

## Tier 2a — `SET LOCAL work_mem` inside summary rebuild queries

### Files

- `apps/browser/stats/codon_rollups.py`
- `apps/browser/stats/codon_length_rollups.py`

### Change

In each `_rebuild_canonical_codon_composition_*_postgresql()` function, the
first statement inside `with connection.cursor() as cursor:` is now:

```python
cursor.execute("SET LOCAL work_mem = '512MB'")
```

### Why

`SET LOCAL` scopes the change to the current transaction and resets
automatically at transaction end. Whether these functions are called from inside
the outer `sync_canonical_catalog_for_run()` (now a separate transaction) or
standalone from the backfill management commands, they always run in their own
`transaction.atomic()` — so `SET LOCAL` is safe in both contexts.

512 MB allows the multi-CTE aggregations to run entirely in memory for large
imports, eliminating disk spill.

---

## Tier 2b + 3 — ANALYZE on committed rows; break monolithic transaction

### File

`apps/browser/catalog/sync.py`

### Change

`sync_canonical_catalog_for_run()` restructured from one `transaction.atomic()`
into three sequential transactions with ANALYZE between the first and second:

```
Transaction 1 (atomic):
    prune stale genomes/sequences/proteins
    upsert canonical genomes, sequences, proteins
    delete + insert canonical repeat calls      (now via COPY)
    insert canonical repeat call codon usages  (now via COPY)

→ ANALYZE browser_canonicalrepeatcall
  ANALYZE browser_canonicalrepeatcallcodonusage
  ANALYZE browser_taxonclosure

Transaction 2 (each rebuild has its own transaction.atomic() internally):
    rebuild_canonical_codon_composition_summaries()
    rebuild_canonical_codon_composition_length_summaries()

Transaction 3 (atomic):
    _refresh_canonical_protein_repeat_call_counts()
    _record_pipeline_run_canonical_sync()          ← stamps canonical_synced_at
```

`connection` is imported from `django.db` (alongside the existing `transaction`
import) to allow the vendor check for the ANALYZE block.

### Why

**ANALYZE:** Running it outside transaction 1 (on committed data) gives the
planner access to the actual committed row counts and column statistics before
the expensive summary-rebuild queries execute. Previously ANALYZE ran only after
the whole function returned, so the summary rebuilds always used stale stats.

**Transaction split:** Canonical table row-level locks are released after
transaction 1 completes (typically ~10–20 min) rather than being held for the
full 47+ min. Web queries against the canonical layer are unblocked much sooner.
WAL is checkpointed between transactions. If transaction 2 fails, transaction 1
is already committed and a retry only re-runs the summary rebuilds.

**Crash-recovery invariant:** `canonical_synced_at` is stamped only in
transaction 3. A crash between transactions 1 and 3 leaves `canonical_synced_at`
unset, so `backfill_canonical_catalog_for_run()` will detect the run as not
fully synced and retry the sync from scratch. This is acceptable.

---

## Tier 4a — Shared COPY utility: `apps/browser/db/copy.py`

### Files

- `apps/browser/db/__init__.py` (new, empty)
- `apps/browser/db/copy.py` (new)

### Change

A new module exposes `copy_rows_to_model(model, field_names, rows)` and
`analyze_models(models)`, implementing the same PostgreSQL `COPY FROM STDIN`
approach as `apps/imports/services/import_run/copy.py` but without the
import-phase batch/reporter progress tracking (which is specific to the imports
pipeline).

`apps/imports` already depends on `apps.browser` (see `api.py` importing from
`apps.browser.catalog`), so the dependency direction is clean.

The imports app's `copy.py` is left unchanged; it has its own progress-reporting
wrapper suitable for the raw-layer ingestion pipeline.

### Why

`apps/browser/catalog/sync.py` cannot import from `apps/imports` (that would
reverse the dependency). Creating `apps/browser/db/copy.py` gives the catalog
sync access to the same COPY mechanism without coupling the two apps in the
wrong direction.

---

## Tier 4b — COPY for canonical repeat-call and codon-usage inserts

### File

`apps/browser/catalog/sync.py`

### Change: `_replace_canonical_repeat_calls()`

Replaced the `bulk_create` loop with a call to `copy_rows_to_model()`. A
`_rows()` generator streams directly from `raw_repeat_calls.iterator()`,
yielding one tuple per repeat call. The full column list includes `created_at`
and `updated_at` (from `TimestampedModel`) set to `last_seen_at`.

If `copy_rows_to_model()` returns `None` (non-PostgreSQL backend, e.g. SQLite
in tests), the function falls through to the original `bulk_create` loop.

### Change: `_replace_canonical_repeat_call_codon_usages()`

On PostgreSQL, replaced the per-batch Python loop with a single server-side
`INSERT … SELECT` that joins the raw codon-usage rows to the canonical repeat
calls via the `latest_repeat_call_id` FK index — no data moves to Python at all:

```sql
INSERT INTO browser_canonicalrepeatcallcodonusage
    (repeat_call_id, amino_acid, codon, codon_count, codon_fraction, created_at, updated_at)
SELECT
    crc.id,
    rccu.amino_acid,
    rccu.codon,
    rccu.codon_count,
    rccu.codon_fraction,
    NOW(),
    NOW()
FROM browser_repeatcallcodonusage rccu
JOIN browser_canonicalrepeatcall crc ON crc.latest_repeat_call_id = rccu.repeat_call_id
WHERE crc.latest_pipeline_run_id = %s
```

The original per-batch lookup + `bulk_create` path is retained as the fallback
for non-PostgreSQL backends.

### Why

The previous approach (and the first COPY attempt) both required a Python-side
mapping of `raw_repeat_call_id → canonical_pk`. For a 90 GB run this mapping
would be hundreds of MB to ~1 GB in RAM. The server-side INSERT uses zero Python
memory — PostgreSQL streams the join output directly into the insert. It also
eliminates the O(N/1000) per-batch DB queries from the original implementation.

---

## Verification

### Check for temp-file spill (before/after)

```sql
SELECT
    pid,
    now() - query_start AS duration,
    state,
    wait_event_type,
    wait_event,
    left(query, 120) AS query
FROM pg_stat_activity
WHERE state != 'idle'
ORDER BY duration DESC;
```

Before: `wait_event IN ('BufFileRead', 'BufFileWrite')` during summary rebuilds
indicates disk spill.  After Tier 2a: these should disappear from the rebuild
queries.

### Confirm `work_mem` settings

```sql
-- In any session:
SHOW work_mem;                      -- should be 64MB (Tier 1)

-- Inside the import worker session during a summary rebuild:
SELECT current_setting('work_mem'); -- should be 512MB (Tier 2a)
```

### Timing

Wrap the two rebuild calls in `time.monotonic()` measurements. Expected:
- Before: 20–40 min each
- After Tiers 1–2: 1–5 min each (hardware-dependent)

### Row-count integrity check after import

```sql
SELECT
    (SELECT COUNT(*) FROM browser_canonicalrepeatcallcodonusage cu
     JOIN browser_canonicalrepeatcall rc ON rc.id = cu.repeat_call_id
     WHERE rc.latest_pipeline_run_id = <run_pk>) AS canonical_cu_count,
    (SELECT COUNT(*) FROM browser_repeatcallcodonusage cu
     JOIN browser_repeatcall rc ON rc.id = cu.repeat_call_id
     WHERE rc.pipeline_run_id = <run_pk>) AS raw_cu_count;
-- canonical_cu_count should equal raw_cu_count
```
