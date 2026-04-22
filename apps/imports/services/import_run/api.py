from __future__ import annotations

from pathlib import Path

from django.db import connection, transaction

from apps.browser.catalog import sync_canonical_catalog_for_run
from apps.browser.metadata import build_browser_metadata
from apps.browser.models import (
    CanonicalCodonCompositionSummary,
    CanonicalGenome,
    CanonicalProtein,
    CanonicalRepeatCall,
    CanonicalRepeatCallCodonUsage,
    CanonicalSequence,
)
from apps.browser.models.genomes import Protein, Sequence
from apps.browser.models.operations import NormalizationWarning
from apps.browser.models.repeat_calls import RepeatCall, RepeatCallCodonUsage
from apps.imports.models import ImportBatch
from apps.imports.services.published_run import ImportContractError, inspect_published_run

from .copy import _analyze_models
from .orchestrator import _import_inspected_run
from .postgresql import _import_inspected_run_postgresql
from .prepare import _prepare_streamed_import_data
from .state import (
    ImportPhase,
    ImportRunResult,
    _ImportBatchStateReporter,
    _claim_import_batch,
    _mark_batch_completed,
    _mark_batch_failed,
    _set_batch_state,
)


def enqueue_published_run(publish_root: Path | str, *, replace_existing: bool = False) -> ImportBatch:
    source_path = str(Path(publish_root).resolve())
    return ImportBatch.objects.create(
        source_path=source_path,
        status=ImportBatch.Status.PENDING,
        replace_existing=replace_existing,
        phase=ImportPhase.QUEUED,
        progress_payload={
            "message": "Queued for background import.",
        },
    )


def import_published_run(publish_root: Path | str, *, replace_existing: bool = False) -> ImportRunResult:
    batch = enqueue_published_run(
        publish_root,
        replace_existing=replace_existing,
    )
    return process_import_batch(batch)


def process_next_pending_import_batch() -> ImportRunResult | None:
    batch = ImportBatch.objects.filter(status=ImportBatch.Status.PENDING).order_by("started_at", "pk").first()
    if batch is None:
        return None
    return process_import_batch(batch)


def process_import_batch(batch_or_id: ImportBatch | int) -> ImportRunResult:
    batch = _claim_import_batch(batch_or_id)
    reporter = _ImportBatchStateReporter(batch)
    pipeline_run = None
    counts = None

    try:
        _set_batch_state(
            batch,
            phase=ImportPhase.PARSING,
            progress_payload={
                "message": "Parsing published raw artifacts.",
            },
            reporter=reporter,
        )
        inspected = inspect_published_run(batch.source_path)
        _set_batch_state(
            batch,
            phase=ImportPhase.PREPARING,
            progress_payload={
                "message": "Preparing repeat-linked import rows.",
                "batch_count": len(inspected.artifact_paths.acquisition_batches),
            },
            reporter=reporter,
        )
        if connection.vendor == "postgresql":
            _set_batch_state(
                batch,
                phase=ImportPhase.IMPORTING,
                progress_payload={
                    "message": "Writing staged rows into PostgreSQL.",
                    "batch_count": len(inspected.artifact_paths.acquisition_batches),
                },
                reporter=reporter,
            )
            with transaction.atomic():
                pipeline_run, counts = _import_inspected_run_postgresql(
                    batch,
                    inspected,
                    replace_existing=batch.replace_existing,
                    reporter=reporter,
                )
                pipeline_run.browser_metadata = build_browser_metadata(
                    pipeline_run,
                    raw_counts=counts,
                )
                pipeline_run.save(update_fields=["browser_metadata"])
                batch.pipeline_run = pipeline_run
                batch.save(update_fields=["pipeline_run"])
        else:
            prepared = _prepare_streamed_import_data(batch, inspected, reporter=reporter)
            _set_batch_state(
                batch,
                phase=ImportPhase.IMPORTING,
                progress_payload={
                    "message": "Writing streamed rows into the database transaction.",
                    "batch_count": len(inspected.artifact_paths.acquisition_batches),
                    "retained_sequences": len(prepared.retained_sequence_ids),
                    "retained_proteins": len(prepared.retained_protein_ids),
                    "repeat_calls": prepared.total_repeat_calls,
                },
                reporter=reporter,
            )
            with transaction.atomic():
                pipeline_run, counts = _import_inspected_run(
                    batch,
                    inspected,
                    prepared,
                    replace_existing=batch.replace_existing,
                    reporter=reporter,
                )
                pipeline_run.browser_metadata = build_browser_metadata(
                    pipeline_run,
                    raw_counts=counts,
                )
                pipeline_run.save(update_fields=["browser_metadata"])
                batch.pipeline_run = pipeline_run
                batch.save(update_fields=["pipeline_run"])
            del prepared
        _set_batch_state(
            batch,
            phase=ImportPhase.CATALOG_SYNC,
            progress_payload={
                "message": "Syncing canonical catalog rows.",
                "counts": counts,
            },
            reporter=reporter,
            force=True,
        )
        sync_canonical_catalog_for_run(
            pipeline_run,
            import_batch=batch,
            replace_all_repeat_call_methods=batch.replace_existing,
            reporter=reporter,
        )
        _set_batch_state(
            batch,
            phase=ImportPhase.CATALOG_SYNC,
            progress_payload={
                "message": "Analyzing bulk-loaded tables.",
                "counts": counts,
            },
            reporter=reporter,
            force=True,
        )
        _analyze_models(
            [
                Sequence,
                Protein,
                RepeatCall,
                RepeatCallCodonUsage,
                NormalizationWarning,
                CanonicalGenome,
                CanonicalSequence,
                CanonicalProtein,
                CanonicalRepeatCall,
                CanonicalRepeatCallCodonUsage,
                CanonicalCodonCompositionSummary,
            ]
        )
    except Exception as exc:
        _mark_batch_failed(batch, exc, reporter=reporter)
        if isinstance(exc, ImportContractError):
            raise ImportContractError(f"Import failed for {batch.source_path}: {exc}") from exc
        raise
    else:
        _mark_batch_completed(batch, pipeline_run, counts, reporter=reporter)
        return ImportRunResult(batch=batch, pipeline_run=pipeline_run, counts=counts)
    finally:
        reporter.close()
