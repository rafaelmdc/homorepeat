from django.db.models import Q

from apps.imports.models import ImportBatch

from ..models import AcquisitionBatch, Genome, PipelineRun, Protein, RepeatCall, Sequence, Taxon, TaxonClosure
from .formatting import _parse_float, _parse_positive_int


def _resolve_current_run(request):
    run_id = request.GET.get("run", "").strip()
    if not run_id:
        return None
    return PipelineRun.objects.active().filter(run_id=run_id).first()


def _match_branch_taxa(branch_q: str):
    if branch_q.isdigit():
        return Taxon.objects.filter(taxon_id=int(branch_q)).order_by("taxon_name", "taxon_id")
    return Taxon.objects.filter(taxon_name__istartswith=branch_q).order_by("taxon_name", "taxon_id")


def _resolve_branch_scope_from_params(branch: str, branch_q: str) -> dict:
    """Resolve branch scope from plain string params.

    Called from both the request path (_resolve_branch_scope) and the
    Celery task path (build_stats_filter_state_from_params) so that filter
    state reconstruction is consistent in both contexts.
    """
    if branch_q:
        matched_taxa = _match_branch_taxa(branch_q)
        return {
            "current_branch": branch,
            "current_branch_q": branch_q,
            "current_branch_input": branch_q,
            "selected_branch_taxon": None,
            "branch_taxa_ids": TaxonClosure.objects.filter(ancestor_id__in=matched_taxa.values("pk"))
            .order_by()
            .values_list("descendant_id", flat=True)
            .distinct(),
            "branch_scope_active": True,
            "branch_scope_label": branch_q,
            "branch_scope_noun": "branch search",
        }

    selected_branch_taxon = Taxon.objects.filter(pk=branch).first() if branch else None
    return {
        "current_branch": branch,
        "current_branch_q": "",
        "current_branch_input": str(selected_branch_taxon.taxon_id) if selected_branch_taxon else "",
        "selected_branch_taxon": selected_branch_taxon,
        "branch_taxa_ids": _branch_taxon_ids(selected_branch_taxon) if selected_branch_taxon else None,
        "branch_scope_active": bool(selected_branch_taxon),
        "branch_scope_label": selected_branch_taxon.taxon_name if selected_branch_taxon else "",
        "branch_scope_noun": "branch",
    }


def _resolve_branch_scope(request) -> dict:
    return _resolve_branch_scope_from_params(
        branch=request.GET.get("branch", "").strip(),
        branch_q=request.GET.get("branch_q", "").strip(),
    )


def _apply_branch_scope_filter(queryset, *, branch_scope, field_name: str):
    branch_taxa_ids = branch_scope["branch_taxa_ids"]
    if branch_taxa_ids is None:
        return queryset
    return queryset.filter(**{f"{field_name}__in": branch_taxa_ids})


def _update_branch_scope_context(context, branch_scope):
    context["current_branch"] = branch_scope["current_branch"]
    context["current_branch_q"] = branch_scope["current_branch_q"]
    context["current_branch_input"] = branch_scope["current_branch_input"]
    context["selected_branch_taxon"] = branch_scope["selected_branch_taxon"]
    context["branch_scope_active"] = branch_scope["branch_scope_active"]
    context["branch_scope_label"] = branch_scope["branch_scope_label"]
    context["branch_scope_noun"] = branch_scope["branch_scope_noun"]
    return context


def _resolve_batch_filter(current_run, batch_pk):
    if not batch_pk:
        return None
    queryset = AcquisitionBatch.objects.select_related("pipeline_run").filter(pk=batch_pk)
    if current_run:
        queryset = queryset.filter(pipeline_run=current_run)
    return queryset.first()


def _resolve_genome_filter(current_run, genome_id):
    if not genome_id:
        return None
    queryset = Genome.objects.select_related("pipeline_run").filter(genome_id=genome_id)
    if current_run:
        queryset = queryset.filter(pipeline_run=current_run)
    return queryset.first()


def _resolve_protein_filter(current_run, protein_id):
    if not protein_id:
        return None
    queryset = Protein.objects.select_related("pipeline_run", "genome").filter(protein_id=protein_id)
    if current_run:
        queryset = queryset.filter(pipeline_run=current_run)
    return queryset.first()


def _resolve_sequence_filter(current_run, sequence_id):
    if not sequence_id:
        return None
    queryset = Sequence.objects.select_related("pipeline_run", "genome").filter(sequence_id=sequence_id)
    if current_run:
        queryset = queryset.filter(pipeline_run=current_run)
    return queryset.first()


def _branch_taxon_ids(taxon: Taxon):
    return TaxonClosure.objects.filter(ancestor=taxon).order_by().values_list("descendant_id", flat=True)


def _repeat_call_filter_q(
    *,
    method: str,
    residue: str,
    length_min: str,
    length_max: str,
    purity_min: str,
    purity_max: str,
):
    filters = Q()
    has_filters = False

    if method:
        filters &= Q(method=method)
        has_filters = True

    if residue:
        filters &= Q(repeat_residue=residue)
        has_filters = True

    parsed_length_min = _parse_positive_int(length_min)
    if parsed_length_min is not None:
        filters &= Q(length__gte=parsed_length_min)
        has_filters = True

    parsed_length_max = _parse_positive_int(length_max)
    if parsed_length_max is not None:
        filters &= Q(length__lte=parsed_length_max)
        has_filters = True

    parsed_purity_min = _parse_float(purity_min)
    if parsed_purity_min is not None:
        filters &= Q(purity__gte=parsed_purity_min)
        has_filters = True

    parsed_purity_max = _parse_float(purity_max)
    if parsed_purity_max is not None:
        filters &= Q(purity__lte=parsed_purity_max)
        has_filters = True

    if not has_filters:
        return None
    return filters


def _scoped_repeat_calls(
    *,
    current_run=None,
    selected_branch_taxon=None,
    branch_taxa_ids=None,
    genome_id="",
    sequence_id="",
    protein_id="",
):
    queryset = RepeatCall.objects.all()
    if current_run:
        queryset = queryset.filter(pipeline_run=current_run)
    if branch_taxa_ids is not None:
        queryset = queryset.filter(taxon_id__in=branch_taxa_ids)
    elif selected_branch_taxon:
        queryset = queryset.filter(taxon_id__in=_branch_taxon_ids(selected_branch_taxon))
    if genome_id:
        queryset = queryset.filter(genome__genome_id=genome_id)
    if sequence_id:
        queryset = queryset.filter(sequence__sequence_id=sequence_id)
    if protein_id:
        queryset = queryset.filter(protein__protein_id=protein_id)
    return queryset


def _run_distinct_taxa_count(pipeline_run: PipelineRun) -> int:
    referenced_taxon_ids = _referenced_taxon_ids(pipeline_run)
    return Taxon.objects.filter(pk__in=referenced_taxon_ids).count()


def _run_taxon_ids(pipeline_run: PipelineRun):
    referenced_taxon_ids = _referenced_taxon_ids(pipeline_run)
    return (
        TaxonClosure.objects.filter(descendant_id__in=referenced_taxon_ids)
        .order_by()
        .values_list("ancestor_id", flat=True)
        .distinct()
    )


def _referenced_taxon_ids(pipeline_run: PipelineRun):
    return Genome.objects.filter(pipeline_run=pipeline_run).order_by().values_list("taxon_id", flat=True).union(
        Sequence.objects.filter(pipeline_run=pipeline_run).order_by().values_list("taxon_id", flat=True),
        Protein.objects.filter(pipeline_run=pipeline_run).order_by().values_list("taxon_id", flat=True),
        RepeatCall.objects.filter(pipeline_run=pipeline_run).order_by().values_list("taxon_id", flat=True),
    )


def _run_import_batches(pipeline_run: PipelineRun):
    filters = Q(pipeline_run=pipeline_run)
    if pipeline_run.publish_root:
        filters |= Q(source_path=pipeline_run.publish_root)
    return ImportBatch.objects.filter(filters)
