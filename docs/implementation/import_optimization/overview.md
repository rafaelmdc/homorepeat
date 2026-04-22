# Import Pipeline Optimisation: Overview

## Problem Statement

A 90 GB pipeline import's `syncing_canonical_catalog` phase ran for 47+ minutes.
The phase serialised all work inside one `transaction.atomic()` in
`apps/browser/catalog/sync.py :: sync_canonical_catalog_for_run()`. The two
summary-rebuild steps near the end of that transaction — each issuing a
multi-CTE `INSERT … SELECT` across three large tables joined against the
taxonomy closure — were the primary bottleneck.

## Root Causes

### 1. PostgreSQL sort/hash-aggregate memory starvation (primary)

The summary rebuilds execute queries of this shape:

```sql
WITH call_scope AS MATERIALIZED (
    SELECT ... FROM browser_canonicalrepeatcall       -- potentially millions of rows
    INNER JOIN browser_taxonclosure ...               -- fans out ×6 (one per allowed rank)
    INNER JOIN browser_taxon ...
    WHERE display_taxon.rank IN ('phylum','class','order','family','genus','species')
),
residue_species_calls AS MATERIALIZED (
    ... GROUP BY repeat_residue, display_rank, display_taxon_id, species_taxon_id
),
...
INSERT INTO <summary_table> SELECT ... GROUP BY (7–8 columns)
```

The `call_scope` CTE materialises `rows(CanonicalRepeatCall) × 6`. All
subsequent CTEs produce further aggregations over that set.

PostgreSQL 16 default `work_mem` is **4 MB**. Every hash-aggregate and hash-join
node spills immediately to temporary files. A query that should run in memory
takes 10–50× longer because each spill pass reads and writes the full
intermediate result through the filesystem. The PostgreSQL `wait_event`
`BufFileRead` / `BufFileWrite` confirms this during an active import.

### 2. Stale query-planner statistics for the summary rebuilds (primary)

`_analyze_models()` was called in `api.py` **after**
`sync_canonical_catalog_for_run()` returned. The summary rebuilds therefore
ran with statistics from before the import — often from empty or much-smaller
canonical tables — causing the planner to mis-estimate intermediate row counts
and choose poor join strategies.

### 3. Monolithic transaction (compounding)

All 11 steps (prune, upsert genomes/sequences/proteins, delete+insert repeat
calls, insert codon usages, rebuild summaries, refresh protein counts, stamp
run) ran inside one `transaction.atomic()`. Effects:

- Canonical table row-level locks held for the full 47+ minutes, blocking
  concurrent web queries against the canonical layer.
- WAL not checkpointed between phases; very large WAL footprint in memory.
- A failure at step 8 after 40 minutes rolled back everything.

### 4. `bulk_create` for large repeat-call and codon-usage inserts (compounding)

The catalog sync used `bulk_create` in batches of 1 000 rows, which generates
individual multi-row `INSERT` statements. The imports app already had a
PostgreSQL `COPY FROM STDIN` utility (`apps/imports/services/import_run/copy.py`)
that is 3–10× faster for large volumes, but it was not accessible from the
browser app.

Additionally, each codon-usage batch issued its own DB query to resolve the
canonical repeat-call PK mapping, resulting in O(N/1000) round-trips.

## Impact Sizing (estimated)

| Step | Estimated share of 47 min |
|------|---------------------------|
| `rebuild_canonical_codon_composition_length_summaries` | 55–70 % |
| `rebuild_canonical_codon_composition_summaries` | 15–25 % |
| repeat-call and codon-usage inserts | 5–15 % |
| prune + upsert genomes/sequences/proteins | < 5 % |

## Implemented Fixes

| Tier | Change | Mechanism |
|------|--------|-----------|
| 1 | `work_mem=64MB`, `maintenance_work_mem=256MB` in `compose.yaml` | Raises the floor for all sessions |
| 2a | `SET LOCAL work_mem = '512MB'` inside each PG summary rebuild | Per-query scoped memory boost; avoids hash-aggregate spill |
| 2b + 3 | Break monolithic transaction; ANALYZE committed rows before rebuilds | Fresh planner stats; earlier lock release; smaller WAL footprint |
| 4 | `COPY FROM STDIN` for repeat-call and codon-usage inserts; one-shot PK lookup for codon usages | Eliminates ORM INSERT overhead; removes O(N/1000) lookup queries |

## File Map

| File | Change |
|------|--------|
| `compose.yaml` | Tier 1: `work_mem` and `maintenance_work_mem` |
| `apps/browser/stats/codon_rollups.py` | Tier 2a: `SET LOCAL work_mem` |
| `apps/browser/stats/codon_length_rollups.py` | Tier 2a: `SET LOCAL work_mem` |
| `apps/browser/catalog/sync.py` | Tiers 2b + 3 + 4b: transaction split, ANALYZE, COPY inserts |
| `apps/browser/db/copy.py` (new) | Tier 4a: shared COPY utility for the browser app |
| `apps/browser/db/__init__.py` (new) | Package marker |

## Caveats

- **`work_mem` is per sort/hash node per query session.** The global `64MB`
  default is safe on most hosts. The `SET LOCAL 512MB` is scoped to the import
  worker's transaction and resets automatically; it does not affect web sessions.
- **Transaction split and crash recovery.** `canonical_synced_at` on `PipelineRun`
  is stamped only after all three transactions succeed. If the worker crashes
  between transaction 1 and 3, the canonical data is committed but summaries may
  be stale; `backfill_canonical_catalog_for_run()` will re-run the sync on the
  next attempt.
- **COPY bypasses Django signals and `auto_now`/`auto_now_add`.** `created_at`
  and `updated_at` are supplied explicitly in the COPY rows. No signal receivers
  are registered on these models.
- **Server-side INSERT for codon usages.** The PostgreSQL path uses
  `INSERT … SELECT` with no data movement to Python. The per-batch
  `bulk_create` fallback is retained for non-PostgreSQL backends (tests).
