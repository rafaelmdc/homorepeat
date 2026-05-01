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

## Importing PAASTA Runs

PAARTA ingests PAASTA (Poly-Amino Acid Sequence Tract Analyzer) — [PAASTA](../homorepeat_pipeline) runs the pipeline; PAARTA imports what it publishes. Browser requests read from the database; they do not access pipeline files at request time.

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

**Import queue UI for mounted runs:**

Set `HOMOREPEAT_RUNS_ROOT` in `.env` to the host directory containing run folders. Compose mounts it read-only at `/workspace/homorepeat_pipeline/runs`. Then use **http://localhost:8000/imports/** to queue runs for the worker to process.

**Import queue UI for zipped runs:**

Use **http://localhost:8000/imports/** to upload a zipped pipeline run when the
run is not already mounted under `HOMOREPEAT_RUNS_ROOT`. The upload flow is
intended for smaller zipped outputs; the default maximum zip size is 5 GB.

The zip must contain exactly one publish root with:

```text
publish/metadata/run_manifest.json
```

The worker assembles uploaded chunks, safely extracts the zip, validates the
publish contract, and copies the validated run into app-managed storage:

```text
/data/imports/library/<run-id>/publish
```

When the uploaded run reaches **Ready**, it appears in the detected-runs list on
`/imports/`. Select that run and submit the import form to create an import
batch. Import progress is shown on the same page and in `/imports/history/`.

Upload cleanup runs from Celery Beat. Stale incomplete uploads are marked failed
and their working files are removed. Failed upload working files are removed
after the configured retention window. Ready/imported library data is kept.

Disk planning for zipped uploads:

- Keep enough free space for the source zip, chunk files, extracted data, and
  the final library copy during extraction.
- A conservative rule is **zip size + extracted size + final publish size**.
- Defaults allow a 5 GB zip and up to 50 GB extracted content, so large uploads
  can temporarily require substantially more than 55 GB.
- For very large uncompressed outputs, prefer the mounted-run path through
  `HOMOREPEAT_RUNS_ROOT`.

Current upload limitations:

- The upload protocol is a focused local-app implementation, not `tus`, S3
  multipart upload, or another external standard.
- The app validates zip structure and publish-contract contents, but it does
  not currently verify per-chunk checksums or a full-file checksum.
- The app enforces configured size limits, but it does not currently run a
  disk-space preflight before upload or extraction.
- Zip extraction and import batches share the `imports` Celery queue in the
  MVP. This keeps deployment simple, but very large extractions can delay
  import jobs.
- Uploads are intended for trusted staff users. Broader deployments should add
  quota/rate limiting, stronger audit/ownership controls, and malware scanning.

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
