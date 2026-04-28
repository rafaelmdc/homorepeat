# Usage

## Local Setup

Copy the example environment file and start the stack:

```bash
cp .env.example .env
docker compose up --build
```

The `migrate` service runs automatically before `web` starts. The app is available at **http://localhost:8000**.

On subsequent starts:

```bash
docker compose up
```

The Compose stack exposes:

- web app: `http://localhost:8000`
- PostgreSQL: local port `5432`
- Celery workers: import, graph pre-warming, and download generation queues

To run management commands inside the stack:

```bash
docker compose exec web python manage.py <command>
```

## Importing Pipeline Runs

The app imports published pipeline output. Browser requests read from the database; they do not access pipeline files at request time.

The supported import format is publish contract v2. A v2 `publish/` directory has this layout:

```text
publish/
  calls/
    repeat_calls.tsv
    run_params.tsv
  tables/
    genomes.tsv
    taxonomy.tsv
    matched_sequences.tsv
    matched_proteins.tsv
    repeat_call_codon_usage.tsv
    repeat_context.tsv
    download_manifest.tsv
    normalization_warnings.tsv
    accession_status.tsv
    accession_call_counts.tsv
  summaries/
    status_summary.json
    acquisition_validation.json
  metadata/
    run_manifest.json
```

`metadata/run_manifest.json` must include `publish_contract_version: 2`.

**Manual import:**

```bash
docker compose exec web python manage.py import_run \
  --publish-root /workspace/homorepeat_pipeline/runs/<run-id>/publish
```

**Import queue UI:**

Set `HOMOREPEAT_RUNS_ROOT` in `.env` to the host directory containing run folders. Compose mounts it read-only at `/workspace/homorepeat_pipeline/runs`. Then use **http://localhost:8000/imports/** to queue runs for the worker to process.

**Process the oldest queued import manually:**

```bash
docker compose exec web python manage.py import_run --next-pending
```

## Routes

| URL | Description |
|-----|-------------|
| `/` | Site home |
| `/healthz/` | JSON healthcheck |
| `/browser/` | Browser directory |
| `/browser/homorepeats/` | Primary homorepeat observation table |
| `/browser/codon-usage/` | Repeat codon-usage profile table |
| `/browser/lengths/` | Repeat-length distributions |
| `/browser/codon-ratios/` | Residue-scoped codon composition |
| `/browser/codon-composition-length/` | Codon composition across length bins |
| `/browser/runs/` | Imported runs and provenance |
| `/browser/accessions/`, `/browser/genomes/`, `/browser/sequences/`, `/browser/proteins/`, `/browser/calls/` | Supporting canonical catalog browsers |
| `/browser/warnings/`, `/browser/accession-status/`, `/browser/accession-call-counts/`, `/browser/download-manifest/` | Operational provenance browsers |
| `/imports/` | Staff-facing import queue |
| `/imports/history/` | Import batch history and progress |

Filtered table downloads use `?download=tsv`. The homorepeat table also supports `?download=aa_fasta` and `?download=dna_fasta`.

## Running Tests

Run all browser tests:

```bash
python3 manage.py test web_tests
```

Run focused test modules:

```bash
python3 manage.py test web_tests.test_browser_stats
python3 manage.py test web_tests.test_browser_lengths
python3 manage.py test web_tests.test_browser_codon_ratios
python3 manage.py test web_tests.test_browser_codon_composition_lengths
```

Check JavaScript syntax:

```bash
node --check static/js/stats-chart-shell.js
node --check static/js/pairwise-overview.js
node --check static/js/taxonomy-gutter.js
node --check static/js/repeat-length-explorer.js
node --check static/js/repeat-codon-ratio-explorer.js
node --check static/js/codon-composition-length-explorer.js
```
