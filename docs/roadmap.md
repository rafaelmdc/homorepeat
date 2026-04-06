# Roadmap

## Current baseline

The repository now has:
- a packaged workflow core under `src/homorepeat/`
- a Nextflow app under `apps/pipeline/`
- a Django project foundation under `apps/web/`
- a Compose development stack with Django plus PostgreSQL
- a stable published run layout under `runs/<run_id>/publish/`

## Next

The next practical milestone is the web data layer:
- land the browser data model under `apps/web/apps/`
- model the published run artifacts for browsing and ingestion
- add PostgreSQL loaders derived from the canonical published TSV contracts

## After that

Once the ingestion boundary is in place:
- build run-browsing pages in Django
- expose summary and call-table views backed by Postgres
- add import commands for published pipeline runs

## Later

Defer until the app data model is stable:
- launch or orchestration features from the web side
- richer frontend exploration workflows
- broader reporting and downstream analytical views

## Strategic direction

The intended long-term structure is:
- a dedicated pipeline repository
- a dedicated web repository
- Kubernetes-native workflow execution
- Django as control plane plus browser, not as workflow runtime

See `docs/production_architecture.md`.
