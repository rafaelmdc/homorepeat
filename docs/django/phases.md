# HomoRepeat Django Refactor Phases

## Purpose

This document turns `docs/django/implementation.md` and
`docs/django/merged.md` into a reviewable implementation sequence.

## Current Status

Completed today:

- `1.1` contract reset in code and tests
- `1.2` real-run inspection fixtures and regression coverage
- `2.1` canonical raw provenance models and import-batch progress fields
- `2.2` obsolete schema cleanup, `seed_extend` support, and hot-list projection
  cleanup
- `3.1` full raw parser for run-level and batch-level artifacts
- `3.2` queued/background import execution with `ImportBatch` status reporting
- `3.3` transactional raw importer against the corrected contract
- `3.4` Postgres-first heartbeat/progress reporting during streamed imports
- `3.5` PostgreSQL bulk-load path, `ANALYZE`, and importer throughput cleanup
- `4.1` run provenance page refresh using imported DB state only
- `4.2` raw operational artifact browsers for warnings, accession status,
  accession call counts, and download manifest
- browser home and inter-view navigation cleanup focused on contextual links
  between related raw and merged views

Validated today:

- real Docker + Postgres import of the small run
  `live_raw_effective_params_2026_04_09`
- real Docker + Postgres import of the large run `chr_all3_raw_2026_04_09`
- imported method coverage on the large run includes `pure`, `threshold`, and
  `seed_extend`
- browser view tests pass after the navigation and provenance refactor

Current next slice:

- `5.1` Merged identity and exclusion rules on the corrected raw layer

The sequencing rules are:

- implement only the current `raw` publish-mode contract
- preserve canonical raw truth first
- keep merged browsing derived-only
- avoid large speculative refactors outside the import and browse path
- validate on both the small and large real pipeline runs
- ensure the running app does not depend on pipeline pod files after import
- make long-running imports observable and non-blocking for operators
- prefer the simplest production-grade mechanisms before adding extra platform
  components
- optimize for a Docker-first deployment and add orchestration-specific pieces
  only when they are actually needed

## Phase 1: Contract Reset

### Slice 1.1: Replace outdated import assumptions in code and tests

Goal:
- remove the flat-acquisition contract assumptions from the importer and tests

Scope:
- switch manifest discovery to `publish/metadata/run_manifest.json`
- reject non-`raw` runs for now
- update required artifact discovery to use run-level and batch-level raw paths
- remove expectations for deleted fields:
  - `download_path`
  - `sequence_path`
  - `protein_path`
  - `source_file`
- update method validation to allow `seed_extend`
- update run-parameter validation to require `repeat_residue`

Out of scope:
- no model migrations yet
- no browser work yet

Exit criteria:
- parser tests reflect the real raw contract
- contract tests pass on a synthetic raw fixture
- importer fails clearly on `merged` publish mode

### Slice 1.2: Add real-run inspection fixtures and regression tests

Goal:
- anchor the refactor to the checked-in example outputs rather than guessed data

Scope:
- add tests that validate parser behavior against the small real raw run when
  available locally
- add large-run contract tests that validate batch discovery, method support,
  and row counting without requiring a full DB import
- update helper fixtures to emit the new raw layout

Out of scope:
- no DB import yet
- no browser work yet

Exit criteria:
- test fixtures produce `raw`-mode publish roots
- helper data no longer encodes the deleted columns
- tests cover multi-batch raw layout and `seed_extend`

## Phase 2: Schema Refactor

### Slice 2.1: Add canonical raw provenance models

Goal:
- create the schema needed to represent the real raw publish structure

Scope:
- add `acquisition_publish_mode` to `PipelineRun`
- add `AcquisitionBatch`
- add `DownloadManifestEntry`
- add `NormalizationWarning`
- add `AccessionStatus`
- add `AccessionCallCount`
- add `repeat_residue` to `RunParameter`
- add batch provenance to `Genome`
- add browse-oriented denormalized fields to `RepeatCall` and `Protein`
- add progress and liveness fields to `ImportBatch`

Required rules:
- `AcquisitionBatch` unique on `(pipeline_run, batch_id)`
- `RunParameter` unique on
  `(pipeline_run, method, repeat_residue, param_name)`
- `RepeatCall` carries the stable filter columns needed for fast website
  filtering without mandatory joins on every request
- status and warning models indexed for run, batch, accession, method, and
  residue filtering
- `ImportBatch` can record job status, phase, heartbeat, and progress payload

Out of scope:
- no import logic yet
- no browser pages yet

Exit criteria:
- migrations apply cleanly
- model tests cover new uniqueness and FK integrity

### Slice 2.2: Remove obsolete schema fields and broaden enums

Goal:
- align existing biological models with the current raw contract

Scope:
- remove obsolete contract fields from relational models:
  - `Genome.download_path`
  - `Sequence.sequence_path`
  - `Protein.protein_path`
  - `RepeatCall.source_file`
- broaden method enums or validation for `seed_extend`
- keep large text fields out of the intended hot-path list projections
- update admin registrations and model tests accordingly

Out of scope:
- no importer yet
- no merged-view redesign yet

Exit criteria:
- schema matches current documented columns
- tests no longer assume deleted fields exist

## Phase 3: Raw Import Backend

### Slice 3.1: Read-only raw parser

Goal:
- build a correct in-memory representation of one raw published run

Scope:
- parse run-level manifest, call, parameter, and status artifacts
- discover acquisition batches
- parse batch-level genome, taxonomy, sequence, protein, download, warning, and
  validation artifacts
- compute batch counts for full raw inventories
- compute repeat-linked derived relationships from canonical `repeat_calls.tsv`

Required behavior:
- taxonomy is preserved in full
- run parameters preserve `repeat_residue`
- parser output is sufficient to populate a self-contained runtime database

Out of scope:
- no DB writes yet

Exit criteria:
- parser can fully describe the small raw run
- parser can describe the large raw run without importing it

### Slice 3.2: Background execution and progress reporting

Goal:
- make imports non-blocking and operator-visible before optimizing the heavy
  import path

Scope:
- define the async import job boundary
- have the web UI create queued import records instead of blocking on the full
  import
- implement worker-side status updates through `ImportBatch`
- define progress phases and heartbeat updates
- keep the management command wired to the same import service layer

Required behavior:
- the web request returns quickly after queuing the import
- the operator can see current phase and recent progress
- a stalled worker is detectable through heartbeat age
- failures are attached to the import batch with the phase that failed
- the default implementation does not require a broker-backed task queue or
  orchestration-specific job runner

Out of scope:
- no final large-run optimization yet

Exit criteria:
- imports can run in the background
- the UI or API can show live import status from the database

### Slice 3.3: Transactional importer

Goal:
- import one raw published run into Postgres transactionally

Scope:
- create `ImportBatch`
- create or replace `PipelineRun`
- create `AcquisitionBatch`
- import full taxonomy and rebuild closure
- import genomes with batch provenance
- import call-linked `Sequence`
- import call-linked `Protein`
- import run parameters
- import accession status and accession call counts
- import download manifest entries and normalization warnings
- import `RepeatCall`
- derive repeat-linked flags or counters inside the database as needed

Required behavior:
- fail without partial commit on any integrity error
- allow `--replace-existing`
- preserve batch provenance throughout
- never collapse raw repeat calls during import
- leave the app able to serve without access to the original TSV files
- update progress and heartbeat during long phases
- avoid user-visible half-replacement of an existing imported run

Out of scope:
- no new browser pages yet

Exit criteria:
- the small raw run imports successfully
- replacement import works
- rollback tests still pass

### Slice 3.4: Scale validation on the large raw run

Goal:
- verify that the self-contained raw-storage approach holds up on realistic
  output

Scope:
- run the importer against the large final-style raw run
- validate total batch discovery
- validate counts for batches, genomes, sequences, proteins, warnings, statuses,
  and repeat calls
- validate that the web app can serve from the imported database without
  reading original TSVs
- validate that progress and heartbeat continue updating during a long import

Out of scope:
- no UI changes yet

Exit criteria:
- large raw run import completes within acceptable resource limits
- stored counts reconcile with the source TSVs

### Slice 3.5: Bulk-load and activation optimization

Goal:
- move the heavy import path onto the efficient database-native path once the
  end-to-end behavior is correct

Scope:
- use PostgreSQL `COPY` or equivalent copy-style loading for the largest raw
  tables
- use simple staging tables only if they are needed for throughput or safer
  replacement
- minimize expensive index work during the load phase
- run validation and final write path after bulk load
- create the hot-path browse indexes after loading
- run `ANALYZE` after the large bulk-load phases

Required behavior:
- large table loading does not rely on ORM row-by-row inserts
- smaller tables may still use ORM bulk methods where that is simpler
- the import path remains observable while using the bulk-load strategy
- indexes are aligned with the actual browse filter and sort patterns

Exit criteria:
- import throughput is materially better on the large run
- replacement semantics remain correct

## Phase 4: Raw Browser Refactor

### Slice 4.1: Run and batch provenance pages

Goal:
- make the raw contract visible in the app

Scope:
- update run detail to show acquisition publish mode, batches, methods,
  residues, statuses, warnings, import counts, and active import state
- add batch list and batch detail pages
- expose batch artifact metadata and full imported raw counts

Required behavior:
- users can see that raw acquisition data is batch-scoped
- users can navigate from a run to its raw batches and provenance artifacts
- pages use imported database state, not direct TSV reads
- an in-progress import surfaces useful progress information

Exit criteria:
- run and batch pages work against imported real data

Status note:
- run provenance was expanded and validated against imported data
- dedicated batch list/detail pages were prototyped and then intentionally
  removed because the run-first navigation model was clearer for this app
- batch-scoped provenance remains visible from run detail and the operational
  artifact browsers

### Slice 4.2: Raw operational artifact browsing

Goal:
- surface side artifacts as first-class provenance rather than hidden metadata

Scope:
- list and detail or filtered views for normalization warnings
- filtered views for accession status and accession call counts
- optional batch-scoped download manifest views
- links from runs and batches into those views

Required behavior:
- filtering works by run, batch, accession, method, residue, and status
- warning scope and provenance are visible

Exit criteria:
- raw side artifacts are browsable from the main UI

Status note:
- implemented with filtered list views for normalization warnings, accession
  status, accession call counts, and download manifest
- run detail, accession detail, protein detail, and operational tables now link
  directly into filtered related views instead of relying on generic menu dumps

### Slice 4.3: Biological browsing on the corrected schema

Goal:
- keep the main scientific browsing path working after the schema reset

Scope:
- update genome, protein, sequence, and repeat-call pages and filters
- allow focused defaults such as repeat-linked filters without hiding the fact
  that only the call-linked sequence and protein subset is stored for browsing
- preserve links between raw repeat calls and their genome, sequence, protein,
  taxon, run, and batch provenance
- use keyset pagination on the largest list pages
- keep list queries narrow and avoid loading large text fields by default

Required behavior:
- raw repeat calls remain the authoritative browse layer
- no UI depends on direct access to pipeline-generated files
- repeat-call and protein list pages stay fast under realistic data volume
- search defaults remain index-friendly

Exit criteria:
- browser tests pass on corrected models and imports

## Phase 5: Merged Redesign

### Slice 5.1: Define merged identity and exclusion rules

Goal:
- move merged semantics from collapsed call fingerprints to trusted biological
  identities

Scope:
- replace the primary merged keys with:
  - protein-level identity `(accession, protein_id)`
  - residue-specific identity `(accession, protein_id, residue)`
- centralize trusted-key validation for accession, protein ID, and residue
- exclude unkeyed or untrusted rows from merged statistics while keeping them
  visible in raw mode and provenance views
- define deterministic representative-row ranking for merged summaries when one
  raw row must be shown for convenience

Out of scope:
- no new materialized tables yet
- no broad merged-page refresh yet

Required behavior:
- coordinate drift, method differences, purity changes, and minor sequence or
  annotation drift do not split merged identity when the relevant key is
  unchanged
- residue only splits identity in residue-specific merged summaries
- merged logic remains derived from raw imported rows

Exit criteria:
- helper-level tests cover duplicate collapse, residue split behavior, excluded
  rows, and representative-row ranking

### Slice 5.2: Rebuild protein-level merged summaries

Goal:
- make accession and taxon merged counts reflect unique proteins rather than
  collapsed repeat-call fingerprints

Scope:
- rework merged accession analytics around unique `(accession, protein_id)`
  units
- update merged protein lists and counters to use presence-per-protein
  semantics
- preserve denominator conflict reporting and contributing source-run and
  source-call counts
- keep merged queries derived from raw tables only

Required behavior:
- the same `(accession, protein_id)` across runs counts once in protein-level
  merged statistics
- filtered merged views include a protein-level unit when at least one
  contributing raw row matches the active filters
- raw and merged pages remain cross-linked

Exit criteria:
- merged accession and protein pages follow the protein-level rules in
  `docs/django/merged.md`

### Slice 5.3: Add residue-specific merged summaries

Goal:
- support residue-aware biological summaries without reintroducing
  call-fingerprint identity

Scope:
- add or refactor residue-specific grouping around
  `(accession, protein_id, residue)`
- update residue-filtered analytics and list pages to use residue-specific
  merged units
- ensure one protein can contribute to multiple residue groups when distinct
  residues are observed

Required behavior:
- the same protein with residues such as Q and N counts:
  - once at the protein level
  - once per residue at the residue-specific level
- residue filters operate on exact residue-specific identities, not on generic
  representative rows

Exit criteria:
- merged residue summaries and filters follow the documented residue-specific
  semantics

### Slice 5.4: Make merged pages evidence-first and provenance-complete

Goal:
- present merged rows as derived summaries over raw evidence rather than as
  independent truth rows

Scope:
- add contributing run count, contributing raw row or raw call count, and
  backlinks to source proteins and repeat calls
- surface methods observed, coordinate drift, and sequence-length or sequence
  variability where relevant
- label any displayed source row as representative evidence, not as canonical
  merged truth

Required behavior:
- every merged row remains auditable back to raw evidence
- merged pages do not imply "latest row wins" semantics
- excluded-row counts remain visible where they affect the summary

Exit criteria:
- merged detail and presentation paths surface provenance and evidence
  variability clearly

### Slice 5.5: Query shaping, performance, and regression coverage

Goal:
- keep the identity-first merged layer fast and stable on realistic imports

Scope:
- keep the implementation as ORM or ordinary-query logic first
- narrow hot-path projections and add any missing browse indexes only if
  profiling justifies them
- add regression tests for:
  - multi-run duplicate collapse
  - residue splits
  - excluded unkeyed rows
  - filter inclusion semantics
  - backlinks to raw evidence
- validate the merged layer on the small and large imported runs

Out of scope:
- no speculative materialized layer unless ordinary queries prove insufficient

Exit criteria:
- merged browser tests pass
- merged pages remain responsive on realistic data
- any further optimization work is evidence-driven rather than speculative

## Phase 6: Documentation And Hardening

### Slice 6.1: Final contract notes and operator guidance

Goal:
- leave the refactor with explicit, non-ambiguous documentation

Scope:
- update import-facing README or operator docs if needed
- document that raw mode is canonical and merged mode is derived from imported
  raw evidence
- document the runtime dependency model:
  Postgres for normal browsing, TSV artifacts for import, and database-backed
  runtime serving
- document the Docker-first import boundary and the fact that runtime serving is
  database-backed

Exit criteria:
- docs match the implemented behavior

### Slice 6.2: Acceptance sweep

Goal:
- confirm the refactor against the original objective

Scope:
- rerun focused tests
- rerun small-run import end to end
- rerun large-run validation
- verify raw truth, merged derivation, and provenance claims in the UI and DB

Acceptance checklist:
- raw published output imports correctly
- outdated assumptions are gone
- raw records remain preserved and traceable
- merged browsing is derived, explicit, and reversible
- current raw contract is documented in the repo
- the deployed app is self-contained after import and does not require direct
  access to pipeline TSV files
- long-running imports are observable and non-blocking
- the production path uses bulk loading where it matters and avoids unnecessary
  infrastructure
