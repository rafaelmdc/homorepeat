# Stream-Mode Rebuild Plan

## Summary

This track addresses the write-path memory problem in merged-summary rebuilds.

The current merged browser read paths are already much lighter than the old
Python-grouped version, but import completion still rebuilds merged summaries
by materializing too much raw `RepeatCall` evidence at once. That is acceptable
on a larger machine and unacceptable on a target developer box with `8–16 GB`
of RAM.

The goal of stream mode is not to make imports faster. The goal is to make
merged-summary rebuilds predictable and bounded in memory, even if rebuild time
increases.

## Problem Statement

Observed large-run facts on `chr_all3_raw_2026_04_09`:

- `repeat_calls.tsv` contains about `1.395M` raw repeat-call rows
- the run spans about `904` accessions
- the run produces about `860k` merged protein/residue identity keys
- the failing import died during merged-summary rebuild, not during raw ingest
- the concrete failure mode was PostgreSQL shared-memory exhaustion while the
  worker was rebuilding merged serving rows

The current rebuild path is still too broad for this machine budget because it:

- loads whole-run raw repeat-call scopes into Python
- re-reads large cross-run raw scopes for touched summary refreshes
- stores large ORM object graphs while also grouping them into merged units
- ties peak memory to run size instead of to a bounded chunk size

## Recommended Direction

Use accession-scoped streaming as the canonical merged-summary rebuild path.

Rules:

- keep raw imported rows canonical
- keep merged semantics unchanged
- keep summary rows fully rebuildable from raw evidence
- keep replace-existing behavior exact
- prefer lower peak memory over shorter rebuild time

Operationally, rebuild one accession at a time:

1. determine the accession set that needs processing for the imported run
2. delete only that run's occurrence rows for one accession
3. read current-run raw repeat calls for that accession only
4. build run-scoped protein and residue occurrence groups from that slice
5. read cross-run raw repeat calls for that accession only
6. refresh touched summary rows from that accession slice
7. recreate run-scoped occurrence rows for that accession
8. release that slice before moving to the next accession

This keeps peak memory proportional to the heaviest accession slice rather than
to the entire import.

## Production Policy

The production rebuild path should converge on stream mode only.

Default policy:

- production uses the streamed rebuild path
- the older full/global rebuild path is not kept as a second permanent mode
- a short-lived debug fallback is acceptable during rollout if needed
- once stream mode is validated on the large run, the old path should not
  remain part of normal operation

Keeping both modes permanently would increase maintenance cost and make
semantic drift more likely in merged-summary rebuild behavior.

## Constraints

- no merged identity-rule changes
- no raw import contract changes
- no public browser URL changes
- no schema migration in the first stream-mode pass unless profiling proves it
  is necessary
- batch failure recording must still happen before the worker continues polling

## Acceptance Criteria

This track is complete when all of the following are true:

- merged-summary rebuild no longer loads whole-run raw repeat-call scopes
- peak rebuild memory is bounded by accession-scoped work rather than by the
  total imported run
- replace-existing imports still remove stale merged summaries and occurrences
- failed batches no longer kill the long-running worker process
- a large-run validation artifact confirms the streamed rebuild completes on
  the target machine envelope
