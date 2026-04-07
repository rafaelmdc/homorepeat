from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from apps.browser.models import (
    Genome,
    PipelineRun,
    Protein,
    RepeatCall,
    RunParameter,
    Sequence,
    Taxon,
    TaxonClosure,
)
from apps.imports.models import ImportBatch

from .published_run import ImportContractError, ParsedPublishedRun, load_published_run


BULK_CREATE_BATCH_SIZE = 5000


@dataclass(frozen=True)
class ImportRunResult:
    batch: ImportBatch
    pipeline_run: PipelineRun
    counts: dict[str, int]


def import_published_run(publish_root: Path | str, *, replace_existing: bool = False) -> ImportRunResult:
    source_path = str(Path(publish_root).resolve())

    try:
        parsed = load_published_run(source_path)
    except ImportContractError as exc:
        batch = ImportBatch.objects.create(
            source_path=source_path,
            status=ImportBatch.Status.FAILED,
            replace_existing=replace_existing,
            finished_at=timezone.now(),
            error_count=1,
            error_message=str(exc),
        )
        raise ImportContractError(f"Import failed for {batch.source_path}: {exc}") from exc

    batch = ImportBatch.objects.create(
        source_path=source_path,
        status=ImportBatch.Status.RUNNING,
        replace_existing=replace_existing,
    )

    try:
        with transaction.atomic():
            pipeline_run, counts = _import_parsed_run(parsed, replace_existing=replace_existing)
    except Exception as exc:
        batch.status = ImportBatch.Status.FAILED
        batch.finished_at = timezone.now()
        batch.error_count = 1
        batch.row_counts = {}
        batch.error_message = str(exc)
        batch.save(update_fields=["status", "finished_at", "error_count", "row_counts", "error_message"])
        raise

    batch.pipeline_run = pipeline_run
    batch.status = ImportBatch.Status.COMPLETED
    batch.finished_at = timezone.now()
    batch.success_count = sum(counts.values())
    batch.error_count = 0
    batch.row_counts = counts
    batch.error_message = ""
    batch.save(
        update_fields=[
            "pipeline_run",
            "status",
            "finished_at",
            "success_count",
            "error_count",
            "row_counts",
            "error_message",
        ]
    )
    return ImportRunResult(batch=batch, pipeline_run=pipeline_run, counts=counts)


def _import_parsed_run(
    parsed: ParsedPublishedRun,
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

    retained_sequence_rows, retained_protein_rows = _select_repeat_linked_rows(
        parsed.genome_rows,
        parsed.sequence_rows,
        parsed.protein_rows,
        parsed.repeat_call_rows,
    )
    analyzed_protein_counts = _count_rows_by_key(parsed.protein_rows, "genome_id")

    genome_by_genome_id = _create_genomes(
        pipeline_run,
        parsed.genome_rows,
        taxon_by_taxon_id,
        analyzed_protein_counts,
    )
    sequence_by_sequence_id = _create_sequences(
        pipeline_run,
        retained_sequence_rows,
        genome_by_genome_id,
        taxon_by_taxon_id,
    )
    protein_by_protein_id = _create_proteins(
        pipeline_run,
        retained_protein_rows,
        genome_by_genome_id,
        sequence_by_sequence_id,
        taxon_by_taxon_id,
    )
    _create_run_parameters(pipeline_run, parsed.run_parameter_rows)
    _create_repeat_calls(
        pipeline_run,
        parsed.repeat_call_rows,
        genome_by_genome_id,
        sequence_by_sequence_id,
        protein_by_protein_id,
        taxon_by_taxon_id,
    )

    counts = {
        "taxonomy": len(parsed.taxonomy_rows),
        "genomes": len(parsed.genome_rows),
        "sequences": len(retained_sequence_rows),
        "proteins": len(retained_protein_rows),
        "run_parameters": len(parsed.run_parameter_rows),
        "repeat_calls": len(parsed.repeat_call_rows),
    }
    return pipeline_run, counts


def _delete_run_scoped_rows(pipeline_run: PipelineRun) -> None:
    pipeline_run.run_parameters.all().delete()
    pipeline_run.genomes.all().delete()


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
    taxon_by_taxon_id: dict[int, Taxon],
    analyzed_protein_counts: dict[str, int],
) -> dict[str, Genome]:
    genome_objects: list[Genome] = []
    for row in rows:
        genome_id = str(row["genome_id"])
        taxon = _require_taxon(row.get("taxon_id"), taxon_by_taxon_id, "genome")
        genome_objects.append(
            Genome(
                pipeline_run=pipeline_run,
                genome_id=genome_id,
                source=str(row["source"]),
                accession=str(row["accession"]),
                genome_name=str(row["genome_name"]),
                assembly_type=str(row["assembly_type"]),
                taxon=taxon,
                assembly_level=str(row.get("assembly_level", "")),
                species_name=str(row.get("species_name", "")),
                download_path=str(row.get("download_path", "")),
                analyzed_protein_count=analyzed_protein_counts.get(genome_id, 0),
                notes=str(row.get("notes", "")),
            )
        )
    Genome.objects.bulk_create(genome_objects, batch_size=BULK_CREATE_BATCH_SIZE)
    return {
        genome.genome_id: genome
        for genome in Genome.objects.filter(pipeline_run=pipeline_run).only("id", "genome_id", "taxon_id")
    }


def _create_sequences(
    pipeline_run: PipelineRun,
    rows: list[dict[str, object]],
    genome_by_genome_id: dict[str, Genome],
    taxon_by_taxon_id: dict[int, Taxon],
) -> dict[str, Sequence]:
    sequence_objects: list[Sequence] = []
    for row in rows:
        genome = genome_by_genome_id.get(str(row["genome_id"]))
        if genome is None:
            raise ImportContractError(
                f"Sequence row references missing genome_id {row['genome_id']!r}"
            )
        taxon_pk = _resolve_optional_taxon_pk(row.get("taxon_id"), genome.taxon_id, taxon_by_taxon_id, "sequence")
        sequence_objects.append(
            Sequence(
                pipeline_run=pipeline_run,
                genome_id=genome.pk,
                taxon_id=taxon_pk,
                sequence_id=str(row["sequence_id"]),
                sequence_name=str(row["sequence_name"]),
                sequence_length=int(row["sequence_length"]),
                sequence_path=str(row["sequence_path"]),
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
        protein_objects.append(
            Protein(
                pipeline_run=pipeline_run,
                genome_id=genome.pk,
                sequence_id=sequence.pk,
                taxon_id=taxon_pk,
                protein_id=str(row["protein_id"]),
                protein_name=str(row["protein_name"]),
                protein_length=int(row["protein_length"]),
                protein_path=str(row["protein_path"]),
                gene_symbol=str(row.get("gene_symbol", "")),
                translation_method=str(row.get("translation_method", "")),
                translation_status=str(row.get("translation_status", "")),
                assembly_accession=str(row.get("assembly_accession", "")),
                gene_group=str(row.get("gene_group", "")),
                protein_external_id=str(row.get("protein_external_id", "")),
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
                param_name=str(row["param_name"]),
                param_value=str(row["param_value"]),
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
                source_file=str(row.get("source_file", "")),
            )
        )
    RepeatCall.objects.bulk_create(repeat_call_objects, batch_size=BULK_CREATE_BATCH_SIZE)


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


def _count_rows_by_key(rows: list[dict[str, object]], key_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row[key_name])
        counts[key] = counts.get(key, 0) + 1
    return counts
