from __future__ import annotations

from dataclasses import dataclass, field

from apps.browser.models import (
    AccessionCallCount,
    AccessionStatus,
    AcquisitionBatch,
    CanonicalGenome,
    CanonicalProtein,
    CanonicalRepeatCall,
    CanonicalRepeatCallCodonUsage,
    CanonicalSequence,
    DownloadManifestEntry,
    Genome,
    NormalizationWarning,
    PipelineRun,
    Protein,
    RepeatCall,
    RepeatCallCodonUsage,
    RepeatCallContext,
    RunParameter,
    Sequence,
)
from apps.imports.models import CatalogVersion, DeletionJob, ImportBatch, UploadedRun
from apps.imports.services.deletion.artifacts import ArtifactPathError, resolve_run_artifact_roots

LARGE_TABLE_WARNING_THRESHOLD = 500_000


@dataclass
class TablePlan:
    table: str
    action: str  # "delete" | "repair" | "retain" | "never_touch" | "rebuild"
    row_count: int
    estimated: bool = False
    notes: str = ""


@dataclass
class DeletionPlan:
    pipeline_run_id: int
    run_id: str
    lifecycle_status: str
    active_job_id: int | None
    tables: list[TablePlan] = field(default_factory=list)
    artifact_roots: list[str] = field(default_factory=list)
    catalog_version: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def total_rows_to_delete(self) -> int:
        return sum(t.row_count for t in self.tables if t.action == "delete")

    @property
    def total_canonical_impacted(self) -> int:
        return sum(t.row_count for t in self.tables if t.action == "repair")


def build_deletion_plan(pipeline_run: PipelineRun) -> DeletionPlan:
    """Return a read-only plan describing the full impact of deleting pipeline_run.

    Does not mutate any data. Safe to call at any point.
    """
    pk = pipeline_run.pk

    active_job = DeletionJob.objects.filter(
        pipeline_run=pipeline_run,
        status__in=[DeletionJob.Status.PENDING, DeletionJob.Status.RUNNING],
    ).first()

    tables: list[TablePlan] = []
    warnings: list[str] = []

    # --- Raw run-owned rows: DELETE (dependency order) ---

    rccu_count = RepeatCallCodonUsage.objects.filter(repeat_call__pipeline_run_id=pk).count()
    tables.append(TablePlan(
        table="browser_repeatcallcodonusage",
        action="delete",
        row_count=rccu_count,
        notes="indirect child of RepeatCall",
    ))

    rcc_count = RepeatCallContext.objects.filter(pipeline_run_id=pk).count()
    tables.append(TablePlan(
        table="browser_repeatcallcontext",
        action="delete",
        row_count=rcc_count,
    ))

    rc_count = RepeatCall.objects.filter(pipeline_run_id=pk).count()
    tables.append(TablePlan(
        table="browser_repeatcall",
        action="delete",
        row_count=rc_count,
    ))

    dme_count = DownloadManifestEntry.objects.filter(pipeline_run_id=pk).count()
    tables.append(TablePlan(
        table="browser_downloadmanifestentry",
        action="delete",
        row_count=dme_count,
    ))

    nw_count = NormalizationWarning.objects.filter(pipeline_run_id=pk).count()
    tables.append(TablePlan(
        table="browser_normalizationwarning",
        action="delete",
        row_count=nw_count,
    ))

    as_count = AccessionStatus.objects.filter(pipeline_run_id=pk).count()
    tables.append(TablePlan(
        table="browser_accessionstatus",
        action="delete",
        row_count=as_count,
    ))

    acc_count = AccessionCallCount.objects.filter(pipeline_run_id=pk).count()
    tables.append(TablePlan(
        table="browser_accessioncallcount",
        action="delete",
        row_count=acc_count,
    ))

    prot_count = Protein.objects.filter(pipeline_run_id=pk).count()
    tables.append(TablePlan(
        table="browser_protein",
        action="delete",
        row_count=prot_count,
    ))

    seq_count = Sequence.objects.filter(pipeline_run_id=pk).count()
    tables.append(TablePlan(
        table="browser_sequence",
        action="delete",
        row_count=seq_count,
    ))

    genome_count = Genome.objects.filter(pipeline_run_id=pk).count()
    tables.append(TablePlan(
        table="browser_genome",
        action="delete",
        row_count=genome_count,
    ))

    rp_count = RunParameter.objects.filter(pipeline_run_id=pk).count()
    tables.append(TablePlan(
        table="browser_runparameter",
        action="delete",
        row_count=rp_count,
    ))

    ab_count = AcquisitionBatch.objects.filter(pipeline_run_id=pk).count()
    tables.append(TablePlan(
        table="browser_acquisitionbatch",
        action="delete",
        row_count=ab_count,
        notes="deleted last; all PROTECT references must be cleared first",
    ))

    # --- Canonical rows: REPAIR or DELETE ---

    cg_count = CanonicalGenome.objects.filter(latest_pipeline_run_id=pk).count()
    tables.append(TablePlan(
        table="browser_canonicalgenome",
        action="repair",
        row_count=cg_count,
        notes="promote to active predecessor or delete",
    ))

    cseq_count = CanonicalSequence.objects.filter(latest_pipeline_run_id=pk).count()
    tables.append(TablePlan(
        table="browser_canonicalsequence",
        action="repair",
        row_count=cseq_count,
        notes="promote to active predecessor or delete",
    ))

    cprot_count = CanonicalProtein.objects.filter(latest_pipeline_run_id=pk).count()
    tables.append(TablePlan(
        table="browser_canonicalprotein",
        action="repair",
        row_count=cprot_count,
        notes="promote to active predecessor or delete",
    ))

    crc_count = CanonicalRepeatCall.objects.filter(latest_pipeline_run_id=pk).count()
    tables.append(TablePlan(
        table="browser_canonicalrepeatcall",
        action="repair",
        row_count=crc_count,
        notes="promote to active predecessor or delete",
    ))

    crccu_count = CanonicalRepeatCallCodonUsage.objects.filter(
        repeat_call__latest_pipeline_run_id=pk
    ).count()
    tables.append(TablePlan(
        table="browser_canonicalrepeatcallcodonusage",
        action="repair",
        row_count=crccu_count,
        notes="cascades from CanonicalRepeatCall deletion",
    ))

    # --- Rollup tables: REBUILD ---

    tables.append(TablePlan(
        table="browser_canonicalcodoncompositionsummary",
        action="rebuild",
        row_count=0,
        notes="fully rebuilt after canonical repair",
    ))
    tables.append(TablePlan(
        table="browser_canonicalcodoncompositionlengthsummary",
        action="rebuild",
        row_count=0,
        notes="fully rebuilt after canonical repair",
    ))

    # --- Audit/import rows: RETAIN ---

    import_batch_count = ImportBatch.objects.filter(pipeline_run=pipeline_run).count()
    tables.append(TablePlan(
        table="imports_importbatch",
        action="retain",
        row_count=import_batch_count,
        notes="audit trail; FK set to NULL on PipelineRun tombstone",
    ))

    uploaded_run_count = UploadedRun.objects.filter(run_id=pipeline_run.run_id).count()
    tables.append(TablePlan(
        table="imports_uploadedrun",
        action="retain",
        row_count=uploaded_run_count,
        notes="upload audit; linked by run_id string only",
    ))

    tables.append(TablePlan(
        table="browser_pipelinerun",
        action="retain",
        row_count=1,
        notes="kept as tombstone with lifecycle_status=deleted",
    ))

    # --- Shared/global: NEVER TOUCH ---

    tables.append(TablePlan(
        table="browser_taxon",
        action="never_touch",
        row_count=0,
        notes="global reference data",
    ))
    tables.append(TablePlan(
        table="browser_taxonclosure",
        action="never_touch",
        row_count=0,
        notes="global reference data",
    ))

    # --- Warnings for large tables ---

    for t in tables:
        if t.action == "delete" and t.row_count >= LARGE_TABLE_WARNING_THRESHOLD:
            warnings.append(
                f"Large delete: {t.table} has {t.row_count:,} rows — "
                "ensure chunk size and lock_timeout are tuned on staging before running."
            )

    # --- Artifact roots ---

    artifact_roots: list[str] = []
    try:
        artifact_roots = [str(p) for p in resolve_run_artifact_roots(pipeline_run)]
    except ArtifactPathError as exc:
        warnings.append(f"Artifact path safety check failed: {exc}")

    catalog_version = CatalogVersion.current()

    return DeletionPlan(
        pipeline_run_id=pipeline_run.pk,
        run_id=pipeline_run.run_id,
        lifecycle_status=pipeline_run.lifecycle_status,
        active_job_id=active_job.pk if active_job else None,
        tables=tables,
        artifact_roots=artifact_roots,
        catalog_version=catalog_version,
        warnings=warnings,
    )
