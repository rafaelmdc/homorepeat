# Stream-Mode Large Validation 2026-04-13

## Summary

This is the real `4.1` validation pass for the stream-mode rebuild track.

The large Compose/Postgres import of
`chr_all3_raw_2026_04_09` completed successfully with the streamed rebuild
path enabled. The earlier failure mode was a merged-summary rebuild crash due
to PostgreSQL shared-memory exhaustion. That failure did not recur.

## Validation Setup

Environment:

- Docker Compose stack with `postgres`, `web`, and `worker`
- existing clean Postgres database
- streamed merged-summary rebuild from
  [apps/browser/merged/build.py](/home/rafael/Documents/GitHub/homorepeat/apps/browser/merged/build.py:22)
- worker hardening from
  [apps/imports/management/commands/import_worker.py](/home/rafael/Documents/GitHub/homorepeat/apps/imports/management/commands/import_worker.py:26)

Published run:

- `/workspace/homorepeat_pipeline/runs/chr_all3_raw_2026_04_09/publish`

## Batch Outcome

Latest import batch state from Postgres:

- batch: `2`
- status: `completed`
- phase: `completed`
- started at: `2026-04-13 20:29:09.455362+00:00`
- finished at: `2026-04-13 21:02:16.673080+00:00`
- elapsed: `0:33:07.217718`

Imported raw counts:

- genomes: `905`
- acquisition batches: `91`
- taxonomy rows: `3080`
- sequences: `382649`
- proteins: `382649`
- repeat calls: `1395494`
- run parameters: `8`
- accession status rows: `905`
- accession call count rows: `2715`
- download manifest entries: `905`
- normalization warnings: `379823`

Post-import merged serving counts:

- `MergedProteinSummary`: `860919`
- `MergedResidueSummary`: `860919`
- `MergedProteinOccurrence`: `860919`
- `MergedResidueOccurrence`: `860919`

## Memory Snapshots

These were one-shot `docker stats --no-stream` snapshots, not true peak memory
measurements.

During raw import:

- `postgres`: `168.8 MiB`
- `worker`: `334.6 MiB`
- `web`: `93.73 MiB`

Immediately after completion:

- `postgres`: `175.6 MiB`
- `worker`: `979.5 MiB`
- `web`: `92.52 MiB`

## Result

The stream-mode rebuild resolves the original write-path failure on this large
run.

What changed operationally:

- the import no longer dies during `summarizing_merged`
- the worker process remains alive after the run
- the run reaches completed batch state with merged serving rows populated

What this validation does **not** prove:

- it does not give a true peak RSS measurement
- it does not prove the import fits every `8 GB` machine under all docker and
  host-memory conditions
- it does not optimize runtime; the import still took about `33` minutes on
  this machine

## Merge Behavior Note

There is an unresolved semantic concern in the merged layer.

Observed on this validation run:

- raw `RepeatCall` rows: `1395494`
- `MergedResidueSummary` rows: `860919`
- `MergedResidueOccurrence` rows: `860919`

If merged behavior is only supposed to collapse equivalent calls across runs,
then a single imported run should theoretically preserve call cardinality.
Current behavior does not do that, which suggests the merged identity/build
logic is still collapsing calls within a single run.

This stream-mode work fixed the write-path memory failure, but it did not
resolve that merge-semantic discrepancy. Merge behavior should be revisited in
a follow-up track.

## Remaining Hotspots

The primary remaining cost is no longer the previous merged-summary memory
crash. The remaining pressure appears to be:

- total runtime of the large raw import and serving-row rebuild
- very large merged serving cardinality on this dataset
  - about `860k` protein summaries
  - about `860k` residue summaries
  - about `860k` occurrence rows for each level

If a follow-up optimization is needed, the next likely target is serving-layer
storage/write volume rather than the old whole-run raw-materialization failure
mode.
