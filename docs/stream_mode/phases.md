# Stream-Mode Rebuild Phases

## Purpose

This document turns
[plan.md](/home/rafael/Documents/GitHub/homorepeat/docs/stream_mode/plan.md)
into a reviewable slice sequence for low-memory merged-summary rebuilds.

Sequencing rules:

- implement slice by slice
- keep merged semantics unchanged
- keep raw rows canonical
- optimize for bounded memory before runtime speed
- validate the large run explicitly before calling the track complete

Preflight notes:

- small-dataset validation:
  [small-validation-2026-04-13.md](/home/rafael/Documents/GitHub/homorepeat/docs/stream_mode/small-validation-2026-04-13.md)
- large-run validation:
  [validation-2026-04-13.md](/home/rafael/Documents/GitHub/homorepeat/docs/stream_mode/validation-2026-04-13.md)

Current next slice:

- none

## Phase 1: Baseline The Write Path

### Slice 1.1: Record the current rebuild failure mode

Goal:

- document exactly what is consuming memory in the current rebuild path

Scope:

- capture the failing phase
- record large-run cardinalities
- identify the current rebuild query shape and Python materialization points
- record the target machine budget for this track

Exit criteria:

- the repo has a stream-mode plan
- the repo has a stream-mode phases document
- the failure mode is described concretely enough to compare against the
  streamed rebuild

Status:

- implemented

## Phase 2: Build The Streamed Rebuild

### Slice 2.1: Stream merged rebuild work by accession

Goal:

- stop whole-run raw repeat-call materialization during merged-summary rebuild

Scope:

- process one accession at a time
- rebuild run-scoped occurrence rows from the accession slice only
- refresh touched protein and residue summaries from the accession slice only
- preserve stale-summary cleanup and replace-existing semantics

Out of scope:

- no schema changes unless the streamed path proves insufficient
- no read-path behavior changes

Exit criteria:

- rebuild memory is bounded by accession-scoped work
- no rebuild query introduces an unnecessary `ORDER BY`
- focused rebuild tests cover multi-accession behavior and stale cleanup

Status:

- implemented

## Phase 3: Harden Worker Behavior

### Slice 3.1: Keep the worker alive after a failed batch

Goal:

- ensure one failed import does not stop background processing entirely

Scope:

- log unexpected batch failures
- continue polling after batch failure recording completes
- keep one-shot command behavior explicit

Exit criteria:

- the long-running worker no longer exits on an unexpected batch failure
- focused tests cover the failure-and-continue behavior

Status:

- implemented

## Phase 4: Validate On The Large Run

### Slice 4.1: Re-run `chr_all3_raw_2026_04_09` with stream mode

Goal:

- prove the streamed rebuild solves the real write-path memory problem

Scope:

- run the Compose/Postgres stack with the large published run
- verify the import completes through merged-summary rebuild
- record timing and remaining hotspots

Exit criteria:

- the large run completes on the target machine envelope
- a dated validation artifact is recorded in `docs/stream_mode/`
- any remaining bottlenecks are clearly documented

Status:

- implemented
