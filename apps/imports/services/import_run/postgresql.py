from __future__ import annotations

from pathlib import Path

from django.db import connection

from apps.browser.models.genomes import Genome, Protein, Sequence
from apps.browser.models.repeat_calls import RepeatCall
from apps.browser.models.runs import AcquisitionBatch, PipelineRun
from apps.browser.models.taxonomy import Taxon
from apps.imports.models import ImportBatch
from apps.imports.services.published_run import (
    BatchArtifactPaths,
    ImportContractError,
    InspectedPublishedRun,
    iter_accession_call_count_rows,
    iter_accession_status_rows,
    iter_codon_usage_artifact_rows,
    iter_genome_rows,
    iter_protein_rows,
    iter_repeat_call_rows,
    iter_run_parameter_rows,
    iter_sequence_rows,
)

from .copy import _copy_rows_to_table
from .entities import _create_acquisition_batches, _parse_codon_ratio_value
from .operational import (
    _create_accession_call_count_rows_streamed,
    _create_accession_status_rows_streamed,
    _create_download_manifest_entries_streamed,
    _create_normalization_warning_rows_streamed,
    _create_run_parameters_streamed,
)
from .orchestrator import _upsert_pipeline_run
from .state import ImportPhase, _ImportBatchStateReporter, _set_batch_state
from .taxonomy import _load_taxonomy_rows, _rebuild_taxon_closure, _upsert_taxa


_TMP_REPEAT_CALLS = "tmp_homorepeat_import_repeat_calls"
_TMP_GENOMES = "tmp_homorepeat_import_genomes"
_TMP_SEQUENCES = "tmp_homorepeat_import_sequences"
_TMP_PROTEINS = "tmp_homorepeat_import_proteins"
_TMP_FASTA = "tmp_homorepeat_import_fasta"
_TMP_FASTA_UNIQUE = "tmp_homorepeat_import_fasta_unique"
_TMP_RETAINED_SEQUENCES = "tmp_homorepeat_import_retained_sequences"
_TMP_RETAINED_PROTEINS = "tmp_homorepeat_import_retained_proteins"


def _import_inspected_run_postgresql(
    batch: ImportBatch,
    inspected: InspectedPublishedRun,
    *,
    replace_existing: bool,
    reporter: _ImportBatchStateReporter | None = None,
) -> tuple[PipelineRun, dict[str, int]]:
    if connection.vendor != "postgresql":
        raise ImportContractError("The PostgreSQL streaming importer requires the PostgreSQL backend.")

    pipeline_run = _upsert_pipeline_run(inspected.pipeline_run, replace_existing=replace_existing)

    _set_batch_state(
        batch,
        phase=ImportPhase.PREPARING,
        progress_payload={
            "message": "Staging repeat-call rows in PostgreSQL.",
            "batch_count": len(inspected.artifact_paths.acquisition_batches),
        },
        reporter=reporter,
    )
    repeat_call_count = _stage_repeat_call_rows(inspected)
    retained_sequence_count, retained_protein_count = _create_retained_entity_tables()
    _set_batch_state(
        batch,
        phase=ImportPhase.PREPARING,
        progress_payload={
            "message": "Staged repeat-call rows in PostgreSQL.",
            "current": repeat_call_count,
            "total": repeat_call_count,
            "unit": "repeat calls",
            "batch_count": len(inspected.artifact_paths.acquisition_batches),
            "retained_sequences": retained_sequence_count,
            "retained_proteins": retained_protein_count,
        },
        reporter=reporter,
        force=True,
    )

    taxonomy_rows = _load_taxonomy_rows(inspected)
    _upsert_taxa(taxonomy_rows)
    _rebuild_taxon_closure()
    batch_by_batch_id = _create_acquisition_batches(
        pipeline_run,
        inspected.artifact_paths.acquisition_batches,
    )

    genome_count = _create_genomes_postgresql(batch, pipeline_run, inspected, reporter=reporter)

    sequence_count, protein_count = _create_call_linked_entities_postgresql(
        batch,
        pipeline_run,
        inspected.artifact_paths.acquisition_batches,
        retained_sequence_count=retained_sequence_count,
        retained_protein_count=retained_protein_count,
        reporter=reporter,
    )

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

    repeat_call_count = _create_repeat_calls_postgresql(batch, pipeline_run, reporter=reporter)
    repeat_call_codon_usage_count = _create_repeat_call_codon_usages_postgresql(
        batch,
        pipeline_run,
        inspected,
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
        "genomes": genome_count,
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


def _stage_repeat_call_rows(inspected: InspectedPublishedRun) -> int:
    _create_temp_table(
        _TMP_REPEAT_CALLS,
        """
        call_id text NOT NULL,
        method text NOT NULL,
        genome_id text NOT NULL,
        taxon_id bigint NOT NULL,
        sequence_id text NOT NULL,
        protein_id text NOT NULL,
        repeat_start integer NOT NULL,
        repeat_end integer NOT NULL,
        length integer NOT NULL,
        repeat_residue text NOT NULL,
        repeat_count integer NOT NULL,
        non_repeat_count integer NOT NULL,
        purity double precision NOT NULL,
        aa_sequence text NOT NULL,
        codon_sequence text NOT NULL,
        codon_metric_name text NOT NULL,
        codon_metric_value text NOT NULL,
        codon_ratio_value double precision,
        window_definition text NOT NULL,
        template_name text NOT NULL,
        merge_rule text NOT NULL,
        score text NOT NULL
        """,
    )
    count = _copy_or_raise(
        _TMP_REPEAT_CALLS,
        [
            "call_id",
            "method",
            "genome_id",
            "taxon_id",
            "sequence_id",
            "protein_id",
            "repeat_start",
            "repeat_end",
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
                str(row["call_id"]),
                str(row["method"]),
                str(row["genome_id"]),
                int(row["taxon_id"]),
                str(row["sequence_id"]),
                str(row["protein_id"]),
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
            for row in iter_repeat_call_rows(inspected.artifact_paths.repeat_calls_tsv)
        ),
    )
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE INDEX {_TMP_REPEAT_CALLS}_call_id_idx ON {_TMP_REPEAT_CALLS} (call_id)")
        cursor.execute(f"CREATE INDEX {_TMP_REPEAT_CALLS}_sequence_id_idx ON {_TMP_REPEAT_CALLS} (sequence_id)")
        cursor.execute(f"CREATE INDEX {_TMP_REPEAT_CALLS}_protein_id_idx ON {_TMP_REPEAT_CALLS} (protein_id)")
        cursor.execute(f"CREATE INDEX {_TMP_REPEAT_CALLS}_genome_id_idx ON {_TMP_REPEAT_CALLS} (genome_id)")
    _raise_if_rows(
        f"""
        SELECT call_id
        FROM {_TMP_REPEAT_CALLS}
        GROUP BY call_id
        HAVING COUNT(*) > 1
        LIMIT 5
        """,
        [],
        "Duplicate repeat-call IDs in repeat_calls.tsv",
    )
    return count


def _create_retained_entity_tables() -> tuple[int, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            DROP TABLE IF EXISTS {_TMP_RETAINED_SEQUENCES}
            """
        )
        cursor.execute(
            f"""
            DROP TABLE IF EXISTS {_TMP_RETAINED_PROTEINS}
            """
        )
        cursor.execute(
            f"""
            CREATE TEMP TABLE {_TMP_RETAINED_SEQUENCES} ON COMMIT DROP AS
            SELECT DISTINCT sequence_id
            FROM {_TMP_REPEAT_CALLS}
            """
        )
        cursor.execute(
            f"""
            CREATE TEMP TABLE {_TMP_RETAINED_PROTEINS} ON COMMIT DROP AS
            SELECT protein_id, COUNT(*)::integer AS repeat_call_count
            FROM {_TMP_REPEAT_CALLS}
            GROUP BY protein_id
            """
        )
        cursor.execute(f"CREATE INDEX {_TMP_RETAINED_SEQUENCES}_sequence_id_idx ON {_TMP_RETAINED_SEQUENCES} (sequence_id)")
        cursor.execute(f"CREATE INDEX {_TMP_RETAINED_PROTEINS}_protein_id_idx ON {_TMP_RETAINED_PROTEINS} (protein_id)")
        cursor.execute(f"SELECT COUNT(*) FROM {_TMP_RETAINED_SEQUENCES}")
        sequence_count = cursor.fetchone()[0]
        cursor.execute(f"SELECT COUNT(*) FROM {_TMP_RETAINED_PROTEINS}")
        protein_count = cursor.fetchone()[0]
    return int(sequence_count or 0), int(protein_count or 0)


def _create_genomes_postgresql(
    batch: ImportBatch,
    pipeline_run: PipelineRun,
    inspected: InspectedPublishedRun,
    *,
    reporter: _ImportBatchStateReporter | None = None,
) -> int:
    _create_temp_table(
        _TMP_GENOMES,
        """
        batch_id text NOT NULL,
        genome_id text NOT NULL,
        source text NOT NULL,
        accession text NOT NULL,
        genome_name text NOT NULL,
        assembly_type text NOT NULL,
        taxon_id bigint NOT NULL,
        assembly_level text NOT NULL,
        species_name text NOT NULL,
        notes text NOT NULL
        """,
    )
    _copy_or_raise(
        _TMP_GENOMES,
        [
            "batch_id",
            "genome_id",
            "source",
            "accession",
            "genome_name",
            "assembly_type",
            "taxon_id",
            "assembly_level",
            "species_name",
            "notes",
        ],
        (
            (
                str(row["batch_id"]),
                str(row["genome_id"]),
                str(row["source"]),
                str(row["accession"]),
                str(row["genome_name"]),
                str(row["assembly_type"]),
                int(row["taxon_id"]),
                str(row.get("assembly_level", "")),
                str(row.get("species_name", "")),
                str(row.get("notes", "")),
            )
            for batch_paths in inspected.artifact_paths.acquisition_batches
            for row in iter_genome_rows(batch_paths.genomes_tsv, batch_id=batch_paths.batch_id)
        ),
    )
    _raise_if_rows(
        f"""
        SELECT staged.batch_id
        FROM {_TMP_GENOMES} staged
        LEFT JOIN {AcquisitionBatch._meta.db_table} batch
          ON batch.pipeline_run_id = %s AND batch.batch_id = staged.batch_id
        WHERE batch.id IS NULL
        LIMIT 5
        """,
        [pipeline_run.pk],
        "Genome rows reference missing acquisition batches",
    )
    _raise_if_rows(
        f"""
        SELECT staged.taxon_id
        FROM {_TMP_GENOMES} staged
        LEFT JOIN {Taxon._meta.db_table} taxon ON taxon.taxon_id = staged.taxon_id
        WHERE taxon.id IS NULL
        LIMIT 5
        """,
        [],
        "Genome rows reference missing taxa",
    )
    _raise_if_rows(
        f"""
        SELECT genome_id
        FROM {_TMP_GENOMES}
        GROUP BY genome_id
        HAVING COUNT(DISTINCT (batch_id, source, accession, genome_name, assembly_type, taxon_id,
                               assembly_level, species_name, notes)) > 1
        LIMIT 5
        """,
        [],
        "Conflicting duplicate genome rows",
    )
    genome_total = _count_sql(f"SELECT COUNT(DISTINCT genome_id) FROM {_TMP_GENOMES}")
    _set_batch_state(
        batch,
        phase=ImportPhase.IMPORTING,
        progress_payload={
            "message": "Importing genome rows.",
            "current": 0,
            "total": genome_total,
            "unit": "genomes",
        },
        reporter=reporter,
        force=True,
    )

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {Genome._meta.db_table}
                (created_at, updated_at, pipeline_run_id, batch_id, genome_id, source, accession,
                 genome_name, assembly_type, taxon_id, assembly_level, species_name,
                 analyzed_protein_count, notes)
            SELECT
                NOW(), NOW(), %s, batch.id, staged.genome_id, staged.source, staged.accession,
                staged.genome_name, staged.assembly_type, taxon.id, staged.assembly_level,
                staged.species_name, 0, staged.notes
            FROM (
                SELECT DISTINCT ON (genome_id) *
                FROM {_TMP_GENOMES}
                ORDER BY genome_id
            ) staged
            JOIN {AcquisitionBatch._meta.db_table} batch
              ON batch.pipeline_run_id = %s AND batch.batch_id = staged.batch_id
            JOIN {Taxon._meta.db_table} taxon ON taxon.taxon_id = staged.taxon_id
            """,
            [pipeline_run.pk, pipeline_run.pk],
        )
        inserted = int(cursor.rowcount or 0)
    _set_batch_state(
        batch,
        phase=ImportPhase.IMPORTING,
        progress_payload={
            "message": "Imported genome rows.",
            "current": inserted,
            "total": genome_total,
            "unit": "genomes",
        },
        reporter=reporter,
        force=True,
    )
    return inserted


def _create_call_linked_entities_postgresql(
    batch: ImportBatch,
    pipeline_run: PipelineRun,
    batch_paths: tuple[BatchArtifactPaths, ...],
    *,
    retained_sequence_count: int,
    retained_protein_count: int,
    reporter: _ImportBatchStateReporter | None = None,
) -> tuple[int, int]:
    total_sequences = 0
    total_proteins = 0

    for batch_path in batch_paths:
        sequence_count = _create_sequences_for_batch_postgresql(pipeline_run, batch_path)
        total_sequences += sequence_count
        _set_batch_state(
            batch,
            phase=ImportPhase.IMPORTING,
            progress_payload={
                "message": "Importing retained sequence rows.",
                "current": total_sequences,
                "total": retained_sequence_count,
                "unit": "sequences",
                "batch_id": batch_path.batch_id,
                "inserted_sequences": total_sequences,
                "inserted_proteins": total_proteins,
            },
            reporter=reporter,
        )

        protein_count = _create_proteins_for_batch_postgresql(
            batch,
            pipeline_run,
            batch_path,
            inserted_sequences=total_sequences,
            inserted_proteins=total_proteins,
            retained_protein_count=retained_protein_count,
            reporter=reporter,
        )
        total_proteins += protein_count
        _set_batch_state(
            batch,
            phase=ImportPhase.IMPORTING,
            progress_payload={
                "message": "Importing retained protein rows.",
                "current": total_proteins,
                "total": retained_protein_count,
                "unit": "proteins",
                "batch_id": batch_path.batch_id,
                "inserted_sequences": total_sequences,
                "inserted_proteins": total_proteins,
            },
            reporter=reporter,
        )

    return total_sequences, total_proteins


def _create_sequences_for_batch_postgresql(
    pipeline_run: PipelineRun,
    batch_path: BatchArtifactPaths,
) -> int:
    _stage_sequence_rows(batch_path)
    _validate_sequence_stage(pipeline_run)
    _stage_fasta_rows(batch_path.cds_fna, label="CDS")
    _raise_if_rows(
        f"""
        SELECT staged.sequence_id
        FROM {_TMP_SEQUENCES} staged
        JOIN {_TMP_RETAINED_SEQUENCES} retained
          ON retained.sequence_id = staged.sequence_id
        LEFT JOIN {_TMP_FASTA_UNIQUE} fasta ON fasta.record_id = staged.sequence_id
        WHERE fasta.record_id IS NULL
        LIMIT 5
        """,
        [],
        "Missing CDS FASTA records for retained sequence IDs",
    )
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {Sequence._meta.db_table}
                (created_at, updated_at, pipeline_run_id, genome_id, taxon_id, sequence_id,
                 sequence_name, sequence_length, nucleotide_sequence, gene_symbol, transcript_id,
                 isoform_id, assembly_accession, source_record_id, protein_external_id,
                 translation_table, gene_group, linkage_status, partial_status)
            SELECT
                NOW(), NOW(), %s, genome.id, COALESCE(taxon.id, genome.taxon_id),
                staged.sequence_id, staged.sequence_name, staged.sequence_length,
                fasta.sequence_value, staged.gene_symbol, staged.transcript_id,
                staged.isoform_id, staged.assembly_accession, staged.source_record_id,
                staged.protein_external_id, staged.translation_table, staged.gene_group,
                staged.linkage_status, staged.partial_status
            FROM {_TMP_SEQUENCES} staged
            JOIN {_TMP_RETAINED_SEQUENCES} retained
              ON retained.sequence_id = staged.sequence_id
            JOIN {Genome._meta.db_table} genome
              ON genome.pipeline_run_id = %s AND genome.genome_id = staged.genome_id
            LEFT JOIN {Taxon._meta.db_table} taxon ON taxon.taxon_id = staged.taxon_id
            JOIN {_TMP_FASTA_UNIQUE} fasta ON fasta.record_id = staged.sequence_id
            """,
            [pipeline_run.pk, pipeline_run.pk],
        )
        return int(cursor.rowcount or 0)


def _set_protein_batch_state(
    batch: ImportBatch,
    *,
    message: str,
    batch_id: str,
    inserted_sequences: int,
    inserted_proteins: int,
    retained_protein_count: int,
    reporter: _ImportBatchStateReporter | None = None,
    force: bool = False,
) -> None:
    _set_batch_state(
        batch,
        phase=ImportPhase.IMPORTING,
        progress_payload={
            "message": message,
            "current": inserted_proteins,
            "total": retained_protein_count,
            "unit": "proteins",
            "batch_id": batch_id,
            "inserted_sequences": inserted_sequences,
            "inserted_proteins": inserted_proteins,
        },
        reporter=reporter,
        force=force,
    )


def _create_proteins_for_batch_postgresql(
    batch: ImportBatch,
    pipeline_run: PipelineRun,
    batch_path: BatchArtifactPaths,
    *,
    inserted_sequences: int,
    inserted_proteins: int,
    retained_protein_count: int,
    reporter: _ImportBatchStateReporter | None = None,
) -> int:
    _set_protein_batch_state(
        batch,
        message="Staging protein TSV rows.",
        batch_id=batch_path.batch_id,
        inserted_sequences=inserted_sequences,
        inserted_proteins=inserted_proteins,
        retained_protein_count=retained_protein_count,
        reporter=reporter,
        force=True,
    )
    _stage_protein_rows(batch_path)
    _set_protein_batch_state(
        batch,
        message="Validating protein references.",
        batch_id=batch_path.batch_id,
        inserted_sequences=inserted_sequences,
        inserted_proteins=inserted_proteins,
        retained_protein_count=retained_protein_count,
        reporter=reporter,
        force=True,
    )
    _validate_protein_stage(pipeline_run)
    _set_protein_batch_state(
        batch,
        message="Updating genome analyzed-protein counts.",
        batch_id=batch_path.batch_id,
        inserted_sequences=inserted_sequences,
        inserted_proteins=inserted_proteins,
        retained_protein_count=retained_protein_count,
        reporter=reporter,
        force=True,
    )
    _update_genome_analyzed_protein_counts(pipeline_run)
    _set_protein_batch_state(
        batch,
        message="Staging protein FASTA rows.",
        batch_id=batch_path.batch_id,
        inserted_sequences=inserted_sequences,
        inserted_proteins=inserted_proteins,
        retained_protein_count=retained_protein_count,
        reporter=reporter,
        force=True,
    )
    _stage_fasta_rows(batch_path.proteins_faa, label="protein")
    _set_protein_batch_state(
        batch,
        message="Checking retained protein FASTA coverage.",
        batch_id=batch_path.batch_id,
        inserted_sequences=inserted_sequences,
        inserted_proteins=inserted_proteins,
        retained_protein_count=retained_protein_count,
        reporter=reporter,
        force=True,
    )
    _raise_if_rows(
        f"""
        SELECT staged.protein_id
        FROM {_TMP_PROTEINS} staged
        JOIN {_TMP_RETAINED_PROTEINS} retained
          ON retained.protein_id = staged.protein_id
        LEFT JOIN {_TMP_FASTA_UNIQUE} fasta ON fasta.record_id = staged.protein_id
        WHERE fasta.record_id IS NULL
        LIMIT 5
        """,
        [],
        "Missing protein FASTA records for retained protein IDs",
    )
    _set_protein_batch_state(
        batch,
        message="Inserting retained protein rows.",
        batch_id=batch_path.batch_id,
        inserted_sequences=inserted_sequences,
        inserted_proteins=inserted_proteins,
        retained_protein_count=retained_protein_count,
        reporter=reporter,
        force=True,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {Protein._meta.db_table}
                (created_at, updated_at, pipeline_run_id, genome_id, sequence_id, taxon_id,
                 protein_id, protein_name, protein_length, accession, amino_acid_sequence,
                 gene_symbol, translation_method, translation_status, assembly_accession,
                 gene_group, protein_external_id, repeat_call_count)
            SELECT
                NOW(), NOW(), %s, genome.id, sequence.id, COALESCE(taxon.id, genome.taxon_id),
                staged.protein_id, staged.protein_name, staged.protein_length,
                COALESCE(NULLIF(staged.assembly_accession, ''), genome.accession),
                fasta.sequence_value, staged.gene_symbol, staged.translation_method,
                staged.translation_status, staged.assembly_accession, staged.gene_group,
                staged.protein_external_id, call_counts.repeat_call_count
            FROM {_TMP_PROTEINS} staged
            JOIN {Genome._meta.db_table} genome
              ON genome.pipeline_run_id = %s AND genome.genome_id = staged.genome_id
            JOIN {Sequence._meta.db_table} sequence
              ON sequence.pipeline_run_id = %s AND sequence.sequence_id = staged.sequence_id
            LEFT JOIN {Taxon._meta.db_table} taxon ON taxon.taxon_id = staged.taxon_id
            JOIN {_TMP_FASTA_UNIQUE} fasta ON fasta.record_id = staged.protein_id
            JOIN {_TMP_RETAINED_PROTEINS} call_counts ON call_counts.protein_id = staged.protein_id
            """,
            [pipeline_run.pk, pipeline_run.pk, pipeline_run.pk],
        )
        return int(cursor.rowcount or 0)


def _create_repeat_calls_postgresql(
    batch: ImportBatch,
    pipeline_run: PipelineRun,
    *,
    reporter: _ImportBatchStateReporter | None = None,
) -> int:
    repeat_call_total = _count_sql(f"SELECT COUNT(*) FROM {_TMP_REPEAT_CALLS}")
    _set_batch_state(
        batch,
        phase=ImportPhase.IMPORTING,
        progress_payload={
            "message": "Bulk-loading repeat-call rows.",
            "current": 0,
            "total": repeat_call_total,
            "unit": "repeat calls",
        },
        reporter=reporter,
        force=True,
    )
    _validate_repeat_call_stage(pipeline_run)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {RepeatCall._meta.db_table}
                (created_at, updated_at, pipeline_run_id, genome_id, sequence_id, protein_id,
                 taxon_id, call_id, method, accession, gene_symbol, protein_name,
                 protein_length, start, "end", length, repeat_residue, repeat_count,
                 non_repeat_count, purity, aa_sequence, codon_sequence, codon_metric_name,
                 codon_metric_value, codon_ratio_value, window_definition, template_name,
                 merge_rule, score)
            SELECT
                NOW(), NOW(), %s, genome.id, sequence.id, protein.id, taxon.id,
                staged.call_id, staged.method, genome.accession,
                COALESCE(NULLIF(protein.gene_symbol, ''), sequence.gene_symbol),
                protein.protein_name, protein.protein_length, staged.repeat_start,
                staged.repeat_end, staged.length, staged.repeat_residue, staged.repeat_count,
                staged.non_repeat_count, staged.purity, staged.aa_sequence,
                staged.codon_sequence, staged.codon_metric_name, staged.codon_metric_value,
                staged.codon_ratio_value, staged.window_definition, staged.template_name,
                staged.merge_rule, staged.score
            FROM {_TMP_REPEAT_CALLS} staged
            JOIN {Genome._meta.db_table} genome
              ON genome.pipeline_run_id = %s AND genome.genome_id = staged.genome_id
            JOIN {Sequence._meta.db_table} sequence
              ON sequence.pipeline_run_id = %s AND sequence.sequence_id = staged.sequence_id
            JOIN {Protein._meta.db_table} protein
              ON protein.pipeline_run_id = %s AND protein.protein_id = staged.protein_id
            JOIN {Taxon._meta.db_table} taxon ON taxon.taxon_id = staged.taxon_id
            """,
            [pipeline_run.pk, pipeline_run.pk, pipeline_run.pk, pipeline_run.pk],
        )
        repeat_call_count = int(cursor.rowcount or 0)
    _set_batch_state(
        batch,
        phase=ImportPhase.IMPORTING,
        progress_payload={
            "message": "Importing repeat-call rows.",
            "current": repeat_call_count,
            "total": repeat_call_total,
            "unit": "repeat calls",
            "repeat_calls": repeat_call_count,
        },
        reporter=reporter,
        force=True,
    )
    return repeat_call_count


def _create_repeat_call_codon_usages_postgresql(
    batch: ImportBatch,
    pipeline_run: PipelineRun,
    inspected: InspectedPublishedRun,
    *,
    reporter: _ImportBatchStateReporter | None = None,
) -> int:
    _create_temp_table(
        "tmp_homorepeat_import_codon_usage",
        """
        call_id text NOT NULL,
        method text NOT NULL,
        repeat_residue text NOT NULL,
        sequence_id text NOT NULL,
        protein_id text NOT NULL,
        amino_acid text NOT NULL,
        codon text NOT NULL,
        codon_count integer NOT NULL,
        codon_fraction double precision NOT NULL
        """,
    )
    count = _copy_or_raise(
        "tmp_homorepeat_import_codon_usage",
        [
            "call_id",
            "method",
            "repeat_residue",
            "sequence_id",
            "protein_id",
            "amino_acid",
            "codon",
            "codon_count",
            "codon_fraction",
        ],
        (
            (
                str(row["call_id"]),
                str(row["method"]),
                str(row["repeat_residue"]),
                str(row["sequence_id"]),
                str(row["protein_id"]),
                str(row["amino_acid"]),
                str(row["codon"]),
                int(row["codon_count"]),
                float(row["codon_fraction"]),
            )
            for row in iter_codon_usage_artifact_rows(inspected.artifact_paths.codon_usage_artifacts)
        ),
    )
    _set_batch_state(
        batch,
        phase=ImportPhase.IMPORTING,
        progress_payload={
            "message": "Staged repeat-call codon-usage rows.",
            "current": count,
            "total": count,
            "unit": "codon-usage rows",
        },
        reporter=reporter,
        force=True,
    )
    _raise_if_rows(
        f"""
        SELECT staged.call_id
        FROM tmp_homorepeat_import_codon_usage staged
        JOIN {_TMP_REPEAT_CALLS} repeat_call ON repeat_call.call_id = staged.call_id
        WHERE staged.method <> repeat_call.method
           OR staged.repeat_residue <> repeat_call.repeat_residue
           OR staged.sequence_id <> repeat_call.sequence_id
           OR staged.protein_id <> repeat_call.protein_id
        LIMIT 5
        """,
        [],
        "Codon usage rows do not match their repeat-call rows",
    )
    _raise_if_rows(
        f"""
        SELECT staged.call_id
        FROM tmp_homorepeat_import_codon_usage staged
        LEFT JOIN {RepeatCall._meta.db_table} repeat_call
          ON repeat_call.pipeline_run_id = %s AND repeat_call.call_id = staged.call_id
        WHERE repeat_call.id IS NULL
        LIMIT 5
        """,
        [pipeline_run.pk],
        "Codon usage rows reference missing repeat-call IDs",
    )
    with connection.cursor() as cursor:
        from apps.browser.models.repeat_calls import RepeatCallCodonUsage

        _set_batch_state(
            batch,
            phase=ImportPhase.IMPORTING,
            progress_payload={
                "message": "Importing repeat-call codon-usage rows.",
                "current": 0,
                "total": count,
                "unit": "codon-usage rows",
            },
            reporter=reporter,
            force=True,
        )
        cursor.execute(
            f"""
            INSERT INTO {RepeatCallCodonUsage._meta.db_table}
                (created_at, updated_at, repeat_call_id, amino_acid, codon, codon_count, codon_fraction)
            SELECT
                NOW(), NOW(), repeat_call.id, staged.amino_acid, staged.codon,
                staged.codon_count, staged.codon_fraction
            FROM tmp_homorepeat_import_codon_usage staged
            JOIN {RepeatCall._meta.db_table} repeat_call
              ON repeat_call.pipeline_run_id = %s AND repeat_call.call_id = staged.call_id
            """,
            [pipeline_run.pk],
        )
        inserted = int(cursor.rowcount or 0)
    _set_batch_state(
        batch,
        phase=ImportPhase.IMPORTING,
        progress_payload={
            "message": "Importing repeat-call codon-usage rows.",
            "current": inserted,
            "total": count,
            "unit": "codon-usage rows",
            "repeat_call_codon_usages": inserted,
        },
        reporter=reporter,
        force=True,
    )
    if inserted != count:
        raise ImportContractError(
            f"Inserted {inserted} repeat-call codon-usage rows, expected {count} staged rows"
        )
    return inserted


def _stage_sequence_rows(batch_path: BatchArtifactPaths) -> None:
    _create_temp_table(
        _TMP_SEQUENCES,
        """
        batch_id text NOT NULL,
        sequence_id text NOT NULL,
        genome_id text NOT NULL,
        sequence_name text NOT NULL,
        sequence_length integer NOT NULL,
        gene_symbol text NOT NULL,
        transcript_id text NOT NULL,
        isoform_id text NOT NULL,
        assembly_accession text NOT NULL,
        taxon_id bigint,
        source_record_id text NOT NULL,
        protein_external_id text NOT NULL,
        translation_table text NOT NULL,
        gene_group text NOT NULL,
        linkage_status text NOT NULL,
        partial_status text NOT NULL
        """,
    )
    _copy_or_raise(
        _TMP_SEQUENCES,
        [
            "batch_id",
            "sequence_id",
            "genome_id",
            "sequence_name",
            "sequence_length",
            "gene_symbol",
            "transcript_id",
            "isoform_id",
            "assembly_accession",
            "taxon_id",
            "source_record_id",
            "protein_external_id",
            "translation_table",
            "gene_group",
            "linkage_status",
            "partial_status",
        ],
        (
            (
                str(row["batch_id"]),
                str(row["sequence_id"]),
                str(row["genome_id"]),
                str(row["sequence_name"]),
                int(row["sequence_length"]),
                str(row.get("gene_symbol", "")),
                str(row.get("transcript_id", "")),
                str(row.get("isoform_id", "")),
                str(row.get("assembly_accession", "")),
                row.get("taxon_id"),
                str(row.get("source_record_id", "")),
                str(row.get("protein_external_id", "")),
                str(row.get("translation_table", "")),
                str(row.get("gene_group", "")),
                str(row.get("linkage_status", "")),
                str(row.get("partial_status", "")),
            )
            for row in iter_sequence_rows(batch_path.sequences_tsv, batch_id=batch_path.batch_id)
        ),
    )
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE INDEX {_TMP_SEQUENCES}_sid_idx ON {_TMP_SEQUENCES} (sequence_id)")
        cursor.execute(f"CREATE INDEX {_TMP_SEQUENCES}_gid_idx ON {_TMP_SEQUENCES} (genome_id)")


def _stage_protein_rows(batch_path: BatchArtifactPaths) -> None:
    _create_temp_table(
        _TMP_PROTEINS,
        """
        batch_id text NOT NULL,
        protein_id text NOT NULL,
        sequence_id text NOT NULL,
        genome_id text NOT NULL,
        protein_name text NOT NULL,
        protein_length integer NOT NULL,
        gene_symbol text NOT NULL,
        translation_method text NOT NULL,
        translation_status text NOT NULL,
        assembly_accession text NOT NULL,
        taxon_id bigint,
        gene_group text NOT NULL,
        protein_external_id text NOT NULL
        """,
    )
    _copy_or_raise(
        _TMP_PROTEINS,
        [
            "batch_id",
            "protein_id",
            "sequence_id",
            "genome_id",
            "protein_name",
            "protein_length",
            "gene_symbol",
            "translation_method",
            "translation_status",
            "assembly_accession",
            "taxon_id",
            "gene_group",
            "protein_external_id",
        ],
        (
            (
                str(row["batch_id"]),
                str(row["protein_id"]),
                str(row["sequence_id"]),
                str(row["genome_id"]),
                str(row["protein_name"]),
                int(row["protein_length"]),
                str(row.get("gene_symbol", "")),
                str(row.get("translation_method", "")),
                str(row.get("translation_status", "")),
                str(row.get("assembly_accession", "")),
                row.get("taxon_id"),
                str(row.get("gene_group", "")),
                str(row.get("protein_external_id", "")),
            )
            for row in iter_protein_rows(batch_path.proteins_tsv, batch_id=batch_path.batch_id)
        ),
    )
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE INDEX {_TMP_PROTEINS}_pid_idx ON {_TMP_PROTEINS} (protein_id)")
        cursor.execute(f"CREATE INDEX {_TMP_PROTEINS}_sid_idx ON {_TMP_PROTEINS} (sequence_id)")
        cursor.execute(f"CREATE INDEX {_TMP_PROTEINS}_gid_idx ON {_TMP_PROTEINS} (genome_id)")


def _stage_fasta_rows(path: Path, *, label: str) -> None:
    _create_temp_table(
        _TMP_FASTA,
        """
        record_id text NOT NULL,
        sequence_value text NOT NULL
        """,
    )
    _copy_or_raise(
        _TMP_FASTA,
        ["record_id", "sequence_value"],
        _iter_fasta_records(path, label=label),
    )
    _raise_if_rows(
        f"""
        SELECT record_id
        FROM {_TMP_FASTA}
        GROUP BY record_id
        HAVING COUNT(DISTINCT sequence_value) > 1
        LIMIT 5
        """,
        [],
        f"Conflicting duplicate {label} FASTA records",
    )
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {_TMP_FASTA_UNIQUE}")
        cursor.execute(
            f"""
            CREATE TEMP TABLE {_TMP_FASTA_UNIQUE} ON COMMIT DROP AS
            SELECT record_id, MIN(sequence_value) AS sequence_value
            FROM {_TMP_FASTA}
            GROUP BY record_id
            """
        )
        cursor.execute(f"CREATE INDEX {_TMP_FASTA_UNIQUE}_record_id_idx ON {_TMP_FASTA_UNIQUE} (record_id)")


def _iter_fasta_records(path: Path, *, label: str):
    current_record_id = ""
    current_chunks: list[str] = []

    def current_record():
        if not current_record_id:
            return None
        return current_record_id, "".join(current_chunks).strip()

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                record = current_record()
                if record is not None:
                    yield record
                current_record_id = line[1:].split()[0]
                current_chunks = []
                continue
            if not current_record_id:
                raise ImportContractError(f"{path} contains {label} FASTA sequence data before the first header")
            current_chunks.append(line)

    record = current_record()
    if record is not None:
        yield record


def _validate_sequence_stage(pipeline_run: PipelineRun) -> None:
    _raise_if_rows(
        f"""
        SELECT staged.genome_id
        FROM {_TMP_SEQUENCES} staged
        LEFT JOIN {Genome._meta.db_table} genome
          ON genome.pipeline_run_id = %s AND genome.genome_id = staged.genome_id
        WHERE genome.id IS NULL
        LIMIT 5
        """,
        [pipeline_run.pk],
        "Sequence rows reference missing genome IDs",
    )
    _raise_if_rows(
        f"""
        SELECT staged.taxon_id
        FROM {_TMP_SEQUENCES} staged
        LEFT JOIN {Taxon._meta.db_table} taxon ON taxon.taxon_id = staged.taxon_id
        WHERE staged.taxon_id IS NOT NULL AND taxon.id IS NULL
        LIMIT 5
        """,
        [],
        "Sequence rows reference missing taxa",
    )


def _validate_protein_stage(pipeline_run: PipelineRun) -> None:
    _raise_if_rows(
        f"""
        SELECT staged.genome_id
        FROM {_TMP_PROTEINS} staged
        LEFT JOIN {Genome._meta.db_table} genome
          ON genome.pipeline_run_id = %s AND genome.genome_id = staged.genome_id
        WHERE genome.id IS NULL
        LIMIT 5
        """,
        [pipeline_run.pk],
        "Protein rows reference missing genome IDs",
    )
    _raise_if_rows(
        f"""
        SELECT staged.sequence_id
        FROM {_TMP_PROTEINS} staged
        LEFT JOIN {_TMP_SEQUENCES} sequence_stage ON sequence_stage.sequence_id = staged.sequence_id
        WHERE sequence_stage.sequence_id IS NULL
        LIMIT 5
        """,
        [],
        "Protein rows reference missing sequence IDs",
    )
    _raise_if_rows(
        f"""
        SELECT staged.taxon_id
        FROM {_TMP_PROTEINS} staged
        LEFT JOIN {Taxon._meta.db_table} taxon ON taxon.taxon_id = staged.taxon_id
        WHERE staged.taxon_id IS NOT NULL AND taxon.id IS NULL
        LIMIT 5
        """,
        [],
        "Protein rows reference missing taxa",
    )


def _validate_repeat_call_stage(pipeline_run: PipelineRun) -> None:
    _raise_if_rows(
        f"""
        SELECT staged.genome_id
        FROM {_TMP_REPEAT_CALLS} staged
        LEFT JOIN {Genome._meta.db_table} genome
          ON genome.pipeline_run_id = %s AND genome.genome_id = staged.genome_id
        WHERE genome.id IS NULL
        LIMIT 5
        """,
        [pipeline_run.pk],
        "Repeat-call rows reference missing genome IDs",
    )
    _raise_if_rows(
        f"""
        SELECT staged.sequence_id
        FROM {_TMP_REPEAT_CALLS} staged
        LEFT JOIN {Sequence._meta.db_table} sequence
          ON sequence.pipeline_run_id = %s AND sequence.sequence_id = staged.sequence_id
        WHERE sequence.id IS NULL
        LIMIT 5
        """,
        [pipeline_run.pk],
        "Repeat-call rows reference missing sequence IDs",
    )
    _raise_if_rows(
        f"""
        SELECT staged.protein_id
        FROM {_TMP_REPEAT_CALLS} staged
        LEFT JOIN {Protein._meta.db_table} protein
          ON protein.pipeline_run_id = %s AND protein.protein_id = staged.protein_id
        WHERE protein.id IS NULL
        LIMIT 5
        """,
        [pipeline_run.pk],
        "Repeat-call rows reference missing protein IDs",
    )
    _raise_if_rows(
        f"""
        SELECT staged.taxon_id
        FROM {_TMP_REPEAT_CALLS} staged
        LEFT JOIN {Taxon._meta.db_table} taxon ON taxon.taxon_id = staged.taxon_id
        WHERE taxon.id IS NULL
        LIMIT 5
        """,
        [],
        "Repeat-call rows reference missing taxa",
    )


def _update_genome_analyzed_protein_counts(pipeline_run: PipelineRun) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {Genome._meta.db_table} genome
            SET analyzed_protein_count = genome.analyzed_protein_count + counts.protein_count,
                updated_at = NOW()
            FROM (
                SELECT genome_id, COUNT(*)::integer AS protein_count
                FROM {_TMP_PROTEINS}
                GROUP BY genome_id
            ) counts
            WHERE genome.pipeline_run_id = %s
              AND genome.genome_id = counts.genome_id
            """,
            [pipeline_run.pk],
        )


def _create_temp_table(table_name: str, column_sql: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
        cursor.execute(f"CREATE TEMP TABLE {table_name} ({column_sql}) ON COMMIT DROP")


def _copy_or_raise(
    table_name: str,
    column_names: list[str],
    rows,
) -> int:
    copied = _copy_rows_to_table(table_name, column_names, rows)
    if copied is None:
        raise ImportContractError("PostgreSQL COPY support is unavailable for streaming import.")
    return copied


def _count_sql(sql: str, params: list[object] | None = None) -> int:
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return int(cursor.fetchone()[0] or 0)


def _raise_if_rows(sql: str, params: list[object], message: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    if not rows:
        return
    preview = ", ".join(str(row[0]) for row in rows[:5])
    raise ImportContractError(f"{message}: {preview}")
