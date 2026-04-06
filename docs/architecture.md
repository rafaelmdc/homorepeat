# Architecture

## Overview

HomoRepeat is a modular Nextflow-based pipeline for detecting and analyzing homorepeat regions across repeat residues.

The project is intentionally split into two layers:

1. **Workflow orchestration**
2. **Scientific logic**

Nextflow is responsible for orchestration, execution, caching, profiles, and reproducibility.

Python scripts and small reusable libraries are responsible for:
- sequence processing
- homorepeat detection
- codon extraction
- taxonomy-aware data shaping
- database assembly
- reporting table generation
- plotting

The goal is to keep the workflow easy to rerun and the scientific logic easy to test independently.

The current development runtime is also split into two operator-facing surfaces:
- a Nextflow pipeline app under `apps/pipeline/`
- a Docker Compose development stack at the repo root for Django plus PostgreSQL

For the intended long-term production structure, see `docs/production_architecture.md`.

---

## Scientific Scope

### v1 target

Version 1 is scoped to general homorepeat detection and analysis.

The detection, normalization, and first reporting layers are expected to work for any repeat residue.

By default, the scientific target is:
- user-configurable taxonomic scope defined by taxon name or taxid
- NCBI-backed acquisition through the Datasets ecosystem
- taxonomy enrichment using NCBI-derived taxonomy data through `taxon-weaver`

Deuterostomes remain an important reference validation case because the current scientific reference material is strongest there, but they are not the only supported target scope.

Local sequence inputs remain supported for:
- smoke tests
- offline development
- debugging normalization and detection logic

They are not the primary scientific acquisition mode for the rebuild.

### What must remain comparable to the earlier project

The rebuild should preserve comparability at the level of:
- the retained v1 detection strategies and their intended meaning
- standardized homorepeat call outputs
- taxon-aware summary tables
- optional codon-linked outputs that can support later residue-specific analyses
- the main biological trends for the configured validation case

The rebuild does not need to preserve:
- legacy code structure
- undocumented implementation quirks
- exact intermediate filenames from the old project
- historical behavior that depended on implicit heuristics rather than stated rules

### Mandatory v1 outputs

The first scientifically valid release is expected to produce:
- canonical metadata tables
- standardized `pure` and `threshold` call tables
- one integrated SQLite database assembled from flat files
- summary tables and any generic reporting tables needed for residue-neutral outputs
- reproducible ECharts-ready reporting outputs

### Non-goals for v1

The first release does not need to include:
- annotation or protein-domain enrichment
- heavy UI or web application features
- direct mutation of SQLite during upstream processing
- premature generalization beyond the current scientific scope
- fully bespoke downstream figure families for every residue from day one

---

## Design principles

### 1. Nextflow handles orchestration, not core biology
The `.nf` files should describe:
- what runs
- in what order
- with which inputs and outputs
- under which profile

They should not contain the main biological logic.

### 2. Each step has a stable file contract
Every process must consume and emit predictable files with documented columns and naming.

### 3. Detection methods are peers
The retained detection methods are independent strategies:
- pure
- threshold

They should be implemented as parallel modules with the same output schema.

### 4. SQLite is a final assembly artifact
Pipeline steps should not write directly into a live shared SQLite database.

Instead:
- intermediate steps emit flat files
- one dedicated database step imports those files
- the database is treated as a reproducible build artifact

### 5. Reporting is downstream only
Figures and summary tables should be generated only from finalized analysis-ready tables, never directly from raw detection code.

### 6. Simplicity over cleverness
Prefer explicit modules, explicit file contracts, and small subworkflows over deeply clever channel logic.

### 7. Compose is for app/runtime services, not workflow logic
The repo-root `compose.yaml` is the operator entrypoint for:
- the Django development server
- the local PostgreSQL instance
- building the pipeline runtime images expected by the Nextflow `docker` profile

It should not become a second workflow orchestrator.
Scientific execution still belongs to Nextflow plus the package-backed CLIs.

---

## Conceptual workflow

The pipeline is divided into four main stages:

1. **Acquisition**
2. **Detection**
3. **Database assembly**
4. **Reporting**

### Acquisition
This stage is responsible for obtaining and normalizing the biological inputs.

Typical tasks:
- enumerate and retrieve NCBI-backed assemblies or local test inputs
- download annotation-focused package contents rather than raw genomic FASTA in v1
- resolve and enrich taxonomy with `taxon-weaver`
- run contamination checks
- normalize metadata
- translate retained CDS records into canonical protein inputs
- optionally filter isoforms

### Detection
This stage extracts homorepeat calls from the prepared inputs.

It contains the current implemented methods:
- **pure**: contiguous homorepeat detection
- **threshold**: sliding-window density-based detection

All methods must emit the same call schema.

### Database assembly
This stage imports validated flat outputs into SQLite.

Responsibilities:
- build schema
- import detection outputs
- import metadata tables
- build indexes
- validate row counts and key integrity

### Reporting
This stage produces analysis-ready summaries and final outputs.

Responsibilities:
- generate summary tables
- compute grouped statistics
- prepare regression inputs
- render reproducible ECharts outputs
- export publication-ready outputs

---

## Layered repository model

### Workflow layer
Owns:
- `apps/pipeline/main.nf`
- `apps/pipeline/nextflow.config`
- `apps/pipeline/conf/*.config`
- `apps/pipeline/modules/local/*.nf`
- `apps/pipeline/workflows/*.nf`

Responsibilities:
- orchestration
- profiles
- execution model
- process resource settings
- file routing
- resumability

Current validated runtime note:
- on April 6, 2026, the `docker` profile completed a smoke run end-to-end on `examples/accessions/smoke_human.txt`
- the validated run root is `runs/phase4_pipeline_2026-04-06_12-03-46Z`

### Script layer
Owns:
- `src/homorepeat/cli/*.py`

Responsibilities:
- one script per operational task
- command-line interfaces
- deterministic input/output behavior

### Library layer
Owns:
- `src/homorepeat/**/*.py`

Responsibilities:
- shared reusable code
- schema definitions
- sequence utilities
- repeat detection helpers
- db utilities
- plotting helpers

### Data contract layer
Owns:
- `docs/contracts.md`
- `src/homorepeat/resources/sql/sqlite/schema.sql`
- `src/homorepeat/resources/sql/sqlite/indexes.sql`

Responsibilities:
- document canonical columns
- define table rules
- define IDs and naming conventions

### Documentation layer
Owns:
- `docs/*.md`
- `AGENTS.md`

Responsibilities:
- architecture
- roadmap
- contracts
- repo conventions
- local agent instructions

### Compose and web layer
Owns:
- `compose.yaml`
- `containers/web.Dockerfile`
- `apps/web/`

Responsibilities:
- Django development runtime
- local PostgreSQL service
- future frontend integration against published run artifacts or Postgres tables derived from them
- convenient image builds for the pipeline Docker profile

---

## Recommended repository structure

text
homorepeat/
├── README.md
├── apps/
│   ├── pipeline/
│   │   ├── main.nf
│   │   ├── nextflow.config
│   │   ├── conf/
│   │   ├── modules/
│   │   ├── workflows/
│   │   └── scripts/
│   └── web/
├── src/
│   └── homorepeat/
├── docs/
├── examples/
├── runtime/
├── runs/
├── tests/
└── containers/

Workflow boundaries
apps/pipeline/workflows/acquisition_from_accessions.nf

Inputs:

accession lists, sequence files, or metadata tables

Outputs:

normalized sequence inputs
normalized metadata
taxonomy-linked records
apps/pipeline/workflows/detection_from_acquisition.nf

Inputs:

prepared protein or CDS inputs
method parameters

Outputs:

pure_calls.tsv
threshold_calls.tsv
apps/pipeline/workflows/database_reporting.nf

Inputs:

normalized metadata
detection call tables
schema files

Outputs:

homorepeat.sqlite
published reporting artifacts

Inputs:

sqlite database or analysis-ready exports

Outputs:

summary tables
regression input tables
figures
supplementary exports

Process-level philosophy

Each process should do one thing only.

Good process examples:

FETCH_GENOMES
ADD_TAXONOMY
FILTER_ISOFORMS
TRANSLATE_CDS
FIND_REPEAT_PURE
FIND_REPEAT_THRESHOLD
BUILD_SQLITE
EXPORT_SUMMARIES
MAKE_PLOTS

Avoid giant mixed-purpose processes.

Identifier policy

The project should define one canonical identifier strategy and preserve it throughout the workflow.

Recommended internal IDs:

genome_id
taxon_id
sequence_id
protein_id
call_id

External identifiers may also be stored, but internal IDs should be the stable relational backbone.

Output philosophy

There are three output levels:

Raw operational outputs

Examples:

downloaded FASTA files
translated FASTA files
intermediate metadata TSVs
Standardized method outputs

Examples:

pure_calls.tsv
threshold_calls.tsv

These are the most important portable workflow artifacts.

Final products

Examples:

homorepeat.sqlite
summary tables
figure PDFs
supplementary TSVs
Why this architecture

This design fits the scientific workflow already established in the current project:

data retrieval
contamination/taxonomy handling
two detection strategies
SQLite integration
downstream statistical summaries and visualizations

The refactor keeps that scientific structure, but makes the implementation more reproducible, modular, and easier to rerun.
