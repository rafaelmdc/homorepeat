from __future__ import annotations

from django.db.models import CharField, Count, IntegerField, OuterRef, Q, Subquery

from ..models import CanonicalRepeatCall, TaxonClosure
from .filters import StatsFilterState


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
    queryset = _with_display_taxon_annotations(
        build_filtered_repeat_call_queryset(filter_state),
        rank=filter_state.rank,
    ).exclude(display_taxon_id__isnull=True)

    return (
        queryset.values("display_taxon_id", "display_taxon_name", "display_taxon_rank")
        .annotate(observation_count=Count("pk"))
        .filter(observation_count__gte=filter_state.min_count)
        .order_by("-observation_count", "display_taxon_name", "display_taxon_id")[: filter_state.top_n]
    )


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
