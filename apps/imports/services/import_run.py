from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from time import monotonic
from typing import Iterable

from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.utils import timezone

from apps.browser.models import (
    AccessionCallCount,
    AccessionStatus,
    AcquisitionBatch,
    DownloadManifestEntry,
    Genome,
    NormalizationWarning,
    PipelineRun,
    Protein,
    RepeatCall,
    RunParameter,
    Sequence,
    Taxon,
    TaxonClosure,
)
from apps.imports.models import ImportBatch

from .published_run import (
    BatchArtifactPaths,
    ImportContractError,
    InspectedPublishedRun,
    ParsedPublishedRun,
    inspect_published_run,
    iter_accession_call_count_rows,
    iter_accession_status_rows,
    iter_download_manifest_rows,
    iter_genome_rows,
    iter_normalization_warning_rows,
    iter_protein_rows,
    iter_repeat_call_rows,
    iter_run_parameter_rows,
    iter_sequence_rows,
    iter_taxonomy_rows,
    load_published_run,
)


BULK_CREATE_BATCH_SIZE = 5000
COPY_FLUSH_ROW_COUNT = 10000
HEARTBEAT_FLUSH_INTERVAL_SECONDS = 2.0


@dataclass(frozen=True)
class ImportRunResult:
    batch: ImportBatch
    pipeline_run: PipelineRun
    counts: dict[str, int]


@dataclass(frozen=True)
class PreparedImportData:
    retained_sequence_rows: list[dict[str, object]]
    retained_protein_rows: list[dict[str, object]]
    nucleotide_sequences_by_id: dict[str, str]
    amino_acid_sequences_by_id: dict[str, str]
    analyzed_protein_counts: dict[str, int]
    repeat_call_counts_by_protein: dict[str, int]


@dataclass(frozen=True)
class PreparedStreamedImportData:
    retained_genome_ids: frozenset[str]
    retained_sequence_ids: frozenset[str]
    retained_protein_ids: frozenset[str]
    repeat_call_counts_by_protein: dict[str, int]
    total_repeat_calls: int


class ImportPhase:
    QUEUED = "queued"
    PARSING = "parsing_contract"
    PREPARING = "preparing_import"
    LOADING_FASTA = "loading_fasta"
    IMPORTING = "importing_rows"
    COMPLETED = "completed"
    FAILED = "failed"


class _ImportBatchStateReporter:
    def __init__(self, batch: ImportBatch) -> None:
        self.batch = batch
        self.connection = None
        self.last_flush_at = 0.0

        default_connection = connections[DEFAULT_DB_ALIAS]
        if default_connection.vendor != "postgresql":
            return

        self.connection = default_connection.copy()
        self.connection.ensure_connection()
        self.connection.set_autocommit(True)

    def save(self, update_fields: list[str], *, force: bool = False) -> None:
        if self.connection is None:
            self.batch.save(update_fields=update_fields)
            return

        now = monotonic()
        if not force and (now - self.last_flush_at) < HEARTBEAT_FLUSH_INTERVAL_SECONDS:
            return

        quoted_table = self.connection.ops.quote_name(self.batch._meta.db_table)
        quoted_pk = self.connection.ops.quote_name(self.batch._meta.pk.column)
        assignments: list[str] = []
        params: list[object] = []

        for field_name in update_fields:
            field = self.batch._meta.get_field(field_name)
            assignments.append(f"{self.connection.ops.quote_name(field.column)} = %s")
            params.append(
                field.get_db_prep_save(
                    getattr(self.batch, field.attname),
                    connection=self.connection,
                )
            )

        params.append(self.batch.pk)
        sql = f"UPDATE {quoted_table} SET {', '.join(assignments)} WHERE {quoted_pk} = %s"
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
        self.last_flush_at = now

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None


def _copy_rows_to_model(
    model,
    field_names: list[str],
    rows: Iterable[tuple[object, ...]],
    *,
    batch: ImportBatch | None = None,
    reporter: _ImportBatchStateReporter | None = None,
    progress_message: str = "",
    progress_key: str = "rows",
    extra_progress: dict[str, object] | None = None,
) -> int | None:
    connection = connections[DEFAULT_DB_ALIAS]
    if connection.vendor != "postgresql":
        return None

    connection.ensure_connection()
    with connection.cursor() as cursor_wrapper:
        raw_cursor = getattr(cursor_wrapper, "cursor", None)
        if raw_cursor is None or not hasattr(raw_cursor, "copy"):
            return None

        quoted_table = connection.ops.quote_name(model._meta.db_table)
        quoted_columns = ", ".join(
            connection.ops.quote_name(model._meta.get_field(field_name).column)
            for field_name in field_names
        )
        count = 0
        buffer = StringIO()
        writer = csv.writer(
            buffer,
            delimiter="\t",
            quotechar='"',
            lineterminator="\n",
            quoting=csv.QUOTE_MINIMAL,
        )

        def flush_buffer(copy) -> None:
            payload = buffer.getvalue()
            if not payload:
                return
            copy.write(payload)
            buffer.seek(0)
            buffer.truncate(0)

        with raw_cursor.copy(
            f"COPY {quoted_table} ({quoted_columns}) FROM STDIN WITH (FORMAT CSV, DELIMITER E'\\t', NULL '\\N')"
        ) as copy:
            for row in rows:
                writer.writerow(_serialize_copy_row(row))
                count += 1
                if count % COPY_FLUSH_ROW_COUNT == 0:
                    flush_buffer(copy)
                if batch is not None and reporter is not None and count % BULK_CREATE_BATCH_SIZE == 0:
                    progress_payload = {progress_key: count}
                    if extra_progress:
                        progress_payload.update(extra_progress)
                    progress_payload["message"] = progress_message
                    _set_batch_state(
                        batch,
                        phase=ImportPhase.IMPORTING,
                        progress_payload=progress_payload,
                        reporter=reporter,
                    )
            flush_buffer(copy)

    if batch is not None and reporter is not None:
        progress_payload = {progress_key: count}
        if extra_progress:
            progress_payload.update(extra_progress)
        progress_payload["message"] = progress_message
        _set_batch_state(
            batch,
            phase=ImportPhase.IMPORTING,
            progress_payload=progress_payload,
            reporter=reporter,
            force=True,
        )
    return count


def _serialize_copy_row(row: tuple[object, ...]) -> tuple[str, ...]:
    return tuple(_serialize_copy_value(value) for value in row)


def _serialize_copy_value(value: object) -> str:
    if value is None:
        return r"\N"
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat(sep=" ")
        except TypeError:
            return value.isoformat()
    return str(value)


def _analyze_models(models: Iterable[type]) -> bool:
    connection = connections[DEFAULT_DB_ALIAS]
    if connection.vendor != "postgresql":
        return False
    try:
        with connection.cursor() as cursor:
            for model in models:
                cursor.execute(f"ANALYZE {connection.ops.quote_name(model._meta.db_table)}")
    except Exception:
        return False
    return True


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
        _set_batch_state(
            batch,
            phase=ImportPhase.IMPORTING,
            progress_payload={
                "message": "Analyzing bulk-loaded tables.",
                "counts": counts,
            },
            reporter=reporter,
            force=True,
        )
        _analyze_models([Sequence, Protein, RepeatCall, NormalizationWarning])
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


def _claim_import_batch(batch_or_id: ImportBatch | int) -> ImportBatch:
    batch_id = batch_or_id.pk if isinstance(batch_or_id, ImportBatch) else int(batch_or_id)
    with transaction.atomic():
        batch = ImportBatch.objects.select_for_update().get(pk=batch_id)
        if batch.status != ImportBatch.Status.PENDING:
            raise ImportContractError(
                f"Import batch {batch.pk} is {batch.status!r} and cannot be claimed for processing."
            )
        batch.status = ImportBatch.Status.RUNNING
        batch.phase = ImportPhase.PARSING
        batch.heartbeat_at = timezone.now()
        batch.progress_payload = {
            "message": "Worker claimed queued import batch.",
        }
        batch.error_message = ""
        batch.save(
            update_fields=[
                "status",
                "phase",
                "heartbeat_at",
                "progress_payload",
                "error_message",
            ]
        )
    return batch


def _set_batch_state(
    batch: ImportBatch,
    *,
    phase: str,
    progress_payload: dict[str, object],
    reporter: _ImportBatchStateReporter | None = None,
    force: bool = False,
) -> None:
    phase_changed = batch.phase != phase
    batch.phase = phase
    batch.heartbeat_at = timezone.now()
    batch.progress_payload = progress_payload
    if reporter is None:
        batch.save(update_fields=["phase", "heartbeat_at", "progress_payload"])
        return
    reporter.save(
        ["phase", "heartbeat_at", "progress_payload"],
        force=force or phase_changed,
    )


def _mark_batch_failed(
    batch: ImportBatch,
    exc: Exception,
    *,
    reporter: _ImportBatchStateReporter | None = None,
) -> None:
    batch.status = ImportBatch.Status.FAILED
    batch.phase = ImportPhase.FAILED
    batch.finished_at = timezone.now()
    batch.heartbeat_at = batch.finished_at
    batch.error_count = 1
    batch.row_counts = {}
    batch.progress_payload = {
        "message": "Import failed.",
    }
    batch.error_message = str(exc)
    update_fields = [
        "status",
        "phase",
        "finished_at",
        "heartbeat_at",
        "error_count",
        "row_counts",
        "progress_payload",
        "error_message",
    ]
    if reporter is None:
        batch.save(update_fields=update_fields)
        return
    reporter.save(update_fields, force=True)


def _mark_batch_completed(
    batch: ImportBatch,
    pipeline_run: PipelineRun,
    counts: dict[str, int],
    *,
    reporter: _ImportBatchStateReporter | None = None,
) -> None:
    finished_at = timezone.now()
    batch.pipeline_run = pipeline_run
    batch.status = ImportBatch.Status.COMPLETED
    batch.phase = ImportPhase.COMPLETED
    batch.finished_at = finished_at
    batch.heartbeat_at = finished_at
    batch.success_count = sum(counts.values())
    batch.error_count = 0
    batch.progress_payload = {
        "message": "Import completed successfully.",
        "counts": counts,
    }
    batch.row_counts = counts
    batch.error_message = ""
    update_fields = [
        "pipeline_run",
        "status",
        "phase",
        "finished_at",
        "heartbeat_at",
        "success_count",
        "error_count",
        "progress_payload",
        "row_counts",
        "error_message",
    ]
    if reporter is None:
        batch.save(update_fields=update_fields)
        return
    reporter.save(update_fields, force=True)


def _import_inspected_run(
    batch: ImportBatch,
    inspected: InspectedPublishedRun,
    prepared: PreparedStreamedImportData,
    *,
    replace_existing: bool,
    reporter: _ImportBatchStateReporter | None = None,
) -> tuple[PipelineRun, dict[str, int]]:
    run_payload = inspected.pipeline_run
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
    else:
        pipeline_run = PipelineRun.objects.create(**run_payload)

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
    }
    return pipeline_run, counts


def _import_parsed_run(
    parsed: ParsedPublishedRun,
    prepared: PreparedImportData,
    *,
    replace_existing: bool,
) -> tuple[PipelineRun, dict[str, int]]:
    run_payload = parsed.pipeline_run
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
    else:
        pipeline_run = PipelineRun.objects.create(**run_payload)

    taxon_by_taxon_id = _upsert_taxa(parsed.taxonomy_rows)
    _rebuild_taxon_closure()
    batch_by_batch_id = _create_acquisition_batches(pipeline_run, parsed)

    genome_by_genome_id = _create_genomes(
        pipeline_run,
        parsed.genome_rows,
        batch_by_batch_id,
        taxon_by_taxon_id,
        prepared.analyzed_protein_counts,
    )
    sequence_by_sequence_id = _create_sequences(
        pipeline_run,
        prepared.retained_sequence_rows,
        genome_by_genome_id,
        taxon_by_taxon_id,
        prepared.nucleotide_sequences_by_id,
    )
    protein_by_protein_id = _create_proteins(
        pipeline_run,
        prepared.retained_protein_rows,
        genome_by_genome_id,
        sequence_by_sequence_id,
        taxon_by_taxon_id,
        prepared.amino_acid_sequences_by_id,
        prepared.repeat_call_counts_by_protein,
    )
    _create_run_parameters(pipeline_run, parsed.run_parameter_rows)
    _create_download_manifest_entries(
        pipeline_run,
        parsed.download_manifest_rows,
        batch_by_batch_id,
    )
    _create_normalization_warning_rows(
        pipeline_run,
        parsed.normalization_warning_rows,
        batch_by_batch_id,
    )
    _create_repeat_calls(
        pipeline_run,
        parsed.repeat_call_rows,
        genome_by_genome_id,
        sequence_by_sequence_id,
        protein_by_protein_id,
        taxon_by_taxon_id,
    )
    _create_accession_status_rows(
        pipeline_run,
        parsed.accession_status_rows,
        batch_by_batch_id,
    )
    _create_accession_call_count_rows(
        pipeline_run,
        parsed.accession_call_count_rows,
        batch_by_batch_id,
    )

    counts = {
        "acquisition_batches": len(parsed.artifact_paths.acquisition_batches),
        "taxonomy": len(parsed.taxonomy_rows),
        "genomes": len(parsed.genome_rows),
        "sequences": len(prepared.retained_sequence_rows),
        "proteins": len(prepared.retained_protein_rows),
        "download_manifest_entries": len(parsed.download_manifest_rows),
        "normalization_warnings": len(parsed.normalization_warning_rows),
        "accession_status_rows": len(parsed.accession_status_rows),
        "accession_call_count_rows": len(parsed.accession_call_count_rows),
        "run_parameters": len(parsed.run_parameter_rows),
        "repeat_calls": len(parsed.repeat_call_rows),
    }
    return pipeline_run, counts


def _delete_run_scoped_rows(pipeline_run: PipelineRun) -> None:
    pipeline_run.normalization_warnings.all().delete()
    pipeline_run.download_manifest_entries.all().delete()
    pipeline_run.accession_call_count_rows.all().delete()
    pipeline_run.accession_status_rows.all().delete()
    pipeline_run.run_parameters.all().delete()
    pipeline_run.genomes.all().delete()
    pipeline_run.acquisition_batches.all().delete()


def _load_taxonomy_rows(inspected: InspectedPublishedRun) -> list[dict[str, object]]:
    merged_by_taxon_id: dict[int, dict[str, object]] = {}
    ordered_taxon_ids: list[int] = []

    for batch_paths in inspected.artifact_paths.acquisition_batches:
        for row in iter_taxonomy_rows(batch_paths.taxonomy_tsv):
            taxon_id = int(row["taxon_id"])
            existing = merged_by_taxon_id.get(taxon_id)
            if existing is None:
                merged_by_taxon_id[taxon_id] = row
                ordered_taxon_ids.append(taxon_id)
                continue
            if existing != row:
                raise ImportContractError(
                    f"Conflicting duplicate taxonomy rows were found for taxon_id={taxon_id!r}"
                )

    return [merged_by_taxon_id[taxon_id] for taxon_id in ordered_taxon_ids]


def _load_genome_rows(inspected: InspectedPublishedRun) -> list[dict[str, object]]:
    merged_by_genome_id: dict[str, dict[str, object]] = {}
    ordered_genome_ids: list[str] = []

    for batch_paths in inspected.artifact_paths.acquisition_batches:
        for row in iter_genome_rows(batch_paths.genomes_tsv, batch_id=batch_paths.batch_id):
            genome_id = str(row["genome_id"])
            existing = merged_by_genome_id.get(genome_id)
            if existing is None:
                merged_by_genome_id[genome_id] = row
                ordered_genome_ids.append(genome_id)
                continue
            if existing != row:
                raise ImportContractError(
                    f"Conflicting duplicate genome rows were found for genome_id={genome_id!r}"
                )

    return [merged_by_genome_id[genome_id] for genome_id in ordered_genome_ids]


def _create_acquisition_batches(
    pipeline_run: PipelineRun,
    batch_artifact_paths: Iterable[BatchArtifactPaths] | ParsedPublishedRun,
) -> dict[str, AcquisitionBatch]:
    if isinstance(batch_artifact_paths, ParsedPublishedRun):
        batch_artifact_paths = batch_artifact_paths.artifact_paths.acquisition_batches
    AcquisitionBatch.objects.bulk_create(
        [
            AcquisitionBatch(
                pipeline_run=pipeline_run,
                batch_id=batch_paths.batch_id,
            )
            for batch_paths in batch_artifact_paths
        ],
        batch_size=BULK_CREATE_BATCH_SIZE,
    )
    return {
        batch.batch_id: batch
        for batch in AcquisitionBatch.objects.filter(pipeline_run=pipeline_run).only("id", "batch_id")
    }


def _upsert_taxa(rows: list[dict[str, object]]) -> dict[int, Taxon]:
    taxon_ids = [int(row["taxon_id"]) for row in rows]
    parent_taxon_ids = {
        int(row["parent_taxon_id"])
        for row in rows
        if row.get("parent_taxon_id") is not None
    }
    existing = Taxon.objects.in_bulk(set(taxon_ids) | parent_taxon_ids, field_name="taxon_id")

    for row in rows:
        taxon_id = int(row["taxon_id"])
        taxon = existing.get(taxon_id)
        if taxon is None:
            taxon = Taxon.objects.create(
                taxon_id=taxon_id,
                taxon_name=str(row["taxon_name"]),
                rank=str(row["rank"]),
                source=str(row["source"]),
            )
        else:
            taxon.taxon_name = str(row["taxon_name"])
            taxon.rank = str(row["rank"])
            taxon.source = str(row["source"])
            taxon.save(update_fields=["taxon_name", "rank", "source", "updated_at"])
        existing[taxon_id] = taxon

    for row in rows:
        taxon = existing[int(row["taxon_id"])]
        parent_taxon_id = row.get("parent_taxon_id")
        parent = existing.get(int(parent_taxon_id)) if parent_taxon_id is not None else None
        if parent_taxon_id is not None and parent is None:
            raise ImportContractError(
                f"Taxonomy references missing parent taxon_id {parent_taxon_id!r}"
            )
        if taxon.parent_taxon_id != (parent.pk if parent else None):
            taxon.parent_taxon = parent
            taxon.save(update_fields=["parent_taxon", "updated_at"])

    return existing


def _rebuild_taxon_closure() -> None:
    taxa = list(Taxon.objects.only("id", "parent_taxon_id"))
    by_pk = {taxon.pk: taxon for taxon in taxa}
    closure_rows: list[TaxonClosure] = []

    for descendant in taxa:
        current = descendant
        depth = 0
        seen: set[int] = set()
        while current is not None:
            if current.pk in seen:
                raise ImportContractError("Taxonomy contains a parent cycle and cannot build closure")
            seen.add(current.pk)
            closure_rows.append(
                TaxonClosure(
                    ancestor_id=current.pk,
                    descendant_id=descendant.pk,
                    depth=depth,
                )
            )
            parent_pk = current.parent_taxon_id
            if parent_pk is None:
                current = None
            else:
                current = by_pk.get(parent_pk)
                if current is None:
                    raise ImportContractError(
                        f"Taxonomy references missing parent primary key {parent_pk!r}"
                    )
                depth += 1

    TaxonClosure.objects.all().delete()
    TaxonClosure.objects.bulk_create(closure_rows, batch_size=BULK_CREATE_BATCH_SIZE)


def _create_genomes(
    pipeline_run: PipelineRun,
    rows: list[dict[str, object]],
    batch_by_batch_id: dict[str, AcquisitionBatch],
    taxon_by_taxon_id: dict[int, Taxon],
    analyzed_protein_counts: dict[str, int] | None = None,
) -> dict[str, Genome]:
    analyzed_protein_counts = analyzed_protein_counts or {}
    genome_objects: list[Genome] = []
    for row in rows:
        genome_id = str(row["genome_id"])
        batch_id = str(row.get("batch_id", ""))
        batch = batch_by_batch_id.get(batch_id)
        if batch is None:
            raise ImportContractError(f"Genome row references missing batch_id {row.get('batch_id')!r}")
        taxon = _require_taxon(row.get("taxon_id"), taxon_by_taxon_id, "genome")
        genome_objects.append(
            Genome(
                pipeline_run=pipeline_run,
                batch_id=batch.pk,
                genome_id=genome_id,
                source=str(row["source"]),
                accession=str(row["accession"]),
                genome_name=str(row["genome_name"]),
                assembly_type=str(row["assembly_type"]),
                taxon=taxon,
                assembly_level=str(row.get("assembly_level", "")),
                species_name=str(row.get("species_name", "")),
                analyzed_protein_count=0,
                notes=str(row.get("notes", "")),
            )
        )
    Genome.objects.bulk_create(genome_objects, batch_size=BULK_CREATE_BATCH_SIZE)
    return {
        genome.genome_id: genome
        for genome in Genome.objects.filter(pipeline_run=pipeline_run).only(
            "id",
            "genome_id",
            "batch_id",
            "taxon_id",
            "accession",
            "analyzed_protein_count",
        )
    }


def _update_genome_analyzed_protein_counts(
    genome_by_genome_id: dict[str, Genome],
    analyzed_protein_counts: dict[str, int],
) -> None:
    genomes_to_update: list[Genome] = []
    for genome_id, genome in genome_by_genome_id.items():
        analyzed_count = analyzed_protein_counts.get(genome_id, 0)
        if genome.analyzed_protein_count == analyzed_count:
            continue
        genome.analyzed_protein_count = analyzed_count
        genomes_to_update.append(genome)
    if genomes_to_update:
        Genome.objects.bulk_update(genomes_to_update, ["analyzed_protein_count"], batch_size=BULK_CREATE_BATCH_SIZE)


def _create_sequences(
    pipeline_run: PipelineRun,
    rows: list[dict[str, object]],
    genome_by_genome_id: dict[str, Genome],
    taxon_by_taxon_id: dict[int, Taxon],
    nucleotide_sequences_by_id: dict[str, str],
) -> dict[str, Sequence]:
    sequence_objects: list[Sequence] = []
    for row in rows:
        genome = genome_by_genome_id.get(str(row["genome_id"]))
        if genome is None:
            raise ImportContractError(
                f"Sequence row references missing genome_id {row['genome_id']!r}"
            )
        taxon_pk = _resolve_optional_taxon_pk(row.get("taxon_id"), genome.taxon_id, taxon_by_taxon_id, "sequence")
        sequence_id = str(row["sequence_id"])
        nucleotide_sequence = nucleotide_sequences_by_id.get(sequence_id)
        if nucleotide_sequence is None:
            raise ImportContractError(
                f"Sequence row references missing CDS FASTA record for sequence_id {row['sequence_id']!r}"
            )
        sequence_objects.append(
            Sequence(
                pipeline_run=pipeline_run,
                genome_id=genome.pk,
                taxon_id=taxon_pk,
                sequence_id=sequence_id,
                sequence_name=str(row["sequence_name"]),
                sequence_length=int(row["sequence_length"]),
                nucleotide_sequence=nucleotide_sequence,
                gene_symbol=str(row.get("gene_symbol", "")),
                transcript_id=str(row.get("transcript_id", "")),
                isoform_id=str(row.get("isoform_id", "")),
                assembly_accession=str(row.get("assembly_accession", "")),
                source_record_id=str(row.get("source_record_id", "")),
                protein_external_id=str(row.get("protein_external_id", "")),
                translation_table=str(row.get("translation_table", "")),
                gene_group=str(row.get("gene_group", "")),
                linkage_status=str(row.get("linkage_status", "")),
                partial_status=str(row.get("partial_status", "")),
            )
        )
    Sequence.objects.bulk_create(sequence_objects, batch_size=BULK_CREATE_BATCH_SIZE)
    return {
        sequence.sequence_id: sequence
        for sequence in Sequence.objects.filter(pipeline_run=pipeline_run).only(
            "id",
            "sequence_id",
            "genome_id",
            "taxon_id",
        )
    }


def _create_proteins(
    pipeline_run: PipelineRun,
    rows: list[dict[str, object]],
    genome_by_genome_id: dict[str, Genome],
    sequence_by_sequence_id: dict[str, Sequence],
    taxon_by_taxon_id: dict[int, Taxon],
    amino_acid_sequences_by_id: dict[str, str],
    repeat_call_counts_by_protein: dict[str, int],
) -> dict[str, Protein]:
    protein_objects: list[Protein] = []
    for row in rows:
        genome = genome_by_genome_id.get(str(row["genome_id"]))
        if genome is None:
            raise ImportContractError(
                f"Protein row references missing genome_id {row['genome_id']!r}"
            )
        sequence = sequence_by_sequence_id.get(str(row["sequence_id"]))
        if sequence is None:
            raise ImportContractError(
                f"Protein row references missing sequence_id {row['sequence_id']!r}"
            )
        taxon_pk = _resolve_optional_taxon_pk(row.get("taxon_id"), genome.taxon_id, taxon_by_taxon_id, "protein")
        protein_id = str(row["protein_id"])
        amino_acid_sequence = amino_acid_sequences_by_id.get(protein_id)
        if amino_acid_sequence is None:
            raise ImportContractError(
                f"Protein row references missing protein FASTA record for protein_id {row['protein_id']!r}"
            )
        protein_objects.append(
            Protein(
                pipeline_run=pipeline_run,
                genome_id=genome.pk,
                sequence_id=sequence.pk,
                taxon_id=taxon_pk,
                protein_id=protein_id,
                protein_name=str(row["protein_name"]),
                protein_length=int(row["protein_length"]),
                accession=str(row.get("assembly_accession") or genome.accession),
                amino_acid_sequence=amino_acid_sequence,
                gene_symbol=str(row.get("gene_symbol", "")),
                translation_method=str(row.get("translation_method", "")),
                translation_status=str(row.get("translation_status", "")),
                assembly_accession=str(row.get("assembly_accession", "")),
                gene_group=str(row.get("gene_group", "")),
                protein_external_id=str(row.get("protein_external_id", "")),
                repeat_call_count=repeat_call_counts_by_protein.get(protein_id, 0),
            )
        )
    Protein.objects.bulk_create(protein_objects, batch_size=BULK_CREATE_BATCH_SIZE)
    return {
        protein.protein_id: protein
        for protein in Protein.objects.filter(pipeline_run=pipeline_run).only(
            "id",
            "protein_id",
            "genome_id",
            "sequence_id",
            "taxon_id",
        )
    }


def _create_run_parameters(
    pipeline_run: PipelineRun,
    rows: list[dict[str, object]],
) -> None:
    RunParameter.objects.bulk_create(
        [
            RunParameter(
                pipeline_run=pipeline_run,
                method=str(row["method"]),
                repeat_residue=str(row.get("repeat_residue", "")),
                param_name=str(row["param_name"]),
                param_value=str(row["param_value"]),
            )
            for row in rows
        ],
        batch_size=BULK_CREATE_BATCH_SIZE,
    )


def _create_download_manifest_entries(
    pipeline_run: PipelineRun,
    rows: list[dict[str, object]],
    batch_by_batch_id: dict[str, AcquisitionBatch],
) -> None:
    DownloadManifestEntry.objects.bulk_create(
        [
            DownloadManifestEntry(
                pipeline_run=pipeline_run,
                batch_id=_require_batch_pk(row.get("batch_id"), batch_by_batch_id, "download manifest"),
                assembly_accession=str(row["assembly_accession"]),
                download_status=str(row.get("download_status", "")),
                package_mode=str(row.get("package_mode", "")),
                download_path=str(row.get("download_path", "")),
                rehydrated_path=str(row.get("rehydrated_path", "")),
                checksum=str(row.get("checksum", "")),
                file_size_bytes=row.get("file_size_bytes"),
                download_started_at=row.get("download_started_at"),
                download_finished_at=row.get("download_finished_at"),
                notes=str(row.get("notes", "")),
            )
            for row in rows
        ],
        batch_size=BULK_CREATE_BATCH_SIZE,
    )


def _create_normalization_warning_rows(
    pipeline_run: PipelineRun,
    rows: list[dict[str, object]],
    batch_by_batch_id: dict[str, AcquisitionBatch],
) -> None:
    NormalizationWarning.objects.bulk_create(
        [
            NormalizationWarning(
                pipeline_run=pipeline_run,
                batch_id=_require_batch_pk(row.get("batch_id"), batch_by_batch_id, "normalization warning"),
                warning_code=str(row.get("warning_code", "")),
                warning_scope=str(row.get("warning_scope", "")),
                warning_message=str(row.get("warning_message", "")),
                genome_id=str(row.get("genome_id", "")),
                sequence_id=str(row.get("sequence_id", "")),
                protein_id=str(row.get("protein_id", "")),
                assembly_accession=str(row.get("assembly_accession", "")),
                source_file=str(row.get("source_file", "")),
                source_record_id=str(row.get("source_record_id", "")),
            )
            for row in rows
        ],
        batch_size=BULK_CREATE_BATCH_SIZE,
    )


def _create_repeat_calls(
    pipeline_run: PipelineRun,
    rows: list[dict[str, object]],
    genome_by_genome_id: dict[str, Genome],
    sequence_by_sequence_id: dict[str, Sequence],
    protein_by_protein_id: dict[str, Protein],
    taxon_by_taxon_id: dict[int, Taxon],
) -> None:
    repeat_call_objects: list[RepeatCall] = []
    for row in rows:
        genome = genome_by_genome_id.get(str(row["genome_id"]))
        if genome is None:
            raise ImportContractError(
                f"Repeat call row references missing genome_id {row['genome_id']!r}"
            )
        sequence = sequence_by_sequence_id.get(str(row["sequence_id"]))
        if sequence is None:
            raise ImportContractError(
                f"Repeat call row references missing sequence_id {row['sequence_id']!r}"
            )
        protein = protein_by_protein_id.get(str(row["protein_id"]))
        if protein is None:
            raise ImportContractError(
                f"Repeat call row references missing protein_id {row['protein_id']!r}"
            )
        taxon = _require_taxon(row.get("taxon_id"), taxon_by_taxon_id, "repeat call")
        repeat_call_objects.append(
            RepeatCall(
                pipeline_run=pipeline_run,
                genome_id=genome.pk,
                sequence_id=sequence.pk,
                protein_id=protein.pk,
                taxon_id=taxon.pk,
                call_id=str(row["call_id"]),
                method=str(row["method"]),
                accession=genome.accession,
                gene_symbol=protein.gene_symbol or sequence.gene_symbol,
                protein_name=protein.protein_name,
                protein_length=protein.protein_length,
                start=int(row["start"]),
                end=int(row["end"]),
                length=int(row["length"]),
                repeat_residue=str(row["repeat_residue"]),
                repeat_count=int(row["repeat_count"]),
                non_repeat_count=int(row["non_repeat_count"]),
                purity=float(row["purity"]),
                aa_sequence=str(row["aa_sequence"]),
                codon_sequence=str(row.get("codon_sequence", "")),
                codon_metric_name=str(row.get("codon_metric_name", "")),
                codon_metric_value=str(row.get("codon_metric_value", "")),
                window_definition=str(row.get("window_definition", "")),
                template_name=str(row.get("template_name", "")),
                merge_rule=str(row.get("merge_rule", "")),
                score=str(row.get("score", "")),
            )
        )
    RepeatCall.objects.bulk_create(repeat_call_objects, batch_size=BULK_CREATE_BATCH_SIZE)


def _create_accession_status_rows(
    pipeline_run: PipelineRun,
    rows: list[dict[str, object]],
    batch_by_batch_id: dict[str, AcquisitionBatch],
) -> None:
    AccessionStatus.objects.bulk_create(
        [
            AccessionStatus(
                pipeline_run=pipeline_run,
                batch_id=_require_batch_pk(row.get("batch_id"), batch_by_batch_id, "accession status"),
                assembly_accession=str(row["assembly_accession"]),
                download_status=str(row.get("download_status", "")),
                normalize_status=str(row.get("normalize_status", "")),
                translate_status=str(row.get("translate_status", "")),
                detect_status=str(row.get("detect_status", "")),
                finalize_status=str(row.get("finalize_status", "")),
                terminal_status=str(row.get("terminal_status", "")),
                failure_stage=str(row.get("failure_stage", "")),
                failure_reason=str(row.get("failure_reason", "")),
                n_genomes=int(row.get("n_genomes", 0)),
                n_proteins=int(row.get("n_proteins", 0)),
                n_repeat_calls=int(row.get("n_repeat_calls", 0)),
                notes=str(row.get("notes", "")),
            )
            for row in rows
        ],
        batch_size=BULK_CREATE_BATCH_SIZE,
    )


def _create_accession_call_count_rows(
    pipeline_run: PipelineRun,
    rows: list[dict[str, object]],
    batch_by_batch_id: dict[str, AcquisitionBatch],
) -> None:
    AccessionCallCount.objects.bulk_create(
        [
            AccessionCallCount(
                pipeline_run=pipeline_run,
                batch_id=_require_batch_pk(row.get("batch_id"), batch_by_batch_id, "accession call count"),
                assembly_accession=str(row["assembly_accession"]),
                method=str(row["method"]),
                repeat_residue=str(row.get("repeat_residue", "")),
                detect_status=str(row.get("detect_status", "")),
                finalize_status=str(row.get("finalize_status", "")),
                n_repeat_calls=int(row.get("n_repeat_calls", 0)),
            )
            for row in rows
        ],
        batch_size=BULK_CREATE_BATCH_SIZE,
    )


def _require_taxon(
    natural_taxon_id: object,
    taxon_by_taxon_id: dict[int, Taxon],
    label: str,
) -> Taxon:
    if natural_taxon_id is None:
        raise ImportContractError(f"{label.capitalize()} row is missing a required taxon_id")
    taxon = taxon_by_taxon_id.get(int(natural_taxon_id))
    if taxon is None:
        raise ImportContractError(
            f"{label.capitalize()} row references missing taxon_id {natural_taxon_id!r}"
        )
    return taxon


def _resolve_optional_taxon_pk(
    natural_taxon_id: object,
    fallback_taxon_pk: int,
    taxon_by_taxon_id: dict[int, Taxon],
    label: str,
) -> int:
    if natural_taxon_id is None:
        return fallback_taxon_pk
    return _require_taxon(natural_taxon_id, taxon_by_taxon_id, label).pk


def _require_batch_pk(
    batch_id: object,
    batch_by_batch_id: dict[str, AcquisitionBatch],
    label: str,
) -> int:
    batch_key = str(batch_id or "")
    batch = batch_by_batch_id.get(batch_key)
    if batch is None:
        raise ImportContractError(f"{label.capitalize()} row references missing batch_id {batch_id!r}")
    return batch.pk


def _prepare_streamed_import_data(
    batch: ImportBatch,
    inspected: InspectedPublishedRun,
    *,
    reporter: _ImportBatchStateReporter | None = None,
) -> PreparedStreamedImportData:
    retained_genome_ids: set[str] = set()
    retained_sequence_ids: set[str] = set()
    retained_protein_ids: set[str] = set()
    repeat_call_counts_by_protein: dict[str, int] = {}
    total_repeat_calls = 0

    for row in iter_repeat_call_rows(inspected.artifact_paths.repeat_calls_tsv):
        genome_id = str(row["genome_id"])
        sequence_id = str(row["sequence_id"])
        protein_id = str(row["protein_id"])
        retained_genome_ids.add(genome_id)
        retained_sequence_ids.add(sequence_id)
        retained_protein_ids.add(protein_id)
        repeat_call_counts_by_protein[protein_id] = repeat_call_counts_by_protein.get(protein_id, 0) + 1
        total_repeat_calls += 1
        if total_repeat_calls % BULK_CREATE_BATCH_SIZE == 0:
            _set_batch_state(
                batch,
                phase=ImportPhase.PREPARING,
                progress_payload={
                    "message": "Scanning repeat calls to determine retained sequence and protein IDs.",
                    "batch_count": len(inspected.artifact_paths.acquisition_batches),
                    "repeat_calls": total_repeat_calls,
                    "retained_sequences": len(retained_sequence_ids),
                    "retained_proteins": len(retained_protein_ids),
                },
                reporter=reporter,
            )

    return PreparedStreamedImportData(
        retained_genome_ids=frozenset(retained_genome_ids),
        retained_sequence_ids=frozenset(retained_sequence_ids),
        retained_protein_ids=frozenset(retained_protein_ids),
        repeat_call_counts_by_protein=repeat_call_counts_by_protein,
        total_repeat_calls=total_repeat_calls,
    )


def _create_call_linked_entities_for_batches(
    batch: ImportBatch,
    pipeline_run: PipelineRun,
    inspected: InspectedPublishedRun,
    prepared: PreparedStreamedImportData,
    genome_by_genome_id: dict[str, Genome],
    taxon_by_taxon_id: dict[int, Taxon],
    batch_by_batch_id: dict[str, AcquisitionBatch],
    *,
    reporter: _ImportBatchStateReporter | None = None,
) -> tuple[int, dict[str, Sequence], int, dict[str, Protein], dict[str, int]]:
    total_sequences = 0
    total_proteins = 0
    sequence_by_sequence_id: dict[str, Sequence] = {}
    protein_by_protein_id: dict[str, Protein] = {}
    analyzed_protein_counts: dict[str, int] = {}
    retained_batch_pks = {
        genome_by_genome_id[genome_id].batch_id
        for genome_id in prepared.retained_genome_ids
        if genome_id in genome_by_genome_id
    }

    for batch_paths in inspected.artifact_paths.acquisition_batches:
        current_batch = batch_by_batch_id.get(batch_paths.batch_id)
        if current_batch is None:
            raise ImportContractError(
                f"Acquisition batch {batch_paths.batch_id!r} was not created before row import"
            )
        batch_has_retained_rows = current_batch.pk in retained_batch_pks
        batch_sequence_ids: set[str] = set()
        retained_sequence_rows: list[dict[str, object]] = []
        for row in iter_sequence_rows(batch_paths.sequences_tsv, batch_id=batch_paths.batch_id):
            genome_id = str(row["genome_id"])
            if genome_id not in genome_by_genome_id:
                raise ImportContractError(
                    f"Sequence row references missing genome_id {row['genome_id']!r}"
                )
            sequence_id = str(row["sequence_id"])
            batch_sequence_ids.add(sequence_id)
            if batch_has_retained_rows and sequence_id in prepared.retained_sequence_ids:
                retained_sequence_rows.append(row)

        retained_sequence_ids = {str(row["sequence_id"]) for row in retained_sequence_rows}
        nucleotide_sequences_by_id = (
            _read_fasta_subset(
                batch_paths.cds_fna,
                retained_sequence_ids,
                existing_records={},
                label="CDS",
            )
            if retained_sequence_ids
            else {}
        )
        missing_sequence_ids = sorted(retained_sequence_ids - set(nucleotide_sequences_by_id))
        if missing_sequence_ids:
            preview = ", ".join(missing_sequence_ids[:5])
            raise ImportContractError(
                f"Missing CDS FASTA records for retained sequence IDs: {preview}"
            )

        sequence_timestamp = timezone.now()
        sequence_copy_count = _copy_rows_to_model(
            Sequence,
            [
                "created_at",
                "updated_at",
                "pipeline_run",
                "genome",
                "taxon",
                "sequence_id",
                "sequence_name",
                "sequence_length",
                "nucleotide_sequence",
                "gene_symbol",
                "transcript_id",
                "isoform_id",
                "assembly_accession",
                "source_record_id",
                "protein_external_id",
                "translation_table",
                "gene_group",
                "linkage_status",
                "partial_status",
            ],
            (
                (
                    sequence_timestamp,
                    sequence_timestamp,
                    pipeline_run.pk,
                    genome_by_genome_id[str(row["genome_id"])].pk,
                    _resolve_optional_taxon_pk(
                        row.get("taxon_id"),
                        genome_by_genome_id[str(row["genome_id"])].taxon_id,
                        taxon_by_taxon_id,
                        "sequence",
                    ),
                    str(row["sequence_id"]),
                    str(row["sequence_name"]),
                    int(row["sequence_length"]),
                    nucleotide_sequences_by_id[str(row["sequence_id"])],
                    str(row.get("gene_symbol", "")),
                    str(row.get("transcript_id", "")),
                    str(row.get("isoform_id", "")),
                    str(row.get("assembly_accession", "")),
                    str(row.get("source_record_id", "")),
                    str(row.get("protein_external_id", "")),
                    str(row.get("translation_table", "")),
                    str(row.get("gene_group", "")),
                    str(row.get("linkage_status", "")),
                    str(row.get("partial_status", "")),
                )
                for row in retained_sequence_rows
            ),
            batch=batch,
            reporter=reporter,
            progress_message="Bulk-loading retained sequence rows.",
            progress_key="inserted_sequences",
            extra_progress={"batch_id": batch_paths.batch_id, "inserted_proteins": total_proteins},
        )
        if sequence_copy_count is None:
            sequence_objects: list[Sequence] = []
            for row in retained_sequence_rows:
                genome = genome_by_genome_id[str(row["genome_id"])]
                taxon_pk = _resolve_optional_taxon_pk(
                    row.get("taxon_id"),
                    genome.taxon_id,
                    taxon_by_taxon_id,
                    "sequence",
                )
                sequence_id = str(row["sequence_id"])
                sequence_objects.append(
                    Sequence(
                        pipeline_run=pipeline_run,
                        genome_id=genome.pk,
                        taxon_id=taxon_pk,
                        sequence_id=sequence_id,
                        sequence_name=str(row["sequence_name"]),
                        sequence_length=int(row["sequence_length"]),
                        nucleotide_sequence=nucleotide_sequences_by_id[sequence_id],
                        gene_symbol=str(row.get("gene_symbol", "")),
                        transcript_id=str(row.get("transcript_id", "")),
                        isoform_id=str(row.get("isoform_id", "")),
                        assembly_accession=str(row.get("assembly_accession", "")),
                        source_record_id=str(row.get("source_record_id", "")),
                        protein_external_id=str(row.get("protein_external_id", "")),
                        translation_table=str(row.get("translation_table", "")),
                        gene_group=str(row.get("gene_group", "")),
                        linkage_status=str(row.get("linkage_status", "")),
                        partial_status=str(row.get("partial_status", "")),
                    )
                )
            Sequence.objects.bulk_create(sequence_objects, batch_size=BULK_CREATE_BATCH_SIZE)
            sequence_copy_count = len(sequence_objects)
        total_sequences += sequence_copy_count
        _set_batch_state(
            batch,
            phase=ImportPhase.IMPORTING,
            progress_payload={
                "message": "Importing retained sequence rows.",
                "batch_id": batch_paths.batch_id,
                "inserted_sequences": total_sequences,
                "inserted_proteins": total_proteins,
            },
            reporter=reporter,
        )
        if retained_sequence_ids:
            sequence_by_sequence_id.update(
                {
                    sequence.sequence_id: sequence
                    for sequence in Sequence.objects.filter(
                        pipeline_run=pipeline_run,
                        sequence_id__in=retained_sequence_ids,
                    ).only("id", "sequence_id", "genome_id", "taxon_id", "gene_symbol")
                }
            )

        retained_protein_rows: list[dict[str, object]] = []
        for row in iter_protein_rows(batch_paths.proteins_tsv, batch_id=batch_paths.batch_id):
            genome_id = str(row["genome_id"])
            sequence_id = str(row["sequence_id"])
            if genome_id not in genome_by_genome_id:
                raise ImportContractError(
                    f"Protein row references missing genome_id {row['genome_id']!r}"
                )
            if sequence_id not in batch_sequence_ids:
                raise ImportContractError(
                    f"Protein row references missing sequence_id {row['sequence_id']!r}"
                )
            analyzed_protein_counts[genome_id] = analyzed_protein_counts.get(genome_id, 0) + 1
            if batch_has_retained_rows and str(row["protein_id"]) in prepared.retained_protein_ids:
                retained_protein_rows.append(row)

        retained_protein_ids = {str(row["protein_id"]) for row in retained_protein_rows}
        amino_acid_sequences_by_id = (
            _read_fasta_subset(
                batch_paths.proteins_faa,
                retained_protein_ids,
                existing_records={},
                label="protein",
            )
            if retained_protein_ids
            else {}
        )
        missing_protein_ids = sorted(retained_protein_ids - set(amino_acid_sequences_by_id))
        if missing_protein_ids:
            preview = ", ".join(missing_protein_ids[:5])
            raise ImportContractError(
                f"Missing protein FASTA records for retained protein IDs: {preview}"
            )

        protein_timestamp = timezone.now()
        protein_copy_count = _copy_rows_to_model(
            Protein,
            [
                "created_at",
                "updated_at",
                "pipeline_run",
                "genome",
                "sequence",
                "taxon",
                "protein_id",
                "protein_name",
                "protein_length",
                "accession",
                "amino_acid_sequence",
                "gene_symbol",
                "translation_method",
                "translation_status",
                "assembly_accession",
                "gene_group",
                "protein_external_id",
                "repeat_call_count",
            ],
            (
                (
                    protein_timestamp,
                    protein_timestamp,
                    pipeline_run.pk,
                    genome_by_genome_id[str(row["genome_id"])].pk,
                    sequence_by_sequence_id[str(row["sequence_id"])].pk,
                    _resolve_optional_taxon_pk(
                        row.get("taxon_id"),
                        genome_by_genome_id[str(row["genome_id"])].taxon_id,
                        taxon_by_taxon_id,
                        "protein",
                    ),
                    str(row["protein_id"]),
                    str(row["protein_name"]),
                    int(row["protein_length"]),
                    str(row.get("assembly_accession") or genome_by_genome_id[str(row["genome_id"])].accession),
                    amino_acid_sequences_by_id[str(row["protein_id"])],
                    str(row.get("gene_symbol", "")),
                    str(row.get("translation_method", "")),
                    str(row.get("translation_status", "")),
                    str(row.get("assembly_accession", "")),
                    str(row.get("gene_group", "")),
                    str(row.get("protein_external_id", "")),
                    prepared.repeat_call_counts_by_protein.get(str(row["protein_id"]), 0),
                )
                for row in retained_protein_rows
            ),
            batch=batch,
            reporter=reporter,
            progress_message="Bulk-loading retained protein rows.",
            progress_key="inserted_proteins",
            extra_progress={"batch_id": batch_paths.batch_id, "inserted_sequences": total_sequences},
        )
        if protein_copy_count is None:
            protein_objects: list[Protein] = []
            for row in retained_protein_rows:
                genome = genome_by_genome_id[str(row["genome_id"])]
                sequence = sequence_by_sequence_id.get(str(row["sequence_id"]))
                if sequence is None:
                    raise ImportContractError(
                        f"Protein row references missing retained sequence_id {row['sequence_id']!r}"
                    )
                taxon_pk = _resolve_optional_taxon_pk(
                    row.get("taxon_id"),
                    genome.taxon_id,
                    taxon_by_taxon_id,
                    "protein",
                )
                protein_id = str(row["protein_id"])
                protein_objects.append(
                    Protein(
                        pipeline_run=pipeline_run,
                        genome_id=genome.pk,
                        sequence_id=sequence.pk,
                        taxon_id=taxon_pk,
                        protein_id=protein_id,
                        protein_name=str(row["protein_name"]),
                        protein_length=int(row["protein_length"]),
                        accession=str(row.get("assembly_accession") or genome.accession),
                        amino_acid_sequence=amino_acid_sequences_by_id[protein_id],
                        gene_symbol=str(row.get("gene_symbol", "")),
                        translation_method=str(row.get("translation_method", "")),
                        translation_status=str(row.get("translation_status", "")),
                        assembly_accession=str(row.get("assembly_accession", "")),
                        gene_group=str(row.get("gene_group", "")),
                        protein_external_id=str(row.get("protein_external_id", "")),
                        repeat_call_count=prepared.repeat_call_counts_by_protein.get(protein_id, 0),
                    )
                )
            Protein.objects.bulk_create(protein_objects, batch_size=BULK_CREATE_BATCH_SIZE)
            protein_copy_count = len(protein_objects)
        total_proteins += protein_copy_count
        _set_batch_state(
            batch,
            phase=ImportPhase.IMPORTING,
            progress_payload={
                "message": "Importing retained protein rows.",
                "batch_id": batch_paths.batch_id,
                "inserted_sequences": total_sequences,
                "inserted_proteins": total_proteins,
            },
            reporter=reporter,
        )
        if retained_protein_ids:
            protein_by_protein_id.update(
                {
                    protein.protein_id: protein
                    for protein in Protein.objects.filter(
                        pipeline_run=pipeline_run,
                        protein_id__in=retained_protein_ids,
                    ).only(
                        "id",
                        "protein_id",
                        "genome_id",
                        "sequence_id",
                        "taxon_id",
                        "gene_symbol",
                        "protein_name",
                        "protein_length",
                    )
                }
            )

    missing_sequences = sorted(prepared.retained_sequence_ids - set(sequence_by_sequence_id))
    if missing_sequences:
        preview = ", ".join(missing_sequences[:5])
        raise ImportContractError(f"Missing retained sequence rows for sequence IDs: {preview}")
    missing_proteins = sorted(prepared.retained_protein_ids - set(protein_by_protein_id))
    if missing_proteins:
        preview = ", ".join(missing_proteins[:5])
        raise ImportContractError(f"Missing retained protein rows for protein IDs: {preview}")

    return total_sequences, sequence_by_sequence_id, total_proteins, protein_by_protein_id, analyzed_protein_counts


def _create_run_parameters_streamed(
    pipeline_run: PipelineRun,
    rows: Iterable[dict[str, object]],
) -> int:
    count = 0
    buffer: list[RunParameter] = []
    for row in rows:
        buffer.append(
            RunParameter(
                pipeline_run=pipeline_run,
                method=str(row["method"]),
                repeat_residue=str(row.get("repeat_residue", "")),
                param_name=str(row["param_name"]),
                param_value=str(row["param_value"]),
            )
        )
        count += 1
        if len(buffer) >= BULK_CREATE_BATCH_SIZE:
            RunParameter.objects.bulk_create(buffer, batch_size=BULK_CREATE_BATCH_SIZE)
            buffer = []
    if buffer:
        RunParameter.objects.bulk_create(buffer, batch_size=BULK_CREATE_BATCH_SIZE)
    return count


def _create_download_manifest_entries_streamed(
    batch: ImportBatch,
    pipeline_run: PipelineRun,
    batch_paths: Iterable[BatchArtifactPaths],
    batch_by_batch_id: dict[str, AcquisitionBatch],
    *,
    reporter: _ImportBatchStateReporter | None = None,
) -> int:
    count = 0
    buffer: list[DownloadManifestEntry] = []
    for batch_path in batch_paths:
        for row in iter_download_manifest_rows(batch_path.download_manifest_tsv, batch_id=batch_path.batch_id):
            buffer.append(
                DownloadManifestEntry(
                    pipeline_run=pipeline_run,
                    batch_id=_require_batch_pk(row.get("batch_id"), batch_by_batch_id, "download manifest"),
                    assembly_accession=str(row["assembly_accession"]),
                    download_status=str(row.get("download_status", "")),
                    package_mode=str(row.get("package_mode", "")),
                    download_path=str(row.get("download_path", "")),
                    rehydrated_path=str(row.get("rehydrated_path", "")),
                    checksum=str(row.get("checksum", "")),
                    file_size_bytes=row.get("file_size_bytes"),
                    download_started_at=row.get("download_started_at"),
                    download_finished_at=row.get("download_finished_at"),
                    notes=str(row.get("notes", "")),
                )
            )
            count += 1
            if len(buffer) >= BULK_CREATE_BATCH_SIZE:
                DownloadManifestEntry.objects.bulk_create(buffer, batch_size=BULK_CREATE_BATCH_SIZE)
                buffer = []
        _set_batch_state(
            batch,
            phase=ImportPhase.IMPORTING,
            progress_payload={
                "message": "Importing batch download manifest rows.",
                "batch_id": batch_path.batch_id,
                "download_manifest_entries": count,
            },
            reporter=reporter,
        )
    if buffer:
        DownloadManifestEntry.objects.bulk_create(buffer, batch_size=BULK_CREATE_BATCH_SIZE)
    return count


def _create_normalization_warning_rows_streamed(
    batch: ImportBatch,
    pipeline_run: PipelineRun,
    batch_paths: Iterable[BatchArtifactPaths],
    batch_by_batch_id: dict[str, AcquisitionBatch],
    *,
    reporter: _ImportBatchStateReporter | None = None,
) -> int:
    count = 0
    warning_timestamp = timezone.now()
    copy_count = _copy_rows_to_model(
        NormalizationWarning,
        [
            "created_at",
            "updated_at",
            "pipeline_run",
            "batch",
            "warning_code",
            "warning_scope",
            "warning_message",
            "genome_id",
            "sequence_id",
            "protein_id",
            "assembly_accession",
            "source_file",
            "source_record_id",
        ],
        (
            (
                warning_timestamp,
                warning_timestamp,
                pipeline_run.pk,
                _require_batch_pk(row.get("batch_id"), batch_by_batch_id, "normalization warning"),
                str(row.get("warning_code", "")),
                str(row.get("warning_scope", "")),
                str(row.get("warning_message", "")),
                str(row.get("genome_id", "")),
                str(row.get("sequence_id", "")),
                str(row.get("protein_id", "")),
                str(row.get("assembly_accession", "")),
                str(row.get("source_file", "")),
                str(row.get("source_record_id", "")),
            )
            for batch_path in batch_paths
            for row in iter_normalization_warning_rows(
                batch_path.normalization_warnings_tsv,
                batch_id=batch_path.batch_id,
            )
        ),
        batch=batch,
        reporter=reporter,
        progress_message="Bulk-loading normalization warning rows.",
        progress_key="normalization_warnings",
    )
    if copy_count is not None:
        return copy_count

    buffer: list[NormalizationWarning] = []
    for batch_path in batch_paths:
        for row in iter_normalization_warning_rows(
            batch_path.normalization_warnings_tsv,
            batch_id=batch_path.batch_id,
        ):
            buffer.append(
                NormalizationWarning(
                    pipeline_run=pipeline_run,
                    batch_id=_require_batch_pk(row.get("batch_id"), batch_by_batch_id, "normalization warning"),
                    warning_code=str(row.get("warning_code", "")),
                    warning_scope=str(row.get("warning_scope", "")),
                    warning_message=str(row.get("warning_message", "")),
                    genome_id=str(row.get("genome_id", "")),
                    sequence_id=str(row.get("sequence_id", "")),
                    protein_id=str(row.get("protein_id", "")),
                    assembly_accession=str(row.get("assembly_accession", "")),
                    source_file=str(row.get("source_file", "")),
                    source_record_id=str(row.get("source_record_id", "")),
                )
            )
            count += 1
            if len(buffer) >= BULK_CREATE_BATCH_SIZE:
                NormalizationWarning.objects.bulk_create(buffer, batch_size=BULK_CREATE_BATCH_SIZE)
                buffer = []
        _set_batch_state(
            batch,
            phase=ImportPhase.IMPORTING,
            progress_payload={
                "message": "Importing normalization warning rows.",
                "batch_id": batch_path.batch_id,
                "normalization_warnings": count,
            },
            reporter=reporter,
        )
    if buffer:
        NormalizationWarning.objects.bulk_create(buffer, batch_size=BULK_CREATE_BATCH_SIZE)
    return count


def _create_repeat_calls_streamed(
    batch: ImportBatch,
    pipeline_run: PipelineRun,
    rows: Iterable[dict[str, object]],
    genome_by_genome_id: dict[str, Genome],
    sequence_by_sequence_id: dict[str, Sequence],
    protein_by_protein_id: dict[str, Protein],
    taxon_by_taxon_id: dict[int, Taxon],
    *,
    reporter: _ImportBatchStateReporter | None = None,
) -> int:
    repeat_call_timestamp = timezone.now()
    copy_count = _copy_rows_to_model(
        RepeatCall,
        [
            "created_at",
            "updated_at",
            "pipeline_run",
            "genome",
            "sequence",
            "protein",
            "taxon",
            "call_id",
            "method",
            "accession",
            "gene_symbol",
            "protein_name",
            "protein_length",
            "start",
            "end",
            "length",
            "repeat_residue",
            "repeat_count",
            "non_repeat_count",
            "purity",
            "aa_sequence",
            "codon_sequence",
            "codon_metric_name",
            "codon_metric_value",
            "window_definition",
            "template_name",
            "merge_rule",
            "score",
        ],
        (
            (
                repeat_call_timestamp,
                repeat_call_timestamp,
                pipeline_run.pk,
                genome_by_genome_id[str(row["genome_id"])].pk,
                sequence_by_sequence_id[str(row["sequence_id"])].pk,
                protein_by_protein_id[str(row["protein_id"])].pk,
                _require_taxon(row.get("taxon_id"), taxon_by_taxon_id, "repeat call").pk,
                str(row["call_id"]),
                str(row["method"]),
                genome_by_genome_id[str(row["genome_id"])].accession,
                protein_by_protein_id[str(row["protein_id"])].gene_symbol
                or sequence_by_sequence_id[str(row["sequence_id"])].gene_symbol,
                protein_by_protein_id[str(row["protein_id"])].protein_name,
                protein_by_protein_id[str(row["protein_id"])].protein_length,
                int(row["start"]),
                int(row["end"]),
                int(row["length"]),
                str(row["repeat_residue"]),
                int(row["repeat_count"]),
                int(row["non_repeat_count"]),
                float(row["purity"]),
                str(row["aa_sequence"]),
                str(row.get("codon_sequence", "")),
                str(row.get("codon_metric_name", "")),
                str(row.get("codon_metric_value", "")),
                str(row.get("window_definition", "")),
                str(row.get("template_name", "")),
                str(row.get("merge_rule", "")),
                str(row.get("score", "")),
            )
            for row in rows
        ),
        batch=batch,
        reporter=reporter,
        progress_message="Bulk-loading repeat-call rows.",
        progress_key="repeat_calls",
    )
    if copy_count is not None:
        return copy_count

    count = 0
    buffer: list[RepeatCall] = []
    for row in rows:
        genome = genome_by_genome_id.get(str(row["genome_id"]))
        if genome is None:
            raise ImportContractError(
                f"Repeat call row references missing genome_id {row['genome_id']!r}"
            )
        sequence = sequence_by_sequence_id.get(str(row["sequence_id"]))
        if sequence is None:
            raise ImportContractError(
                f"Repeat call row references missing sequence_id {row['sequence_id']!r}"
            )
        protein = protein_by_protein_id.get(str(row["protein_id"]))
        if protein is None:
            raise ImportContractError(
                f"Repeat call row references missing protein_id {row['protein_id']!r}"
            )
        taxon = _require_taxon(row.get("taxon_id"), taxon_by_taxon_id, "repeat call")
        buffer.append(
            RepeatCall(
                pipeline_run=pipeline_run,
                genome_id=genome.pk,
                sequence_id=sequence.pk,
                protein_id=protein.pk,
                taxon_id=taxon.pk,
                call_id=str(row["call_id"]),
                method=str(row["method"]),
                accession=genome.accession,
                gene_symbol=protein.gene_symbol or sequence.gene_symbol,
                protein_name=protein.protein_name,
                protein_length=protein.protein_length,
                start=int(row["start"]),
                end=int(row["end"]),
                length=int(row["length"]),
                repeat_residue=str(row["repeat_residue"]),
                repeat_count=int(row["repeat_count"]),
                non_repeat_count=int(row["non_repeat_count"]),
                purity=float(row["purity"]),
                aa_sequence=str(row["aa_sequence"]),
                codon_sequence=str(row.get("codon_sequence", "")),
                codon_metric_name=str(row.get("codon_metric_name", "")),
                codon_metric_value=str(row.get("codon_metric_value", "")),
                window_definition=str(row.get("window_definition", "")),
                template_name=str(row.get("template_name", "")),
                merge_rule=str(row.get("merge_rule", "")),
                score=str(row.get("score", "")),
            )
        )
        count += 1
        if len(buffer) >= BULK_CREATE_BATCH_SIZE:
            RepeatCall.objects.bulk_create(buffer, batch_size=BULK_CREATE_BATCH_SIZE)
            buffer = []
            _set_batch_state(
                batch,
                phase=ImportPhase.IMPORTING,
                progress_payload={
                    "message": "Importing repeat-call rows.",
                    "repeat_calls": count,
                },
                reporter=reporter,
            )
    if buffer:
        RepeatCall.objects.bulk_create(buffer, batch_size=BULK_CREATE_BATCH_SIZE)
        _set_batch_state(
            batch,
            phase=ImportPhase.IMPORTING,
            progress_payload={
                "message": "Importing repeat-call rows.",
                "repeat_calls": count,
            },
            reporter=reporter,
        )
    return count


def _create_accession_status_rows_streamed(
    pipeline_run: PipelineRun,
    rows: Iterable[dict[str, object]],
    batch_by_batch_id: dict[str, AcquisitionBatch],
) -> int:
    count = 0
    buffer: list[AccessionStatus] = []
    for row in rows:
        buffer.append(
            AccessionStatus(
                pipeline_run=pipeline_run,
                batch_id=_require_batch_pk(row.get("batch_id"), batch_by_batch_id, "accession status"),
                assembly_accession=str(row["assembly_accession"]),
                download_status=str(row.get("download_status", "")),
                normalize_status=str(row.get("normalize_status", "")),
                translate_status=str(row.get("translate_status", "")),
                detect_status=str(row.get("detect_status", "")),
                finalize_status=str(row.get("finalize_status", "")),
                terminal_status=str(row.get("terminal_status", "")),
                failure_stage=str(row.get("failure_stage", "")),
                failure_reason=str(row.get("failure_reason", "")),
                n_genomes=int(row.get("n_genomes", 0)),
                n_proteins=int(row.get("n_proteins", 0)),
                n_repeat_calls=int(row.get("n_repeat_calls", 0)),
                notes=str(row.get("notes", "")),
            )
        )
        count += 1
        if len(buffer) >= BULK_CREATE_BATCH_SIZE:
            AccessionStatus.objects.bulk_create(buffer, batch_size=BULK_CREATE_BATCH_SIZE)
            buffer = []
    if buffer:
        AccessionStatus.objects.bulk_create(buffer, batch_size=BULK_CREATE_BATCH_SIZE)
    return count


def _create_accession_call_count_rows_streamed(
    pipeline_run: PipelineRun,
    rows: Iterable[dict[str, object]],
    batch_by_batch_id: dict[str, AcquisitionBatch],
) -> int:
    count = 0
    buffer: list[AccessionCallCount] = []
    for row in rows:
        buffer.append(
            AccessionCallCount(
                pipeline_run=pipeline_run,
                batch_id=_require_batch_pk(row.get("batch_id"), batch_by_batch_id, "accession call count"),
                assembly_accession=str(row["assembly_accession"]),
                method=str(row["method"]),
                repeat_residue=str(row.get("repeat_residue", "")),
                detect_status=str(row.get("detect_status", "")),
                finalize_status=str(row.get("finalize_status", "")),
                n_repeat_calls=int(row.get("n_repeat_calls", 0)),
            )
        )
        count += 1
        if len(buffer) >= BULK_CREATE_BATCH_SIZE:
            AccessionCallCount.objects.bulk_create(buffer, batch_size=BULK_CREATE_BATCH_SIZE)
            buffer = []
    if buffer:
        AccessionCallCount.objects.bulk_create(buffer, batch_size=BULK_CREATE_BATCH_SIZE)
    return count


def _select_repeat_linked_rows(
    genome_rows: list[dict[str, object]],
    sequence_rows: list[dict[str, object]],
    protein_rows: list[dict[str, object]],
    repeat_call_rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    genome_ids = {str(row["genome_id"]) for row in genome_rows}
    sequence_rows_by_id = {str(row["sequence_id"]): row for row in sequence_rows}
    protein_rows_by_id = {str(row["protein_id"]): row for row in protein_rows}

    for row in sequence_rows:
        genome_id = str(row["genome_id"])
        if genome_id not in genome_ids:
            raise ImportContractError(f"Sequence row references missing genome_id {row['genome_id']!r}")

    for row in protein_rows:
        genome_id = str(row["genome_id"])
        sequence_id = str(row["sequence_id"])
        if genome_id not in genome_ids:
            raise ImportContractError(f"Protein row references missing genome_id {row['genome_id']!r}")
        if sequence_id not in sequence_rows_by_id:
            raise ImportContractError(f"Protein row references missing sequence_id {row['sequence_id']!r}")

    retained_sequence_ids: set[str] = set()
    retained_protein_ids: set[str] = set()

    for row in repeat_call_rows:
        genome_id = str(row["genome_id"])
        sequence_id = str(row["sequence_id"])
        protein_id = str(row["protein_id"])

        if genome_id not in genome_ids:
            raise ImportContractError(
                f"Repeat call row references missing genome_id {row['genome_id']!r}"
            )

        sequence_row = sequence_rows_by_id.get(sequence_id)
        if sequence_row is None:
            raise ImportContractError(
                f"Repeat call row references missing sequence_id {row['sequence_id']!r}"
            )

        protein_row = protein_rows_by_id.get(protein_id)
        if protein_row is None:
            raise ImportContractError(
                f"Repeat call row references missing protein_id {row['protein_id']!r}"
            )

        if str(sequence_row["genome_id"]) != genome_id:
            raise ImportContractError(
                f"Repeat call row references sequence_id {row['sequence_id']!r} outside genome_id {row['genome_id']!r}"
            )
        if str(protein_row["genome_id"]) != genome_id:
            raise ImportContractError(
                f"Repeat call row references protein_id {row['protein_id']!r} outside genome_id {row['genome_id']!r}"
            )
        if str(protein_row["sequence_id"]) != sequence_id:
            raise ImportContractError(
                f"Repeat call row references protein_id {row['protein_id']!r} with mismatched sequence_id {row['sequence_id']!r}"
            )

        retained_sequence_ids.add(sequence_id)
        retained_protein_ids.add(protein_id)

    retained_sequence_rows = [
        row for row in sequence_rows if str(row["sequence_id"]) in retained_sequence_ids
    ]
    retained_protein_rows = [
        row for row in protein_rows if str(row["protein_id"]) in retained_protein_ids
    ]
    return retained_sequence_rows, retained_protein_rows


def _prepare_import_data(batch: ImportBatch, parsed: ParsedPublishedRun) -> PreparedImportData:
    retained_sequence_rows, retained_protein_rows = _select_repeat_linked_rows(
        parsed.genome_rows,
        parsed.sequence_rows,
        parsed.protein_rows,
        parsed.repeat_call_rows,
    )
    _set_batch_state(
        batch,
        phase=ImportPhase.LOADING_FASTA,
        progress_payload={
            "message": "Loading retained CDS and protein FASTA records.",
            "retained_sequences": len(retained_sequence_rows),
            "retained_proteins": len(retained_protein_rows),
        },
    )
    nucleotide_sequences_by_id, amino_acid_sequences_by_id = _load_retained_sequence_content(
        parsed,
        retained_sequence_rows=retained_sequence_rows,
        retained_protein_rows=retained_protein_rows,
    )
    return PreparedImportData(
        retained_sequence_rows=retained_sequence_rows,
        retained_protein_rows=retained_protein_rows,
        nucleotide_sequences_by_id=nucleotide_sequences_by_id,
        amino_acid_sequences_by_id=amino_acid_sequences_by_id,
        analyzed_protein_counts=_count_rows_by_key(parsed.protein_rows, "genome_id"),
        repeat_call_counts_by_protein=_count_rows_by_key(parsed.repeat_call_rows, "protein_id"),
    )


def _load_retained_sequence_content(
    parsed: ParsedPublishedRun,
    *,
    retained_sequence_rows: list[dict[str, object]],
    retained_protein_rows: list[dict[str, object]],
) -> tuple[dict[str, str], dict[str, str]]:
    retained_sequence_ids = {str(row["sequence_id"]) for row in retained_sequence_rows}
    retained_protein_ids = {str(row["protein_id"]) for row in retained_protein_rows}
    nucleotide_sequences_by_id: dict[str, str] = {}
    amino_acid_sequences_by_id: dict[str, str] = {}

    for batch_paths in parsed.artifact_paths.acquisition_batches:
        nucleotide_sequences_by_id.update(
            _read_fasta_subset(
                batch_paths.cds_fna,
                retained_sequence_ids,
                existing_records=nucleotide_sequences_by_id,
                label="CDS",
            )
        )
        amino_acid_sequences_by_id.update(
            _read_fasta_subset(
                batch_paths.proteins_faa,
                retained_protein_ids,
                existing_records=amino_acid_sequences_by_id,
                label="protein",
            )
        )

    missing_sequence_ids = sorted(retained_sequence_ids - set(nucleotide_sequences_by_id))
    if missing_sequence_ids:
        preview = ", ".join(missing_sequence_ids[:5])
        raise ImportContractError(
            f"Missing CDS FASTA records for retained sequence IDs: {preview}"
        )

    missing_protein_ids = sorted(retained_protein_ids - set(amino_acid_sequences_by_id))
    if missing_protein_ids:
        preview = ", ".join(missing_protein_ids[:5])
        raise ImportContractError(
            f"Missing protein FASTA records for retained protein IDs: {preview}"
        )

    return nucleotide_sequences_by_id, amino_acid_sequences_by_id


def _read_fasta_subset(
    path: Path,
    retained_ids: set[str],
    *,
    existing_records: dict[str, str],
    label: str,
) -> dict[str, str]:
    records: dict[str, str] = {}
    current_record_id = ""
    current_chunks: list[str] = []

    def store_current_record() -> None:
        if not current_record_id or current_record_id not in retained_ids:
            return
        sequence_value = "".join(current_chunks).strip()
        existing_value = existing_records.get(current_record_id, records.get(current_record_id))
        if existing_value is not None and existing_value != sequence_value:
            raise ImportContractError(
                f"Conflicting duplicate {label} FASTA records were found for {current_record_id!r}"
            )
        records[current_record_id] = sequence_value

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                store_current_record()
                current_record_id = line[1:].split()[0]
                current_chunks = []
                continue
            if not current_record_id:
                raise ImportContractError(f"{path} contains FASTA sequence data before the first header")
            current_chunks.append(line)

    store_current_record()
    return records


def _count_rows_by_key(rows: list[dict[str, object]], key_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row[key_name])
        counts[key] = counts.get(key, 0) + 1
    return counts
