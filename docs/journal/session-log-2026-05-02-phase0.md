# Session Log — Phase 0 Preflight

**Date:** 2026-05-02

## Objective

Complete Phase 0 of the async deletion implementation plan: confirm model graph, index coverage, cache and artifact paths, and existing deletion code before writing any new application code.

---

## Slice 0.1: Model Graph — Table Classification

Every table relevant to `PipelineRun` deletion has been classified as `delete`, `repair/rebuild`, `retain`, or `never touch`.

### Raw run-owned tables — DELETE (in this dependency order)

| # | Table | DB table | pipeline_run FK | on_delete | Notes |
|---|-------|----------|-----------------|-----------|-------|
| 1 | `RepeatCallCodonUsage` | `browser_repeatcallcodonusage` | indirect via `RepeatCall` | CASCADE | No direct FK; join through `RepeatCall.pipeline_run_id` |
| 2 | `RepeatCallContext` | `browser_repeatcallcontext` | direct | CASCADE | Also has `OneToOneField` to `RepeatCall` |
| 3 | `RepeatCall` | `browser_repeatcall` | direct | CASCADE | taxon → PROTECT (don't delete Taxon) |
| 4 | `DownloadManifestEntry` | `browser_downloadmanifestentry` | direct | CASCADE | batch → AcquisitionBatch, **PROTECT**, non-nullable — must delete before AcquisitionBatch |
| 5 | `NormalizationWarning` | `browser_normalizationwarning` | direct | CASCADE | batch → AcquisitionBatch, **PROTECT**, non-nullable — must delete before AcquisitionBatch |
| 6 | `AccessionStatus` | `browser_accessionstatus` | direct | CASCADE | batch → AcquisitionBatch, **PROTECT**, nullable |
| 7 | `AccessionCallCount` | `browser_accessioncallcount` | direct | CASCADE | batch → AcquisitionBatch, **PROTECT**, nullable |
| 8 | `Protein` | `browser_protein` | direct | CASCADE | genome/sequence → CASCADE; taxon → PROTECT |
| 9 | `Sequence` | `browser_sequence` | direct | CASCADE | genome → CASCADE; taxon → PROTECT |
| 10 | `Genome` | `browser_genome` | direct | CASCADE | batch → AcquisitionBatch, **PROTECT**, nullable — must delete before AcquisitionBatch |
| 11 | `RunParameter` | `browser_runparameter` | direct | CASCADE | No blocking constraints |
| 12 | `AcquisitionBatch` | `browser_acquisitionbatch` | direct | CASCADE | Must be last: all PROTECT references (rows 4–7, 10) must be gone first |

**Dependency constraint summary:**
- `DownloadManifestEntry`, `NormalizationWarning` have a non-nullable PROTECT FK to `AcquisitionBatch` → must be deleted in steps 4–5 before step 12.
- `Genome` has a nullable PROTECT FK to `AcquisitionBatch` → must be deleted in step 10 before step 12.
- `AccessionStatus`, `AccessionCallCount` have nullable PROTECT FKs to `AcquisitionBatch` → deleted in steps 6–7.
- `RepeatCallCodonUsage` has no direct `pipeline_run_id` — must join through `RepeatCall` for chunked delete.

### Canonical tables — REPAIR then possibly DELETE

| Table | Relationship to run | Action |
|-------|---------------------|--------|
| `CanonicalGenome` | `latest_pipeline_run` → **PROTECT**, non-nullable | Promote predecessor active run or delete row |
| `CanonicalSequence` | `latest_pipeline_run` → **PROTECT**, non-nullable | Promote predecessor or delete (cascades from CanonicalGenome) |
| `CanonicalProtein` | `latest_pipeline_run` → **PROTECT**, non-nullable | Promote predecessor or delete (cascades from CanonicalGenome/CanonicalSequence) |
| `CanonicalRepeatCall` | `latest_pipeline_run` → **PROTECT**, non-nullable; `latest_repeat_call` → **SET_NULL** | Promote predecessor or delete (cascades from parents); `latest_repeat_call` auto-NULLs on raw delete |
| `CanonicalRepeatCallCodonUsage` | `repeat_call` → `CanonicalRepeatCall`, CASCADE | Handled by cascade when CanonicalRepeatCall deleted |

**Critical:** The four `PROTECT` constraints on canonical tables mean `PipelineRun` **cannot be physically deleted** while any canonical row still references it. The lifecycle tombstone approach (keep the `PipelineRun` row, set `lifecycle_status=deleted`) resolves this — we never physically delete `PipelineRun`.

### Canonical rollup tables — REBUILD

| Table | Relationship | Action |
|-------|-------------|--------|
| `CanonicalCodonCompositionSummary` | No direct run FK | Rebuild via existing rollup function after canonical repair |
| `CanonicalCodonCompositionLengthSummary` | No direct run FK | Rebuild via existing rollup function after canonical repair |

### Import/upload audit tables — RETAIN

| Table | Relationship | Why retained |
|-------|-------------|-------------|
| `PipelineRun` | target | Kept as tombstone with `lifecycle_status=deleted` |
| `ImportBatch` | `pipeline_run` → PipelineRun, **SET_NULL** | Audit trail; FK becomes NULL after deletion |
| `UploadedRun` | linked by `run_id` CharField only; `import_batch` → SET_NULL | No FK to PipelineRun; retained as upload audit |
| `UploadedRunChunk` | `uploaded_run` → UploadedRun, CASCADE | Follows UploadedRun |

### Shared/global reference tables — NEVER TOUCH

| Table | Reason |
|-------|--------|
| `Taxon` | Global reference data; run rows reference it via PROTECT but we never delete Taxon |
| `TaxonClosure` | Same; global |

---

## Slice 0.2: Index Coverage

### Raw table indexes for chunked deletion

Every large raw table has `pipeline_run_id` as the leading column of at least one composite index. PostgreSQL can use a composite index for a query filtering only on the leading column.

| Table | Index covering pipeline_run_id | Status |
|-------|-------------------------------|--------|
| `Genome` | `brw_genome_run_acc_idx` `(pipeline_run, accession)` | ✓ covered |
| `Sequence` | `brw_seq_run_asm_name_id` `(pipeline_run, assembly_accession, sequence_name, id)` | ✓ covered |
| `Protein` | `brw_prot_run_acc_name_id` `(pipeline_run, accession, protein_name, id)` | ✓ covered |
| `RepeatCall` | `brw_rc_run_acc_pn_start_id` `(pipeline_run, accession, protein_name, start, id)` | ✓ covered |
| `RepeatCallContext` | `brw_rcctx_run_prot_idx` `(pipeline_run, protein_id)` | ✓ covered |
| `DownloadManifestEntry` | `brw_dlmfest_run_batch_idx` `(pipeline_run, batch)` | ✓ covered |
| `NormalizationWarning` | `brw_normwarn_run_batch_idx` `(pipeline_run, batch)` | ✓ covered |
| `AccessionStatus` | Unique constraint `(pipeline_run, assembly_accession)` | ✓ covered |
| `AccessionCallCount` | Unique constraint `(pipeline_run, assembly_accession, method, repeat_residue)` | ✓ covered |
| `RunParameter` | Unique constraint `(pipeline_run, method, repeat_residue, param_name)` | ✓ covered |
| `AcquisitionBatch` | Unique constraint `(pipeline_run, batch_id)` | ✓ covered |

**RepeatCallCodonUsage (indirect child):** No direct `pipeline_run_id`. The delete CTE joins through `RepeatCall`. The unique constraint on `(repeat_call, amino_acid, codon)` creates an index with `repeat_call_id` as the leading column — the join is covered. ✓

### Canonical table indexes for repair queries

| Table | Index on latest_pipeline_run_id | Status |
|-------|--------------------------------|--------|
| `CanonicalGenome` | None | **MISSING — needs migration** |
| `CanonicalSequence` | None | **MISSING — needs migration** |
| `CanonicalProtein` | None | **MISSING — needs migration** |
| `CanonicalRepeatCall` | `brw_crcall_run_tax_len_idx` `(latest_pipeline_run, taxon, length)` | ✓ covered |

**Required migration before enabling confirmed deletion:**

Add these three indexes (can be in a single migration, preferably `CONCURRENTLY` if running against live data):

```python
models.Index(fields=["latest_pipeline_run"], name="brw_cgenome_run_idx")   # on CanonicalGenome
models.Index(fields=["latest_pipeline_run"], name="brw_cseq_run_idx")      # on CanonicalSequence
models.Index(fields=["latest_pipeline_run"], name="brw_cprot_run_idx")     # on CanonicalProtein
```

These will be added as part of **Phase 1 Slice 1.1** (the lifecycle migration), so they land before any destructive phases are enabled.

---

## Slice 0.3: Cache And Artifact Paths

### CatalogVersion

- Singleton model at `apps.imports.models.CatalogVersion` (pk=1 enforced by CHECK constraint)
- Cache key: `"browser:stats:catalog_version"`, TTL = 10 seconds
- `increment()`: `UPDATE ... SET version = version + 1` + `cache.delete(key)` + re-reads
- Stats cache keys include catalog_version via `StatsFilterState.cache_key_data()` → a SHA-1 hash. Bumping catalog_version makes all existing stat cache keys unreachable without requiring per-key invalidation.
- `PayloadBuild`/`DownloadBuild` both store `catalog_version` and index `(build_type, scope_key, catalog_version)`. Old rows with a stale catalog_version become unreachable and expire naturally; no explicit cleanup needed.
- `HOMOREPEAT_BROWSER_STATS_CACHE_TTL = 60` seconds — stat caches auto-expire within 60s regardless.

**Deletion workflow calls `CatalogVersion.increment()` twice:**
1. When run is marked `deleting` (hides from stat queries immediately)
2. After canonical repair completes (refreshes canonical browsing data)

### Artifact paths

| Path | Owner | Action |
|------|-------|--------|
| `HOMOREPEAT_IMPORTS_ROOT/library/<run_id>/` | App-managed import library | **DELETE** — primary artifact target |
| `PipelineRun.publish_root` (CharField) | May overlap library root | Delete **only if** path resolves inside `HOMOREPEAT_IMPORTS_ROOT/library/<run_id>/` |
| `HOMOREPEAT_IMPORTS_ROOT/uploads/<uuid>/` | `UploadedRun.upload_root` | **NEVER DELETE** — belongs to UploadedRun, not PipelineRun |
| `HOMOREPEAT_RUNS_ROOT/<anything>` | External source data, mounted read-only | **NEVER DELETE** |
| `DownloadManifestEntry.download_path` | External download location | **NEVER DELETE** |
| `DownloadManifestEntry.rehydrated_path` | External rehydration path | **NEVER DELETE** |

Note: `UploadedRun.library_root` is a computed property `HOMOREPEAT_IMPORTS_ROOT/library/<run_id>/` — this matches the primary artifact target. The deletion worker uses `run_id` (from `PipelineRun.run_id`) to construct the path, not any stored field.

### Celery queues (current routing from settings.py)

| Task | Queue | Route |
|------|-------|-------|
| `apps.imports.tasks.extract_uploaded_run` | `uploads` | explicit |
| `apps.imports.tasks.cleanup_stale_uploaded_runs` | `uploads` | explicit |
| `apps.imports.tasks.*` | `imports` | wildcard |
| `apps.browser.tasks.expire_stale_download_builds` | `downloads` | explicit |
| `apps.browser.tasks.*` | `payload_graph` | wildcard |

**Important:** The new `apps.imports.tasks.delete_pipeline_run_job` task will match the wildcard `apps.imports.tasks.*` and go to the `imports` queue unless an **explicit route is added before the wildcard**. This is required in Phase 5 Slice 5.2:

```python
"apps.imports.tasks.delete_pipeline_run_job": {"queue": "deletions"},  # add BEFORE wildcard
"apps.imports.tasks.*": {"queue": "imports"},
```

---

## Slice 0.4: Existing Deletion Code

**Location:** `apps/imports/services/import_run/entities.py:8-15`

```python
def _delete_run_scoped_rows(pipeline_run: PipelineRun) -> None:
    pipeline_run.normalization_warnings.all().delete()
    pipeline_run.download_manifest_entries.all().delete()
    pipeline_run.accession_call_count_rows.all().delete()
    pipeline_run.accession_status_rows.all().delete()
    pipeline_run.run_parameters.all().delete()
    pipeline_run.genomes.all().delete()          # cascades Sequence, Protein, RepeatCall, RepeatCallCodonUsage, RepeatCallContext
    pipeline_run.acquisition_batches.all().delete()
```

Called from `apps/imports/services/import_run/orchestrator.py` during re-import (`replace_existing=True`). It is a synchronous ORM cascade approach — **safe only for small test fixtures, not for production large runs**.

**Do not reuse this as the production deletion path.** The new chunked Celery approach replaces it for large data. The re-import path can keep using it for small replaced runs (it is not in scope to change that).

No existing management command for deletion. No existing `apps/imports/services/deletion/` package.

---

## Findings Summary

### Confirmed implementation prerequisites

1. **Three index migrations required** before confirmed deletion can be enabled:
   - `CanonicalGenome.latest_pipeline_run` → `brw_cgenome_run_idx`
   - `CanonicalSequence.latest_pipeline_run` → `brw_cseq_run_idx`
   - `CanonicalProtein.latest_pipeline_run` → `brw_cprot_run_idx`
   These go into the **Phase 1 lifecycle migration** alongside `PipelineRun.lifecycle_status`.

2. **Celery routing must add explicit `deletions` queue** before the `apps.imports.tasks.*` wildcard in `CELERY_TASK_ROUTES`.

3. **PipelineRun is never physically deleted** — canonical PROTECT constraints block it. The tombstone lifecycle approach (`lifecycle_status=deleted`) is confirmed correct.

4. **PROTECT constraint order** for chunked raw deletion (steps 4–5 before step 12, step 10 before step 12) matches the planned dependency order in the implementation plan. No changes needed to the deletion order.

5. **RepeatCallCodonUsage indirect join is index-covered** by the unique constraint on `(repeat_call, amino_acid, codon)`.

6. **`CanonicalRepeatCall.latest_repeat_call` is SET_NULL** — auto-NULLs when raw `RepeatCall` rows are deleted; no explicit handling needed beyond canonical repair pointing it at a valid predecessor first.

7. **Upload artifacts (`uploads/<uuid>/`) must not be touched** — they are owned by `UploadedRun`, not `PipelineRun`.

8. **CatalogVersion.increment() is the only cache invalidation needed** — stats caches keyed by catalog_version version hash become unreachable automatically; no per-key deletion required.

### No blockers to starting Phase 1

All Phase 0 acceptance criteria are met:
- Delete/repair/retain/never-touch classification is complete.
- Every large-table delete has an indexed filter or an identified migration prerequisite.
- Missing indexes are identified and assigned to Phase 1.
- Cache invalidation points are confirmed.
- Artifact roots are classified.
- No existing deletion management command or service package conflicts.

---

## Next Step

Start **Phase 1 Slice 1.1**: add `PipelineRun` lifecycle fields and the three canonical repair indexes in a single migration.
