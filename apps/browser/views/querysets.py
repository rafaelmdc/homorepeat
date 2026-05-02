from django.db.models import Count, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Cast, Coalesce

from apps.imports.models import ImportBatch

from ..models import (
    AccessionCallCount,
    AccessionStatus,
    AcquisitionBatch,
    CanonicalGenome,
    CanonicalProtein,
    CanonicalRepeatCall,
    CanonicalSequence,
    DownloadManifestEntry,
    Genome,
    NormalizationWarning,
    PipelineRun,
    Protein,
    RepeatCall,
    RunParameter,
    Sequence,
)


def _annotated_runs(queryset=None):
    if queryset is None:
        queryset = PipelineRun.objects.active()
    return queryset.annotate(
        acquisition_batches_count=Coalesce(_count_subquery(AcquisitionBatch, "pipeline_run"), Value(0)),
        current_accessions_count=Coalesce(_count_subquery(CanonicalGenome, "latest_pipeline_run"), Value(0)),
        current_sequences_count=Coalesce(_count_subquery(CanonicalSequence, "latest_pipeline_run"), Value(0)),
        current_proteins_count=Coalesce(_count_subquery(CanonicalProtein, "latest_pipeline_run"), Value(0)),
        current_repeat_calls_count=Coalesce(_count_subquery(CanonicalRepeatCall, "latest_pipeline_run"), Value(0)),
        download_manifest_entries_count=Coalesce(_count_subquery(DownloadManifestEntry, "pipeline_run"), Value(0)),
        genomes_count=Coalesce(_count_subquery(Genome, "pipeline_run"), Value(0)),
        normalization_warnings_count=Coalesce(_count_subquery(NormalizationWarning, "pipeline_run"), Value(0)),
        sequences_count=Coalesce(_count_subquery(Sequence, "pipeline_run"), Value(0)),
        proteins_count=Coalesce(_count_subquery(Protein, "pipeline_run"), Value(0)),
        repeat_calls_count=Coalesce(_count_subquery(RepeatCall, "pipeline_run"), Value(0)),
        accession_status_rows_count=Coalesce(_count_subquery(AccessionStatus, "pipeline_run"), Value(0)),
        accession_call_count_rows_count=Coalesce(_count_subquery(AccessionCallCount, "pipeline_run"), Value(0)),
        run_parameters_count=Coalesce(_count_subquery(RunParameter, "pipeline_run"), Value(0)),
    )


def _summary_runs(queryset=None):
    if queryset is None:
        queryset = PipelineRun.objects.active()
    return queryset.annotate(
        genomes_count=_run_summary_count_annotation("genomes"),
        sequences_count=_run_summary_count_annotation("sequences"),
        proteins_count=_run_summary_count_annotation("proteins"),
        repeat_calls_count=_run_summary_count_annotation("repeat_calls"),
    )


def _annotated_batches(queryset=None):
    if queryset is None:
        queryset = AcquisitionBatch.objects.all()
    return queryset.annotate(
        genomes_count=Coalesce(_count_subquery(Genome, "batch"), Value(0)),
        sequences_count=Coalesce(_count_subquery(Sequence, "genome__batch", group_field_name="genome__batch"), Value(0)),
        proteins_count=Coalesce(_count_subquery(Protein, "genome__batch", group_field_name="genome__batch"), Value(0)),
        repeat_calls_count=Coalesce(
            _count_subquery(RepeatCall, "genome__batch", group_field_name="genome__batch"),
            Value(0),
        ),
        download_manifest_entries_count=Coalesce(_count_subquery(DownloadManifestEntry, "batch"), Value(0)),
        normalization_warnings_count=Coalesce(_count_subquery(NormalizationWarning, "batch"), Value(0)),
        accession_status_rows_count=Coalesce(_count_subquery(AccessionStatus, "batch"), Value(0)),
        accession_call_count_rows_count=Coalesce(_count_subquery(AccessionCallCount, "batch"), Value(0)),
    )


def _run_summary_count_annotation(count_key: str):
    return Coalesce(
        Cast(f"browser_metadata__raw_counts__{count_key}", IntegerField()),
        _latest_completed_import_batch_row_count_subquery(count_key),
        output_field=IntegerField(),
    )


def _latest_completed_import_batch_row_count_subquery(count_key: str):
    filters = Q(pipeline_run=OuterRef("pk")) | Q(source_path=OuterRef("publish_root"))
    return Subquery(
        ImportBatch.objects.filter(filters, status=ImportBatch.Status.COMPLETED)
        .order_by("-finished_at", "-started_at", "-pk")
        .annotate(row_count_value=Cast(f"row_counts__{count_key}", IntegerField()))
        .values("row_count_value")[:1],
        output_field=IntegerField(),
    )


def _annotated_genomes(queryset=None):
    if queryset is None:
        queryset = Genome.objects.all()
    return queryset.annotate(
        sequences_count=Coalesce(_count_subquery(Sequence, "genome"), Value(0)),
        proteins_count=Coalesce(_count_subquery(Protein, "genome"), Value(0)),
        repeat_calls_count=Coalesce(_count_subquery(RepeatCall, "genome"), Value(0)),
    )


def _annotated_sequences(queryset=None):
    if queryset is None:
        queryset = Sequence.objects.all()
    return queryset.annotate(
        proteins_count=Coalesce(_count_subquery(Protein, "sequence"), Value(0)),
        repeat_calls_count=Coalesce(_count_subquery(RepeatCall, "sequence"), Value(0)),
    )


def _annotated_proteins(queryset=None):
    if queryset is None:
        queryset = Protein.objects.all()
    return queryset.annotate(
        repeat_calls_count=Coalesce(_count_subquery(RepeatCall, "protein"), Value(0)),
    )


def _count_subquery(model, field_name, *, group_field_name=None):
    if group_field_name is None:
        group_field_name = field_name
    return Subquery(
        model.objects.filter(**{field_name: OuterRef("pk")})
        .order_by()
        .values(group_field_name)
        .annotate(total=Count("pk"))
        .values("total")[:1],
        output_field=IntegerField(),
    )
