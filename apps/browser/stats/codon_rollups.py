from __future__ import annotations

from collections import defaultdict

from django.db import connection, transaction
from django.utils import timezone

from ..models import (
    CanonicalCodonCompositionSummary,
    CanonicalRepeatCall,
    CanonicalRepeatCallCodonUsage,
    TaxonClosure,
)
from .params import ALLOWED_STATS_RANKS


def rebuild_canonical_codon_composition_summaries() -> int:
    with transaction.atomic():
        if connection.vendor == "postgresql":
            return _rebuild_canonical_codon_composition_summaries_postgresql()
        return _rebuild_canonical_codon_composition_summaries_python()


def _rebuild_canonical_codon_composition_summaries_postgresql() -> int:
    table_name = CanonicalCodonCompositionSummary._meta.db_table
    rank_placeholders = ", ".join(["%s"] * len(ALLOWED_STATS_RANKS))
    sql = f"""
        WITH call_scope AS MATERIALIZED (
            SELECT
                repeat_call.id AS repeat_call_id,
                repeat_call.repeat_residue AS repeat_residue,
                repeat_call.taxon_id AS species_taxon_id,
                closure.ancestor_id AS display_taxon_id,
                display_taxon.taxon_name AS display_taxon_name,
                display_taxon.rank AS display_rank
            FROM browser_canonicalrepeatcall repeat_call
            INNER JOIN browser_taxonclosure closure
                ON closure.descendant_id = repeat_call.taxon_id
            INNER JOIN browser_taxon display_taxon
                ON display_taxon.id = closure.ancestor_id
            WHERE display_taxon.rank IN ({rank_placeholders})
        ),
        residue_species_calls AS MATERIALIZED (
            SELECT
                scope.repeat_residue,
                scope.display_rank,
                scope.display_taxon_id,
                scope.display_taxon_name,
                scope.species_taxon_id,
                COUNT(*)::bigint AS call_count
            FROM call_scope scope
            GROUP BY
                scope.repeat_residue,
                scope.display_rank,
                scope.display_taxon_id,
                scope.display_taxon_name,
                scope.species_taxon_id
        ),
        display_taxon_counts AS MATERIALIZED (
            SELECT
                species_calls.repeat_residue,
                species_calls.display_rank,
                species_calls.display_taxon_id,
                species_calls.display_taxon_name,
                SUM(species_calls.call_count)::bigint AS observation_count,
                COUNT(*)::bigint AS species_count
            FROM residue_species_calls species_calls
            GROUP BY
                species_calls.repeat_residue,
                species_calls.display_rank,
                species_calls.display_taxon_id,
                species_calls.display_taxon_name
        ),
        residue_codons AS MATERIALIZED (
            SELECT DISTINCT
                codon_usage.amino_acid AS repeat_residue,
                codon_usage.codon AS codon
            FROM browser_canonicalrepeatcallcodonusage codon_usage
        ),
        species_codon_sums AS MATERIALIZED (
            SELECT
                scope.repeat_residue,
                scope.display_rank,
                scope.display_taxon_id,
                scope.species_taxon_id,
                codon_usage.codon,
                SUM(codon_usage.codon_fraction)::double precision AS codon_fraction_sum
            FROM call_scope scope
            INNER JOIN browser_canonicalrepeatcallcodonusage codon_usage
                ON codon_usage.repeat_call_id = scope.repeat_call_id
               AND codon_usage.amino_acid = scope.repeat_residue
            GROUP BY
                scope.repeat_residue,
                scope.display_rank,
                scope.display_taxon_id,
                scope.species_taxon_id,
                codon_usage.codon
        )
        INSERT INTO {table_name} (
            created_at,
            updated_at,
            repeat_residue,
            display_rank,
            display_taxon_id,
            display_taxon_name,
            observation_count,
            species_count,
            codon,
            codon_share
        )
        SELECT
            NOW(),
            NOW(),
            display_taxon_counts.repeat_residue,
            display_taxon_counts.display_rank,
            display_taxon_counts.display_taxon_id,
            display_taxon_counts.display_taxon_name,
            display_taxon_counts.observation_count,
            display_taxon_counts.species_count,
            residue_codons.codon,
            COALESCE(
                SUM(
                    COALESCE(species_codon_sums.codon_fraction_sum, 0.0)
                    / residue_species_calls.call_count::double precision
                )
                / display_taxon_counts.species_count::double precision,
                0.0
            ) AS codon_share
        FROM display_taxon_counts
        INNER JOIN residue_codons
            ON residue_codons.repeat_residue = display_taxon_counts.repeat_residue
        INNER JOIN residue_species_calls
            ON residue_species_calls.repeat_residue = display_taxon_counts.repeat_residue
           AND residue_species_calls.display_rank = display_taxon_counts.display_rank
           AND residue_species_calls.display_taxon_id = display_taxon_counts.display_taxon_id
        LEFT JOIN species_codon_sums
            ON species_codon_sums.repeat_residue = residue_species_calls.repeat_residue
           AND species_codon_sums.display_rank = residue_species_calls.display_rank
           AND species_codon_sums.display_taxon_id = residue_species_calls.display_taxon_id
           AND species_codon_sums.species_taxon_id = residue_species_calls.species_taxon_id
           AND species_codon_sums.codon = residue_codons.codon
        GROUP BY
            display_taxon_counts.repeat_residue,
            display_taxon_counts.display_rank,
            display_taxon_counts.display_taxon_id,
            display_taxon_counts.display_taxon_name,
            display_taxon_counts.observation_count,
            display_taxon_counts.species_count,
            residue_codons.codon
    """
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL work_mem = '512MB'")
        cursor.execute(f"DELETE FROM {table_name}")
        cursor.execute(sql, list(ALLOWED_STATS_RANKS))
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        return int(cursor.fetchone()[0] or 0)


def _rebuild_canonical_codon_composition_summaries_python() -> int:
    CanonicalCodonCompositionSummary.objects.all().delete()

    repeat_calls = list(
        CanonicalRepeatCall.objects.order_by().values_list("id", "repeat_residue", "taxon_id")
    )
    if not repeat_calls:
        return 0

    species_taxon_ids = {taxon_id for _, _, taxon_id in repeat_calls}
    ancestor_rows = (
        TaxonClosure.objects.filter(
            descendant_id__in=species_taxon_ids,
            ancestor__rank__in=ALLOWED_STATS_RANKS,
        )
        .select_related("ancestor")
        .order_by("descendant_id", "ancestor__taxon_id")
    )
    ancestor_details_by_species_taxon_id: dict[int, list[tuple[int, str, str]]] = defaultdict(list)
    for ancestor_row in ancestor_rows:
        ancestor_details_by_species_taxon_id[ancestor_row.descendant_id].append(
            (
                ancestor_row.ancestor_id,
                ancestor_row.ancestor.taxon_name,
                ancestor_row.ancestor.rank,
            )
        )

    call_details_by_id: dict[int, tuple[str, int, list[tuple[int, str, str]]]] = {}
    call_count_by_species_taxon: dict[tuple[str, str, int, int], int] = defaultdict(int)
    display_taxon_counts: dict[tuple[str, str, int, str], dict[str, int]] = {}
    for repeat_call_id, repeat_residue, species_taxon_id in repeat_calls:
        ancestor_details = ancestor_details_by_species_taxon_id.get(species_taxon_id, [])
        call_details_by_id[repeat_call_id] = (repeat_residue, species_taxon_id, ancestor_details)
        for display_taxon_id, display_taxon_name, display_rank in ancestor_details:
            species_key = (
                repeat_residue,
                display_rank,
                display_taxon_id,
                species_taxon_id,
            )
            call_count_by_species_taxon[species_key] += 1
            counts_key = (
                repeat_residue,
                display_rank,
                display_taxon_id,
                display_taxon_name,
            )
            counts = display_taxon_counts.setdefault(
                counts_key,
                {
                    "observation_count": 0,
                    "species_count": 0,
                },
            )
            counts["observation_count"] += 1

    species_keys_by_display_taxon: dict[tuple[str, str, int, str], list[int]] = defaultdict(list)
    for repeat_residue, display_rank, display_taxon_id, species_taxon_id in call_count_by_species_taxon:
        display_taxon_name = next(
            key[3]
            for key in display_taxon_counts
            if key[0] == repeat_residue
            and key[1] == display_rank
            and key[2] == display_taxon_id
        )
        species_keys_by_display_taxon[
            (
                repeat_residue,
                display_rank,
                display_taxon_id,
                display_taxon_name,
            )
        ].append(species_taxon_id)

    for counts_key, species_taxon_ids_for_group in species_keys_by_display_taxon.items():
        display_taxon_counts[counts_key]["species_count"] = len(species_taxon_ids_for_group)

    residue_codons: dict[str, set[str]] = defaultdict(set)
    species_codon_fraction_sums: dict[tuple[str, str, int, int, str], float] = defaultdict(float)
    codon_usage_rows = CanonicalRepeatCallCodonUsage.objects.order_by().values_list(
        "repeat_call_id",
        "amino_acid",
        "codon",
        "codon_fraction",
    )
    for repeat_call_id, amino_acid, codon, codon_fraction in codon_usage_rows:
        call_details = call_details_by_id.get(repeat_call_id)
        if call_details is None:
            continue

        repeat_residue, species_taxon_id, ancestor_details = call_details
        if amino_acid != repeat_residue:
            continue

        residue_codons[repeat_residue].add(codon)
        for display_taxon_id, _, display_rank in ancestor_details:
            species_codon_fraction_sums[
                (
                    repeat_residue,
                    display_rank,
                    display_taxon_id,
                    species_taxon_id,
                    codon,
                )
            ] += float(codon_fraction)

    now = timezone.now()
    summary_rows: list[CanonicalCodonCompositionSummary] = []
    for (
        repeat_residue,
        display_rank,
        display_taxon_id,
        display_taxon_name,
    ), counts in display_taxon_counts.items():
        visible_codons = sorted(residue_codons.get(repeat_residue, set()))
        if not visible_codons:
            continue

        species_taxon_ids_for_group = species_keys_by_display_taxon[
            (
                repeat_residue,
                display_rank,
                display_taxon_id,
                display_taxon_name,
            )
        ]
        species_count = counts["species_count"]
        for codon in visible_codons:
            codon_share_total = 0.0
            for species_taxon_id in species_taxon_ids_for_group:
                call_count = call_count_by_species_taxon[
                    (
                        repeat_residue,
                        display_rank,
                        display_taxon_id,
                        species_taxon_id,
                    )
                ]
                codon_fraction_sum = species_codon_fraction_sums.get(
                    (
                        repeat_residue,
                        display_rank,
                        display_taxon_id,
                        species_taxon_id,
                        codon,
                    ),
                    0.0,
                )
                codon_share_total += codon_fraction_sum / call_count

            summary_rows.append(
                CanonicalCodonCompositionSummary(
                    created_at=now,
                    updated_at=now,
                    repeat_residue=repeat_residue,
                    display_rank=display_rank,
                    display_taxon_id=display_taxon_id,
                    display_taxon_name=display_taxon_name,
                    observation_count=counts["observation_count"],
                    species_count=species_count,
                    codon=codon,
                    codon_share=codon_share_total / species_count,
                )
            )

    if summary_rows:
        CanonicalCodonCompositionSummary.objects.bulk_create(summary_rows, batch_size=1000)
    return len(summary_rows)
