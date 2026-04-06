# Phase 4 Reference

This folder contains the current workflow-engine implementation notes for Phase 4.

Current workflow entry point:
- [main.nf](../../../main.nf)

Current workflow scope:
- [workflows/acquisition_from_accessions.nf](../../../workflows/acquisition_from_accessions.nf)
- [workflows/detection_from_acquisition.nf](../../../workflows/detection_from_acquisition.nf)
- [workflows/database_reporting.nf](../../../workflows/database_reporting.nf)
- [nextflow.config](../../../nextflow.config)
- [base.config](../../../conf/base.config)
- [local.config](../../../conf/local.config)
- [docker.config](../../../conf/docker.config)
- [run_phase4_pipeline.sh](../../../scripts/run_phase4_pipeline.sh)

Current boundaries:
- the pipeline starts from `params.accessions_file`
- NCBI retrieval is wrapped in Nextflow as isolated per-batch processes
- taxonomy lineage enrichment still depends on a local `taxon-weaver` DB path via `params.taxonomy_db`
- `threshold` is treated as frozen and live-validated
- the recommended execution profile is now `docker`, not `local`, unless the host already has the required CLI toolchain

Preferred run entry point:

```bash
HOMOREPEAT_PHASE4_PROFILE=docker \
bash scripts/run_phase4_pipeline.sh my_accessions.txt
```

What that wrapper does:
- writes the Nextflow log under one run root instead of the repo root
- keeps the Nextflow work directory under the configured output tree
- launches Nextflow from the run root so `.nextflow` state also stays with the run
- defaults the taxonomy DB to `cache/taxonomy/ncbi_taxonomy.sqlite`
- still allows `HOMOREPEAT_TAXONOMY_DB` and `HOMOREPEAT_NXF_HOME` overrides

Default run-root layout:

```text
results/phase4/<run_id>/
  .nextflow/
  nextflow/nextflow.log
  results/
    nextflow/
      trace.txt
    planning/
      accession_batches.tsv
      selected_accessions.txt
    sqlite/
    reports/
      nextflow_report.html
      nextflow_timeline.html
      nextflow_dag.html
    report_prep/
    acquisition/
    calls/
```

Equivalent direct command:

```bash
nextflow run . \
  -profile docker \
  --accessions_file my_accessions.txt \
  --taxonomy_db cache/taxonomy/ncbi_taxonomy.sqlite \
  --output_dir results/phase4_run
```

Current structural design:
- one process file per operational unit
- one subworkflow for accession-driven acquisition
- one subworkflow for detection plus codon finalization
- one subworkflow for SQLite and reporting
- directory-based handoffs between major stages instead of wiring every TSV separately
- process labels map cleanly to runtime classes: planning, acquisition, detection, database, reporting

Current module groups:
- planning: `modules/local/planning/`
- acquisition: `modules/local/acquisition/`
- detection: `modules/local/detection/`
- reporting: `modules/local/reporting/`

Current isolated process chain:
- plan accession batches
- download one NCBI package batch
- normalize one package batch
- translate one normalized batch
- merge batch acquisition outputs
- detect pure calls
- detect threshold calls
- finalize codon-enriched call directories
- build SQLite
- export summary tables
- prepare report tables
- render ECharts HTML report

Current validated behavior:
- the Phase 4 workflow was run successfully end to end under the `docker` profile from a one-accession input list
- validated accession: `GCF_000001405.40`
- validated detection outputs for residue `Q`:
  - pure calls: `209`
  - threshold calls: `399`
- SQLite validation passed
- acquisition validation remained `warn`, which is consistent with the standalone acquisition smoke behavior

Expected outputs from a successful run:
- `results/phase4_run/planning/accession_batches.tsv`
- `results/phase4_run/acquisition/genomes.tsv`
- `results/phase4_run/acquisition/proteins.tsv`
- `results/phase4_run/calls/pure/`
- `results/phase4_run/calls/threshold/`
- `results/phase4_run/sqlite/homorepeat.sqlite`
- `results/phase4_run/sqlite/sqlite_validation.json`
- `results/phase4_run/reports/summary_by_taxon.tsv`
- `results/phase4_run/reports/regression_input.tsv`
- `results/phase4_run/report_prep/echarts_options.json`
- `results/phase4_run/report_prep/echarts_report.html`

Next slice:
- replace manual accession lists with a future taxon-weaver-driven accession generator once that feature exists
- add a cluster-oriented profile such as Apptainer without changing the process graph
