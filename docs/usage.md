# Usage

HomoRepeat is a Django application for importing published HomoRepeat pipeline
runs and browsing the current canonical repeat-call catalog.

## Local Setup

From the repository root:

```bash
cp .env.example .env
python3 manage.py migrate
python3 manage.py test web_tests
python3 manage.py runserver 0.0.0.0:8000
```

With no database environment variables, Django uses `db.sqlite3`. The local
Docker Compose stack uses PostgreSQL:

```bash
docker compose up web worker postgres
```

For Compose auto-discovery, set `HOMOREPEAT_RUNS_ROOT` in `.env` to the
host-side directory containing run folders. Compose mounts that directory at
`/workspace/homorepeat_pipeline/runs` inside the web and worker containers, which
is the path Django uses.

The Compose stack exposes:

- web app: `http://localhost:8000`
- PostgreSQL: local port `5432`
- worker: queued import processor

## Importing Pipeline Runs

The app imports published pipeline output. Normal browser requests read from the
database; they do not read pipeline files at request time.

Manual import:

```bash
python3 manage.py import_run --publish-root /absolute/path/to/<run>/publish
```

Inside Compose:

```bash
docker compose exec web python manage.py import_run --publish-root /workspace/homorepeat_pipeline/runs/<run-id>/publish
docker compose exec web python manage.py import_run --next-pending
```

Set `HOMOREPEAT_RUNS_ROOT` to the directory containing run folders if the import
UI should auto-detect published runs. In Docker Compose, use the host-side path
in `.env`; inside the container, import paths use
`/workspace/homorepeat_pipeline/runs`.

## Main Routes

- `/`: site home.
- `/healthz/`: JSON healthcheck.
- `/imports/`: staff-facing import queue.
- `/imports/history/`: import batch progress and history.
- `/browser/`: browser directory.
- `/browser/runs/`: imported runs and provenance.
- `/browser/accessions/`, `/browser/genomes/`, `/browser/sequences/`,
  `/browser/proteins/`, `/browser/calls/`: canonical biology browsers.
- `/browser/lengths/`: repeat length statistics.
- `/browser/codon-ratios/`: residue-scoped codon composition.
- `/browser/codon-composition-length/`: residue-scoped codon composition across
  repeat-length bins.
- `/browser/warnings/`, `/browser/accession-status/`,
  `/browser/accession-call-counts/`, `/browser/download-manifest/`: operational
  provenance browsers.

## Common Checks

Run all browser tests:

```bash
python3 manage.py test web_tests
```

Run focused stats/browser checks:

```bash
python3 manage.py test web_tests.test_browser_stats
python3 manage.py test web_tests.test_browser_lengths
python3 manage.py test web_tests.test_browser_codon_ratios
python3 manage.py test web_tests.test_browser_codon_composition_lengths
```

Check JavaScript syntax for chart files:

```bash
node --check static/js/stats-chart-shell.js
node --check static/js/pairwise-overview.js
node --check static/js/taxonomy-gutter.js
node --check static/js/repeat-length-explorer.js
node --check static/js/repeat-codon-ratio-explorer.js
node --check static/js/codon-composition-length-explorer.js
```
