# Phase 3 Validation Strategy

## Purpose

This document defines how the standalone scientific-core implementation should be checked before Phase 4 wraps it in Nextflow.

The goal is to catch contract drift and scientific regressions early, using the smallest reliable checks first.

---

## Validation levels

### Level 0: pure-function checks

Use for:
- ID generation
- tract-boundary calculations
- purity calculations
- translation acceptance/rejection rules
- codon slicing helpers

Why:
- these checks are fast and isolate logic errors before CLI plumbing adds noise

---

### Level 1: single-script CLI checks

Use for:
- one CLI on one tiny synthetic fixture
- TSV shape validation
- warning-row emission
- parameter-record output

Why:
- every `bin/` script must remain runnable outside Nextflow

---

### Level 2: small integrated slice checks

Use for:
- acquisition normalization on one tiny package snapshot
- pure detection on translated proteins from that normalization slice
- codon extraction on a small validated call set
- SQLite build from a tiny but complete artifact set

Why:
- this verifies that neighboring scripts compose correctly before the full pipeline exists

---

### Level 3: smoke end-to-end checks

Use for:
- one very small real-world or reduced fixture run covering:
  - request resolution
  - selection
  - batch derivation
  - normalization
  - one or more detection methods
  - SQLite assembly
  - summary exports

Why:
- this is the nearest substitute for Phase 4 workflow checks without introducing workflow orchestration yet

Current implementation note:
- the live acquisition smoke check is intentionally opt-in and lives outside the default unit-test suite
- the same smoke now also exercises one detection path, codon extraction, SQLite assembly, and summary/report-prep on live acquisition outputs
- a separate live detection smoke exercises `threshold` and real `diamond blastp` on previously acquired live proteins
- see [live-smoke.md](../../live-smoke.md) and `scripts/smoke_live_acquisition.sh`
- see [live-detection-smoke.md](../../live-detection-smoke.md) and `scripts/smoke_live_detection.sh`

---

## Validation targets by slice

### Acquisition and planning

Must verify:
- deterministic request resolution behavior
- review-queue rows are separated cleanly
- selected assemblies are reproducible
- every selected assembly belongs to exactly one batch

Likely problems:
- live NCBI metadata changes break reproducibility
- taxonomy build versions drift silently

Mitigation:
- use frozen fixture projections for routine tests
- reserve live-network checks for explicit smoke or manual validation runs

### Normalization and translation

Must verify:
- GFF-backed CDS linkage works on representative fixtures
- CDS rejection rules emit expected warning codes
- translated protein rows can be traced back to CDS rows deterministically

Likely problems:
- fixture coverage misses weird annotation structures
- local translation accidentally becomes permissive

Mitigation:
- include at least one rejected CDS example
- include at least one multi-isoform example

### Detection

Must verify:
- pure, threshold, and similarity methods each reproduce their Phase 2 worked example
- all methods emit the same shared core columns
- method-specific score semantics are labeled correctly

Likely problems:
- methods accidentally drift into each other
- fallback similarity output is treated as interchangeable with BLAST output

Mitigation:
- keep example-based checks for all three methods
- assert backend identity in `run_params.tsv`

### Codon extraction

Must verify:
- successful codon extraction produces length `3 * amino_acid_length`
- failed codon extraction preserves the amino-acid call and empties codon fields
- v1 codon metric fields remain empty

### SQLite assembly

Must verify:
- import order is correct
- row counts reconcile with flat inputs
- foreign-key reachability checks pass

### Summary and reporting prep

Must verify:
- summary counts reconcile with source call tables
- regression/grouped outputs reconcile with summaries
- any combined `echarts_options.json` is derived only from finalized tables

---

## Required fixture types

### Synthetic sequence fixtures

Purpose:
- pure string-level detection and codon-slicing checks

Examples:
- one pure-method success case
- one threshold-only success case
- one similarity-fallback success case
- one invalid CDS translation case

### Reduced package fixtures

Purpose:
- normalization and translation checks without depending on live downloads

Examples:
- one clean RefSeq package fragment
- one package fragment with missing or partial annotation
- one multi-isoform package fragment

### Smoke manifests

Purpose:
- small integration checks for Phase 3 CLIs

Examples:
- one deterministic taxon request
- one review-queue taxonomy request
- one small selected-batch manifest

---

## What should not block routine validation

- live network availability
- full-scale NCBI download performance
- final HTML polish
- large-scale batch throughput

Those belong in later smoke, integration, or workflow phases.

---

## Phase 3 acceptance gate

Phase 3 should not be considered complete until:
- all three detection methods pass worked-example validation
- at least one normalization slice passes from package input to translated proteins
- rejected CDS cases are warning-driven and deterministic
- SQLite can be built from validated flat outputs
- summary/report-prep tables reconcile numerically with the underlying calls

If any of those fail, Phase 3 is not ready for Nextflow wrapping.
