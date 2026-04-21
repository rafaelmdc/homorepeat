from __future__ import annotations

from dataclasses import asdict

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import Count, Exists, F, Max, Min, OuterRef, Q, Sum

from ..models import (
    CanonicalCodonCompositionSummary,
    CanonicalCodonCompositionLengthSummary,
    CanonicalRepeatCall,
    CanonicalRepeatCallCodonUsage,
)
from .aggregates import PercentileCont
from .bins import build_visible_length_bins
from .filters import StatsFilterState
from .ordering import order_taxon_rows_by_lineage
from .summaries import (
    _build_dominance_summary,
    build_length_inspect_summary,
    normalize_length_summary_value,
    normalize_numeric_summary_value,
    summarize_codon_length_composition_rows,
    summarize_length_profile_vectors,
    summarize_ranked_codon_composition_groups,
    summarize_ranked_length_groups,
)


def build_ranked_length_summary_bundle(filter_state: StatsFilterState) -> dict[str, object]:
    cache_key = f"browser:stats:length-summary:{filter_state.cache_key()}"
    cached_bundle = cache.get(cache_key)
    if cached_bundle is not None:
        return cached_bundle

    matching_repeat_calls_count = build_filtered_repeat_call_queryset(filter_state).count()
    total_taxa_count = build_ranked_taxon_group_count(filter_state)
    if connection.vendor == "postgresql":
        summary_rows = list(build_ranked_length_summary_queryset(filter_state))
    else:
        group_rows = list(build_ranked_taxon_group_queryset(filter_state))
        display_taxon_ids = [row["display_taxon_id"] for row in group_rows]
        grouped_lengths = (
            list(
                build_group_length_values_queryset(
                    filter_state,
                    display_taxon_ids=display_taxon_ids,
                )
            )
            if display_taxon_ids
            else []
        )
        summary_rows = summarize_ranked_length_groups(group_rows, grouped_lengths)

    if summary_rows:
        summary_rows = order_taxon_rows_by_lineage(summary_rows)

    bundle = {
        "matching_repeat_calls_count": matching_repeat_calls_count,
        "summary_rows": summary_rows,
        "total_taxa_count": total_taxa_count,
        "visible_taxa_count": len(summary_rows),
    }
    cache.set(cache_key, bundle, timeout=getattr(settings, "HOMOREPEAT_BROWSER_STATS_CACHE_TTL", 60))
    return bundle


def build_length_profile_vector_bundle(filter_state: StatsFilterState) -> dict[str, object]:
    cache_key = f"browser:stats:length-profile-vectors:{filter_state.cache_key()}"
    cached_bundle = cache.get(cache_key)
    if cached_bundle is not None:
        return cached_bundle

    summary_bundle = build_ranked_length_summary_bundle(filter_state)
    summary_rows = summary_bundle["summary_rows"]
    if not summary_rows:
        bundle = {
            "matching_repeat_calls_count": summary_bundle["matching_repeat_calls_count"],
            "visible_taxa_count": 0,
            "visible_bins": [],
            "profile_rows": [],
        }
        cache.set(cache_key, bundle, timeout=getattr(settings, "HOMOREPEAT_BROWSER_STATS_CACHE_TTL", 60))
        return bundle

    visible_taxon_ids = [row["taxon_id"] for row in summary_rows]
    grouped_length_counts = list(
        build_group_length_counts_queryset(
            filter_state,
            display_taxon_ids=visible_taxon_ids,
        )
    )
    vector_summary = summarize_length_profile_vectors(
        summary_rows,
        grouped_length_counts,
        species_count_by_taxon_id={
            row["taxon_id"]: int(row["species_count"])
            for row in summary_rows
            if row.get("species_count") is not None
        },
    )
    bundle = {
        "matching_repeat_calls_count": summary_bundle["matching_repeat_calls_count"],
        "visible_taxa_count": len(vector_summary["profile_rows"]),
        "visible_bins": vector_summary["visible_bins"],
        "profile_rows": vector_summary["profile_rows"],
    }
    cache.set(cache_key, bundle, timeout=getattr(settings, "HOMOREPEAT_BROWSER_STATS_CACHE_TTL", 60))
    return bundle


def build_length_inspect_bundle(filter_state: StatsFilterState) -> dict[str, object]:
    cache_key = f"browser:stats:length-inspect:{filter_state.cache_key()}"
    cached_bundle = cache.get(cache_key)
    if cached_bundle is not None:
        return cached_bundle

    lengths = sorted(
        int(v)
        for v in build_filtered_repeat_call_queryset(filter_state)
        .values_list("length", flat=True)
        if v is not None
    )
    summary = build_length_inspect_summary(lengths)
    bundle = summary if summary is not None else {
        "observation_count": 0,
        "ccdf_points": [],
        "median": None,
        "q90": None,
        "q95": None,
        "max": None,
    }
    cache.set(cache_key, bundle, timeout=getattr(settings, "HOMOREPEAT_BROWSER_STATS_CACHE_TTL", 60))
    return bundle


def build_ranked_codon_composition_summary_bundle(filter_state: StatsFilterState) -> dict[str, object]:
    if not filter_state.residue:
        return {
            "matching_repeat_calls_count": 0,
            "summary_rows": [],
            "total_taxa_count": 0,
            "visible_taxa_count": 0,
            "visible_codons": [],
        }

    cache_key = f"browser:stats:codon-composition:{filter_state.cache_key()}"
    cached_bundle = cache.get(cache_key)
    if cached_bundle is not None:
        return cached_bundle

    filtered_repeat_call_queryset = build_filtered_repeat_call_queryset(filter_state)
    matching_repeat_calls_count = filtered_repeat_call_queryset.count()
    if _can_use_codon_composition_summary_rollup(filter_state):
        rollup_bundle = _build_ranked_codon_composition_summary_bundle_from_rollup(
            filter_state,
            matching_repeat_calls_count=matching_repeat_calls_count,
        )
        if rollup_bundle is None:
            total_taxa_count, summary_rows, visible_codons = (
                _build_ranked_codon_composition_summary_bundle_live(
                    filter_state,
                    filtered_repeat_call_queryset=filtered_repeat_call_queryset,
                )
            )
        else:
            total_taxa_count, summary_rows, visible_codons = rollup_bundle
    else:
        total_taxa_count, summary_rows, visible_codons = (
            _build_ranked_codon_composition_summary_bundle_live(
                filter_state,
                filtered_repeat_call_queryset=filtered_repeat_call_queryset,
            )
        )
    if summary_rows:
        summary_rows = order_taxon_rows_by_lineage(summary_rows)

    bundle = {
        "matching_repeat_calls_count": matching_repeat_calls_count,
        "summary_rows": summary_rows,
        "total_taxa_count": total_taxa_count,
        "visible_taxa_count": len(summary_rows),
        "visible_codons": visible_codons,
    }
    cache.set(cache_key, bundle, timeout=getattr(settings, "HOMOREPEAT_BROWSER_STATS_CACHE_TTL", 60))
    return bundle


def build_codon_length_composition_bundle(filter_state: StatsFilterState) -> dict[str, object]:
    if not filter_state.residue:
        return {
            "matching_repeat_calls_count": 0,
            "total_taxa_count": 0,
            "visible_taxa_count": 0,
            "visible_codons": [],
            "visible_bins": [],
            "matrix_rows": [],
        }

    cache_key = f"browser:stats:codon-composition-length:{filter_state.cache_key()}"
    cached_bundle = cache.get(cache_key)
    if cached_bundle is not None:
        return cached_bundle

    filtered_repeat_call_queryset = build_filtered_repeat_call_queryset(filter_state)
    matching_repeat_calls_count = filtered_repeat_call_queryset.count()
    if _can_use_codon_composition_length_summary_rollup(filter_state):
        rollup_bundle = _build_codon_length_composition_bundle_from_rollup(
            filter_state,
            matching_repeat_calls_count=matching_repeat_calls_count,
        )
        if rollup_bundle is None:
            total_taxa_count, visible_codons, visible_bins, matrix_rows = (
                _build_codon_length_composition_bundle_live(filter_state)
            )
        else:
            total_taxa_count, visible_codons, visible_bins, matrix_rows = rollup_bundle
    else:
        total_taxa_count, visible_codons, visible_bins, matrix_rows = (
            _build_codon_length_composition_bundle_live(filter_state)
        )

    if matrix_rows:
        matrix_rows = order_taxon_rows_by_lineage(matrix_rows)
        visible_bins, matrix_rows = _filter_codon_length_matrix_rows_by_min_count(
            visible_bins,
            matrix_rows,
            min_count=filter_state.min_count,
        )

    if not matrix_rows or not visible_codons:
        bundle = {
            "matching_repeat_calls_count": matching_repeat_calls_count,
            "total_taxa_count": total_taxa_count,
            "visible_taxa_count": 0,
            "visible_codons": list(visible_codons),
            "visible_bins": list(visible_bins),
            "matrix_rows": [],
        }
        cache.set(cache_key, bundle, timeout=getattr(settings, "HOMOREPEAT_BROWSER_STATS_CACHE_TTL", 60))
        return bundle

    bundle = {
        "matching_repeat_calls_count": matching_repeat_calls_count,
        "total_taxa_count": total_taxa_count,
        "visible_taxa_count": len(matrix_rows),
        "visible_codons": list(visible_codons),
        "visible_bins": list(visible_bins),
        "matrix_rows": matrix_rows,
    }
    cache.set(cache_key, bundle, timeout=getattr(settings, "HOMOREPEAT_BROWSER_STATS_CACHE_TTL", 60))
    return bundle


def _filter_codon_length_matrix_rows_by_min_count(visible_bins, matrix_rows, *, min_count: int):
    if min_count <= 1:
        return visible_bins, matrix_rows

    visible_bins_by_start = {
        visible_bin["start"]: visible_bin
        for visible_bin in visible_bins
    }
    retained_bin_starts = set()
    filtered_matrix_rows = []
    for matrix_row in matrix_rows:
        retained_bin_rows = [
            bin_row
            for bin_row in matrix_row["bin_rows"]
            if int(bin_row["observation_count"]) >= min_count
        ]
        if not retained_bin_rows:
            continue
        for bin_row in retained_bin_rows:
            retained_bin_starts.add(bin_row["bin"]["start"])
        filtered_matrix_rows.append(
            {
                **matrix_row,
                "bin_rows": retained_bin_rows,
            }
        )

    filtered_visible_bins = [
        visible_bin
        for visible_bin in visible_bins
        if visible_bin["start"] in retained_bin_starts
    ]
    missing_visible_bins = [
        bin_row["bin"]
        for matrix_row in filtered_matrix_rows
        for bin_row in matrix_row["bin_rows"]
        if bin_row["bin"]["start"] not in visible_bins_by_start
    ]
    if missing_visible_bins:
        filtered_visible_bins.extend(
            sorted(
                missing_visible_bins,
                key=lambda visible_bin: visible_bin["start"],
            )
        )
    return filtered_visible_bins, filtered_matrix_rows


def build_matching_repeat_calls_with_codon_usage_count(filter_state: StatsFilterState) -> int:
    if not filter_state.residue:
        return 0

    cache_key = f"browser:stats:codon-usage-count:{filter_state.cache_key()}"
    cached_count = cache.get(cache_key)
    if cached_count is not None:
        return cached_count

    codon_usage_exists = CanonicalRepeatCallCodonUsage.objects.filter(
        repeat_call_id=OuterRef("pk"),
        amino_acid=filter_state.residue,
    )
    matching_count = (
        build_filtered_repeat_call_queryset(filter_state)
        .annotate(has_codon_usage=Exists(codon_usage_exists))
        .filter(has_codon_usage=True)
        .count()
    )
    cache.set(
        cache_key,
        matching_count,
        timeout=getattr(settings, "HOMOREPEAT_BROWSER_STATS_CACHE_TTL", 60),
    )
    return matching_count


def build_codon_composition_inspect_bundle(filter_state: StatsFilterState) -> dict[str, object]:
    if not filter_state.residue:
        return {
            "observation_count": 0,
            "visible_codons": [],
            "codon_shares": [],
        }

    cache_key = f"browser:stats:codon-composition-inspect:{filter_state.cache_key()}"
    cached_bundle = cache.get(cache_key)
    if cached_bundle is not None:
        return cached_bundle

    observation_count = build_filtered_repeat_call_queryset(filter_state).count()
    codon_fraction_sums = list(
        build_filtered_codon_usage_queryset(filter_state)
        .values("codon")
        .annotate(total_fraction=Sum("codon_fraction"))
        .order_by("codon")
        .values_list("codon", "total_fraction")
    )
    visible_codons = [codon for codon, _ in codon_fraction_sums]
    codon_shares = (
        [
            {
                "codon": codon,
                "share": normalize_numeric_summary_value(float(total_fraction) / observation_count),
            }
            for codon, total_fraction in codon_fraction_sums
        ]
        if observation_count > 0
        else []
    )
    bundle = {
        "observation_count": observation_count,
        "visible_codons": visible_codons,
        "codon_shares": codon_shares,
    }
    cache.set(cache_key, bundle, timeout=getattr(settings, "HOMOREPEAT_BROWSER_STATS_CACHE_TTL", 60))
    return bundle


def build_filtered_repeat_call_queryset(filter_state: StatsFilterState):
    queryset = CanonicalRepeatCall.objects.order_by()

    if filter_state.current_run is not None:
        queryset = queryset.filter(latest_pipeline_run=filter_state.current_run)
    if filter_state.branch_taxa_ids is not None:
        queryset = queryset.filter(taxon_id__in=filter_state.branch_taxa_ids)
    if filter_state.q:
        queryset = queryset.filter(
            Q(gene_symbol__istartswith=filter_state.q)
            | Q(protein__protein_id__istartswith=filter_state.q)
            | Q(protein_name__istartswith=filter_state.q)
            | Q(accession__istartswith=filter_state.q)
        )
    if filter_state.method:
        queryset = queryset.filter(method=filter_state.method)
    if filter_state.residue:
        queryset = queryset.filter(repeat_residue=filter_state.residue)
    if filter_state.length_min is not None:
        queryset = queryset.filter(length__gte=filter_state.length_min)
    if filter_state.length_max is not None:
        queryset = queryset.filter(length__lte=filter_state.length_max)
    if filter_state.purity_min is not None:
        queryset = queryset.filter(purity__gte=filter_state.purity_min)
    if filter_state.purity_max is not None:
        queryset = queryset.filter(purity__lte=filter_state.purity_max)

    return queryset


def build_filtered_codon_usage_queryset(filter_state: StatsFilterState):
    if not filter_state.residue:
        return CanonicalRepeatCallCodonUsage.objects.none()

    return CanonicalRepeatCallCodonUsage.objects.order_by().filter(
        repeat_call__in=build_filtered_repeat_call_queryset(filter_state),
        amino_acid=filter_state.residue,
    )


def _can_use_codon_composition_summary_rollup(filter_state: StatsFilterState) -> bool:
    return (
        bool(filter_state.residue)
        and filter_state.current_run is None
        and not filter_state.branch_scope_active
        and not filter_state.q
        and not filter_state.method
        and filter_state.length_min is None
        and filter_state.length_max is None
        and filter_state.purity_min is None
        and filter_state.purity_max is None
    )


def _can_use_codon_composition_length_summary_rollup(filter_state: StatsFilterState) -> bool:
    return (
        bool(filter_state.residue)
        and filter_state.current_run is None
        and not filter_state.branch_scope_active
        and not filter_state.q
        and not filter_state.method
        and filter_state.length_min is None
        and filter_state.length_max is None
        and filter_state.purity_min is None
        and filter_state.purity_max is None
    )


def _build_ranked_codon_composition_summary_bundle_from_rollup(
    filter_state: StatsFilterState,
    *,
    matching_repeat_calls_count: int,
) -> tuple[int, list[dict[str, object]], list[str]] | None:
    if matching_repeat_calls_count <= 0:
        return 0, [], []

    base_queryset = CanonicalCodonCompositionSummary.objects.order_by().filter(
        repeat_residue=filter_state.residue,
        display_rank=filter_state.rank,
    )
    if not base_queryset.exists():
        return None

    candidate_taxa_queryset = (
        base_queryset.filter(observation_count__gte=filter_state.min_count)
        .values(
            "display_taxon_id",
            "display_taxon_name",
            "observation_count",
            "species_count",
        )
        .distinct()
    )
    total_taxa_count = candidate_taxa_queryset.count()
    visible_taxa = list(
        candidate_taxa_queryset.order_by(
            "-observation_count",
            "display_taxon_name",
            "display_taxon_id",
        )[: filter_state.top_n]
    )
    if not visible_taxa:
        return total_taxa_count, [], []

    visible_taxon_ids = [row["display_taxon_id"] for row in visible_taxa]
    visible_codons = list(
        base_queryset.filter(
            display_taxon_id__in=visible_taxon_ids,
            codon_share__gt=0,
        )
        .order_by("codon")
        .values_list("codon", flat=True)
        .distinct()
    )
    if not visible_codons:
        return total_taxa_count, [], []

    summary_rows_by_taxon_id = {
        row["display_taxon_id"]: {
            "taxon_id": row["display_taxon_id"],
            "taxon_name": row["display_taxon_name"],
            "rank": filter_state.rank,
            "observation_count": int(row["observation_count"]),
            "species_count": int(row["species_count"]),
            "codon_shares_by_codon": {},
        }
        for row in visible_taxa
    }
    summary_rows = list(summary_rows_by_taxon_id.values())
    codon_rows = base_queryset.filter(
        display_taxon_id__in=visible_taxon_ids,
        codon__in=visible_codons,
    ).values_list(
        "display_taxon_id",
        "codon",
        "codon_share",
    )
    for display_taxon_id, codon, codon_share in codon_rows:
        summary_rows_by_taxon_id[display_taxon_id]["codon_shares_by_codon"][codon] = (
            normalize_numeric_summary_value(float(codon_share))
        )

    return (
        total_taxa_count,
        [
            {
                "taxon_id": row["taxon_id"],
                "taxon_name": row["taxon_name"],
                "rank": row["rank"],
                "observation_count": row["observation_count"],
                "species_count": row["species_count"],
                "codon_shares": [
                    {
                        "codon": codon,
                        "share": row["codon_shares_by_codon"].get(codon, 0),
                    }
                    for codon in visible_codons
                ],
            }
            for row in summary_rows
        ],
        visible_codons,
    )


def _build_codon_length_composition_bundle_from_rollup(
    filter_state: StatsFilterState,
    *,
    matching_repeat_calls_count: int,
) -> tuple[int, list[str], list[dict[str, object]], list[dict[str, object]]] | None:
    if matching_repeat_calls_count <= 0:
        return 0, [], [], []

    base_queryset = CanonicalCodonCompositionLengthSummary.objects.order_by().filter(
        repeat_residue=filter_state.residue,
        display_rank=filter_state.rank,
    )
    if not base_queryset.exists():
        return None

    codon_summary_rollup_bundle = _build_ranked_codon_composition_summary_bundle_from_rollup(
        filter_state,
        matching_repeat_calls_count=matching_repeat_calls_count,
    )
    if codon_summary_rollup_bundle is None:
        return None

    total_taxa_count, visible_taxa, visible_codons = codon_summary_rollup_bundle
    if not visible_taxa or not visible_codons:
        return total_taxa_count, [], [], []

    visible_taxon_ids = [row["taxon_id"] for row in visible_taxa]

    visible_bin_starts = list(
        base_queryset.filter(
            display_taxon_id__in=visible_taxon_ids,
        )
        .order_by("length_bin_start")
        .values_list("length_bin_start", flat=True)
        .distinct()
    )
    visible_bins = [asdict(length_bin) for length_bin in build_visible_length_bins(visible_bin_starts)]

    matrix_rows_by_taxon_id = {
        row["taxon_id"]: {
            "taxon_id": row["taxon_id"],
            "taxon_name": row["taxon_name"],
            "rank": filter_state.rank,
            "observation_count": int(row["observation_count"]),
            "species_count": int(row["species_count"]),
            "bin_rows_by_start": {},
        }
        for row in visible_taxa
    }
    rollup_rows = base_queryset.filter(
        display_taxon_id__in=visible_taxon_ids,
        codon__in=visible_codons,
    ).values_list(
        "display_taxon_id",
        "length_bin_start",
        "observation_count",
        "species_count",
        "codon",
        "codon_share",
    )
    for (
        display_taxon_id,
        length_bin_start,
        observation_count,
        species_count,
        codon,
        codon_share,
    ) in rollup_rows:
        taxon_row = matrix_rows_by_taxon_id[display_taxon_id]
        bin_row = taxon_row["bin_rows_by_start"].setdefault(
            int(length_bin_start),
            {
                "bin": next(bin_row for bin_row in visible_bins if bin_row["start"] == int(length_bin_start)),
                "observation_count": int(observation_count),
                "species_count": int(species_count),
                "codon_shares_by_codon": {},
            },
        )
        bin_row["codon_shares_by_codon"][codon] = normalize_numeric_summary_value(float(codon_share))

    matrix_rows = []
    for visible_taxon in visible_taxa:
        taxon_row = matrix_rows_by_taxon_id[visible_taxon["taxon_id"]]
        bin_rows = []
        for visible_bin in visible_bins:
            bin_row = taxon_row["bin_rows_by_start"].get(visible_bin["start"])
            if bin_row is None:
                continue
            codon_shares = [
                {
                    "codon": codon,
                    "share": bin_row["codon_shares_by_codon"].get(codon, 0),
                }
                for codon in visible_codons
            ]
            dominant_codon, dominance_margin = _build_dominance_summary(codon_shares)
            bin_rows.append(
                {
                    "bin": bin_row["bin"],
                    "observation_count": bin_row["observation_count"],
                    "species_count": bin_row["species_count"],
                    "codon_shares": codon_shares,
                    "dominant_codon": dominant_codon,
                    "dominance_margin": dominance_margin,
                }
            )
        if not bin_rows:
            continue
        matrix_rows.append(
            {
                "taxon_id": taxon_row["taxon_id"],
                "taxon_name": taxon_row["taxon_name"],
                "rank": taxon_row["rank"],
                "observation_count": taxon_row["observation_count"],
                "species_count": taxon_row["species_count"],
                "bin_rows": bin_rows,
            }
        )

    return total_taxa_count, visible_codons, visible_bins, matrix_rows


def _build_codon_length_composition_bundle_live(
    filter_state: StatsFilterState,
) -> tuple[int, list[str], list[dict[str, object]], list[dict[str, object]]]:
    summary_bundle = build_ranked_codon_composition_summary_bundle(filter_state)
    summary_rows = summary_bundle["summary_rows"]
    visible_codons = summary_bundle["visible_codons"]
    if not summary_rows or not visible_codons:
        return summary_bundle["total_taxa_count"], list(visible_codons), [], []

    visible_taxon_ids = [row["taxon_id"] for row in summary_rows]
    grouped_species_length_call_counts = list(
        build_group_codon_length_species_call_count_queryset(
            filter_state,
            display_taxon_ids=visible_taxon_ids,
        )
    )
    grouped_species_length_codon_fraction_sums = list(
        build_group_codon_length_species_codon_fraction_sum_queryset(
            filter_state,
            display_taxon_ids=visible_taxon_ids,
        )
    )
    grouped_summary = summarize_codon_length_composition_rows(
        summary_rows,
        grouped_species_length_call_counts,
        grouped_species_length_codon_fraction_sums,
        visible_codons=visible_codons,
    )
    return (
        summary_bundle["total_taxa_count"],
        list(visible_codons),
        grouped_summary["visible_bins"],
        grouped_summary["matrix_rows"],
    )


def _build_ranked_codon_composition_summary_bundle_live(
    filter_state: StatsFilterState,
    *,
    filtered_repeat_call_queryset,
) -> tuple[int, list[dict[str, object]], list[str]]:
    if connection.vendor == "postgresql":
        return _build_ranked_codon_composition_summary_bundle_postgresql(
            filter_state,
            filtered_repeat_call_queryset=filtered_repeat_call_queryset,
        )

    total_taxa_count = build_ranked_taxon_group_count(filter_state)
    group_rows = list(build_ranked_taxon_group_queryset(filter_state))
    display_taxon_ids = [row["display_taxon_id"] for row in group_rows]
    grouped_species_call_codon_fractions = (
        list(
            build_group_codon_species_call_fraction_queryset(
                filter_state,
                display_taxon_ids=display_taxon_ids,
            )
        )
        if display_taxon_ids
        else []
    )
    visible_codons = sorted({codon for _, _, _, codon, _ in grouped_species_call_codon_fractions})
    summary_rows = (
        summarize_ranked_codon_composition_groups(
            group_rows,
            grouped_species_call_codon_fractions,
            visible_codons=visible_codons,
        )
        if visible_codons
        else []
    )
    return total_taxa_count, summary_rows, visible_codons


def _build_ranked_codon_composition_summary_bundle_postgresql(
    filter_state: StatsFilterState,
    *,
    filtered_repeat_call_queryset,
) -> tuple[int, list[dict[str, object]], list[str]]:
    filtered_calls_sql, filtered_calls_params = (
        filtered_repeat_call_queryset.values("id", "taxon_id").query.sql_with_params()
    )
    sql = f"""
        WITH filtered_calls AS MATERIALIZED (
            {filtered_calls_sql}
        ),
        scoped_calls AS MATERIALIZED (
            SELECT
                fc.id AS repeat_call_id,
                fc.taxon_id AS species_taxon_id,
                tc.ancestor_id AS display_taxon_id,
                display_taxon.taxon_name AS display_taxon_name,
                display_taxon.rank AS display_taxon_rank
            FROM filtered_calls fc
            INNER JOIN browser_taxonclosure tc
                ON tc.descendant_id = fc.taxon_id
            INNER JOIN browser_taxon display_taxon
                ON display_taxon.id = tc.ancestor_id
            WHERE display_taxon.rank = %s
        ),
        grouped_taxa AS MATERIALIZED (
            SELECT
                sc.display_taxon_id,
                sc.display_taxon_name,
                sc.display_taxon_rank,
                COUNT(*)::bigint AS observation_count,
                COUNT(DISTINCT sc.species_taxon_id)::bigint AS species_count
            FROM scoped_calls sc
            GROUP BY
                sc.display_taxon_id,
                sc.display_taxon_name,
                sc.display_taxon_rank
            HAVING COUNT(*) >= %s
        ),
        ranked_taxa AS MATERIALIZED (
            SELECT
                gt.display_taxon_id,
                gt.display_taxon_name,
                gt.display_taxon_rank,
                gt.observation_count,
                gt.species_count,
                COUNT(*) OVER ()::bigint AS total_taxa_count
            FROM grouped_taxa gt
            ORDER BY
                gt.observation_count DESC,
                gt.display_taxon_name ASC,
                gt.display_taxon_id ASC
            LIMIT %s
        ),
        species_call_counts AS MATERIALIZED (
            SELECT
                sc.display_taxon_id,
                sc.species_taxon_id,
                COUNT(*)::bigint AS call_count
            FROM scoped_calls sc
            INNER JOIN ranked_taxa rt
                ON rt.display_taxon_id = sc.display_taxon_id
            GROUP BY sc.display_taxon_id, sc.species_taxon_id
        ),
        species_codon_sums AS MATERIALIZED (
            SELECT
                sc.display_taxon_id,
                sc.species_taxon_id,
                cu.codon,
                SUM(cu.codon_fraction)::double precision AS codon_fraction_sum
            FROM scoped_calls sc
            INNER JOIN ranked_taxa rt
                ON rt.display_taxon_id = sc.display_taxon_id
            INNER JOIN browser_canonicalrepeatcallcodonusage cu
                ON cu.repeat_call_id = sc.repeat_call_id
               AND cu.amino_acid = %s
            GROUP BY sc.display_taxon_id, sc.species_taxon_id, cu.codon
        ),
        display_taxon_codon_shares AS MATERIALIZED (
            SELECT
                scs.display_taxon_id,
                scs.codon,
                (
                    SUM(scs.codon_fraction_sum / scc.call_count::double precision)
                    / MAX(rt.species_count)::double precision
                )::double precision AS codon_share
            FROM species_codon_sums scs
            INNER JOIN species_call_counts scc
                ON scc.display_taxon_id = scs.display_taxon_id
               AND scc.species_taxon_id = scs.species_taxon_id
            INNER JOIN ranked_taxa rt
                ON rt.display_taxon_id = scs.display_taxon_id
            GROUP BY scs.display_taxon_id, scs.codon
        )
        SELECT
            rt.display_taxon_id,
            rt.display_taxon_name,
            rt.display_taxon_rank,
            rt.observation_count,
            rt.species_count,
            rt.total_taxa_count,
            dtcs.codon,
            dtcs.codon_share
        FROM ranked_taxa rt
        LEFT JOIN display_taxon_codon_shares dtcs
            ON dtcs.display_taxon_id = rt.display_taxon_id
        ORDER BY
            rt.observation_count DESC,
            rt.display_taxon_name ASC,
            rt.display_taxon_id ASC,
            dtcs.codon ASC
    """
    params = [
        *filtered_calls_params,
        filter_state.rank,
        filter_state.min_count,
        filter_state.top_n,
        filter_state.residue,
    ]

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        result_rows = cursor.fetchall()

    total_taxa_count = 0
    visible_codons = set()
    summary_rows_by_taxon_id: dict[int, dict[str, object]] = {}
    ranked_taxon_ids: list[int] = []

    for (
        display_taxon_id,
        display_taxon_name,
        display_taxon_rank,
        observation_count,
        species_count,
        row_total_taxa_count,
        codon,
        codon_share,
    ) in result_rows:
        total_taxa_count = max(total_taxa_count, int(row_total_taxa_count or 0))
        if display_taxon_id not in summary_rows_by_taxon_id:
            summary_rows_by_taxon_id[display_taxon_id] = {
                "taxon_id": display_taxon_id,
                "taxon_name": display_taxon_name,
                "rank": display_taxon_rank,
                "observation_count": int(observation_count),
                "species_count": int(species_count),
                "codon_shares_by_codon": {},
            }
            ranked_taxon_ids.append(display_taxon_id)

        if codon is None:
            continue

        visible_codons.add(codon)
        summary_rows_by_taxon_id[display_taxon_id]["codon_shares_by_codon"][codon] = (
            normalize_numeric_summary_value(float(codon_share))
        )

    ordered_visible_codons = sorted(visible_codons)
    if not ordered_visible_codons:
        return total_taxa_count, [], []

    summary_rows = []
    for display_taxon_id in ranked_taxon_ids:
        summary_row = summary_rows_by_taxon_id[display_taxon_id]
        codon_shares_by_codon = summary_row.pop("codon_shares_by_codon")
        summary_rows.append(
            {
                **summary_row,
                "codon_shares": [
                    {
                        "codon": codon,
                        "share": codon_shares_by_codon.get(codon, 0),
                    }
                    for codon in ordered_visible_codons
                ],
            }
        )

    return total_taxa_count, summary_rows, ordered_visible_codons


def build_ranked_taxon_group_queryset(filter_state: StatsFilterState):
    return build_ranked_taxon_group_base_queryset(
        filter_state,
    ).order_by(
        "-observation_count",
        "display_taxon_name",
        "display_taxon_id",
    )[: filter_state.top_n]


def build_ranked_taxon_group_count(filter_state: StatsFilterState) -> int:
    return build_ranked_taxon_group_base_queryset(
        filter_state,
    ).count()


def build_group_length_values_queryset(filter_state: StatsFilterState, *, display_taxon_ids):
    return (
        _with_display_taxon_annotations(
            build_filtered_repeat_call_queryset(filter_state),
            rank=filter_state.rank,
        )
        .filter(display_taxon_id__in=display_taxon_ids)
        .values_list("display_taxon_id", "length")
        .order_by("display_taxon_id", "length")
    )


def build_group_length_counts_queryset(filter_state: StatsFilterState, *, display_taxon_ids):
    return (
        _with_display_taxon_annotations(
            build_filtered_repeat_call_queryset(filter_state),
            rank=filter_state.rank,
        )
        .filter(display_taxon_id__in=display_taxon_ids)
        .values("display_taxon_id", "length")
        .annotate(length_count=Count("pk"))
        .values_list("display_taxon_id", "length", "length_count")
        .order_by("display_taxon_id", "length")
    )


def build_group_codon_species_call_fraction_queryset(filter_state: StatsFilterState, *, display_taxon_ids):
    return (
        _with_display_taxon_annotations(
            build_filtered_codon_usage_queryset(filter_state),
            rank=filter_state.rank,
            taxon_field_name="repeat_call__taxon",
        )
        .filter(display_taxon_id__in=display_taxon_ids)
        .values_list(
            "display_taxon_id",
            "repeat_call__taxon_id",
            "repeat_call_id",
            "codon",
            "codon_fraction",
        )
        .order_by("display_taxon_id", "repeat_call__taxon_id", "repeat_call_id", "codon")
    )


def build_group_codon_length_species_call_count_queryset(filter_state: StatsFilterState, *, display_taxon_ids):
    return (
        _with_display_taxon_annotations(
            build_filtered_codon_usage_queryset(filter_state),
            rank=filter_state.rank,
            taxon_field_name="repeat_call__taxon",
        )
        .filter(display_taxon_id__in=display_taxon_ids)
        .values(
            "display_taxon_id",
            "repeat_call__taxon_id",
            "repeat_call__length",
        )
        .annotate(call_count=Count("repeat_call_id", distinct=True))
        .values_list("display_taxon_id", "repeat_call__taxon_id", "repeat_call__length", "call_count")
        .order_by("display_taxon_id", "repeat_call__taxon_id", "repeat_call__length")
    )


def build_group_codon_length_species_codon_fraction_sum_queryset(
    filter_state: StatsFilterState,
    *,
    display_taxon_ids,
):
    return (
        _with_display_taxon_annotations(
            build_filtered_codon_usage_queryset(filter_state),
            rank=filter_state.rank,
            taxon_field_name="repeat_call__taxon",
        )
        .filter(display_taxon_id__in=display_taxon_ids)
        .values(
            "display_taxon_id",
            "repeat_call__taxon_id",
            "repeat_call__length",
            "codon",
        )
        .annotate(codon_fraction_sum=Sum("codon_fraction"))
        .values_list(
            "display_taxon_id",
            "repeat_call__taxon_id",
            "repeat_call__length",
            "codon",
            "codon_fraction_sum",
        )
        .order_by("display_taxon_id", "repeat_call__taxon_id", "repeat_call__length", "codon")
    )


def build_ranked_length_summary_queryset(filter_state: StatsFilterState):
    queryset = _with_display_taxon_annotations(
        build_filtered_repeat_call_queryset(filter_state),
        rank=filter_state.rank,
    ).exclude(display_taxon_id__isnull=True)

    summary_rows = (
        queryset.values("display_taxon_id", "display_taxon_name", "display_taxon_rank")
        .annotate(
            observation_count=Count("pk"),
            species_count=Count("taxon_id", distinct=True),
            min_length=Min("length"),
            q1=PercentileCont(0.25, "length"),
            median=PercentileCont(0.5, "length"),
            q3=PercentileCont(0.75, "length"),
            max_length=Max("length"),
        )
        .filter(observation_count__gte=filter_state.min_count)
        .order_by("-observation_count", "display_taxon_name", "display_taxon_id")[: filter_state.top_n]
    )

    return [
        {
            "taxon_id": row["display_taxon_id"],
            "taxon_name": row["display_taxon_name"],
            "rank": row["display_taxon_rank"],
            "observation_count": row["observation_count"],
            "species_count": row["species_count"],
            "min_length": row["min_length"],
            "q1": normalize_length_summary_value(row["q1"]),
            "median": normalize_length_summary_value(row["median"]),
            "q3": normalize_length_summary_value(row["q3"]),
            "max_length": row["max_length"],
        }
        for row in summary_rows
    ]
def build_ranked_taxon_group_base_queryset(filter_state: StatsFilterState):
    queryset = _with_display_taxon_annotations(
        build_filtered_repeat_call_queryset(filter_state),
        rank=filter_state.rank,
    ).exclude(display_taxon_id__isnull=True)

    return (
        queryset.values("display_taxon_id", "display_taxon_name", "display_taxon_rank")
        .annotate(
            observation_count=Count("pk"),
            species_count=Count("taxon_id", distinct=True),
        )
        .filter(observation_count__gte=filter_state.min_count)
    )


def _with_display_taxon_annotations(queryset, *, rank: str, taxon_field_name: str = "taxon"):
    return queryset.filter(
        **{f"{taxon_field_name}__closure_ancestors__ancestor__rank": rank},
    ).annotate(
        display_taxon_id=F(f"{taxon_field_name}__closure_ancestors__ancestor_id"),
        display_taxon_name=F(f"{taxon_field_name}__closure_ancestors__ancestor__taxon_name"),
        display_taxon_rank=F(f"{taxon_field_name}__closure_ancestors__ancestor__rank"),
    )
