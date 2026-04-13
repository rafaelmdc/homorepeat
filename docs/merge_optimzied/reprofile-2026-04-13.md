# Merged Reprofile

**Date:** 2026-04-13

## Scope

This note records the merged browser profile after the summary-table serving
redesign, exact evidence filter preservation, and first-page provenance payload
trimming landed on the current branch.

Compared artifact:

- [baseline-2026-04-13.md](/home/rafael/Documents/GitHub/homorepeat/docs/merge_optimzied/baseline-2026-04-13.md)

Measured run:

- `live_raw_effective_params_2026_04_09`

## Measurement Method

- Environment: local sqlite DB in the workspace
- The measured run was already imported locally with these raw counts:
  - genomes: `1`
  - sequences: `303`
  - proteins: `303`
  - repeat calls: `608`
  - accession status rows: `1`
  - accession call count rows: `2`
  - normalization warnings: `685`
- Because this local DB predated the merged serving-layer rollout, the profile
  first ran:
  - `python manage.py backfill_merged_summaries --run-id live_raw_effective_params_2026_04_09`
- Serving-layer counts after backfill:
  - protein summaries: `460`
  - residue summaries: `460`
  - protein occurrences: `460`
  - residue occurrences: `460`
- Request timings were captured with Django's test client against the loaded
  sqlite DB.
- Reported wall time is server-side request time only.
- SQL counts and dominant query shapes come from `CaptureQueriesContext`.

## Measured Requests

The timings below are local sqlite timings on the current branch. They are used
to confirm that merged mode now scales with summary rows plus page-scoped raw
drill-down, rather than full-scope raw evidence materialization.

| Path | Status | Time | Queries | Baseline | Main signal |
| --- | --- | ---: | ---: | ---: | --- |
| `/browser/accessions/?run=live_raw_effective_params_2026_04_09` | `200` | `55.8 ms` | `12` | `91.1 ms` | grouped genome analytics plus merged occurrence counters; still pays raw repeat-call count queries for exclusion metrics |
| `/browser/proteins/?run=live_raw_effective_params_2026_04_09&mode=merged` | `200` | `41.2 ms` | `5` | `44.3 ms` | summary count plus one page summary fetch and one page-scoped raw `RepeatCall` fetch |
| `/browser/calls/?run=live_raw_effective_params_2026_04_09&mode=merged` | `200` | `26.1 ms` | `5` | `44.3 ms` | summary count plus one page summary fetch and one page-scoped raw `RepeatCall` fetch |
| `/browser/accessions/GCF_000001405.40/` | `200` | `279.1 ms` | `8` | `306.5 ms` | still the slowest path because accession detail deliberately rematerializes accession-scoped raw evidence for the residue table and provenance drill-down |
| `/browser/taxa/32/?run=live_raw_effective_params_2026_04_09&mode=merged` | `200` | `12.0 ms` | `9` | `80.2 ms` | branch taxonomy scaffolding plus grouped accession counts and distinct summary-occurrence counts; no full merged helper materialization |

## Query Shape Notes

Observed request patterns:

- merged protein and merged repeat-call list pages no longer fetch a full raw
  evidence scope before pagination
- both merged list pages now follow the same bounded pattern:
  - one summary-table `COUNT(*)`
  - one summary-row page fetch
  - one raw `RepeatCall` fetch limited to the active page identities
- accession analytics now combines:
  - grouped `Genome` analytics
  - merged occurrence-based counters
  - raw repeat-call count queries used only for exclusion and duplicate metrics
- taxon detail in merged mode no longer calls helper paths that group the full
  branch evidence scope in Python
- accession detail still performs one accession-scoped raw evidence fetch after
  reading merged summary counts because the full residue table and drill-down
  backlinks remain live

The main scaling failure mode from the baseline is therefore removed:

- merged list and taxon-summary paths are no longer dominated by full raw
  evidence materialization and Python-side grouping before pagination
- merged list costs are now anchored to summary rows plus page-scoped raw
  evidence rematerialization

## Page Payload Check

The merged list pages now trim page-scoped provenance payloads before render:

- first merged proteins page: `20` groups
- first merged repeat-call page: `20` groups
- sampled first-group preview payload after render:
  - `source_run_records`: `1`
  - `source_proteins`: `1`
  - `source_repeat_calls`: `2`

That matches the intended `4.2` contract:

- counts remain visible
- representative evidence remains linked
- list-page provenance is bounded
- full provenance still remains available on accession/detail or filtered raw
  evidence pages

## Remaining Bottlenecks

The main remaining merged hotspot on this small sqlite profile is:

1. Accession detail still rematerializes accession-scoped raw evidence for its
   residue table and provenance drill-down.

Secondary observations:

1. Accessions analytics still pays several live raw repeat-call count queries
   for duplicate and exclusion metrics.
2. Merged list pages still do an exact paginator `COUNT(*)` on the summary
   table, but that is materially cheaper than the old full raw-evidence pass on
   this dataset.

## Conclusion

This reprofile is sufficient to mark slice `5.1` complete on the small sibling
dataset.

The merged redesign changed the dominant cost on the list and taxon-summary
paths from full raw evidence materialization to bounded summary-table reads plus
page-scoped raw drill-down. The main remaining intentionally expensive path is
accession detail, where full provenance remains part of the page contract.
