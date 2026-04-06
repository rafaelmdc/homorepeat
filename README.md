# HomoRepeat

Modular Nextflow workflow for homorepeat acquisition, detection, database assembly, and downstream reporting.

Current baseline:
- accession-driven acquisition from NCBI RefSeq packages
- `pure` and `threshold` detection methods
- codon attachment from normalized CDS
- SQLite build from flat contracts
- report-prep JSON plus an offline-capable ECharts HTML bundle

## Quick start

1. Build the local development images:

```bash
bash scripts/build_dev_containers.sh
```

2. Confirm the taxonomy DB exists:

```bash
ls cache/taxonomy/ncbi_taxonomy.sqlite
```

3. Run the pipeline on the checked-in smoke accession list:

```bash
HOMOREPEAT_PHASE4_PROFILE=docker \
bash scripts/run_phase4_pipeline.sh examples/accessions/smoke_human.txt
```

That creates one timestamped run root under `results/phase4/`.
The wrapper also updates `results/phase4/latest` on success.

To use a checked-in params example:

```bash
HOMOREPEAT_PHASE4_PROFILE=docker \
HOMOREPEAT_PARAMS_FILE=examples/params/smoke_default.json \
bash scripts/run_phase4_pipeline.sh examples/accessions/smoke_human.txt
```

## Direct Nextflow run

If you prefer the raw `nextflow run` entrypoint:

```bash
nextflow run . \
  -profile docker \
  --accessions_file examples/accessions/smoke_human.txt \
  --taxonomy_db cache/taxonomy/ncbi_taxonomy.sqlite \
  --output_dir results/phase4_run \
  -params-file examples/params/smoke_default.json
```

## Main outputs

A successful run publishes:
- `planning/accession_batches.tsv`
- `acquisition/genomes.tsv`
- `acquisition/taxonomy.tsv`
- `acquisition/sequences.tsv`
- `acquisition/proteins.tsv`
- `calls/pure/`
- `calls/threshold/`
- `sqlite/homorepeat.sqlite`
- `reports/summary_by_taxon.tsv`
- `reports/regression_input.tsv`
- `report_prep/echarts_options.json`
- `report_prep/echarts_report.html`
- `report_prep/echarts.min.js`

Nextflow execution artifacts are also written under the run output:
- `reports/nextflow_report.html`
- `reports/nextflow_timeline.html`
- `reports/nextflow_dag.html`
- `nextflow/trace.txt`

## Runtime profiles

Recommended:
- `docker`

Available:
- `local`

`local` assumes the host already has the required CLI toolchain.
`docker` is the validated path for reproducible runs.

## Repo entrypoints

Primary workflow files:
- `main.nf`
- `nextflow.config`
- `conf/base.config`
- `conf/docker.config`
- `conf/local.config`

Primary helper scripts:
- `scripts/build_dev_containers.sh`
- `scripts/run_phase4_pipeline.sh`
- `scripts/smoke_live_acquisition.sh`
- `scripts/smoke_live_detection.sh`

## Key docs

Core:
- [architecture](docs/architecture.md)
- [contracts](docs/contracts.md)
- [methods](docs/methods.md)
- [roadmap](docs/roadmap.md)

Operational:
- [acquisition](docs/acquisition.md)
- [validation](docs/validation.md)
- [phase 4 workflow notes](docs/plans/phase-4/README.md)
- [phase 7 usability plan](docs/plans/phase-7/README.md)
- [phase 7 output layout](docs/plans/phase-7/output-layout.md)

Planning history:
- [implementation plan](docs/implementation-plan.md)
- [phase 2 scientific core](docs/plans/phase-2/phase-2-scientific-core.md)
- [phase 3 implementation notes](docs/plans/phase-3/README.md)
- [phase 6 reporting plan](docs/plans/phase-6/README.md)
