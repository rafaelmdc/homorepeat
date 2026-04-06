# Operator Runbook

## Purpose

Define the default operator path for running HomoRepeat reproducibly from a clean checkout.

## Default run sequence

1. Build the development images.

```bash
bash scripts/build_dev_containers.sh
```

2. Confirm the taxonomy DB exists.

```bash
ls cache/taxonomy/ncbi_taxonomy.sqlite
```

3. Run the accession-driven smoke example.

```bash
HOMOREPEAT_PHASE4_PROFILE=docker \
HOMOREPEAT_PARAMS_FILE=examples/params/smoke_default.json \
bash scripts/run_phase4_pipeline.sh examples/accessions/smoke_human.txt
```

## Default inputs

Current checked-in example:
- `examples/accessions/smoke_human.txt`
- `examples/params/smoke_default.json`
- `examples/params/multi_residue_qn.json`

Current row unit:
- one assembly accession per line

## Default outputs

The wrapper creates one run root under `results/phase4/<run_id>/`.

That run root should include:
- `.nextflow/`
- `nextflow/nextflow.log`
- `run_started_at_utc.txt`
- `run_context.env`
- `nextflow_command.sh`
- `results/planning/`
- `results/acquisition/`
- `results/calls/`
- `results/sqlite/`
- `results/reports/`
- `results/report_prep/`

On successful runs, the wrapper also updates:
- `results/phase4/latest`

## Current recommended profile

- `docker`

`local` remains available for hosts that already carry the required CLI toolchain, but it is not the primary reproducible path.
