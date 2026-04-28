# HomoRepeat Browser

HomoRepeat is a web application for browsing and analysing homorepeats — runs of consecutive identical or near-identical amino acids — found in proteins across organisms spanning the tree of life. It provides searchable tables, statistical charts, and bulk downloads of repeat observations linked to taxonomy, gene, and codon-usage data.

## Requirements

- [Docker](https://docs.docker.com/get-docker/) with the Compose plugin (included in Docker Desktop)

## Getting Started

Clone the repository and start the stack:

```bash
git clone <repo-url>
cd homorepeat
docker compose up --build
```

The first run builds the container image and applies all database migrations automatically. When the stack is ready, open **http://localhost:8000** in your browser.

On subsequent starts, omit `--build`:

```bash
docker compose up
```

## Loading Data

The app is empty on first start. Populate it by importing a published HomoRepeat pipeline run.

**Option 1 — command line:**

```bash
docker compose exec web python manage.py import_run \
  --publish-root /absolute/path/to/<run-id>/publish
```

**Option 2 — import queue UI:**

Set `HOMOREPEAT_RUNS_ROOT` in a `.env` file at the repo root (copy `.env.example` as a starting point):

```bash
cp .env.example .env
# Edit HOMOREPEAT_RUNS_ROOT= to point to your runs directory
```

Then visit **http://localhost:8000/imports/** to queue and monitor imports.

## Browsing

| URL | Contents |
|-----|----------|
| `/browser/homorepeats/` | Full homorepeat table — organism, assembly, gene, repeat type, architecture, length, purity |
| `/browser/codon-usage/` | Per-repeat codon usage profiles for each target residue |
| `/browser/lengths/` | Repeat-length distributions grouped by taxonomy |
| `/browser/codon-ratios/` | Codon composition heatmaps by residue and taxon |
| `/browser/codon-composition-length/` | Codon composition across repeat-length bins |
| `/browser/runs/` | Imported pipeline runs and provenance |

All tables support free-text search and column-level filtering. Downloads are available as TSV (all tables), amino-acid FASTA, and codon DNA FASTA from the homorepeat table.

## Documentation

- [Usage](docs/usage.md) — local setup, imports, routes, and tests
- [Architecture](docs/architecture.md) — app structure, data model, and view hierarchy
- [Statistics](docs/statistics.md) — filter definitions and biological semantics
- [Operations](docs/operations.md) — management commands, cache behaviour, and maintenance
- [Development](docs/development.md) — contributor workflow and testing strategy

## License

See [LICENSE](LICENSE).
