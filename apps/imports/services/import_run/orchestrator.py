from __future__ import annotations

from django.utils import timezone

from apps.browser.models.runs import PipelineRun
from apps.imports.models import ImportBatch
from apps.imports.services.published_run import (
    ImportContractError,
    InspectedPublishedRun,
    iter_codon_usage_artifact_rows,
    iter_accession_call_count_rows,
    iter_accession_status_rows,
    iter_repeat_call_rows,
    iter_run_parameter_rows,
)

from .entities import (
    _create_acquisition_batches,
    _create_call_linked_entities_for_batches,
    _create_genomes,
    _create_repeat_calls_streamed,
    _create_repeat_call_codon_usages_streamed,
    _delete_run_scoped_rows,
    _load_genome_rows,
    _update_genome_analyzed_protein_counts,
)
from .operational import (
    _create_accession_call_count_rows_streamed,
    _create_accession_status_rows_streamed,
    _create_download_manifest_entries_streamed,
    _create_normalization_warning_rows_streamed,
    _create_run_parameters_streamed,
)
from .prepare import PreparedStreamedImportData
from .state import _ImportBatchStateReporter
from .taxonomy import _load_taxonomy_rows, _rebuild_taxon_closure, _upsert_taxa


def _upsert_pipeline_run(run_payload: dict[str, object], *, replace_existing: bool) -> PipelineRun:
    existing_run = PipelineRun.objects.filter(run_id=run_payload["run_id"]).first()
    if existing_run and not replace_existing:
        raise ImportContractError(
            f"Run {run_payload['run_id']!r} already exists. Re-run with --replace-existing to replace it."
        )

    if existing_run:
        _delete_run_scoped_rows(existing_run)
        pipeline_run = existing_run
        for field_name, value in run_payload.items():
            setattr(pipeline_run, field_name, value)
        pipeline_run.imported_at = timezone.now()
        pipeline_run.save()
        return pipeline_run

    return PipelineRun.objects.create(**run_payload)


def _import_inspected_run(
    batch: ImportBatch,
    inspected: InspectedPublishedRun,
    prepared: PreparedStreamedImportData,
    *,
    replace_existing: bool,
    reporter: _ImportBatchStateReporter | None = None,
) -> tuple[PipelineRun, dict[str, int]]:
    pipeline_run = _upsert_pipeline_run(inspected.pipeline_run, replace_existing=replace_existing)

    taxonomy_rows = _load_taxonomy_rows(inspected)
    genome_rows = _load_genome_rows(inspected)
    taxon_by_taxon_id = _upsert_taxa(taxonomy_rows)
    _rebuild_taxon_closure()
    batch_by_batch_id = _create_acquisition_batches(
        pipeline_run,
        inspected.artifact_paths.acquisition_batches,
    )
    genome_by_genome_id = _create_genomes(
        pipeline_run,
        genome_rows,
        batch_by_batch_id,
        taxon_by_taxon_id,
    )

    sequence_count, sequence_by_sequence_id, protein_count, protein_by_protein_id, analyzed_protein_counts = (
        _create_call_linked_entities_for_batches(
            batch,
            pipeline_run,
            inspected,
            prepared,
            genome_by_genome_id,
            taxon_by_taxon_id,
            batch_by_batch_id,
            reporter=reporter,
        )
    )
    _update_genome_analyzed_protein_counts(genome_by_genome_id, analyzed_protein_counts)

    run_parameter_count = _create_run_parameters_streamed(
        pipeline_run,
        iter_run_parameter_rows(inspected.artifact_paths.run_params_tsv),
    )
    download_manifest_count = _create_download_manifest_entries_streamed(
        batch,
        pipeline_run,
        inspected.artifact_paths.acquisition_batches,
        batch_by_batch_id,
        reporter=reporter,
    )
    normalization_warning_count = _create_normalization_warning_rows_streamed(
        batch,
        pipeline_run,
        inspected.artifact_paths.acquisition_batches,
        batch_by_batch_id,
        reporter=reporter,
    )
    repeat_call_count = _create_repeat_calls_streamed(
        batch,
        pipeline_run,
        iter_repeat_call_rows(inspected.artifact_paths.repeat_calls_tsv),
        genome_by_genome_id,
        sequence_by_sequence_id,
        protein_by_protein_id,
        taxon_by_taxon_id,
        reporter=reporter,
    )
    repeat_call_codon_usage_count = _create_repeat_call_codon_usages_streamed(
        batch,
        pipeline_run,
        iter_codon_usage_artifact_rows(inspected.artifact_paths.codon_usage_artifacts),
        reporter=reporter,
    )
    accession_status_count = _create_accession_status_rows_streamed(
        pipeline_run,
        iter_accession_status_rows(inspected.artifact_paths.accession_status_tsv),
        batch_by_batch_id,
    )
    accession_call_count = _create_accession_call_count_rows_streamed(
        pipeline_run,
        iter_accession_call_count_rows(inspected.artifact_paths.accession_call_counts_tsv),
        batch_by_batch_id,
    )

    counts = {
        "acquisition_batches": len(inspected.artifact_paths.acquisition_batches),
        "taxonomy": len(taxonomy_rows),
        "genomes": len(genome_rows),
        "sequences": sequence_count,
        "proteins": protein_count,
        "download_manifest_entries": download_manifest_count,
        "normalization_warnings": normalization_warning_count,
        "accession_status_rows": accession_status_count,
        "accession_call_count_rows": accession_call_count,
        "run_parameters": run_parameter_count,
        "repeat_calls": repeat_call_count,
        "repeat_call_codon_usages": repeat_call_codon_usage_count,
    }
    return pipeline_run, counts
