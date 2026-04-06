# Example Inputs

## Purpose

Phase 7 replaces ad hoc local scratch inputs with checked-in example inputs that are safe to reference from docs and smoke commands.

## Current example accession list

File:
- `examples/accessions/smoke_human.txt`

Content:
- `GCF_000001405.40`

## Current example params files

Files:
- `examples/params/smoke_default.json`
- `examples/params/multi_residue_qn.json`

Purpose:
- provide checked-in parameter sets that can be passed with `-params-file`
- remove the need for ad hoc local scratch config during routine runs

## Current policy

Checked-in examples should be:
- small
- stable
- scientifically unambiguous
- safe to use in docs and runbooks

They should not:
- depend on local absolute paths
- embed user-specific environment assumptions
- be the only way to run the workflow
