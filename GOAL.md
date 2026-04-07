  # Two-Root Restructure: pipeline/ and web/

  ## Summary

  Restructure the repo into a hard-cutover, split-ready monorepo with only two product roots:

  repo-root/
    pipeline/
    web/

  Boundary decisions from the audit:

  - apps/pipeline/** is pipeline-only.
  - src/homorepeat/** is pipeline-only in current reality, not shared runtime code.
  - tests/**, examples/**, runs/**, and runtime/** are pipeline-only.
  - apps/web/** is web-only.
  - containers/acquisition.Dockerfile and containers/detection.Dockerfile are pipeline-only.
  - containers/web.Dockerfile is web-only.
  - The only true cross-product boundary is the published artifact contract under publish/**; there is no current shared Python/runtime layer that both sides depend on.
  - src/homorepeat/db/postgres/** stays pipeline-owned for now because it is only a placeholder and the web app does not import it today.

  The root becomes nearly empty: only repo metadata plus a thin root README.md. No legacy apps/* compatibility layer and no root-level command wrappers.

  ## Target Layout And Ownership

  ### pipeline/

  Move and flatten pipeline-owned assets here:

  - apps/pipeline/* -> pipeline/
    Result: pipeline/main.nf, pipeline/nextflow.config, pipeline/conf/, pipeline/modules/, pipeline/workflows/, pipeline/scripts/
  - src/ -> pipeline/src/
  - tests/ -> pipeline/tests/
  - examples/ -> pipeline/examples/
  - runtime/ -> pipeline/runtime/
  - runs/ -> pipeline/runs/
  - containers/acquisition.Dockerfile -> pipeline/containers/acquisition.Dockerfile
  - containers/detection.Dockerfile -> pipeline/containers/detection.Dockerfile
  - pipeline-owned docs -> pipeline/docs/
    Includes current docs/architecture.md, docs/contracts.md, docs/methods.md, docs/operations.md, docs/roadmap.md
  - pyproject.toml -> pipeline/pyproject.toml

  Add a pipeline-local compose.yaml for acquisition and detection image builds so pipeline image workflows remain local to pipeline/.

  ### web/

  Move and flatten web-owned assets here:

  - apps/web/* -> web/
    Result: web/manage.py, web/config/, web/apps/, web/static/, web/templates/
  - containers/web.Dockerfile -> web/containers/web.Dockerfile
  - web-specific docs -> web/docs/
  - create web/pyproject.toml as the web-local dependency manifest
  - create web/compose.yaml for Django + Postgres

  The web image and compose stack must no longer copy or install pipeline/src/homorepeat.

  ### Repo root

  Keep only:

  - root README.md as a monorepo index pointing to pipeline/ and web/
  - repo metadata such as .gitignore, LICENSE, editor config, and agent docs

  Remove product-owned root assets after relocation:

  - root compose.yaml
  - root pyproject.toml
  - root containers/
  - root docs/
  - root src/
  - root tests/
  - root examples/
  - root runtime/
  - root runs/
  - root apps/

  If the currently staged-but-missing docs docs/production_phases.md and docs/repository_split_runbook.md are intended to remain in the repo, relocate them intentionally under pipeline/docs/; do not drop them.

  ## Implementation Changes

  ### Pipeline path and config surgery

  Update all path-sensitive pipeline assets to use the new pipeline-local root:

  - pipeline/scripts/*.sh compute PIPELINE_ROOT from their own location and default to pipeline/runs/ and pipeline/runtime/
  - pipeline/tests/** stop referencing apps/pipeline, root tests, root examples, and root runtime
  - all docs and smoke commands switch to product-local invocations such as cd pipeline && ...
  - Docker build context for pipeline images becomes pipeline/
  - pipeline/pyproject.toml keeps package name/import surface as homorepeat so python -m homorepeat.cli.* remains unchanged

  ### Web decoupling

  Make the web side independently operable:

  - web/pyproject.toml defines Django and psycopg dependencies
  - web/containers/web.Dockerfile copies only web-owned files from web/
  - web/compose.yaml builds from web/ and runs Django + Postgres without root-repo assumptions
  - docs and commands switch to cd web && ...

  ### Contract preservation

  Do not change the published artifact boundary:

  - publish/manifest/run_manifest.json
  - publish/acquisition/*.tsv
  - publish/calls/repeat_calls.tsv
  - publish/calls/run_params.tsv
  - downstream published SQLite/report outputs

  Do not change:

  - Python import namespace homorepeat
  - Nextflow workflow semantics
  - TSV column contracts
  - run manifest meaning
  - image tags expected by the pipeline unless a path move requires only config relocation, not semantic change

  ### Cleanup rules

  After migration:

  - there should be no live code or docs references to apps/pipeline, apps/web, root src/, root tests/, or root containers/
  - there should be no web runtime dependency on pipeline package layout
  - the only intentional link between products is the copied publish/ artifact contract

  ## Test Plan

  ### Pipeline validation

  Run from repo root or inside pipeline/, but against product-local paths:

  - python3 -m pip install -e ./pipeline
  - pytest pipeline/tests/workflow/test_pipeline_config.py
  - pytest pipeline/tests/cli/test_runtime_artifacts.py
  - pytest pipeline/tests/unit
  - nextflow config pipeline
  - cd pipeline && docker compose build pipeline-acquisition pipeline-detection
  - cd pipeline && HOMOREPEAT_PHASE4_PROFILE=docker bash scripts/run_phase4_pipeline.sh examples/accessions/smoke_human.txt

  Acceptance checks:

  - Nextflow config parses from pipeline/
  - pipeline smoke run succeeds
  - pipeline/runs/<run_id>/publish/** matches the existing contract
  - no script or test relies on repo-root apps/, src/, tests/, examples/, runtime/, or runs/

  ### Web validation

  Run against the product-local web root:

  - python3 -m pip install -e ./web
  - python3 web/manage.py check
  - cd web && docker compose build web
  - cd web && docker compose up web postgres
  - verify the health endpoint still returns the current response

  Acceptance checks:

  - the web container builds without copying pipeline code
  - Django starts with only web-local files
  - Postgres-backed dev startup still works
  - web docs no longer instruct users to operate through repo-root paths

  ### Final repository checks

  - rg returns no remaining code/docs references to legacy ownership paths
  - only pipeline/ and web/ contain product code
  - root README.md is only an index/handoff document

  ## Assumptions And Defaults

  - Hard cutover is approved: no legacy apps/* compatibility layer and no old command-path preservation wrappers.
  - Nearly empty root is approved: product-owned docs, tests, examples, containers, configs, and manifests move under pipeline/ or web/.
  - The current web app does not depend on homorepeat; therefore no third shared package root is retained.
  - The canonical integration boundary remains the published artifact contract, not shared source code.
  - Any currently dirty user-owned docs in the worktree are preserved by relocation or explicit review, not silently deleted.
