# Payload Inventory

Phase 1 classification of every payload family in the app. Classifications
drive decisions in later phases; no payload moves to async without timing
evidence gathered after Phase 2 (Redis cache backend) is live.

Classifications:
- `sync` — always inline, no caching; re-generated on every request
- `sync+cache` — inline computation cached in Redis; served from cache on hits
- `async+persisted` — enqueued Celery task; result stored as a durable artifact
- `defer` — not worth addressing in this refactor

---

## Import execution

| Flow | Classification | Notes |
|---|---|---|
| `process_import_batch()` via `import_worker` poll | `async+persisted` | Phase 3 migration target; `ImportBatch` is the durable state model |

---

## Graph payloads

All graph payloads are currently `sync+cache`. No timing data yet justifies
async promotion. The existing rollup tables
(`CanonicalCodonCompositionSummary`, `CanonicalCodonCompositionLengthSummary`)
make the most common unfiltered queries fast. Re-evaluate after Phase 4 adds
timing instrumentation.

### RepeatLengthExplorerView (`apps/browser/views/stats/lengths.py`)

| Bundle builder | Payload builder | Classification | Timing baseline |
|---|---|---|---|
| `build_ranked_length_summary_bundle` | `build_ranked_length_chart_payload` | `sync+cache` | TBD |
| `build_length_profile_vector_bundle` | `build_typical_length_overview_payload` | `sync+cache` | TBD |
| `build_length_profile_vector_bundle` | `build_tail_burden_overview_payload` | `sync+cache` | TBD |
| `build_length_inspect_bundle` | `build_length_inspect_payload` | `sync+cache` | TBD |
| `build_taxonomy_gutter_payload` | (direct payload) | `sync+cache` | TBD |

### CodonRatioExplorerView (`apps/browser/views/stats/codon_ratios.py`)

| Bundle builder | Payload builder | Classification | Timing baseline |
|---|---|---|---|
| `build_ranked_codon_composition_summary_bundle` | `build_ranked_codon_composition_chart_payload` | `sync+cache` | TBD |
| `build_codon_length_composition_bundle` | `build_codon_overview_payload` | `sync+cache` | TBD |
| `build_matching_repeat_calls_with_codon_usage_count` | (count only) | `sync+cache` | TBD |
| `build_codon_composition_inspect_bundle` | `build_codon_composition_inspect_payload` | `sync+cache` | TBD |
| `build_taxonomy_gutter_payload` | (direct payload) | `sync+cache` | TBD |

### CodonCompositionLengthExplorerView (`apps/browser/views/stats/codon_composition_lengths.py`)

| Bundle builder | Payload builder | Classification | Timing baseline |
|---|---|---|---|
| `build_codon_length_composition_bundle` | `build_codon_length_preference_overview_payload` | `sync+cache` | TBD |
| `build_codon_length_composition_bundle` | `build_codon_length_dominance_overview_payload` | `sync+cache` | TBD |
| `build_codon_length_composition_bundle` | `build_codon_length_shift_overview_payload` | `sync+cache` | TBD |
| `build_codon_length_composition_bundle` | `build_codon_length_pairwise_overview_payload` | `sync+cache` | TBD |
| `build_codon_length_composition_bundle` | `build_codon_length_browse_payload` | `sync+cache` | TBD |
| `build_codon_length_inspect_bundle` | `build_codon_length_inspect_payload` | `sync+cache` | TBD |
| `build_codon_length_parent_comparison_bundle` | `build_codon_length_inspect_payload` (comparison) | `sync+cache` | TBD |
| `build_taxonomy_gutter_payload` | (direct payload) | `sync+cache` | TBD |

---

## Download payloads

All downloads are currently `sync` (streamed via `StreamingHttpResponse`). None
are large enough to warrant async promotion for this codebase at this stage.
The `BrowserTSVExportMixin` and `StatsTSVExportMixin` in
`apps/browser/exports.py` already separate export assembly from views; the
inline streaming path requires no changes for this refactor.

### List-page exports (`BrowserTSVExportMixin`)

| Export | View | Classification | Notes |
|---|---|---|---|
| Genome list TSV | `CanonicalGenomeListView` | `sync` | Streamed, chunked queryset |
| Sequence list TSV | `CanonicalSequenceListView` | `sync` | Streamed, chunked queryset |
| Repeat call list TSV | `CanonicalRepeatCallListView` | `sync` | Streamed, chunked queryset |

### Stats-page exports (`StatsTSVExportMixin`)

| Export key | View | Classification | Notes |
|---|---|---|---|
| `summary` | RepeatLengthExplorerView | `sync` | Driven by `summary_bundle`; already in memory |
| `overview_typical` | RepeatLengthExplorerView | `sync` | Driven by `overview_bundle`; already in memory |
| `overview_tail` | RepeatLengthExplorerView | `sync` | Driven by `overview_bundle`; already in memory |
| `inspect` | RepeatLengthExplorerView | `sync` | Driven by `inspect_bundle`; already in memory |
| `summary` | CodonRatioExplorerView | `sync` | |
| `overview` | CodonRatioExplorerView | `sync` | |
| `browse` | CodonRatioExplorerView | `sync` | |
| `inspect` | CodonRatioExplorerView | `sync` | |
| `summary` | CodonCompositionLengthExplorerView | `sync` | |
| `preference` | CodonCompositionLengthExplorerView | `sync` | |
| `dominance` | CodonCompositionLengthExplorerView | `sync` | |
| `shift` | CodonCompositionLengthExplorerView | `sync` | |
| `similarity` | CodonCompositionLengthExplorerView | `sync` | |
| `browse` | CodonCompositionLengthExplorerView | `sync` | |
| `inspect` | CodonCompositionLengthExplorerView | `sync` | |
| `comparison` | CodonCompositionLengthExplorerView | `sync` | |

---

## Async promotion candidates (future)

These are not being moved in this refactor but are the natural candidates if
timing data from Phase 4 reveals unacceptable latency:

- `build_length_profile_vector_bundle` — drives Wasserstein and tail-burden
  pairwise matrix payloads; matrix computation scales with `O(n²)` taxon pairs
  and may become slow at large `top_n` values
- `build_codon_length_composition_bundle` — the largest matrix bundle; drives
  multiple overview payloads; filtered (non-rollup) paths are the most expensive

No payload should be promoted to `async+persisted` without observed
`elapsed_ms` data from the Phase 4 timing instrumentation under realistic
filter scopes.

---

## Cache key design (agreed for Phase 4)

Current key format (Phase 1–3):
```
browser:stats:<bundle-name>:<filter_state.cache_key()>
```

Target key format (Phase 4, after `CatalogVersion` is implemented):
```
browser:stats:<bundle-name>:<filter_state.cache_key()>:<catalog_version>
```

`catalog_version` will be read via `get_catalog_version()` (Redis-cached,
10 s TTL) to avoid a DB hit per request. See the Data And Task Flow Design
section of the implementation plan for the `CatalogVersion` model definition.
