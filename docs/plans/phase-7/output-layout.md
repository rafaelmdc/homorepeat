# Output Layout

## Purpose

Freeze the expected operator-facing run tree for the current workflow baseline.

## Run root

The wrapper creates:

```text
results/phase4/<run_id>/
  .nextflow/
  nextflow/
    nextflow.log
  run_started_at_utc.txt
  run_context.env
  nextflow_command.sh
  results/
    planning/
    acquisition/
    calls/
    sqlite/
    reports/
    report_prep/
    nextflow/
      trace.txt
```

## Convenience link

After a successful wrapper run, Phase 7 maintains:

```text
results/phase4/latest -> <run_id>
```

That link is only updated on successful runs.

## Published outputs

Stable operator-facing directories under `results/`:
- `planning/`
- `acquisition/`
- `calls/`
- `sqlite/`
- `reports/`
- `report_prep/`

These remain the primary browsing surface for completed runs.
