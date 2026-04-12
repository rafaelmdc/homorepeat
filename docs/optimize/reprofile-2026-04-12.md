# Large-Run Reprofile

Date: 2026-04-12

## Dataset

- Environment: `docker compose` Postgres + one-off `web` container
- Schema state: current branch migrations applied through
  `browser.0011_add_hot_raw_browse_indexes`
- Run measured: `chr_all3_raw_2026_04_09`
- Imported counts:
  - genomes: `905`
  - sequences: `382649`
  - proteins: `382649`
  - repeat calls: `1395494`

## Measurement method

- Request timings were captured inside the real `web` container with Django's
  test client against the loaded Postgres database.
- Reported wall time is server-side request time only; container startup time is
  excluded.
- SQL counts and top queries come from `CaptureQueriesContext`.
- Browse plans come from `EXPLAIN ANALYZE` on the actual view queryset with the
  default raw order and a `LIMIT 21` page slice.

## Request timings

| Path | First page | Follow-up fragment | Query count | Main observed cost |
| --- | --- | --- | --- | --- |
| `/browser/` | `146.7 ms` | n/a | `12` | global `COUNT(*)` on `browser_repeatcall`, `browser_protein`, and `browser_sequence` |
| `/browser/runs/` | `9.9 ms` | n/a | `3` | cheap run list query; no second page with only two imported runs |
| `/browser/proteins/?run=chr_all3_raw_2026_04_09` | `30.8 ms` | `23.6 ms` | `5` / `4` | exact `COUNT(*)` on `browser_protein` dominates both requests |
| `/browser/calls/?run=chr_all3_raw_2026_04_09` | `50.8 ms` | `45.8 ms` | `5` / `4` | exact `COUNT(*)` on `browser_repeatcall` dominates both requests |
| `/browser/sequences/?run=chr_all3_raw_2026_04_09` | `28.0 ms` | `24.1 ms` | `4` / `3` | exact `COUNT(*)` on `browser_sequence` dominates both requests |

Hot raw fragment payload results:

- proteins: `row_count=20`, `count` omitted
- repeat calls: `row_count=20`, `count` omitted
- sequences: `row_count=20`, `count` omitted

Important note:

- Even though the hot raw fragment payloads omit `count`, the cursor paginator
  still executes an exact `COUNT(*)` query before serving the fragment. The row
  fetch itself is no longer the dominant cost on these pages; the total-count
  query is.

## EXPLAIN summary

| Path | Index used for default row fetch | `EXPLAIN ANALYZE` execution time | Notes |
| --- | --- | --- | --- |
| proteins | `brw_prot_run_acc_name_id` | `0.312 ms` | default browse path is index-backed after `0011` |
| repeat calls | `brw_rc_run_acc_pn_start_id` | `0.151 ms` | hottest raw row fetch is index-backed after `0011` |
| sequences | `brw_seq_run_asm_name_id` | `0.383 ms` | default browse path is index-backed after `0011` |

Plan-level observations:

- The default row fetch plans now use the intended composite browse indexes.
- The trimmed raw list views keep only `pipeline_run` and `taxon` as eager joins
  on the hot row path.
- The remaining subplans on sequences and proteins are the per-row aggregate
  counts for linked proteins/repeat calls, not broad row materialization.

## Acceptance findings

- The new browse indexes are active on the real Postgres dataset.
- Branch dropdown generation is not visible in the measured raw requests.
  No large taxon-choice query showed up in the measured first-page or fragment
  SQL.
- Metadata-backed method/residue facets are not visible as live `RepeatCall`
  scans in the measured raw requests.
- `/browser/runs/` is cheap on the current two-run dataset.
- `/browser/` is still dominated by live directory-card `COUNT(*)` queries.
- The hot raw pages still pay exact total-count cost on both first-page and
  follow-up fragment requests because cursor pagination calls `queryset.count()`
  unconditionally.

## Limits of this artifact

- Slice `1.1` was skipped, so there is no trustworthy before-change timing set
  for direct before/after comparison.
- This artifact is therefore a post-change large-run profile, not a complete
  before/after benchmark history.

## Immediate follow-up suggested by the measurements

- Stop doing exact total counts on hot raw cursor pages when the UI does not
  need them.
- If `/browser/` must be part of raw acceptance, move the home directory-card
  totals off the live request path as well.
