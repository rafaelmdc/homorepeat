# Live Smoke Check

## Purpose

This document defines the opt-in live acquisition, codon-enrichment, SQLite, and summary/report-prep smoke check for the current standalone Phase 3 implementation.

It exists because:
- routine tests should stay deterministic and offline
- acquisition still needs at least one real validation path against live NCBI and a real `taxon-weaver` taxonomy DB

This smoke check is not part of the default unit-test suite.

---

## Scope

The current live smoke check verifies:
1. `taxon-weaver` can resolve one real scientific name through `bin/resolve_taxa.py`
2. one real RefSeq accession can pass through:
   - `resolve_taxa.py`
   - `enumerate_assemblies.py`
   - `select_assemblies.py`
   - `plan_batches.py`
   - `download_ncbi_packages.py`
   - `normalize_cds.py`
   - `translate_cds.py`
   - `merge_acquisition_batches.py`
3. one real residue can pass through:
   - `detect_pure.py`
   - `extract_repeat_codons.py`
4. the same finalized smoke artifacts can pass through:
   - `build_sqlite.py`
   - `export_summary_tables.py`
   - `prepare_report_tables.py`
5. canonical acquisition, codon-enriched call, SQLite, and reporting artifacts are non-empty and structurally sane

It does not currently test:
- large taxon enumeration
- multi-batch retry behavior under real failure
- threshold or similarity detection backends
- Nextflow orchestration

---

## Entry Point

Script:
- `scripts/smoke_live_acquisition.sh`

This script is intentionally explicit and environment-gated so it never runs by accident.

---

## Required Environment

Runtime default:
- if `TAXONOMY_DB_PATH` is unset, the smoke script defaults to `cache/taxonomy/ncbi_taxonomy.sqlite` under the repo root
- if that DB does not exist, the script bootstraps it itself with `taxon-weaver build-db --download`

Required:
- enough network access to reach NCBI for both taxonomy bootstrap and package retrieval

Optional:
- `TAXONOMY_DB_PATH`
  Override the taxonomy SQLite path.
- `TAXONOMY_TAXDUMP_PATH`
  Override the downloaded `taxdump.tar.gz` location used during bootstrap.
- `TAXONOMY_BUILD_REPORT_PATH`
  Override the `taxon-weaver` build report path.
- `NCBI_API_KEY`
- `TAXON_WEAVER_BIN`
  Defaults to `taxon-weaver`
- `DATASETS_BIN`
  Defaults to `datasets`
- `PYTHON_BIN`
  Defaults to `python3`
- `NCBI_CACHE_DIR`
  External cache directory for package downloads
- `HOMOREPEAT_SMOKE_RUN_ID`
  Override the generated run ID. The default format is `live_smoke_YYYY-MM-DD_HH-MM-SSZ`.
- `HOMOREPEAT_SMOKE_RUN_ROOT`
  Override the default run root
- `HOMOREPEAT_SMOKE_TAXON_NAME`
  Defaults to `Homo sapiens`
- `HOMOREPEAT_SMOKE_ACCESSION`
  Defaults to `GCF_000001405.40`
- `HOMOREPEAT_SMOKE_REPEAT_RESIDUE`
  Defaults to `Q`

Why the accession default is explicit:
- it keeps the live smoke bounded to one accession
- it avoids accidentally enumerating an entire broad taxon during the real acquisition check

Why the residue default is explicit:
- the codon-enrichment step needs at least one real detected call
- `Q` on the default human accession is expected to yield a bounded but non-empty pure-call set

---

## Run On Host

Example:

```bash
export NCBI_API_KEY="..."

bash scripts/smoke_live_acquisition.sh
```

---

## Run In Docker

If you built the acquisition image:

```bash
docker run --rm \
  -v "$PWD":/work \
  -v "$PWD/cache/taxonomy":/data/taxonomy \
  -v "$PWD/cache/ncbi":/data/ncbi-cache \
  -w /work \
  -e TAXONOMY_DB_PATH=/data/taxonomy/ncbi_taxonomy.sqlite \
  -e NCBI_API_KEY="$NCBI_API_KEY" \
  homorepeat-acquisition:0.1 \
  bash scripts/smoke_live_acquisition.sh
```

---

## Success Criteria

The smoke check passes only if:
- taxonomy resolution does not enter the review queue
- the live accession is selected and assigned to `batch_0001`
- a real package is downloaded and normalized
- merged `genomes.tsv`, `taxonomy.tsv`, `sequences.tsv`, and `proteins.tsv` are non-empty
- merged `acquisition_validation.json` has status `pass` or `warn`
- all structural validation checks in that JSON are `true`
- `pure_calls.tsv` is non-empty for the chosen smoke residue
- codon-enriched `pure_calls.tsv` is non-empty
- at least one smoke call has a non-empty `codon_sequence`
- every non-empty smoke `codon_sequence` has length `3 * length`
- `codon_metric_name` and `codon_metric_value` remain empty in the smoke output
- `homorepeat.sqlite` is created
- `sqlite_validation.json` has status `pass`
- `summary_by_taxon.tsv` and `regression_input.tsv` are non-empty
- `echarts_options.json` is valid JSON and contains the expected chart blocks

Warnings are allowed.
Structural failure is not.

---

## Run Naming

By default the smoke script writes runs under:

- `runs/live_smoke_YYYY-MM-DD_HH-MM-SSZ`

It also writes:

- `run_started_at_utc.txt`

at the run root with the exact UTC start time in ISO 8601 form, for example:

- `2026-04-05T17:34:14Z`

---

## Operational Notes

- live NCBI metadata can change over time
- live download performance is not part of the pass/fail contract
- the first run may spend extra time bootstrapping the taxonomy DB
- this smoke check should be run intentionally after acquisition-side changes or before cutting a reproducibility milestone
