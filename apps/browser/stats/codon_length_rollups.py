from __future__ import annotations

from collections import defaultdict

from django.db import connection, transaction
from django.utils import timezone

from ..models import (
    CanonicalCodonCompositionLengthSummary,
    CanonicalRepeatCall,
    CanonicalRepeatCallCodonUsage,
    TaxonClosure,
)
from .bins import build_length_bin_definition
from .params import ALLOWED_STATS_RANKS


def rebuild_canonical_codon_composition_length_summaries() -> int:
    with transaction.atomic():
        if connection.vendor == "postgresql":
            return _rebuild_canonical_codon_composition_length_summaries_postgresql()
        return _rebuild_canonical_codon_composition_length_summaries_python()


def _rebuild_canonical_codon_composition_length_summaries_postgresql() -> int:
    table_name = CanonicalCodonCompositionLengthSummary._meta.db_table
    rank_placeholders = ", ".join(["%s"] * len(ALLOWED_STATS_RANKS))
    sql = f"""
        WITH call_scope AS MATERIALIZED (
            SELECT
                repeat_call.id AS repeat_call_id,
                repeat_call.repeat_residue AS repeat_residue,
                repeat_call.length AS repeat_length,
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
        residue_species_bin_calls AS MATERIALIZED (
            SELECT
                scope.repeat_residue,
                scope.display_rank,
                scope.display_taxon_id,
                scope.display_taxon_name,
                (FLOOR(scope.repeat_length / 5.0)::int * 5) AS length_bin_start,
                scope.species_taxon_id,
                COUNT(*)::bigint AS call_count
            FROM call_scope scope
            INNER JOIN browser_canonicalrepeatcallcodonusage codon_usage
                ON codon_usage.repeat_call_id = scope.repeat_call_id
               AND codon_usage.amino_acid = scope.repeat_residue
            GROUP BY
                scope.repeat_residue,
                scope.display_rank,
                scope.display_taxon_id,
                scope.display_taxon_name,
                length_bin_start,
                scope.species_taxon_id
        ),
        display_taxon_bin_counts AS MATERIALIZED (
            SELECT
                species_bin_calls.repeat_residue,
                species_bin_calls.display_rank,
                species_bin_calls.display_taxon_id,
                species_bin_calls.display_taxon_name,
                species_bin_calls.length_bin_start,
                SUM(species_bin_calls.call_count)::bigint AS observation_count,
                COUNT(*)::bigint AS species_count
            FROM residue_species_bin_calls species_bin_calls
            GROUP BY
                species_bin_calls.repeat_residue,
                species_bin_calls.display_rank,
                species_bin_calls.display_taxon_id,
                species_bin_calls.display_taxon_name,
                species_bin_calls.length_bin_start
        ),
        residue_codons AS MATERIALIZED (
            SELECT DISTINCT
                codon_usage.amino_acid AS repeat_residue,
                codon_usage.codon AS codon
            FROM browser_canonicalrepeatcallcodonusage codon_usage
        ),
        species_bin_codon_sums AS MATERIALIZED (
            SELECT
                scope.repeat_residue,
                scope.display_rank,
                scope.display_taxon_id,
                (FLOOR(scope.repeat_length / 5.0)::int * 5) AS length_bin_start,
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
                length_bin_start,
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
            length_bin_start,
            observation_count,
            species_count,
            codon,
            codon_share
        )
        SELECT
            NOW(),
            NOW(),
            display_taxon_bin_counts.repeat_residue,
            display_taxon_bin_counts.display_rank,
            display_taxon_bin_counts.display_taxon_id,
            display_taxon_bin_counts.display_taxon_name,
            display_taxon_bin_counts.length_bin_start,
            display_taxon_bin_counts.observation_count,
            display_taxon_bin_counts.species_count,
            residue_codons.codon,
            COALESCE(
                SUM(
                    COALESCE(species_bin_codon_sums.codon_fraction_sum, 0.0)
                    / residue_species_bin_calls.call_count::double precision
                )
                / display_taxon_bin_counts.species_count::double precision,
                0.0
            ) AS codon_share
        FROM display_taxon_bin_counts
        INNER JOIN residue_codons
            ON residue_codons.repeat_residue = display_taxon_bin_counts.repeat_residue
        INNER JOIN residue_species_bin_calls
            ON residue_species_bin_calls.repeat_residue = display_taxon_bin_counts.repeat_residue
           AND residue_species_bin_calls.display_rank = display_taxon_bin_counts.display_rank
           AND residue_species_bin_calls.display_taxon_id = display_taxon_bin_counts.display_taxon_id
           AND residue_species_bin_calls.length_bin_start = display_taxon_bin_counts.length_bin_start
        LEFT JOIN species_bin_codon_sums
            ON species_bin_codon_sums.repeat_residue = residue_species_bin_calls.repeat_residue
           AND species_bin_codon_sums.display_rank = residue_species_bin_calls.display_rank
           AND species_bin_codon_sums.display_taxon_id = residue_species_bin_calls.display_taxon_id
           AND species_bin_codon_sums.length_bin_start = residue_species_bin_calls.length_bin_start
           AND species_bin_codon_sums.species_taxon_id = residue_species_bin_calls.species_taxon_id
           AND species_bin_codon_sums.codon = residue_codons.codon
        GROUP BY
            display_taxon_bin_counts.repeat_residue,
            display_taxon_bin_counts.display_rank,
            display_taxon_bin_counts.display_taxon_id,
            display_taxon_bin_counts.display_taxon_name,
            display_taxon_bin_counts.length_bin_start,
            display_taxon_bin_counts.observation_count,
            display_taxon_bin_counts.species_count,
            residue_codons.codon
    """
    with connection.cursor() as cursor:
        cursor.execute(f"DELETE FROM {table_name}")
        cursor.execute(sql, list(ALLOWED_STATS_RANKS))
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        return int(cursor.fetchone()[0] or 0)


def _rebuild_canonical_codon_composition_length_summaries_python() -> int:
    CanonicalCodonCompositionLengthSummary.objects.all().delete()

    repeat_calls = list(
        CanonicalRepeatCall.objects.order_by().values_list("id", "repeat_residue", "length", "taxon_id")
    )
    if not repeat_calls:
        return 0

    species_taxon_ids = {taxon_id for _, _, _, taxon_id in repeat_calls}
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

    call_details_by_id: dict[int, tuple[str, int, int, list[tuple[int, str, str]]]] = {}
    for repeat_call_id, repeat_residue, repeat_length, species_taxon_id in repeat_calls:
        ancestor_details = ancestor_details_by_species_taxon_id.get(species_taxon_id, [])
        length_bin_start = build_length_bin_definition(repeat_length).start
        call_details_by_id[repeat_call_id] = (
            repeat_residue,
            length_bin_start,
            species_taxon_id,
            ancestor_details,
        )

    residue_codons: dict[str, set[str]] = defaultdict(set)
    supported_repeat_call_ids: set[int] = set()
    species_bin_codon_fraction_sums: dict[tuple[str, str, int, int, int, str], float] = defaultdict(float)
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

        repeat_residue, length_bin_start, species_taxon_id, ancestor_details = call_details
        if amino_acid != repeat_residue:
            continue

        supported_repeat_call_ids.add(repeat_call_id)
        residue_codons[repeat_residue].add(codon)
        for display_taxon_id, _, display_rank in ancestor_details:
            species_bin_codon_fraction_sums[
                (
                    repeat_residue,
                    display_rank,
                    display_taxon_id,
                    length_bin_start,
                    species_taxon_id,
                    codon,
                )
            ] += float(codon_fraction)

    call_count_by_species_bin: dict[tuple[str, str, int, int, int], int] = defaultdict(int)
    display_taxon_bin_counts: dict[tuple[str, str, int, str, int], dict[str, int]] = {}
    for repeat_call_id in supported_repeat_call_ids:
        repeat_residue, length_bin_start, species_taxon_id, ancestor_details = call_details_by_id[
            repeat_call_id
        ]
        for display_taxon_id, display_taxon_name, display_rank in ancestor_details:
            species_bin_key = (
                repeat_residue,
                display_rank,
                display_taxon_id,
                length_bin_start,
                species_taxon_id,
            )
            call_count_by_species_bin[species_bin_key] += 1
            counts_key = (
                repeat_residue,
                display_rank,
                display_taxon_id,
                display_taxon_name,
                length_bin_start,
            )
            counts = display_taxon_bin_counts.setdefault(
                counts_key,
                {
                    "observation_count": 0,
                    "species_count": 0,
                },
            )
            counts["observation_count"] += 1

    species_keys_by_display_taxon_bin: dict[tuple[str, str, int, str, int], list[int]] = defaultdict(list)
    for repeat_residue, display_rank, display_taxon_id, length_bin_start, species_taxon_id in (
        call_count_by_species_bin
    ):
        display_taxon_name = next(
            key[3]
            for key in display_taxon_bin_counts
            if key[0] == repeat_residue
            and key[1] == display_rank
            and key[2] == display_taxon_id
            and key[4] == length_bin_start
        )
        species_keys_by_display_taxon_bin[
            (
                repeat_residue,
                display_rank,
                display_taxon_id,
                display_taxon_name,
                length_bin_start,
            )
        ].append(species_taxon_id)

    for counts_key, species_taxon_ids_for_group in species_keys_by_display_taxon_bin.items():
        display_taxon_bin_counts[counts_key]["species_count"] = len(species_taxon_ids_for_group)

    now = timezone.now()
    summary_rows: list[CanonicalCodonCompositionLengthSummary] = []
    for (
        repeat_residue,
        display_rank,
        display_taxon_id,
        display_taxon_name,
        length_bin_start,
    ), counts in display_taxon_bin_counts.items():
        visible_codons = sorted(residue_codons.get(repeat_residue, set()))
        if not visible_codons:
            continue

        species_taxon_ids_for_group = species_keys_by_display_taxon_bin[
            (
                repeat_residue,
                display_rank,
                display_taxon_id,
                display_taxon_name,
                length_bin_start,
            )
        ]
        species_count = counts["species_count"]
        for codon in visible_codons:
            codon_share_total = 0.0
            for species_taxon_id in species_taxon_ids_for_group:
                call_count = call_count_by_species_bin[
                    (
                        repeat_residue,
                        display_rank,
                        display_taxon_id,
                        length_bin_start,
                        species_taxon_id,
                    )
                ]
                codon_fraction_sum = species_bin_codon_fraction_sums.get(
                    (
                        repeat_residue,
                        display_rank,
                        display_taxon_id,
                        length_bin_start,
                        species_taxon_id,
                        codon,
                    ),
                    0.0,
                )
                codon_share_total += codon_fraction_sum / call_count

            summary_rows.append(
                CanonicalCodonCompositionLengthSummary(
                    created_at=now,
                    updated_at=now,
                    repeat_residue=repeat_residue,
                    display_rank=display_rank,
                    display_taxon_id=display_taxon_id,
                    display_taxon_name=display_taxon_name,
                    length_bin_start=length_bin_start,
                    observation_count=counts["observation_count"],
                    species_count=species_count,
                    codon=codon,
                    codon_share=codon_share_total / species_count,
                )
            )

    if summary_rows:
        CanonicalCodonCompositionLengthSummary.objects.bulk_create(summary_rows, batch_size=1000)
    return len(summary_rows)
