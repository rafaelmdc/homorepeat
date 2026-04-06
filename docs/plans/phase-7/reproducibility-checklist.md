# Reproducibility Checklist

## Required runtime pieces

- built `homorepeat-acquisition:dev` image
- built `homorepeat-detection:dev` image
- local taxonomy DB at `cache/taxonomy/ncbi_taxonomy.sqlite`
- checked-in accession list or an explicit user-provided accession list

## Required command surface

For the current baseline, these commands should be sufficient:
- `bash scripts/build_dev_containers.sh`
- `HOMOREPEAT_PHASE4_PROFILE=docker HOMOREPEAT_PARAMS_FILE=examples/params/smoke_default.json bash scripts/run_phase4_pipeline.sh examples/accessions/smoke_human.txt`

## Expected reproducible outputs

Each successful run should publish:
- canonical acquisition TSV/FASTA artifacts
- finalized call directories for the retained methods
- `homorepeat.sqlite`
- `summary_by_taxon.tsv`
- `regression_input.tsv`
- `echarts_options.json`
- `echarts_report.html`
- local `echarts.min.js`
- run metadata files under the run root
- a refreshed `results/phase4/latest` symlink after successful wrapper runs

## Not yet frozen

These are still expected to evolve:
- cluster execution profiles
- taxon-driven accession generation
- broader smoke datasets beyond the one-accession baseline
