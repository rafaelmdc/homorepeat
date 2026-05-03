# PAARTA

**PAARTA** (Poly-Amino Acid Repeat Tract Atlas) is a web application for
browsing and analysing homorepeats: runs of consecutive identical or
near-identical amino acids in proteins.

Use it to search imported PAASTA results, inspect repeat calls across organisms,
compare codon usage, view summary charts, and download tables or FASTA files.

## Requirements

- [Docker](https://docs.docker.com/get-docker/) with the Compose plugin (included in Docker Desktop)

## Quick Start

Clone the repository:

```bash
git clone <repo-url>
cd homorepeat
cp .env.example .env
```

For a single-user local workstation, you can make the import page available
without creating a Django login. In `.env`, set:

```bash
no_admin=1
```

Do not use `no_admin=1` on a shared, LAN-accessible, or internet-facing server.

Start PAARTA:

```bash
docker compose up --build
```

The first run builds the container image and applies database migrations. When
the stack is ready, open **http://localhost:8000**.

On subsequent starts, omit `--build`:

```bash
docker compose up
```

## Loading Data

The app is empty on first start. Load data by importing a published PAASTA run.
The run must contain one `publish/metadata/run_manifest.json` file for publish
contract v2.

### Option 1: Upload a Zipped Run

Use this when the PAASTA run is on your laptop or workstation and is not mounted
inside the Docker stack.

1. Zip the publish folder. The zip can contain `publish/` at the top level or inside
   one parent folder, but it must contain exactly one
   `publish/metadata/run_manifest.json`.
2. Open **http://localhost:8000/imports/**.
3. Upload the zip.
4. Wait for the upload to reach **Ready**.
5. Click **Import** and monitor progress on the same page or in
   **http://localhost:8000/imports/history/**.

Uploads are chunked, SHA-256 checked, resumable after a browser interruption,
and extracted by a background worker before import. The default maximum zip
size is 5 GB.

### Option 2: Import Mounted Runs

Use this when the PAASTA run directory already exists on the machine running
Docker.

```bash
# In .env, point HOMOREPEAT_RUNS_ROOT to your runs directory:
HOMOREPEAT_RUNS_ROOT=/path/to/paasta/runs
docker compose up -d
```

Then open **http://localhost:8000/imports/**. PAARTA detects runs in that
directory and lets you queue imports from the browser.

### Option 3: Command-Line Import

Use this for scripted or administrative imports:

```bash
docker compose exec web python manage.py import_run \
  --publish-root /workspace/homorepeat_pipeline/runs/<run-id>/publish
```

The path must be visible inside the container. If you are using
`HOMOREPEAT_RUNS_ROOT`, the container path is usually
`/workspace/homorepeat_pipeline/runs/<run-id>/publish`.

## Browsing

| URL | Contents |
|-----|----------|
| `/browser/homorepeats/` | Full homorepeat table — organism, assembly, gene, repeat type, architecture, length, purity |
| `/browser/codon-usage/` | Per-repeat codon usage profiles for each target residue |
| `/browser/lengths/` | Repeat-length distributions grouped by taxonomy |
| `/browser/codon-ratios/` | Codon composition heatmaps by residue and taxon |
| `/browser/codon-composition-length/` | Codon composition across repeat-length bins |
| `/browser/runs/` | Imported pipeline runs and provenance |

All tables support search and column filtering. TSV downloads are available from
tables. The homorepeat table also supports amino-acid FASTA and codon DNA FASTA
downloads.

## Documentation

- [Usage](docs/usage.md) — step-by-step setup, imports, browsing, and downloads
- [Configuration](docs/configuration.md) — all environment variables and their defaults
- [Architecture](docs/architecture.md) — app structure, data model, and view hierarchy
- [Statistics](docs/statistics.md) — filter definitions and biological semantics
- [Operations](docs/operations.md) — management commands, cache behaviour, and maintenance
- [Development](docs/development.md) — contributor workflow and testing strategy

## License

See [LICENSE](LICENSE).
