from collections import Counter

from django.db.models import Count, Max, Min, Q

from ..models import Genome, Taxon
from .identity import (
    _identity_audit,
    _identity_merged_residue_groups_from_repeat_calls,
    _merged_protein_groups_from_repeat_calls,
    _protein_identity_key,
    _protein_residue_identity_key,
)
from .metrics import _counter_summary
from .repeat_calls import _merged_repeat_call_queryset, _resolved_branch_taxa_ids


def accession_group_queryset(
    *,
    current_run=None,
    search_query: str = "",
    accession_query: str = "",
    genome_name: str = "",
    branch_taxon: Taxon | None = None,
    branch_taxa_ids=None,
):
    return source_genome_queryset(
        current_run=current_run,
        search_query=search_query,
        accession_query=accession_query,
        genome_name=genome_name,
        branch_taxon=branch_taxon,
        branch_taxa_ids=branch_taxa_ids,
    ).values("accession").annotate(
        source_genomes_count=Count("pk", distinct=True),
        source_runs_count=Count("pipeline_run", distinct=True),
        raw_repeat_calls_count=Count("repeat_calls", distinct=True),
        analyzed_protein_min=Min("analyzed_protein_count"),
        analyzed_protein_max=Max("analyzed_protein_count"),
    )


def build_accession_summary(accession: str) -> dict:
    source_genomes = list(
        Genome.objects.filter(accession=accession)
        .select_related("pipeline_run", "taxon")
        .annotate(
            proteins_count=Count("proteins", distinct=True),
            repeat_calls_count=Count("repeat_calls", distinct=True),
        )
        .order_by("pipeline_run__run_id", "genome_id")
    )
    if not source_genomes:
        raise Genome.DoesNotExist(f"No imported genomes found for accession {accession}.")

    source_repeat_calls = list(
        _merged_repeat_call_queryset()
        .filter(accession=accession)
        .order_by("method", "protein_name", "start", "call_id")
    )
    protein_identity_audit = _identity_audit(source_repeat_calls, _protein_identity_key)
    residue_identity_audit = _identity_audit(source_repeat_calls, _protein_residue_identity_key)
    collapsed_call_groups = _identity_merged_residue_groups_from_repeat_calls(source_repeat_calls)
    protein_groups = _merged_protein_groups_from_repeat_calls(source_repeat_calls)
    analyzed_protein_counts = sorted({genome.analyzed_protein_count for genome in source_genomes})
    merged_analyzed_protein_count = analyzed_protein_counts[0] if len(analyzed_protein_counts) == 1 else None
    merged_repeat_bearing_proteins_count = len(protein_groups)
    repeat_bearing_protein_percentage = None
    if merged_analyzed_protein_count:
        repeat_bearing_protein_percentage = (merged_repeat_bearing_proteins_count / merged_analyzed_protein_count) * 100

    source_runs = {}
    source_taxa = {}
    for genome in source_genomes:
        source_runs[genome.pipeline_run.pk] = genome.pipeline_run
        source_taxa[genome.taxon.pk] = genome.taxon

    return {
        "accession": accession,
        "source_genomes": source_genomes,
        "source_runs": sorted(source_runs.values(), key=lambda run: run.run_id),
        "source_taxa": sorted(source_taxa.values(), key=lambda taxon: (taxon.taxon_name, taxon.taxon_id)),
        "source_genomes_count": len(source_genomes),
        "source_runs_count": len({genome.pipeline_run_id for genome in source_genomes}),
        "source_repeat_calls_count": len(source_repeat_calls),
        "collapsed_repeat_calls_count": len(collapsed_call_groups),
        "duplicate_source_repeat_calls_count": residue_identity_audit["included_count"] - len(collapsed_call_groups),
        "excluded_protein_identity_repeat_calls_count": protein_identity_audit["excluded_count"],
        "excluded_residue_identity_repeat_calls_count": residue_identity_audit["excluded_count"],
        "collapsed_call_groups": collapsed_call_groups,
        "merged_repeat_bearing_proteins_count": merged_repeat_bearing_proteins_count,
        "analyzed_protein_counts": analyzed_protein_counts,
        "merged_analyzed_protein_count": merged_analyzed_protein_count,
        "has_analyzed_protein_conflict": len(analyzed_protein_counts) > 1,
        "repeat_bearing_protein_percentage": repeat_bearing_protein_percentage,
    }


def source_genome_queryset(
    *,
    current_run=None,
    search_query: str = "",
    accession_query: str = "",
    genome_name: str = "",
    branch_taxon: Taxon | None = None,
    branch_taxa_ids=None,
):
    queryset = Genome.objects.exclude(accession="")

    if current_run is not None:
        queryset = queryset.filter(pipeline_run=current_run)

    if search_query:
        queryset = queryset.filter(
            Q(accession__icontains=search_query) | Q(genome_name__icontains=search_query)
        )

    if accession_query:
        queryset = queryset.filter(accession__icontains=accession_query)

    if genome_name:
        queryset = queryset.filter(genome_name__icontains=genome_name)

    resolved_branch_taxa_ids = _resolved_branch_taxa_ids(
        branch_taxon=branch_taxon,
        branch_taxa_ids=branch_taxa_ids,
    )
    if resolved_branch_taxa_ids is not None:
        queryset = queryset.filter(taxon_id__in=resolved_branch_taxa_ids)

    return queryset


def build_accession_analytics(
    *,
    current_run=None,
    search_query: str = "",
    accession_query: str = "",
    genome_name: str = "",
    branch_taxon: Taxon | None = None,
    branch_taxa_ids=None,
):
    accession_groups = list(
        accession_group_queryset(
            current_run=current_run,
            search_query=search_query,
            accession_query=accession_query,
            genome_name=genome_name,
            branch_taxon=branch_taxon,
            branch_taxa_ids=branch_taxa_ids,
        )
    )
    source_genomes = source_genome_queryset(
        current_run=current_run,
        search_query=search_query,
        accession_query=accession_query,
        genome_name=genome_name,
        branch_taxon=branch_taxon,
        branch_taxa_ids=branch_taxa_ids,
    )
    source_repeat_calls = list(
        _merged_repeat_call_queryset()
        .filter(genome_id__in=source_genomes.values("pk"))
        .order_by("accession", "protein_name", "method", "start", "call_id")
    )
    protein_identity_audit = _identity_audit(source_repeat_calls, _protein_identity_key)
    residue_identity_audit = _identity_audit(source_repeat_calls, _protein_residue_identity_key)
    collapsed_call_groups = _identity_merged_residue_groups_from_repeat_calls(source_repeat_calls)
    protein_groups = _merged_protein_groups_from_repeat_calls(source_repeat_calls)

    collapsed_calls_by_accession = Counter(group["accession"] for group in collapsed_call_groups)
    proteins_by_accession = Counter(group["accession"] for group in protein_groups)
    method_summary = Counter()
    for group in collapsed_call_groups:
        for method_name in group["methods"]:
            method_summary[method_name] += 1
    residue_summary = Counter(group["repeat_residue"] for group in collapsed_call_groups)
    safe_accessions = {
        group["accession"]
        for group in accession_groups
        if group["analyzed_protein_min"] == group["analyzed_protein_max"]
    }
    analyzed_proteins_total = sum(
        group["analyzed_protein_min"]
        for group in accession_groups
        if group["accession"] in safe_accessions
    )
    safe_repeat_bearing_proteins_count = sum(
        proteins_by_accession.get(accession, 0) for accession in safe_accessions
    )
    repeat_bearing_protein_percentage = None
    if analyzed_proteins_total:
        repeat_bearing_protein_percentage = (
            safe_repeat_bearing_proteins_count / analyzed_proteins_total
        ) * 100

    accession_metrics = {}
    for group in accession_groups:
        accession = group["accession"]
        has_analyzed_protein_conflict = group["analyzed_protein_min"] != group["analyzed_protein_max"]
        merged_analyzed_protein_count = None if has_analyzed_protein_conflict else group["analyzed_protein_min"]
        merged_repeat_bearing_proteins_count = proteins_by_accession.get(accession, 0)
        accession_percentage = None
        if merged_analyzed_protein_count:
            accession_percentage = (
                merged_repeat_bearing_proteins_count / merged_analyzed_protein_count
            ) * 100

        accession_metrics[accession] = {
            "has_analyzed_protein_conflict": has_analyzed_protein_conflict,
            "collapsed_repeat_calls_count": collapsed_calls_by_accession.get(accession, 0),
            "duplicate_source_repeat_calls_count": (
                residue_identity_audit["included_by_accession"].get(accession, 0)
                - collapsed_calls_by_accession.get(accession, 0)
            ),
            "excluded_protein_identity_repeat_calls_count": protein_identity_audit["excluded_by_accession"].get(
                accession, 0
            ),
            "excluded_residue_identity_repeat_calls_count": residue_identity_audit["excluded_by_accession"].get(
                accession, 0
            ),
            "merged_repeat_bearing_proteins_count": merged_repeat_bearing_proteins_count,
            "merged_analyzed_protein_count": merged_analyzed_protein_count,
            "repeat_bearing_protein_percentage": accession_percentage,
        }

    for group in accession_groups:
        group.update(accession_metrics[group["accession"]])

    return {
        "accession_groups": accession_groups,
        "accession_groups_count": len(accession_groups),
        "source_genomes_count": source_genomes.count(),
        "source_runs_count": source_genomes.order_by().values("pipeline_run_id").distinct().count(),
        "source_repeat_calls_count": len(source_repeat_calls),
        "collapsed_repeat_calls_count": len(collapsed_call_groups),
        "duplicate_source_repeat_calls_count": residue_identity_audit["included_count"] - len(collapsed_call_groups),
        "excluded_protein_identity_repeat_calls_count": protein_identity_audit["excluded_count"],
        "excluded_residue_identity_repeat_calls_count": residue_identity_audit["excluded_count"],
        "merged_repeat_bearing_proteins_count": len(protein_groups),
        "conflict_accessions_count": len(accession_groups) - len(safe_accessions),
        "safe_accessions_count": len(safe_accessions),
        "analyzed_proteins_total": analyzed_proteins_total,
        "safe_repeat_bearing_proteins_count": safe_repeat_bearing_proteins_count,
        "repeat_bearing_protein_percentage": repeat_bearing_protein_percentage,
        "method_summary": _counter_summary(method_summary),
        "residue_summary": _counter_summary(residue_summary),
        "accession_metrics": accession_metrics,
    }
