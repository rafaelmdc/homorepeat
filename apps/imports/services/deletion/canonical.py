from __future__ import annotations

from django.db import connection
from django.db.models import Exists, OuterRef

from apps.browser.models import (
    CanonicalGenome,
    CanonicalProtein,
    CanonicalRepeatCall,
    CanonicalSequence,
    PipelineRun,
)
from apps.browser.models.genomes import Genome, Protein, Sequence
from apps.browser.models.repeat_calls import RepeatCall
from apps.imports.models import ImportBatch


def repair_canonical_catalog(pipeline_run: PipelineRun) -> dict[str, int]:
    """Promote or remove canonical rows whose latest_pipeline_run is pipeline_run.

    For each impacted canonical entity:
    - If an active predecessor exists in another run: promote canonical row to that run.
    - If no active predecessor exists: delete the canonical row (children cascade).

    Returns a dict of counts keyed by action+entity (e.g. "canonical_genomes_promoted").
    """
    if connection.vendor == "postgresql":
        return _repair_postgresql(pipeline_run)
    return _repair_orm(pipeline_run)


def rebuild_canonical_rollups() -> None:
    """Rebuild CanonicalCodonCompositionSummary and CanonicalCodonCompositionLengthSummary."""
    from apps.browser.stats import (
        rebuild_canonical_codon_composition_length_summaries,
        rebuild_canonical_codon_composition_summaries,
    )
    rebuild_canonical_codon_composition_summaries()
    rebuild_canonical_codon_composition_length_summaries()


def _repair_postgresql(pipeline_run: PipelineRun) -> dict[str, int]:
    run_pk = pipeline_run.pk
    counts: dict[str, int] = {}

    with connection.cursor() as cursor:
        # --- Canonical Genomes ---
        # Promote: point at the newest active run that also has the same raw genome.
        cursor.execute("""
            WITH target AS (
                SELECT cg.id, cg.accession
                FROM browser_canonicalgenome cg
                WHERE cg.latest_pipeline_run_id = %s
            ),
            best AS (
                SELECT DISTINCT ON (g.accession)
                    g.accession,
                    g.pipeline_run_id,
                    ib.id AS import_batch_id
                FROM browser_genome g
                JOIN browser_pipelinerun pr ON pr.id = g.pipeline_run_id
                JOIN imports_importbatch ib ON ib.pipeline_run_id = g.pipeline_run_id
                WHERE g.accession IN (SELECT accession FROM target)
                  AND pr.lifecycle_status = 'active'
                  AND g.pipeline_run_id != %s
                  AND ib.status = 'completed'
                ORDER BY g.accession, pr.imported_at DESC, pr.id DESC
            )
            UPDATE browser_canonicalgenome cg
            SET latest_pipeline_run_id = best.pipeline_run_id,
                latest_import_batch_id = best.import_batch_id,
                updated_at = NOW()
            FROM target
            JOIN best ON best.accession = target.accession
            WHERE cg.id = target.id
        """, [run_pk, run_pk])
        counts["canonical_genomes_promoted"] = cursor.rowcount

        # Delete orphans (cascade removes all child sequences, proteins, repeat calls).
        cursor.execute("""
            DELETE FROM browser_canonicalgenome
            WHERE latest_pipeline_run_id = %s
        """, [run_pk])
        counts["canonical_genomes_deleted"] = cursor.rowcount

        # --- Canonical Sequences ---
        cursor.execute("""
            WITH target AS (
                SELECT cs.id, cs.genome_id, cs.sequence_id
                FROM browser_canonicalsequence cs
                WHERE cs.latest_pipeline_run_id = %s
            ),
            best AS (
                SELECT DISTINCT ON (cg.id, s.sequence_id)
                    cg.id AS canonical_genome_id,
                    s.sequence_id,
                    s.pipeline_run_id,
                    ib.id AS import_batch_id
                FROM browser_sequence s
                JOIN browser_genome g ON g.id = s.genome_id
                JOIN browser_canonicalgenome cg ON cg.accession = g.accession
                JOIN browser_pipelinerun pr ON pr.id = s.pipeline_run_id
                JOIN imports_importbatch ib ON ib.pipeline_run_id = s.pipeline_run_id
                WHERE (cg.id, s.sequence_id) IN (SELECT genome_id, sequence_id FROM target)
                  AND pr.lifecycle_status = 'active'
                  AND s.pipeline_run_id != %s
                  AND ib.status = 'completed'
                ORDER BY cg.id, s.sequence_id, pr.imported_at DESC, pr.id DESC
            )
            UPDATE browser_canonicalsequence cs
            SET latest_pipeline_run_id = best.pipeline_run_id,
                latest_import_batch_id = best.import_batch_id,
                updated_at = NOW()
            FROM target
            JOIN best ON best.canonical_genome_id = target.genome_id
                     AND best.sequence_id = target.sequence_id
            WHERE cs.id = target.id
        """, [run_pk, run_pk])
        counts["canonical_sequences_promoted"] = cursor.rowcount

        cursor.execute("""
            DELETE FROM browser_canonicalsequence
            WHERE latest_pipeline_run_id = %s
        """, [run_pk])
        counts["canonical_sequences_deleted"] = cursor.rowcount

        # --- Canonical Proteins ---
        cursor.execute("""
            WITH target AS (
                SELECT cp.id, cp.genome_id, cp.protein_id
                FROM browser_canonicalprotein cp
                WHERE cp.latest_pipeline_run_id = %s
            ),
            best AS (
                SELECT DISTINCT ON (cg.id, p.protein_id)
                    cg.id AS canonical_genome_id,
                    p.protein_id,
                    p.pipeline_run_id,
                    ib.id AS import_batch_id
                FROM browser_protein p
                JOIN browser_genome g ON g.id = p.genome_id
                JOIN browser_canonicalgenome cg ON cg.accession = g.accession
                JOIN browser_pipelinerun pr ON pr.id = p.pipeline_run_id
                JOIN imports_importbatch ib ON ib.pipeline_run_id = p.pipeline_run_id
                WHERE (cg.id, p.protein_id) IN (SELECT genome_id, protein_id FROM target)
                  AND pr.lifecycle_status = 'active'
                  AND p.pipeline_run_id != %s
                  AND ib.status = 'completed'
                ORDER BY cg.id, p.protein_id, pr.imported_at DESC, pr.id DESC
            )
            UPDATE browser_canonicalprotein cp
            SET latest_pipeline_run_id = best.pipeline_run_id,
                latest_import_batch_id = best.import_batch_id,
                updated_at = NOW()
            FROM target
            JOIN best ON best.canonical_genome_id = target.genome_id
                     AND best.protein_id = target.protein_id
            WHERE cp.id = target.id
        """, [run_pk, run_pk])
        counts["canonical_proteins_promoted"] = cursor.rowcount

        cursor.execute("""
            DELETE FROM browser_canonicalprotein
            WHERE latest_pipeline_run_id = %s
        """, [run_pk])
        counts["canonical_proteins_deleted"] = cursor.rowcount

        # --- Canonical Repeat Calls ---
        # Predecessor lookup: same (genome.accession, protein_id, sequence_id,
        # method, repeat_residue, start, end) in another active run's raw repeat calls.
        cursor.execute("""
            WITH target AS (
                SELECT crc.id, crc.protein_id, crc.sequence_id,
                       crc.method, crc.repeat_residue, crc.start, crc."end"
                FROM browser_canonicalrepeatcall crc
                WHERE crc.latest_pipeline_run_id = %s
            ),
            best AS (
                SELECT DISTINCT ON (cp.id, cs.id, rc.method, rc.repeat_residue, rc.start, rc."end")
                    cp.id  AS canonical_protein_id,
                    cs.id  AS canonical_sequence_id,
                    rc.method, rc.repeat_residue, rc.start, rc."end",
                    rc.pipeline_run_id,
                    ib.id  AS import_batch_id,
                    rc.id  AS raw_repeat_call_id
                FROM browser_repeatcall rc
                JOIN browser_genome g ON g.id = rc.genome_id
                JOIN browser_protein p ON p.id = rc.protein_id
                JOIN browser_sequence s ON s.id = rc.sequence_id
                JOIN browser_canonicalgenome cg ON cg.accession = g.accession
                JOIN browser_canonicalprotein cp ON cp.genome_id = cg.id
                                                AND cp.protein_id = p.protein_id
                JOIN browser_canonicalsequence cs ON cs.genome_id = cg.id
                                                 AND cs.sequence_id = s.sequence_id
                JOIN browser_pipelinerun pr ON pr.id = rc.pipeline_run_id
                JOIN imports_importbatch ib ON ib.pipeline_run_id = rc.pipeline_run_id
                WHERE (cp.id, cs.id, rc.method, rc.repeat_residue, rc.start, rc."end")
                      IN (SELECT protein_id, sequence_id, method, repeat_residue, start, "end"
                          FROM target)
                  AND pr.lifecycle_status = 'active'
                  AND rc.pipeline_run_id != %s
                  AND ib.status = 'completed'
                ORDER BY cp.id, cs.id, rc.method, rc.repeat_residue, rc.start, rc."end",
                         pr.imported_at DESC, pr.id DESC
            )
            UPDATE browser_canonicalrepeatcall crc
            SET latest_pipeline_run_id = best.pipeline_run_id,
                latest_import_batch_id = best.import_batch_id,
                latest_repeat_call_id  = best.raw_repeat_call_id,
                updated_at = NOW()
            FROM target
            JOIN best ON best.canonical_protein_id  = target.protein_id
                     AND best.canonical_sequence_id = target.sequence_id
                     AND best.method                = target.method
                     AND best.repeat_residue        = target.repeat_residue
                     AND best.start                 = target.start
                     AND best."end"                 = target."end"
            WHERE crc.id = target.id
        """, [run_pk, run_pk])
        counts["canonical_repeat_calls_promoted"] = cursor.rowcount

        # Delete orphan repeat calls (CanonicalRepeatCallCodonUsage cascades).
        cursor.execute("""
            DELETE FROM browser_canonicalrepeatcall
            WHERE latest_pipeline_run_id = %s
        """, [run_pk])
        counts["canonical_repeat_calls_deleted"] = cursor.rowcount

    return counts


def _repair_orm(pipeline_run: PipelineRun) -> dict[str, int]:
    """ORM-based repair for non-PostgreSQL backends (used in tests)."""
    counts: dict[str, int] = {}

    # --- Canonical Genomes ---
    other_active_genome = Genome.objects.filter(
        pipeline_run__lifecycle_status=PipelineRun.LifecycleStatus.ACTIVE,
        accession=OuterRef("accession"),
    ).exclude(pipeline_run=pipeline_run)

    promoted = 0
    for cg in (
        CanonicalGenome.objects.filter(latest_pipeline_run=pipeline_run)
        .filter(Exists(other_active_genome))
    ):
        pred_run = (
            PipelineRun.objects.filter(
                lifecycle_status=PipelineRun.LifecycleStatus.ACTIVE,
                genomes__accession=cg.accession,
            )
            .exclude(pk=pipeline_run.pk)
            .order_by("-imported_at", "-pk")
            .first()
        )
        pred_batch = _latest_completed_batch(pred_run)
        if pred_run and pred_batch:
            CanonicalGenome.objects.filter(pk=cg.pk).update(
                latest_pipeline_run=pred_run,
                latest_import_batch=pred_batch,
            )
            promoted += 1
    counts["canonical_genomes_promoted"] = promoted

    deleted, _ = CanonicalGenome.objects.filter(latest_pipeline_run=pipeline_run).delete()
    counts["canonical_genomes_deleted"] = deleted

    # --- Canonical Sequences ---
    other_active_sequence = Sequence.objects.filter(
        pipeline_run__lifecycle_status=PipelineRun.LifecycleStatus.ACTIVE,
        genome__accession=OuterRef("genome__accession"),
        sequence_id=OuterRef("sequence_id"),
    ).exclude(pipeline_run=pipeline_run)

    promoted = 0
    for cs in (
        CanonicalSequence.objects.filter(latest_pipeline_run=pipeline_run)
        .filter(Exists(other_active_sequence))
        .select_related("genome")
    ):
        pred_run = (
            PipelineRun.objects.filter(
                lifecycle_status=PipelineRun.LifecycleStatus.ACTIVE,
                sequences__genome__accession=cs.genome.accession,
                sequences__sequence_id=cs.sequence_id,
            )
            .exclude(pk=pipeline_run.pk)
            .order_by("-imported_at", "-pk")
            .first()
        )
        pred_batch = _latest_completed_batch(pred_run)
        if pred_run and pred_batch:
            CanonicalSequence.objects.filter(pk=cs.pk).update(
                latest_pipeline_run=pred_run,
                latest_import_batch=pred_batch,
            )
            promoted += 1
    counts["canonical_sequences_promoted"] = promoted

    deleted, _ = CanonicalSequence.objects.filter(latest_pipeline_run=pipeline_run).delete()
    counts["canonical_sequences_deleted"] = deleted

    # --- Canonical Proteins ---
    other_active_protein = Protein.objects.filter(
        pipeline_run__lifecycle_status=PipelineRun.LifecycleStatus.ACTIVE,
        genome__accession=OuterRef("genome__accession"),
        protein_id=OuterRef("protein_id"),
    ).exclude(pipeline_run=pipeline_run)

    promoted = 0
    for cp in (
        CanonicalProtein.objects.filter(latest_pipeline_run=pipeline_run)
        .filter(Exists(other_active_protein))
        .select_related("genome")
    ):
        pred_run = (
            PipelineRun.objects.filter(
                lifecycle_status=PipelineRun.LifecycleStatus.ACTIVE,
                proteins__genome__accession=cp.genome.accession,
                proteins__protein_id=cp.protein_id,
            )
            .exclude(pk=pipeline_run.pk)
            .order_by("-imported_at", "-pk")
            .first()
        )
        pred_batch = _latest_completed_batch(pred_run)
        if pred_run and pred_batch:
            CanonicalProtein.objects.filter(pk=cp.pk).update(
                latest_pipeline_run=pred_run,
                latest_import_batch=pred_batch,
            )
            promoted += 1
    counts["canonical_proteins_promoted"] = promoted

    deleted, _ = CanonicalProtein.objects.filter(latest_pipeline_run=pipeline_run).delete()
    counts["canonical_proteins_deleted"] = deleted

    # --- Canonical Repeat Calls ---
    other_active_repeat_call = RepeatCall.objects.filter(
        pipeline_run__lifecycle_status=PipelineRun.LifecycleStatus.ACTIVE,
        genome__accession=OuterRef("genome__accession"),
        protein__protein_id=OuterRef("protein__protein_id"),
        sequence__sequence_id=OuterRef("sequence__sequence_id"),
        method=OuterRef("method"),
        repeat_residue=OuterRef("repeat_residue"),
        start=OuterRef("start"),
        end=OuterRef("end"),
    ).exclude(pipeline_run=pipeline_run)

    promoted = 0
    for crc in (
        CanonicalRepeatCall.objects.filter(latest_pipeline_run=pipeline_run)
        .filter(Exists(other_active_repeat_call))
        .select_related("genome", "sequence", "protein")
    ):
        pred_rc = (
            RepeatCall.objects.filter(
                pipeline_run__lifecycle_status=PipelineRun.LifecycleStatus.ACTIVE,
                genome__accession=crc.genome.accession,
                protein__protein_id=crc.protein.protein_id,
                sequence__sequence_id=crc.sequence.sequence_id,
                method=crc.method,
                repeat_residue=crc.repeat_residue,
                start=crc.start,
                end=crc.end,
            )
            .exclude(pipeline_run=pipeline_run)
            .order_by("-pipeline_run__imported_at", "-pipeline_run__pk")
            .first()
        )
        if pred_rc is None:
            continue
        pred_batch = _latest_completed_batch(pred_rc.pipeline_run)
        if pred_batch is None:
            continue
        CanonicalRepeatCall.objects.filter(pk=crc.pk).update(
            latest_pipeline_run=pred_rc.pipeline_run,
            latest_import_batch=pred_batch,
            latest_repeat_call=pred_rc,
        )
        promoted += 1
    counts["canonical_repeat_calls_promoted"] = promoted

    deleted, _ = CanonicalRepeatCall.objects.filter(latest_pipeline_run=pipeline_run).delete()
    counts["canonical_repeat_calls_deleted"] = deleted

    return counts


def _latest_completed_batch(pipeline_run: PipelineRun | None) -> ImportBatch | None:
    if pipeline_run is None:
        return None
    return (
        ImportBatch.objects.filter(pipeline_run=pipeline_run, status=ImportBatch.Status.COMPLETED)
        .order_by("-started_at")
        .first()
    )
