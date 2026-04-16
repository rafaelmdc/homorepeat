from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import CharField, Count, IntegerField, Max, Min, OuterRef, Q, Subquery

from ..models import CanonicalRepeatCall, TaxonClosure
from .aggregates import PercentileCont
from .filters import StatsFilterState
from .summaries import normalize_length_summary_value, summarize_ranked_length_groups


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


def build_filtered_repeat_call_queryset(filter_state: StatsFilterState):
    queryset = CanonicalRepeatCall.objects.all()

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


def build_ranked_taxon_group_queryset(filter_state: StatsFilterState):
    return build_ranked_taxon_group_base_queryset(filter_state).order_by(
        "-observation_count",
        "display_taxon_name",
        "display_taxon_id",
    )[: filter_state.top_n]


def build_ranked_taxon_group_count(filter_state: StatsFilterState) -> int:
    return build_ranked_taxon_group_base_queryset(filter_state).count()


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


def build_ranked_taxon_group_base_queryset(filter_state: StatsFilterState):
    queryset = _with_display_taxon_annotations(
        build_filtered_repeat_call_queryset(filter_state),
        rank=filter_state.rank,
    ).exclude(display_taxon_id__isnull=True)

    return (
        queryset.values("display_taxon_id", "display_taxon_name", "display_taxon_rank")
        .annotate(observation_count=Count("pk"))
        .filter(observation_count__gte=filter_state.min_count)
    )


def _with_display_taxon_annotations(queryset, *, rank: str):
    ancestor_links = TaxonClosure.objects.filter(
        descendant_id=OuterRef("taxon_id"),
        ancestor__rank=rank,
    ).order_by("depth", "ancestor_id")

    return queryset.annotate(
        display_taxon_id=Subquery(
            ancestor_links.values("ancestor_id")[:1],
            output_field=IntegerField(),
        ),
        display_taxon_name=Subquery(
            ancestor_links.values("ancestor__taxon_name")[:1],
            output_field=CharField(),
        ),
        display_taxon_rank=Subquery(
            ancestor_links.values("ancestor__rank")[:1],
            output_field=CharField(),
        ),
    )
