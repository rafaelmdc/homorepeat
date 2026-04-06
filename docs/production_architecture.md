# Production Architecture Plan

## Purpose

This document defines the target production structure for HomoRepeat once the
Nextflow pipeline is moved into its own repository.

This is the intended architecture, not a local-development convenience layout.
Development environments should imitate these contracts as closely as possible,
but they must not redefine them.

For the phased delivery sequence, see `docs/production_phases.md`.

## Core decision

Split the system into three concerns:

1. pipeline code and pipeline runtime
2. web control plane and browser
3. infrastructure and deployment

The main rule is:

- Django is a control plane, browser, and import surface
- Nextflow is a compute plane
- the boundary between them is a stable launch-and-publish contract

## Repository structure

### Pipeline repository

Owns:

- Nextflow entrypoints
- profiles
- modules and subworkflows
- pipeline runtime images
- published artifact contract
- release tags and pinned image versions

Does not own:

- Django code
- browser models
- web launch UI
- Postgres browser schema

### Web repository

Owns:

- Django application
- browser and import models
- launch request models
- queue worker code
- operator UI
- import-from-published-run logic

Does not own:

- Nextflow workflow files
- executor-specific scientific runtime code
- Docker-socket-based orchestration

### Infrastructure repository

Owns:

- Kubernetes manifests or Helm charts
- Postgres deployment
- object storage configuration
- secrets, RBAC, and service accounts
- ingress
- monitoring and alerting

This keeps deployment concerns out of both the pipeline repo and the Django repo.

## Production runtime topology

The production deployment should have these runtime roles:

- `web`: Django web application
- `worker`: queue consumer for launch requests
- `postgres`: application database
- `object storage`: durable run artifacts, manifests, and copied logs
- `kubernetes jobs`: one submitted workflow head job per run
- `workflow task pods`: pods created by Nextflow under the Kubernetes executor

### Web

Responsibilities:

- authentication and authorization
- operator launch forms
- launch request creation
- run browser
- import initiation
- display of status and logs already persisted by the worker side

Restrictions:

- no Nextflow installation required
- no Docker socket
- no Kubernetes job creation rights
- no dependence on local `runs/` paths

### Worker

Responsibilities:

- claim pending launch requests transactionally
- resolve the requested pipeline release
- materialize launch inputs
- submit a Kubernetes workflow job
- record job identifiers and artifact URIs
- poll status and capture failure information
- update launch records as the run progresses

Restrictions:

- it should not implement scientific logic
- it should not bypass the pipeline wrapper contract
- it should not write scientific results directly into Postgres

### Workflow head job

Responsibilities:

- execute the pinned pipeline release
- run Nextflow with the Kubernetes executor
- produce canonical published artifacts
- write the run manifest

The workflow head job is compute-plane code, not application-plane code.

## Canonical storage model

Use two storage classes with distinct purposes.

### Executor-visible working storage

Use durable Kubernetes-visible storage for workflow execution state:

- Nextflow work directory
- transient internal pipeline outputs
- task staging data

This is typically a PVC or another executor-visible workspace.

### Durable artifact storage

Use object storage for durable outputs and integration boundaries:

- submission bundle
- launcher-side copied logs
- published `publish/` outputs
- final manifest

Django should treat durable artifact storage as the read boundary for imports and
operator inspection.

### Storage rules

- Django must not assume local filesystem access to workflow work directories
- workflow pods must not need access to the Django container filesystem
- imports should read from published artifact URIs or a mounted object-store gateway path, not from ad hoc host paths
- local executor work state and durable published artifacts are separate concerns

## Launch request contract

The web side should persist a logical launch request, not executor-specific file paths.

Recommended launch-request fields:

- `run_id`
- `pipeline_release`
- `executor_profile`
- `requested_by`
- `status`
- `accessions_text`
- `params_json`
- `artifact_base_uri`
- `publish_uri`
- `manifest_uri`
- `logs_uri`
- `submitted_job_id`
- `submitted_pod_name` or equivalent runtime identifier
- `error_message`
- timestamps

### Rules

- `accessions_text` and `params_json` are the source request payload
- executor-facing file paths are derived by the worker side, not authored by the web side
- a launch request is immutable after submission except for status and runtime metadata
- every launch request pins one pipeline release
- production launches must not follow floating branches or unpinned images

## Launch lifecycle

1. An operator submits accession IDs and params in Django.
2. Django validates the request and creates a pending launch row in Postgres.
3. The worker claims the request.
4. The worker resolves the pipeline release and materializes the submission bundle.
5. The worker submits a Kubernetes job for the workflow head pod.
6. The workflow runs and emits canonical `publish/` artifacts plus a manifest.
7. The worker records job state, copies or links logs into durable storage, and updates the launch status.
8. Django shows the result and, when requested, imports the published run into the browser database.

This keeps the web side synchronous only for request validation and queueing.

## Pipeline release model

Every launch must pin a concrete pipeline release.

Acceptable identifiers:

- git tag
- release version string
- immutable OCI image tag set
- git SHA if the release discipline is not fully established yet

Production rule:

- the worker must never launch an unspecified "latest" workflow revision

This is necessary for reproducibility and auditability.

## Import contract in production

The browser import path remains independent from execution.

Import rules:

- import uses the published artifact contract only
- import does not read Nextflow work directories
- import may be triggered by an operator or by explicit post-success automation
- import must preserve the existing provenance-first browser model

This keeps workflow execution and browser ingestion loosely coupled.

## Security model

### Web service account

Allowed:

- Postgres access
- application secrets
- read access to durable artifacts when needed for operator views or imports

Not allowed:

- Kubernetes job creation
- workflow execution credentials
- Docker socket access

### Worker service account

Allowed:

- Postgres access
- object storage read/write
- Kubernetes Job creation in the designated namespace
- read access to workflow status and pod logs

Not allowed:

- direct writes to browser biological tables

### Workflow service account

Allowed:

- executor-visible storage access
- object storage access required by the pipeline
- external scientific data source access needed by the workflow

Not allowed:

- direct access to Django internals
- direct mutation of the browser database

## Observability

The system should track two distinct statuses:

### Launch status

Application-level state:

- pending
- submitted
- running
- completed
- failed
- imported

### Pipeline status

Scientific execution state taken from the published manifest:

- success
- failed
- timestamps
- pinned release metadata

The manifest remains the source of truth for workflow completion.
The launch row is the source of truth for queue and submission state.

### Logs

Do not make Django depend on live local log files.

Instead:

- worker records runtime identifiers
- worker copies or publishes launcher and Nextflow logs to durable storage
- Django reads those durable log artifacts or a stored tail or summary

## What to avoid

Avoid these patterns in the target architecture:

- keeping pipeline and web in the same repo long-term
- storing absolute local filesystem paths as the primary launch contract
- running production workflow launches through a container with `/var/run/docker.sock`
- making Django depend on the same filesystem namespace as workflow execution
- importing from transient work directories instead of published artifacts
- launching unpinned pipeline code in production

## Recommended implementation phases

### Phase A: Repository split

- move Nextflow workflow code into its own repository
- preserve the current published artifact contract
- define a release and versioning policy for the pipeline

### Phase B: Web launch model cleanup

- keep launch requests logical in Django
- remove path-first assumptions from the launch model
- pin every request to a pipeline release

### Phase C: Worker as a first-class deployment unit

- run the worker as its own Kubernetes deployment
- give it queue-claim, object-store, and Kubernetes Job permissions
- remove any production reliance on Compose-only assumptions

### Phase D: Kubernetes-native pipeline execution

- create one supported Kubernetes profile in the pipeline repo
- standardize workspace and durable artifact storage
- make worker submission Kubernetes-native

### Phase E: Import from durable artifact URIs

- treat `publish_uri` as the import source
- keep published-artifact ingestion independent from execution location
- preserve the browser provenance model

### Phase F: Operational hardening

- add retries and backoff policies
- add alerting and audit trails
- expose durable log links and manifest inspection in Django
- document RBAC and secret boundaries explicitly

## Final target summary

The long-term production-safe structure is:

- pipeline repository for workflow code and runtime images
- web repository for Django control plane and browser
- infrastructure repository for Kubernetes and storage
- Django web deployment
- Django worker deployment
- Postgres
- object storage
- Kubernetes-native Nextflow execution

That structure is simple, reproducible, and does not depend on development-only
runtime tricks.
