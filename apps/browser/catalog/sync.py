from __future__ import annotations

from dataclasses import dataclass
from itertools import islice
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Count, Exists, OuterRef
from django.utils import timezone

from apps.browser.models import (
    CanonicalGenome,
    CanonicalProtein,
    CanonicalRepeatCall,
    CanonicalRepeatCallCodonUsage,
    CanonicalSequence,
    PipelineRun,
    Protein,
    RepeatCall,
    RepeatCallCodonUsage,
    Sequence,
)
from apps.browser.models.genomes import Genome
from apps.browser.stats.codon_length_rollups import rebuild_canonical_codon_composition_length_summaries
from apps.browser.stats.codon_rollups import rebuild_canonical_codon_composition_summaries
from apps.imports.models import ImportBatch
from apps.browser.import_batches import latest_completed_import_batch_for_run

if TYPE_CHECKING:
    from apps.imports.services.import_run.state import _ImportBatchStateReporter


@dataclass(frozen=True)
class CatalogSyncResult:
    genomes: int
    sequences: int
    proteins: int
    repeat_calls: int
    replaced_repeat_calls: int


@dataclass(frozen=True)
class _CanonicalGenomeRef:
    pk: int
    accession: str


CANONICAL_SYNC_BATCH_SIZE = 1000


def _report_catalog_sync_progress(
    import_batch: ImportBatch,
    *,
    reporter: _ImportBatchStateReporter | None = None,
    stage: str,
    message: str,
    processed: int | None = None,
    force: bool = False,
) -> None:
    if reporter is None:
        return

    prior_payload = import_batch.progress_payload if isinstance(import_batch.progress_payload, dict) else {}
    progress_payload: dict[str, object] = {
        "message": message,
        "stage": stage,
    }
    counts = prior_payload.get("counts")
    if isinstance(counts, dict):
        progress_payload["counts"] = counts
    if processed is not None:
        progress_payload["processed"] = processed

    stage_changed = (
        prior_payload.get("stage") != stage
        or prior_payload.get("message") != message
    )
    import_batch.phase = "syncing_canonical_catalog"
    import_batch.heartbeat_at = timezone.now()
    import_batch.progress_payload = progress_payload
    reporter.save(
        ["phase", "heartbeat_at", "progress_payload"],
        force=force or stage_changed,
    )


def sync_canonical_catalog_for_run(
    pipeline_run: PipelineRun,
    *,
    import_batch: ImportBatch,
    last_seen_at=None,
    replace_all_repeat_call_methods: bool = False,
    reporter: _ImportBatchStateReporter | None = None,
) -> CatalogSyncResult:
    if import_batch.pipeline_run_id not in (None, pipeline_run.pk):
        raise ValueError("Import batch does not belong to the requested pipeline run.")

    if last_seen_at is None:
        last_seen_at = timezone.now()

    raw_genomes = _raw_genome_queryset(pipeline_run)
    raw_sequences = _raw_sequence_queryset(pipeline_run)
    raw_proteins = _raw_protein_queryset(pipeline_run)
    raw_repeat_calls = _raw_repeat_call_queryset(pipeline_run)
    raw_repeat_call_codon_usages = _raw_repeat_call_codon_usage_queryset(pipeline_run)

    with transaction.atomic():
        _prune_stale_canonical_genomes(pipeline_run)
        canonical_genomes_by_raw_pk, genome_count = _sync_canonical_genomes(
            raw_genomes,
            pipeline_run=pipeline_run,
            import_batch=import_batch,
            last_seen_at=last_seen_at,
            reporter=reporter,
        )
        _prune_stale_canonical_sequences(pipeline_run)
        canonical_sequences_by_raw_pk, sequence_count = _sync_canonical_sequences(
            raw_sequences,
            canonical_genomes_by_raw_pk=canonical_genomes_by_raw_pk,
            pipeline_run=pipeline_run,
            import_batch=import_batch,
            last_seen_at=last_seen_at,
            reporter=reporter,
        )
        _prune_stale_canonical_proteins(pipeline_run)
        canonical_proteins_by_raw_pk, protein_count = _sync_canonical_proteins(
            raw_proteins,
            canonical_genomes_by_raw_pk=canonical_genomes_by_raw_pk,
            canonical_sequences_by_raw_pk=canonical_sequences_by_raw_pk,
            pipeline_run=pipeline_run,
            import_batch=import_batch,
            last_seen_at=last_seen_at,
            reporter=reporter,
        )

        touched_methods = _touched_methods_for_run(pipeline_run, raw_repeat_calls)
        repeat_call_count, replaced_repeat_calls = _replace_canonical_repeat_calls(
            raw_repeat_calls,
            canonical_genomes_by_raw_pk=canonical_genomes_by_raw_pk,
            canonical_sequences_by_raw_pk=canonical_sequences_by_raw_pk,
            canonical_proteins_by_raw_pk=canonical_proteins_by_raw_pk,
            pipeline_run=pipeline_run,
            import_batch=import_batch,
            last_seen_at=last_seen_at,
            touched_methods=touched_methods,
            replace_all_repeat_call_methods=replace_all_repeat_call_methods,
            reporter=reporter,
        )
        _replace_canonical_repeat_call_codon_usages(
            raw_repeat_call_codon_usages,
            pipeline_run=pipeline_run,
            import_batch=import_batch,
            reporter=reporter,
        )
        _report_catalog_sync_progress(
            import_batch,
            reporter=reporter,
            stage="canonical_codon_composition_summaries",
            message="Rebuilding canonical codon-composition summaries.",
            force=True,
        )
        rebuild_canonical_codon_composition_summaries()
        _report_catalog_sync_progress(
            import_batch,
            reporter=reporter,
            stage="canonical_codon_composition_length_summaries",
            message="Rebuilding canonical codon-composition by length summaries.",
            force=True,
        )
        rebuild_canonical_codon_composition_length_summaries()

        _refresh_canonical_protein_repeat_call_counts(
            pipeline_run=pipeline_run,
            import_batch=import_batch,
            reporter=reporter,
        )
        _record_pipeline_run_canonical_sync(
            pipeline_run,
            import_batch=import_batch,
            synced_at=last_seen_at,
        )

    return CatalogSyncResult(
        genomes=genome_count,
        sequences=sequence_count,
        proteins=protein_count,
        repeat_calls=repeat_call_count,
        replaced_repeat_calls=replaced_repeat_calls,
    )


def _iter_queryset_batches(queryset, *, chunk_size: int = CANONICAL_SYNC_BATCH_SIZE):
    iterator = queryset.iterator(chunk_size=chunk_size)
    while True:
        batch = list(islice(iterator, chunk_size))
        if not batch:
            return
        yield batch


def _raw_genome_queryset(pipeline_run: PipelineRun):
    return pipeline_run.genomes.order_by("pk").only(
        "id",
        "genome_id",
        "source",
        "accession",
        "genome_name",
        "assembly_type",
        "taxon_id",
        "assembly_level",
        "species_name",
        "analyzed_protein_count",
        "notes",
    )


def _raw_sequence_queryset(pipeline_run: PipelineRun):
    return pipeline_run.sequences.order_by("pk").only(
        "id",
        "genome_id",
        "taxon_id",
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
    )


def _raw_protein_queryset(pipeline_run: PipelineRun):
    return pipeline_run.proteins.order_by("pk").only(
        "id",
        "genome_id",
        "sequence_id",
        "taxon_id",
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
    )


def _raw_repeat_call_queryset(pipeline_run: PipelineRun):
    return pipeline_run.repeat_calls.order_by("pk").only(
        "id",
        "genome_id",
        "sequence_id",
        "protein_id",
        "taxon_id",
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
    )


def _raw_repeat_call_codon_usage_queryset(pipeline_run: PipelineRun):
    return RepeatCallCodonUsage.objects.filter(repeat_call__pipeline_run=pipeline_run).order_by("pk").only(
        "id",
        "repeat_call_id",
        "amino_acid",
        "codon",
        "codon_count",
        "codon_fraction",
    )


def backfill_canonical_catalog_for_run(
    pipeline_run: PipelineRun,
    *,
    force: bool = False,
) -> tuple[CatalogSyncResult | None, bool]:
    latest_batch = latest_completed_import_batch_for_run(pipeline_run)
    if latest_batch is None:
        raise ValueError(f"Run {pipeline_run.run_id!r} does not have a completed import batch.")

    if not force and _pipeline_run_has_current_canonical_sync(pipeline_run, latest_batch=latest_batch):
        return None, False

    result = sync_canonical_catalog_for_run(
        pipeline_run,
        import_batch=latest_batch,
    )
    return result, True


def _sync_canonical_genomes(
    raw_genomes,
    *,
    pipeline_run: PipelineRun,
    import_batch: ImportBatch,
    last_seen_at,
    reporter: _ImportBatchStateReporter | None = None,
) -> tuple[dict[int, _CanonicalGenomeRef], int]:
    canonical_by_raw_pk: dict[int, _CanonicalGenomeRef] = {}
    genome_count = 0
    _report_catalog_sync_progress(
        import_batch,
        reporter=reporter,
        stage="canonical_genomes",
        message="Syncing canonical genome rows.",
        processed=genome_count,
        force=True,
    )

    for batch in _iter_queryset_batches(raw_genomes):
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
                    taxon_id=genome.taxon_id,
                    assembly_level=genome.assembly_level,
                    species_name=genome.species_name,
                    analyzed_protein_count=genome.analyzed_protein_count,
                    notes=genome.notes,
                )
                for genome in batch
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
            batch_size=CANONICAL_SYNC_BATCH_SIZE,
        )

        canonical_by_accession = CanonicalGenome.objects.in_bulk(
            [genome.accession for genome in batch],
            field_name="accession",
        )
        for genome in batch:
            canonical_genome = canonical_by_accession[genome.accession]
            canonical_by_raw_pk[genome.pk] = _CanonicalGenomeRef(
                pk=canonical_genome.pk,
                accession=canonical_genome.accession,
            )
        genome_count += len(batch)
        _report_catalog_sync_progress(
            import_batch,
            reporter=reporter,
            stage="canonical_genomes",
            message="Syncing canonical genome rows.",
            processed=genome_count,
        )

    return canonical_by_raw_pk, genome_count


def _pipeline_run_has_current_canonical_sync(
    pipeline_run: PipelineRun,
    *,
    latest_batch: ImportBatch,
) -> bool:
    return (
        pipeline_run.canonical_sync_batch_id == latest_batch.pk
        and pipeline_run.canonical_synced_at is not None
    )


def _record_pipeline_run_canonical_sync(
    pipeline_run: PipelineRun,
    *,
    import_batch: ImportBatch,
    synced_at,
) -> None:
    pipeline_run.canonical_sync_batch = import_batch
    pipeline_run.canonical_synced_at = synced_at
    pipeline_run.save(update_fields=["canonical_sync_batch", "canonical_synced_at"])


def _prune_stale_canonical_genomes(
    pipeline_run: PipelineRun,
) -> None:
    current_run_genomes = Genome.objects.filter(
        pipeline_run=pipeline_run,
        accession=OuterRef("accession"),
    )
    any_run_genomes = Genome.objects.filter(accession=OuterRef("accession"))
    (
        CanonicalGenome.objects.filter(latest_pipeline_run=pipeline_run)
        .annotate(
            present_in_current_run=Exists(current_run_genomes),
            present_in_any_run=Exists(any_run_genomes),
        )
        .filter(present_in_current_run=False, present_in_any_run=False)
        .delete()
    )


def _prune_stale_canonical_sequences(
    pipeline_run: PipelineRun,
) -> None:
    current_run_sequences = Sequence.objects.filter(
        pipeline_run=pipeline_run,
        genome__accession=OuterRef("genome__accession"),
        sequence_id=OuterRef("sequence_id"),
    )
    any_run_sequences = Sequence.objects.filter(
        genome__accession=OuterRef("genome__accession"),
        sequence_id=OuterRef("sequence_id"),
    )
    (
        CanonicalSequence.objects.filter(latest_pipeline_run=pipeline_run)
        .annotate(
            present_in_current_run=Exists(current_run_sequences),
            present_in_any_run=Exists(any_run_sequences),
        )
        .filter(present_in_current_run=False, present_in_any_run=False)
        .delete()
    )


def _prune_stale_canonical_proteins(
    pipeline_run: PipelineRun,
) -> None:
    current_run_proteins = Protein.objects.filter(
        pipeline_run=pipeline_run,
        genome__accession=OuterRef("genome__accession"),
        protein_id=OuterRef("protein_id"),
    )
    any_run_proteins = Protein.objects.filter(
        genome__accession=OuterRef("genome__accession"),
        protein_id=OuterRef("protein_id"),
    )
    (
        CanonicalProtein.objects.filter(latest_pipeline_run=pipeline_run)
        .annotate(
            present_in_current_run=Exists(current_run_proteins),
            present_in_any_run=Exists(any_run_proteins),
        )
        .filter(present_in_current_run=False, present_in_any_run=False)
        .delete()
    )


def _sync_canonical_sequences(
    raw_sequences,
    *,
    canonical_genomes_by_raw_pk: dict[int, _CanonicalGenomeRef],
    pipeline_run: PipelineRun,
    import_batch: ImportBatch,
    last_seen_at,
    reporter: _ImportBatchStateReporter | None = None,
) -> tuple[dict[int, int], int]:
    canonical_by_raw_pk: dict[int, int] = {}
    sequence_count = 0
    _report_catalog_sync_progress(
        import_batch,
        reporter=reporter,
        stage="canonical_sequences",
        message="Syncing canonical sequence rows.",
        processed=sequence_count,
        force=True,
    )

    for batch in _iter_queryset_batches(raw_sequences):
        CanonicalSequence.objects.bulk_create(
            [
                CanonicalSequence(
                    latest_pipeline_run=pipeline_run,
                    latest_import_batch=import_batch,
                    last_seen_at=last_seen_at,
                    genome_id=canonical_genomes_by_raw_pk[sequence.genome_id].pk,
                    taxon_id=sequence.taxon_id,
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
                for sequence in batch
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
            batch_size=CANONICAL_SYNC_BATCH_SIZE,
        )

        canonical_by_key = {
            (sequence.genome_id, sequence.sequence_id): sequence.pk
            for sequence in CanonicalSequence.objects.filter(
                genome_id__in={canonical_genomes_by_raw_pk[row.genome_id].pk for row in batch},
                sequence_id__in={row.sequence_id for row in batch},
            ).only("id", "genome_id", "sequence_id")
        }
        for sequence in batch:
            canonical_by_raw_pk[sequence.pk] = canonical_by_key[
                (canonical_genomes_by_raw_pk[sequence.genome_id].pk, sequence.sequence_id)
            ]
        sequence_count += len(batch)
        _report_catalog_sync_progress(
            import_batch,
            reporter=reporter,
            stage="canonical_sequences",
            message="Syncing canonical sequence rows.",
            processed=sequence_count,
        )

    return canonical_by_raw_pk, sequence_count


def _sync_canonical_proteins(
    raw_proteins,
    *,
    canonical_genomes_by_raw_pk: dict[int, _CanonicalGenomeRef],
    canonical_sequences_by_raw_pk: dict[int, int],
    pipeline_run: PipelineRun,
    import_batch: ImportBatch,
    last_seen_at,
    reporter: _ImportBatchStateReporter | None = None,
) -> tuple[dict[int, int], int]:
    canonical_by_raw_pk: dict[int, int] = {}
    protein_count = 0
    _report_catalog_sync_progress(
        import_batch,
        reporter=reporter,
        stage="canonical_proteins",
        message="Syncing canonical protein rows.",
        processed=protein_count,
        force=True,
    )

    for batch in _iter_queryset_batches(raw_proteins):
        CanonicalProtein.objects.bulk_create(
            [
                CanonicalProtein(
                    latest_pipeline_run=pipeline_run,
                    latest_import_batch=import_batch,
                    last_seen_at=last_seen_at,
                    genome_id=canonical_genomes_by_raw_pk[protein.genome_id].pk,
                    sequence_id=canonical_sequences_by_raw_pk[protein.sequence_id],
                    taxon_id=protein.taxon_id,
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
                for protein in batch
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
            batch_size=CANONICAL_SYNC_BATCH_SIZE,
        )

        canonical_by_key = {
            (protein.genome_id, protein.protein_id): protein.pk
            for protein in CanonicalProtein.objects.filter(
                genome_id__in={canonical_genomes_by_raw_pk[row.genome_id].pk for row in batch},
                protein_id__in={row.protein_id for row in batch},
            ).only("id", "genome_id", "protein_id")
        }
        for protein in batch:
            canonical_by_raw_pk[protein.pk] = canonical_by_key[
                (canonical_genomes_by_raw_pk[protein.genome_id].pk, protein.protein_id)
            ]
        protein_count += len(batch)
        _report_catalog_sync_progress(
            import_batch,
            reporter=reporter,
            stage="canonical_proteins",
            message="Syncing canonical protein rows.",
            processed=protein_count,
        )

    return canonical_by_raw_pk, protein_count


def _touched_methods_for_run(
    pipeline_run: PipelineRun,
    raw_repeat_calls,
) -> tuple[str, ...]:
    touched_methods = tuple(
        pipeline_run.run_parameters.order_by().values_list("method", flat=True).distinct()
    )
    if touched_methods:
        return touched_methods
    return tuple(
        raw_repeat_calls.order_by().values_list("method", flat=True).distinct()
    )


def _replace_canonical_repeat_calls(
    raw_repeat_calls,
    *,
    canonical_genomes_by_raw_pk: dict[int, _CanonicalGenomeRef],
    canonical_sequences_by_raw_pk: dict[int, int],
    canonical_proteins_by_raw_pk: dict[int, int],
    pipeline_run: PipelineRun,
    import_batch: ImportBatch,
    last_seen_at,
    touched_methods: tuple[str, ...],
    replace_all_repeat_call_methods: bool,
    reporter: _ImportBatchStateReporter | None = None,
) -> tuple[int, int]:
    _report_catalog_sync_progress(
        import_batch,
        reporter=reporter,
        stage="canonical_repeat_calls",
        message="Syncing canonical repeat-call rows.",
        processed=0,
        force=True,
    )
    if replace_all_repeat_call_methods or touched_methods:
        delete_queryset = CanonicalRepeatCall.objects.filter(
            protein__latest_pipeline_run=pipeline_run,
        )
        if not replace_all_repeat_call_methods:
            delete_queryset = delete_queryset.filter(method__in=touched_methods)
        replaced_repeat_calls, _ = delete_queryset.delete()
    else:
        replaced_repeat_calls = 0

    repeat_call_count = 0
    for batch in _iter_queryset_batches(raw_repeat_calls):
        CanonicalRepeatCall.objects.bulk_create(
            [
                CanonicalRepeatCall(
                    latest_pipeline_run=pipeline_run,
                    latest_import_batch=import_batch,
                    last_seen_at=last_seen_at,
                    latest_repeat_call_id=repeat_call.pk,
                    genome_id=canonical_genomes_by_raw_pk[repeat_call.genome_id].pk,
                    sequence_id=canonical_sequences_by_raw_pk[repeat_call.sequence_id],
                    protein_id=canonical_proteins_by_raw_pk[repeat_call.protein_id],
                    taxon_id=repeat_call.taxon_id,
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
                    codon_ratio_value=repeat_call.codon_ratio_value,
                    window_definition=repeat_call.window_definition,
                    template_name=repeat_call.template_name,
                    merge_rule=repeat_call.merge_rule,
                    score=repeat_call.score,
                )
                for repeat_call in batch
            ],
            batch_size=CANONICAL_SYNC_BATCH_SIZE,
        )
        repeat_call_count += len(batch)
        _report_catalog_sync_progress(
            import_batch,
            reporter=reporter,
            stage="canonical_repeat_calls",
            message="Syncing canonical repeat-call rows.",
            processed=repeat_call_count,
        )

    return repeat_call_count, replaced_repeat_calls


def _replace_canonical_repeat_call_codon_usages(
    raw_repeat_call_codon_usages,
    *,
    pipeline_run: PipelineRun,
    import_batch: ImportBatch,
    reporter: _ImportBatchStateReporter | None = None,
) -> None:
    processed_count = 0
    _report_catalog_sync_progress(
        import_batch,
        reporter=reporter,
        stage="canonical_repeat_call_codon_usages",
        message="Syncing canonical repeat-call codon-usage rows.",
        processed=processed_count,
        force=True,
    )
    for batch in _iter_queryset_batches(raw_repeat_call_codon_usages):
        raw_repeat_call_ids = {codon_usage.repeat_call_id for codon_usage in batch}
        canonical_repeat_call_pk_by_raw_pk = dict(
            CanonicalRepeatCall.objects.filter(
                latest_pipeline_run=pipeline_run,
                latest_repeat_call_id__in=raw_repeat_call_ids,
            )
            .order_by()
            .values_list("latest_repeat_call_id", "pk")
        )
        canonical_codon_usages: list[CanonicalRepeatCallCodonUsage] = []
        for codon_usage in batch:
            canonical_repeat_call_pk = canonical_repeat_call_pk_by_raw_pk.get(codon_usage.repeat_call_id)
            if canonical_repeat_call_pk is None:
                raise ValueError(
                    f"Missing canonical repeat call for raw repeat-call codon usage {codon_usage.pk}"
                )
            canonical_codon_usages.append(
                CanonicalRepeatCallCodonUsage(
                    repeat_call_id=canonical_repeat_call_pk,
                    amino_acid=codon_usage.amino_acid,
                    codon=codon_usage.codon,
                    codon_count=codon_usage.codon_count,
                    codon_fraction=codon_usage.codon_fraction,
                )
            )
        CanonicalRepeatCallCodonUsage.objects.bulk_create(
            canonical_codon_usages,
            batch_size=CANONICAL_SYNC_BATCH_SIZE,
        )
        processed_count += len(batch)
        _report_catalog_sync_progress(
            import_batch,
            reporter=reporter,
            stage="canonical_repeat_call_codon_usages",
            message="Syncing canonical repeat-call codon-usage rows.",
            processed=processed_count,
        )


def _refresh_canonical_protein_repeat_call_counts(
    *,
    pipeline_run: PipelineRun,
    import_batch: ImportBatch,
    reporter: _ImportBatchStateReporter | None = None,
) -> None:
    processed_count = 0
    _report_catalog_sync_progress(
        import_batch,
        reporter=reporter,
        stage="canonical_protein_repeat_call_counts",
        message="Refreshing canonical protein repeat-call counts.",
        processed=processed_count,
        force=True,
    )
    repeat_call_counts = {
        row["protein_id"]: row["total"]
        for row in CanonicalRepeatCall.objects.filter(protein__latest_pipeline_run=pipeline_run)
        .values("protein_id")
        .annotate(total=Count("pk"))
    }

    proteins_to_update = []
    for protein in CanonicalProtein.objects.filter(latest_pipeline_run=pipeline_run).only(
        "id",
        "repeat_call_count",
    ).iterator(chunk_size=CANONICAL_SYNC_BATCH_SIZE):
        repeat_call_count = repeat_call_counts.get(protein.pk, 0)
        if protein.repeat_call_count == repeat_call_count:
            processed_count += 1
        else:
            protein.repeat_call_count = repeat_call_count
            proteins_to_update.append(protein)
            processed_count += 1
            if len(proteins_to_update) >= CANONICAL_SYNC_BATCH_SIZE:
                CanonicalProtein.objects.bulk_update(
                    proteins_to_update,
                    ["repeat_call_count"],
                    batch_size=CANONICAL_SYNC_BATCH_SIZE,
                )
                proteins_to_update = []
        if processed_count % CANONICAL_SYNC_BATCH_SIZE == 0:
            _report_catalog_sync_progress(
                import_batch,
                reporter=reporter,
                stage="canonical_protein_repeat_call_counts",
                message="Refreshing canonical protein repeat-call counts.",
                processed=processed_count,
            )

    if proteins_to_update:
        CanonicalProtein.objects.bulk_update(
            proteins_to_update,
            ["repeat_call_count"],
            batch_size=CANONICAL_SYNC_BATCH_SIZE,
        )
    _report_catalog_sync_progress(
        import_batch,
        reporter=reporter,
        stage="canonical_protein_repeat_call_counts",
        message="Refreshing canonical protein repeat-call counts.",
        processed=processed_count,
    )
