from __future__ import annotations

from math import isfinite
from typing import Iterable

from django.utils import timezone

from apps.browser.models.genomes import Genome, Protein, Sequence
from apps.browser.models.repeat_calls import RepeatCall, RepeatCallCodonUsage
from apps.browser.models.runs import AcquisitionBatch, PipelineRun
from apps.browser.models.taxonomy import Taxon
from apps.imports.models import ImportBatch
from apps.imports.services.published_run import (
    BatchArtifactPaths,
    ImportContractError,
    InspectedPublishedRun,
    iter_genome_rows,
    iter_protein_rows,
    iter_repeat_call_rows,
    iter_sequence_rows,
)

from .copy import BULK_CREATE_BATCH_SIZE, _copy_rows_to_model
from .prepare import PreparedStreamedImportData, _read_fasta_subset
from .state import ImportPhase, _ImportBatchStateReporter, _set_batch_state
from .taxonomy import _require_taxon, _resolve_optional_taxon_pk


def _delete_run_scoped_rows(pipeline_run: PipelineRun) -> None:
    pipeline_run.normalization_warnings.all().delete()
    pipeline_run.download_manifest_entries.all().delete()
    pipeline_run.accession_call_count_rows.all().delete()
    pipeline_run.accession_status_rows.all().delete()
    pipeline_run.run_parameters.all().delete()
    pipeline_run.genomes.all().delete()
    pipeline_run.acquisition_batches.all().delete()


def _parse_codon_ratio_value(raw_value: object) -> float | None:
    if raw_value is None:
        return None

    text = str(raw_value).strip()
    if not text:
        return None

    try:
        parsed = float(text)
    except (TypeError, ValueError):
        return None

    return parsed if isfinite(parsed) else None


def _iter_row_batches(
    rows: Iterable[dict[str, object]],
    *,
    chunk_size: int = BULK_CREATE_BATCH_SIZE,
):
    batch: list[dict[str, object]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= chunk_size:
            yield batch
            batch = []
    if batch:
        yield batch


def _load_repeat_call_refs_for_codon_usage_rows(
    pipeline_run: PipelineRun,
    rows: list[dict[str, object]],
) -> dict[str, tuple[int, str, str, str, str]]:
    call_ids = {str(row["call_id"]) for row in rows}
    refs = {
        str(call_id): (pk, method, repeat_residue, sequence_id, protein_id)
        for call_id, pk, method, repeat_residue, sequence_id, protein_id in RepeatCall.objects.filter(
            pipeline_run=pipeline_run,
            call_id__in=call_ids,
        )
        .order_by()
        .values_list("call_id", "pk", "method", "repeat_residue", "sequence__sequence_id", "protein__protein_id")
    }

    missing_call_ids = sorted(call_ids - set(refs))
    if missing_call_ids:
        preview = ", ".join(missing_call_ids[:5])
        raise ImportContractError(f"Codon usage rows reference missing repeat call IDs: {preview}")

    return refs


def _validate_codon_usage_row_against_repeat_call(
    row: dict[str, object],
    repeat_call_ref: tuple[int, str, str, str, str],
) -> int:
    repeat_call_pk, method, repeat_residue, sequence_id, protein_id = repeat_call_ref
    if str(row["method"]) != method:
        raise ImportContractError(
            f"Codon usage row for call_id={row['call_id']!r} has method={row['method']!r}, expected {method!r}"
        )
    if str(row["repeat_residue"]) != repeat_residue:
        raise ImportContractError(
            "Codon usage row for "
            f"call_id={row['call_id']!r} has repeat_residue={row['repeat_residue']!r}, expected {repeat_residue!r}"
        )
    if str(row["sequence_id"]) != sequence_id:
        raise ImportContractError(
            f"Codon usage row for call_id={row['call_id']!r} has sequence_id={row['sequence_id']!r}, "
            f"expected {sequence_id!r}"
        )
    if str(row["protein_id"]) != protein_id:
        raise ImportContractError(
            f"Codon usage row for call_id={row['call_id']!r} has protein_id={row['protein_id']!r}, "
            f"expected {protein_id!r}"
        )
    return repeat_call_pk


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
    batch_artifact_paths: Iterable[BatchArtifactPaths],
) -> dict[str, AcquisitionBatch]:
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


def _prepare_retained_sequence_rows(
    batch_paths: BatchArtifactPaths,
    prepared: PreparedStreamedImportData,
    genome_by_genome_id: dict[str, Genome],
    batch_has_retained_rows: bool,
) -> tuple[list[dict[str, object]], set[str], set[str]]:
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
    return retained_sequence_rows, retained_sequence_ids, batch_sequence_ids


def _prepare_retained_protein_rows(
    batch_paths: BatchArtifactPaths,
    prepared: PreparedStreamedImportData,
    genome_by_genome_id: dict[str, Genome],
    batch_sequence_ids: set[str],
    analyzed_protein_counts: dict[str, int],
    batch_has_retained_rows: bool,
) -> tuple[list[dict[str, object]], set[str]]:
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
    return retained_protein_rows, retained_protein_ids


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
        retained_sequence_rows, retained_sequence_ids, batch_sequence_ids = _prepare_retained_sequence_rows(
            batch_paths,
            prepared,
            genome_by_genome_id,
            batch_has_retained_rows,
        )
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

        retained_protein_rows, retained_protein_ids = _prepare_retained_protein_rows(
            batch_paths,
            prepared,
            genome_by_genome_id,
            batch_sequence_ids,
            analyzed_protein_counts,
            batch_has_retained_rows,
        )
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
            "codon_ratio_value",
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
                _parse_codon_ratio_value(row.get("codon_metric_value", "")),
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
                codon_ratio_value=_parse_codon_ratio_value(row.get("codon_metric_value", "")),
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


def _create_repeat_call_codon_usages_streamed(
    batch: ImportBatch,
    pipeline_run: PipelineRun,
    rows: Iterable[dict[str, object]],
    *,
    reporter: _ImportBatchStateReporter | None = None,
) -> int:
    codon_usage_timestamp = timezone.now()
    field_names = [
        "created_at",
        "updated_at",
        "repeat_call",
        "amino_acid",
        "codon",
        "codon_count",
        "codon_fraction",
    ]
    count = 0

    for batch_rows in _iter_row_batches(rows):
        repeat_call_refs = _load_repeat_call_refs_for_codon_usage_rows(pipeline_run, batch_rows)

        def iter_copy_rows():
            for row in batch_rows:
                yield (
                    codon_usage_timestamp,
                    codon_usage_timestamp,
                    _validate_codon_usage_row_against_repeat_call(
                        row,
                        repeat_call_refs[str(row["call_id"])],
                    ),
                    str(row["amino_acid"]),
                    str(row["codon"]),
                    int(row["codon_count"]),
                    float(row["codon_fraction"]),
                )

        copy_count = _copy_rows_to_model(
            RepeatCallCodonUsage,
            field_names,
            iter_copy_rows(),
        )
        if copy_count is None:
            RepeatCallCodonUsage.objects.bulk_create(
                [
                    RepeatCallCodonUsage(
                        repeat_call_id=_validate_codon_usage_row_against_repeat_call(
                            row,
                            repeat_call_refs[str(row["call_id"])],
                        ),
                        amino_acid=str(row["amino_acid"]),
                        codon=str(row["codon"]),
                        codon_count=int(row["codon_count"]),
                        codon_fraction=float(row["codon_fraction"]),
                    )
                    for row in batch_rows
                ],
                batch_size=BULK_CREATE_BATCH_SIZE,
            )
            copy_count = len(batch_rows)

        count += copy_count
        _set_batch_state(
            batch,
            phase=ImportPhase.IMPORTING,
            progress_payload={
                "message": "Importing repeat-call codon-usage rows.",
                "repeat_call_codon_usages": count,
            },
            reporter=reporter,
        )
    return count
