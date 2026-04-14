from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.browser.models import (
    CanonicalGenome,
    CanonicalProtein,
    CanonicalRepeatCall,
    CanonicalSequence,
    PipelineRun,
    Protein,
    RepeatCall,
    Sequence,
)
from apps.browser.models.genomes import Genome
from apps.imports.models import ImportBatch


@dataclass(frozen=True)
class CatalogSyncResult:
    genomes: int
    sequences: int
    proteins: int
    repeat_calls: int
    replaced_repeat_calls: int


def sync_canonical_catalog_for_run(
    pipeline_run: PipelineRun,
    *,
    import_batch: ImportBatch,
    last_seen_at=None,
) -> CatalogSyncResult:
    if import_batch.pipeline_run_id not in (None, pipeline_run.pk):
        raise ValueError("Import batch does not belong to the requested pipeline run.")

    if last_seen_at is None:
        last_seen_at = timezone.now()

    raw_genomes = list(pipeline_run.genomes.select_related("taxon"))
    raw_sequences = list(pipeline_run.sequences.select_related("genome", "taxon"))
    raw_proteins = list(pipeline_run.proteins.select_related("genome", "sequence", "taxon"))
    raw_repeat_calls = list(
        pipeline_run.repeat_calls.select_related("genome", "sequence", "protein", "taxon")
    )

    with transaction.atomic():
        canonical_genomes_by_raw_pk = _sync_canonical_genomes(
            raw_genomes,
            pipeline_run=pipeline_run,
            import_batch=import_batch,
            last_seen_at=last_seen_at,
        )
        canonical_sequences_by_raw_pk = _sync_canonical_sequences(
            raw_sequences,
            canonical_genomes_by_raw_pk=canonical_genomes_by_raw_pk,
            pipeline_run=pipeline_run,
            import_batch=import_batch,
            last_seen_at=last_seen_at,
        )
        canonical_proteins_by_raw_pk = _sync_canonical_proteins(
            raw_proteins,
            canonical_genomes_by_raw_pk=canonical_genomes_by_raw_pk,
            canonical_sequences_by_raw_pk=canonical_sequences_by_raw_pk,
            pipeline_run=pipeline_run,
            import_batch=import_batch,
            last_seen_at=last_seen_at,
        )

        touched_methods = _touched_methods_for_run(pipeline_run, raw_repeat_calls)
        replaced_repeat_calls = _replace_canonical_repeat_calls(
            raw_repeat_calls,
            raw_proteins=raw_proteins,
            canonical_genomes_by_raw_pk=canonical_genomes_by_raw_pk,
            canonical_sequences_by_raw_pk=canonical_sequences_by_raw_pk,
            canonical_proteins_by_raw_pk=canonical_proteins_by_raw_pk,
            pipeline_run=pipeline_run,
            import_batch=import_batch,
            last_seen_at=last_seen_at,
            touched_methods=touched_methods,
        )

        _refresh_canonical_protein_repeat_call_counts(
            canonical_proteins_by_raw_pk.values(),
        )

    return CatalogSyncResult(
        genomes=len(raw_genomes),
        sequences=len(raw_sequences),
        proteins=len(raw_proteins),
        repeat_calls=len(raw_repeat_calls),
        replaced_repeat_calls=replaced_repeat_calls,
    )


def _sync_canonical_genomes(
    raw_genomes: list[Genome],
    *,
    pipeline_run: PipelineRun,
    import_batch: ImportBatch,
    last_seen_at,
) -> dict[int, CanonicalGenome]:
    if not raw_genomes:
        return {}

    CanonicalGenome.objects.bulk_create(
        [
            CanonicalGenome(
                latest_pipeline_run=pipeline_run,
                latest_import_batch=import_batch,
                last_seen_at=last_seen_at,
                genome_id=genome.genome_id,
                source=genome.source,
                accession=genome.accession,
                genome_name=genome.genome_name,
                assembly_type=genome.assembly_type,
                taxon=genome.taxon,
                assembly_level=genome.assembly_level,
                species_name=genome.species_name,
                analyzed_protein_count=genome.analyzed_protein_count,
                notes=genome.notes,
            )
            for genome in raw_genomes
        ],
        update_conflicts=True,
        update_fields=[
            "latest_pipeline_run",
            "latest_import_batch",
            "last_seen_at",
            "genome_id",
            "source",
            "genome_name",
            "assembly_type",
            "taxon",
            "assembly_level",
            "species_name",
            "analyzed_protein_count",
            "notes",
        ],
        unique_fields=["accession"],
    )

    canonical_by_accession = CanonicalGenome.objects.in_bulk(
        [genome.accession for genome in raw_genomes],
        field_name="accession",
    )
    return {genome.pk: canonical_by_accession[genome.accession] for genome in raw_genomes}


def _sync_canonical_sequences(
    raw_sequences: list[Sequence],
    *,
    canonical_genomes_by_raw_pk: dict[int, CanonicalGenome],
    pipeline_run: PipelineRun,
    import_batch: ImportBatch,
    last_seen_at,
) -> dict[int, CanonicalSequence]:
    if not raw_sequences:
        return {}

    CanonicalSequence.objects.bulk_create(
        [
            CanonicalSequence(
                latest_pipeline_run=pipeline_run,
                latest_import_batch=import_batch,
                last_seen_at=last_seen_at,
                genome=canonical_genomes_by_raw_pk[sequence.genome_id],
                taxon=sequence.taxon,
                sequence_id=sequence.sequence_id,
                sequence_name=sequence.sequence_name,
                sequence_length=sequence.sequence_length,
                nucleotide_sequence=sequence.nucleotide_sequence,
                gene_symbol=sequence.gene_symbol,
                transcript_id=sequence.transcript_id,
                isoform_id=sequence.isoform_id,
                assembly_accession=sequence.assembly_accession,
                source_record_id=sequence.source_record_id,
                protein_external_id=sequence.protein_external_id,
                translation_table=sequence.translation_table,
                gene_group=sequence.gene_group,
                linkage_status=sequence.linkage_status,
                partial_status=sequence.partial_status,
            )
            for sequence in raw_sequences
        ],
        update_conflicts=True,
        update_fields=[
            "latest_pipeline_run",
            "latest_import_batch",
            "last_seen_at",
            "taxon",
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
        unique_fields=["genome", "sequence_id"],
    )

    canonical_sequences = CanonicalSequence.objects.filter(
        genome_id__in={canonical_genomes_by_raw_pk[sequence.genome_id].pk for sequence in raw_sequences},
        sequence_id__in={sequence.sequence_id for sequence in raw_sequences},
    )
    canonical_by_key = {
        (sequence.genome_id, sequence.sequence_id): sequence
        for sequence in canonical_sequences
    }
    return {
        sequence.pk: canonical_by_key[(canonical_genomes_by_raw_pk[sequence.genome_id].pk, sequence.sequence_id)]
        for sequence in raw_sequences
    }


def _sync_canonical_proteins(
    raw_proteins: list[Protein],
    *,
    canonical_genomes_by_raw_pk: dict[int, CanonicalGenome],
    canonical_sequences_by_raw_pk: dict[int, CanonicalSequence],
    pipeline_run: PipelineRun,
    import_batch: ImportBatch,
    last_seen_at,
) -> dict[int, CanonicalProtein]:
    if not raw_proteins:
        return {}

    CanonicalProtein.objects.bulk_create(
        [
            CanonicalProtein(
                latest_pipeline_run=pipeline_run,
                latest_import_batch=import_batch,
                last_seen_at=last_seen_at,
                genome=canonical_genomes_by_raw_pk[protein.genome_id],
                sequence=canonical_sequences_by_raw_pk[protein.sequence_id],
                taxon=protein.taxon,
                protein_id=protein.protein_id,
                protein_name=protein.protein_name,
                protein_length=protein.protein_length,
                accession=protein.accession,
                amino_acid_sequence=protein.amino_acid_sequence,
                gene_symbol=protein.gene_symbol,
                translation_method=protein.translation_method,
                translation_status=protein.translation_status,
                assembly_accession=protein.assembly_accession,
                gene_group=protein.gene_group,
                protein_external_id=protein.protein_external_id,
                repeat_call_count=protein.repeat_call_count,
            )
            for protein in raw_proteins
        ],
        update_conflicts=True,
        update_fields=[
            "latest_pipeline_run",
            "latest_import_batch",
            "last_seen_at",
            "sequence",
            "taxon",
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
        unique_fields=["genome", "protein_id"],
    )

    canonical_proteins = CanonicalProtein.objects.filter(
        genome_id__in={canonical_genomes_by_raw_pk[protein.genome_id].pk for protein in raw_proteins},
        protein_id__in={protein.protein_id for protein in raw_proteins},
    )
    canonical_by_key = {
        (protein.genome_id, protein.protein_id): protein
        for protein in canonical_proteins
    }
    return {
        protein.pk: canonical_by_key[(canonical_genomes_by_raw_pk[protein.genome_id].pk, protein.protein_id)]
        for protein in raw_proteins
    }


def _touched_methods_for_run(
    pipeline_run: PipelineRun,
    raw_repeat_calls: list[RepeatCall],
) -> tuple[str, ...]:
    touched_methods = tuple(
        pipeline_run.run_parameters.order_by().values_list("method", flat=True).distinct()
    )
    if touched_methods:
        return touched_methods
    return tuple(sorted({repeat_call.method for repeat_call in raw_repeat_calls}))


def _replace_canonical_repeat_calls(
    raw_repeat_calls: list[RepeatCall],
    *,
    raw_proteins: list[Protein],
    canonical_genomes_by_raw_pk: dict[int, CanonicalGenome],
    canonical_sequences_by_raw_pk: dict[int, CanonicalSequence],
    canonical_proteins_by_raw_pk: dict[int, CanonicalProtein],
    pipeline_run: PipelineRun,
    import_batch: ImportBatch,
    last_seen_at,
    touched_methods: tuple[str, ...],
) -> int:
    touched_protein_ids = {canonical_proteins_by_raw_pk[protein.pk].pk for protein in raw_proteins}
    if touched_protein_ids and touched_methods:
        replaced_repeat_calls, _ = CanonicalRepeatCall.objects.filter(
            protein_id__in=touched_protein_ids,
            method__in=touched_methods,
        ).delete()
    else:
        replaced_repeat_calls = 0

    if raw_repeat_calls:
        CanonicalRepeatCall.objects.bulk_create(
            [
                CanonicalRepeatCall(
                    latest_pipeline_run=pipeline_run,
                    latest_import_batch=import_batch,
                    last_seen_at=last_seen_at,
                    latest_repeat_call=repeat_call,
                    genome=canonical_genomes_by_raw_pk[repeat_call.genome_id],
                    sequence=canonical_sequences_by_raw_pk[repeat_call.sequence_id],
                    protein=canonical_proteins_by_raw_pk[repeat_call.protein_id],
                    taxon=repeat_call.taxon,
                    source_call_id=repeat_call.call_id,
                    method=repeat_call.method,
                    accession=repeat_call.accession,
                    gene_symbol=repeat_call.gene_symbol,
                    protein_name=repeat_call.protein_name,
                    protein_length=repeat_call.protein_length,
                    start=repeat_call.start,
                    end=repeat_call.end,
                    length=repeat_call.length,
                    repeat_residue=repeat_call.repeat_residue,
                    repeat_count=repeat_call.repeat_count,
                    non_repeat_count=repeat_call.non_repeat_count,
                    purity=repeat_call.purity,
                    aa_sequence=repeat_call.aa_sequence,
                    codon_sequence=repeat_call.codon_sequence,
                    codon_metric_name=repeat_call.codon_metric_name,
                    codon_metric_value=repeat_call.codon_metric_value,
                    window_definition=repeat_call.window_definition,
                    template_name=repeat_call.template_name,
                    merge_rule=repeat_call.merge_rule,
                    score=repeat_call.score,
                )
                for repeat_call in raw_repeat_calls
            ]
        )

    return replaced_repeat_calls


def _refresh_canonical_protein_repeat_call_counts(
    canonical_proteins,
) -> None:
    canonical_proteins = list(canonical_proteins)
    if not canonical_proteins:
        return

    canonical_protein_ids = [protein.pk for protein in canonical_proteins]
    repeat_call_counts = {
        row["protein_id"]: row["total"]
        for row in CanonicalRepeatCall.objects.filter(protein_id__in=canonical_protein_ids)
        .values("protein_id")
        .annotate(total=Count("pk"))
    }

    proteins_to_update = []
    for protein in canonical_proteins:
        repeat_call_count = repeat_call_counts.get(protein.pk, 0)
        if protein.repeat_call_count == repeat_call_count:
            continue
        protein.repeat_call_count = repeat_call_count
        proteins_to_update.append(protein)

    if proteins_to_update:
        CanonicalProtein.objects.bulk_update(proteins_to_update, ["repeat_call_count"])
