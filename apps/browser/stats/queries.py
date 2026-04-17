from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import Count, F, Max, Min, Q

from ..models import CanonicalRepeatCall
from .aggregates import PercentileCont
from .filters import StatsFilterState
from .ordering import order_taxon_rows_by_lineage
from .summaries import (
    build_codon_ratio_summary,
    build_numeric_histogram_bins,
    normalize_length_summary_value,
    normalize_numeric_summary_value,
    summarize_codon_heatmap_groups,
    summarize_ranked_codon_ratio_groups,
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

    bundle = {
        "matching_repeat_calls_count": matching_repeat_calls_count,
        "summary_rows": summary_rows,
        "total_taxa_count": total_taxa_count,
        "visible_taxa_count": len(summary_rows),
    }
    cache.set(cache_key, bundle, timeout=getattr(settings, "HOMOREPEAT_BROWSER_STATS_CACHE_TTL", 60))
    return bundle


def build_ranked_codon_summary_bundle(filter_state: StatsFilterState) -> dict[str, object]:
    cache_key = f"browser:stats:codon-summary:{filter_state.cache_key()}"
    cached_bundle = cache.get(cache_key)
    if cached_bundle is not None:
        return cached_bundle

    matching_repeat_calls_count = build_filtered_repeat_call_queryset(
        filter_state,
        require_codon_ratio=True,
    ).count()
    total_taxa_count = build_ranked_taxon_group_count(
        filter_state,
        require_codon_ratio=True,
    )
    if connection.vendor == "postgresql":
        summary_rows = list(build_ranked_codon_summary_queryset(filter_state))
    else:
        group_rows = list(
            build_ranked_taxon_group_queryset(
                filter_state,
                require_codon_ratio=True,
            )
        )
        display_taxon_ids = [row["display_taxon_id"] for row in group_rows]
        grouped_codon_ratio_values = (
            list(
                build_group_codon_ratio_values_queryset(
                    filter_state,
                    display_taxon_ids=display_taxon_ids,
                )
            )
            if display_taxon_ids
            else []
        )
        summary_rows = summarize_ranked_codon_ratio_groups(group_rows, grouped_codon_ratio_values)

    bundle = {
        "matching_repeat_calls_count": matching_repeat_calls_count,
        "summary_rows": summary_rows,
        "total_taxa_count": total_taxa_count,
        "visible_taxa_count": len(summary_rows),
    }
    cache.set(cache_key, bundle, timeout=getattr(settings, "HOMOREPEAT_BROWSER_STATS_CACHE_TTL", 60))
    return bundle


def build_codon_heatmap_summary_bundle(filter_state: StatsFilterState) -> dict[str, object]:
    cache_key = f"browser:stats:codon-heatmap:{filter_state.cache_key()}"
    cached_bundle = cache.get(cache_key)
    if cached_bundle is not None:
        return cached_bundle

    matching_repeat_calls_count = build_filtered_repeat_call_queryset(
        filter_state,
        require_codon_ratio=True,
    ).count()
    total_taxa_count = build_ranked_taxon_group_count(
        filter_state,
        require_codon_ratio=True,
    )
    group_rows = list(
        build_ranked_taxon_group_queryset(
            filter_state,
            require_codon_ratio=True,
        )
    )
    ordered_group_rows = order_taxon_rows_by_lineage(group_rows)
    display_taxon_ids = [row["display_taxon_id"] for row in ordered_group_rows]
    grouped_length_codon_ratio_values = (
        list(
            build_group_codon_heatmap_values_queryset(
                filter_state,
                display_taxon_ids=display_taxon_ids,
            )
        )
        if display_taxon_ids
        else []
    )
    summary_rows = summarize_codon_heatmap_groups(ordered_group_rows, grouped_length_codon_ratio_values)

    bundle = {
        "matching_repeat_calls_count": matching_repeat_calls_count,
        "summary_rows": summary_rows,
        "total_taxa_count": total_taxa_count,
        "visible_taxa_count": len(ordered_group_rows),
    }
    cache.set(cache_key, bundle, timeout=getattr(settings, "HOMOREPEAT_BROWSER_STATS_CACHE_TTL", 60))
    return bundle


def build_codon_inspect_bundle(filter_state: StatsFilterState) -> dict[str, object]:
    cache_key = f"browser:stats:codon-inspect:{filter_state.cache_key()}"
    cached_bundle = cache.get(cache_key)
    if cached_bundle is not None:
        return cached_bundle

    codon_ratio_values = list(
        build_filtered_repeat_call_queryset(
            filter_state,
            require_codon_ratio=True,
        )
        .order_by("codon_ratio_value")
        .values_list("codon_ratio_value", flat=True)
    )

    bundle = {
        "observation_count": len(codon_ratio_values),
        "summary": build_codon_ratio_summary(codon_ratio_values),
        "histogram_bins": build_numeric_histogram_bins(codon_ratio_values),
    }
    cache.set(cache_key, bundle, timeout=getattr(settings, "HOMOREPEAT_BROWSER_STATS_CACHE_TTL", 60))
    return bundle


def build_filtered_repeat_call_queryset(
    filter_state: StatsFilterState,
    *,
    require_codon_ratio: bool = False,
    apply_codon_metric_name: bool = True,
):
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
    if require_codon_ratio:
        queryset = queryset.exclude(codon_ratio_value__isnull=True)
        if apply_codon_metric_name and filter_state.codon_metric_name:
            queryset = queryset.filter(codon_metric_name=filter_state.codon_metric_name)

    return queryset


def build_available_codon_metric_names(filter_state: StatsFilterState) -> list[str]:
    return list(
        build_filtered_repeat_call_queryset(
            filter_state,
            require_codon_ratio=True,
            apply_codon_metric_name=False,
        )
        .exclude(codon_metric_name="")
        .order_by("codon_metric_name")
        .values_list("codon_metric_name", flat=True)
        .distinct()
    )


def build_ranked_taxon_group_queryset(filter_state: StatsFilterState, *, require_codon_ratio: bool = False):
    return build_ranked_taxon_group_base_queryset(
        filter_state,
        require_codon_ratio=require_codon_ratio,
    ).order_by(
        "-observation_count",
        "display_taxon_name",
        "display_taxon_id",
    )[: filter_state.top_n]


def build_ranked_taxon_group_count(filter_state: StatsFilterState, *, require_codon_ratio: bool = False) -> int:
    return build_ranked_taxon_group_base_queryset(
        filter_state,
        require_codon_ratio=require_codon_ratio,
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


def build_group_codon_ratio_values_queryset(filter_state: StatsFilterState, *, display_taxon_ids):
    return (
        _with_display_taxon_annotations(
            build_filtered_repeat_call_queryset(
                filter_state,
                require_codon_ratio=True,
            ),
            rank=filter_state.rank,
        )
        .filter(display_taxon_id__in=display_taxon_ids)
        .values_list("display_taxon_id", "codon_ratio_value")
        .order_by("display_taxon_id", "codon_ratio_value")
    )


def build_group_codon_heatmap_values_queryset(filter_state: StatsFilterState, *, display_taxon_ids):
    return (
        _with_display_taxon_annotations(
            build_filtered_repeat_call_queryset(
                filter_state,
                require_codon_ratio=True,
            ),
            rank=filter_state.rank,
        )
        .filter(display_taxon_id__in=display_taxon_ids)
        .values_list("display_taxon_id", "length", "codon_ratio_value")
        .order_by("display_taxon_id", "length", "codon_ratio_value")
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
            "min_length": row["min_length"],
            "q1": normalize_length_summary_value(row["q1"]),
            "median": normalize_length_summary_value(row["median"]),
            "q3": normalize_length_summary_value(row["q3"]),
            "max_length": row["max_length"],
        }
        for row in summary_rows
    ]


def build_ranked_codon_summary_queryset(filter_state: StatsFilterState):
    queryset = _with_display_taxon_annotations(
        build_filtered_repeat_call_queryset(
            filter_state,
            require_codon_ratio=True,
        ),
        rank=filter_state.rank,
    ).exclude(display_taxon_id__isnull=True)

    summary_rows = (
        queryset.values("display_taxon_id", "display_taxon_name", "display_taxon_rank")
        .annotate(
            observation_count=Count("pk"),
            min_codon_ratio=Min("codon_ratio_value"),
            q1=PercentileCont(0.25, "codon_ratio_value"),
            median=PercentileCont(0.5, "codon_ratio_value"),
            q3=PercentileCont(0.75, "codon_ratio_value"),
            max_codon_ratio=Max("codon_ratio_value"),
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
            "min_codon_ratio": normalize_numeric_summary_value(row["min_codon_ratio"]),
            "q1": normalize_numeric_summary_value(row["q1"]),
            "median": normalize_numeric_summary_value(row["median"]),
            "q3": normalize_numeric_summary_value(row["q3"]),
            "max_codon_ratio": normalize_numeric_summary_value(row["max_codon_ratio"]),
        }
        for row in summary_rows
    ]


def build_ranked_taxon_group_base_queryset(filter_state: StatsFilterState, *, require_codon_ratio: bool = False):
    queryset = _with_display_taxon_annotations(
        build_filtered_repeat_call_queryset(
            filter_state,
            require_codon_ratio=require_codon_ratio,
        ),
        rank=filter_state.rank,
    ).exclude(display_taxon_id__isnull=True)

    return (
        queryset.values("display_taxon_id", "display_taxon_name", "display_taxon_rank")
        .annotate(observation_count=Count("pk"))
        .filter(observation_count__gte=filter_state.min_count)
    )


def _with_display_taxon_annotations(queryset, *, rank: str):
    return queryset.filter(
        taxon__closure_ancestors__ancestor__rank=rank,
    ).annotate(
        display_taxon_id=F("taxon__closure_ancestors__ancestor_id"),
        display_taxon_name=F("taxon__closure_ancestors__ancestor__taxon_name"),
        display_taxon_rank=F("taxon__closure_ancestors__ancestor__rank"),
    )
