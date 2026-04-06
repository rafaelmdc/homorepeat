# HomoRepeat Production Phases and Slices

## Purpose

This document turns `docs/production_architecture.md` into a delivery sequence
that can be implemented in small, reviewable slices.

The sequencing rules are:

- keep the published artifact contract stable
- separate web control-plane work from pipeline compute-plane work
- make the queue contract logical before changing executors
- make Kubernetes execution native, not Docker-socket-based
- make durable artifact storage the integration boundary
- defer automation and hardening until the core launch path is structurally correct

## Phase 0: Contract Freeze

### Slice 0.1: Freeze the published artifact boundary

Goal:
- lock the file-level boundary that the future split pipeline repo and web repo will share

Scope:
- confirm the required `publish/` manifest and TSV artifacts
- confirm which fields are authoritative for import
- confirm that imports only depend on published outputs, not Nextflow work dirs

Out of scope:
- no executor changes yet
- no repository split yet

Exit criteria:
- one written artifact contract exists and is treated as the cross-repo boundary
- web import behavior is defined only in terms of published artifacts

### Slice 0.2: Freeze the launch request contract

Goal:
- define the logical request model that the web side will persist

Scope:
- define required launch fields such as `run_id`, `pipeline_release`, `accessions_text`, and `params_json`
- define allowed mutable fields such as status and runtime metadata
- define the required pinned-release policy

Out of scope:
- no Kubernetes submission implementation yet
- no worker deployment changes yet

Exit criteria:
- there is one documented launch-request contract
- executor-facing paths are explicitly excluded from the web-side request model

## Phase 1: Repository Separation

### Slice 1.1: Extract the pipeline into its own repository

Goal:
- separate Nextflow workflow ownership from Django ownership

Scope:
- move workflow entrypoints, modules, profiles, and pipeline image definitions into a dedicated pipeline repo
- preserve the current published artifact contract
- preserve the current scientific output semantics

Out of scope:
- no web-side launch refactor yet
- no Kubernetes deployment work yet

Exit criteria:
- the pipeline repo can run independently and still produce valid published artifacts
- the web repo no longer owns Nextflow workflow files

### Slice 1.2: Define a release and versioning policy

Goal:
- make pipeline launches reproducible across repos and deployments

Scope:
- define pipeline release identifiers
- define pinned runtime image expectations
- define what the web worker is allowed to reference when submitting a run

Out of scope:
- no automatic release tooling required yet

Exit criteria:
- every production launch can pin one concrete pipeline release
- "latest" is not a valid production release target

## Phase 2: Web Control Plane Cleanup

### Slice 2.1: Make launch requests fully logical

Goal:
- ensure the web side persists only logical request data

Scope:
- store request payloads such as accessions and params
- store pinned pipeline release metadata
- remove primary reliance on local executor paths in launch records

Out of scope:
- no Kubernetes job submission yet
- no object-storage import changes yet

Exit criteria:
- a pending launch row is valid without any local filesystem path assumptions
- web-side request creation does not depend on executor namespace details

### Slice 2.2: Move submission-bundle materialization to the worker

Goal:
- make the worker the owner of executor-facing file creation

Scope:
- worker creates submission bundle files
- worker assigns runtime identifiers, paths, and artifact destinations
- worker records derived runtime metadata back into the launch row

Out of scope:
- no production Kubernetes profile yet

Exit criteria:
- the web service never needs to materialize executor-facing paths
- worker-side materialization is deterministic from the logical request

## Phase 3: Worker as a First-Class Deployment Unit

### Slice 3.1: Make the worker independently deployable

Goal:
- treat the queue worker as its own production service, not a sidecar convenience

Scope:
- define a dedicated worker command
- define worker environment variables and secrets
- define worker ownership of launch claiming and status updates

Out of scope:
- no final Kubernetes executor integration yet

Exit criteria:
- the worker can run independently of the web process
- the worker has a clean, bounded responsibility set

### Slice 3.2: Add durable runtime status and log reconciliation

Goal:
- make launch visibility independent from live local files

Scope:
- record submitted job IDs and runtime identifiers
- store durable log locations or copied log artifacts
- reconcile queue state against runtime state and published manifest state

Out of scope:
- no browser-side biological import automation yet

Exit criteria:
- operator status views do not depend on reading local worker files directly
- completed and failed runs have durable log and manifest references

## Phase 4: Kubernetes-Native Execution

### Slice 4.1: Define the supported Kubernetes execution profile

Goal:
- make Kubernetes the intended production executor for pipeline launches

Scope:
- add or finalize one supported Kubernetes profile in the pipeline repo
- define required executor settings, images, and runtime expectations
- define how the workflow head job and task pods access shared storage

Out of scope:
- no automatic import yet

Exit criteria:
- one production-ready Kubernetes profile exists for the pipeline
- the profile no longer depends on Docker-daemon assumptions

### Slice 4.2: Submit workflow head jobs from the worker

Goal:
- make launch submission Kubernetes-native

Scope:
- worker creates one Kubernetes Job per requested run
- worker passes pinned pipeline release, request payload, and storage locations
- worker records the resulting job metadata

Out of scope:
- no advanced retry policy yet

Exit criteria:
- worker submission no longer depends on `docker.sock`
- launch requests can be mapped cleanly to Kubernetes jobs

### Slice 4.3: Standardize the storage contract

Goal:
- separate transient execution state from durable integration artifacts

Scope:
- define executor-visible working storage
- define durable artifact storage for submission bundles, logs, manifests, and `publish/`
- define the path or URI conventions used by the worker and importer

Out of scope:
- no analytics or browser changes beyond what import requires

Exit criteria:
- workflow execution and published artifact access use one documented storage contract
- imports can target durable artifact locations rather than transient work paths

## Phase 5: Import from Durable Artifacts

### Slice 5.1: Make `publish_uri` a first-class import source

Goal:
- decouple browser ingestion from local filesystem assumptions

Scope:
- support import from durable published artifact locations
- preserve the current provenance-first browser model
- keep import validation focused on the published artifact contract

Out of scope:
- no automatic import trigger yet

Exit criteria:
- imported runs can come from durable artifact locations without local ad hoc path tricks
- import semantics remain unchanged from the browser’s point of view

### Slice 5.2: Optional post-success import automation

Goal:
- reduce operator friction after the core launch path is stable

Scope:
- optionally trigger an import after manifest-confirmed success
- keep import explicit in failure and conflict scenarios
- record whether a launch has been imported

Out of scope:
- no destructive merge or overwrite behavior

Exit criteria:
- import automation is optional, explicit, and auditable
- launch state and import state remain distinguishable

## Phase 6: Operational Hardening

### Slice 6.1: Security, RBAC, and secret boundaries

Goal:
- lock down the runtime boundaries for production

Scope:
- define web, worker, and workflow service-account permissions
- define secret ownership and injection points
- ensure the web service does not hold workflow execution privileges

Out of scope:
- no feature expansion

Exit criteria:
- the production permission model is documented and enforceable
- the worker is the only application component allowed to submit workflow execution

### Slice 6.2: Reliability and observability

Goal:
- make failures diagnosable and retries controlled

Scope:
- add launch retry and backoff rules
- define idempotency expectations
- expose durable status, logs, and manifest inspection
- add alerting and audit-trail expectations

Out of scope:
- no new scientific features

Exit criteria:
- operators can diagnose failed launches without inspecting transient local state
- retries do not violate pinned-release reproducibility

## Recommended Implementation Order

Implement in this order:

1. Slice 0.1
2. Slice 0.2
3. Slice 1.1
4. Slice 1.2
5. Slice 2.1
6. Slice 2.2
7. Slice 3.1
8. Slice 3.2
9. Slice 4.1
10. Slice 4.2
11. Slice 4.3
12. Slice 5.1
13. Slice 5.2
14. Slice 6.1
15. Slice 6.2

This order keeps risk low:

- contracts land before code motion
- repository boundaries land before deployment-specific work
- the worker boundary is made correct before executor migration
- Kubernetes execution lands before import automation
- hardening happens only after the architectural seams are stable

## Definition of Done

The production architecture migration should be considered complete when:

- the pipeline lives in its own repository
- the web repository no longer owns workflow orchestration code
- launch requests are logical and pinned to one pipeline release
- the worker is independently deployable
- workflow execution is Kubernetes-native
- durable artifacts, not transient work dirs, are the import boundary
- the web service has no workflow execution privileges
- operators can launch, monitor, and import runs through durable status and artifact references
