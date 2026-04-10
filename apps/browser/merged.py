from collections import Counter, OrderedDict
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Count, Max, Min, Q

from .models import Genome, RepeatCall, Taxon, TaxonClosure


PURITY_QUANTUM = Decimal("0.0001")


def accession_group_queryset(
    *,
    current_run=None,
    search_query: str = "",
    accession_query: str = "",
    genome_name: str = "",
    branch_taxon: Taxon | None = None,
):
    return source_genome_queryset(
        current_run=current_run,
        search_query=search_query,
        accession_query=accession_query,
        genome_name=genome_name,
        branch_taxon=branch_taxon,
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
        RepeatCall.objects.filter(genome__accession=accession)
        .select_related("pipeline_run", "genome", "sequence", "protein", "taxon")
        .order_by("method", "protein__protein_name", "start", "call_id")
    )
    collapsed_call_groups = _collapsed_repeat_call_groups(source_repeat_calls)
    analyzed_protein_counts = sorted({genome.analyzed_protein_count for genome in source_genomes})
    merged_analyzed_protein_count = analyzed_protein_counts[0] if len(analyzed_protein_counts) == 1 else None
    merged_repeat_bearing_proteins_count = len(
        {(group["protein_name"], group["protein_length"]) for group in collapsed_call_groups}
    )
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
        "duplicate_source_repeat_calls_count": len(source_repeat_calls) - len(collapsed_call_groups),
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

    if branch_taxon is not None:
        queryset = queryset.filter(taxon_id__in=_branch_taxon_ids(branch_taxon))

    return queryset


def source_repeat_call_queryset(
    *,
    current_run=None,
    branch_taxon: Taxon | None = None,
    search_query: str = "",
    gene_symbol: str = "",
    accession_query: str = "",
    genome_id: str = "",
    protein_id: str = "",
    method: str = "",
    residue: str = "",
    length_min: str = "",
    length_max: str = "",
    purity_min: str = "",
    purity_max: str = "",
):
    queryset = RepeatCall.objects.select_related("pipeline_run", "genome", "sequence", "protein", "taxon").exclude(
        genome__accession=""
    )

    if current_run is not None:
        queryset = queryset.filter(pipeline_run=current_run)

    if branch_taxon is not None:
        queryset = queryset.filter(taxon_id__in=_branch_taxon_ids(branch_taxon))

    if search_query:
        queryset = queryset.filter(
            Q(call_id__icontains=search_query)
            | Q(protein__protein_name__icontains=search_query)
            | Q(protein__protein_id__icontains=search_query)
            | Q(protein__gene_symbol__icontains=search_query)
            | Q(genome__accession__icontains=search_query)
        )

    if gene_symbol:
        queryset = queryset.filter(
            Q(protein__gene_symbol__icontains=gene_symbol)
            | Q(sequence__gene_symbol__icontains=gene_symbol)
        )

    if accession_query:
        queryset = queryset.filter(genome__accession__icontains=accession_query)

    if genome_id:
        queryset = queryset.filter(genome__genome_id=genome_id)

    if protein_id:
        queryset = queryset.filter(protein__protein_id=protein_id)

    if method:
        queryset = queryset.filter(method=method)

    if residue:
        queryset = queryset.filter(repeat_residue=residue)

    parsed_length_min = _parse_positive_int(length_min)
    if parsed_length_min is not None:
        queryset = queryset.filter(length__gte=parsed_length_min)

    parsed_length_max = _parse_positive_int(length_max)
    if parsed_length_max is not None:
        queryset = queryset.filter(length__lte=parsed_length_max)

    parsed_purity_min = _parse_float(purity_min)
    if parsed_purity_min is not None:
        queryset = queryset.filter(purity__gte=parsed_purity_min)

    parsed_purity_max = _parse_float(purity_max)
    if parsed_purity_max is not None:
        queryset = queryset.filter(purity__lte=parsed_purity_max)

    return queryset.order_by("genome__accession", "protein__protein_name", "method", "start", "call_id")


def merged_protein_groups(
    *,
    current_run=None,
    branch_taxon: Taxon | None = None,
    search_query: str = "",
    gene_symbol: str = "",
    accession_query: str = "",
    genome_id: str = "",
    protein_id: str = "",
    method: str = "",
    residue: str = "",
    length_min: str = "",
    length_max: str = "",
    purity_min: str = "",
    purity_max: str = "",
):
    return _merged_protein_groups_from_repeat_calls(
        source_repeat_call_queryset(
            current_run=current_run,
            branch_taxon=branch_taxon,
            search_query=search_query,
            gene_symbol=gene_symbol,
            accession_query=accession_query,
            genome_id=genome_id,
            protein_id=protein_id,
            method=method,
            residue=residue,
            length_min=length_min,
            length_max=length_max,
            purity_min=purity_min,
            purity_max=purity_max,
        )
    )


def build_accession_analytics(
    *,
    current_run=None,
    search_query: str = "",
    accession_query: str = "",
    genome_name: str = "",
    branch_taxon: Taxon | None = None,
):
    accession_groups = list(
        accession_group_queryset(
            current_run=current_run,
            search_query=search_query,
            accession_query=accession_query,
            genome_name=genome_name,
            branch_taxon=branch_taxon,
        )
    )
    source_genomes = source_genome_queryset(
        current_run=current_run,
        search_query=search_query,
        accession_query=accession_query,
        genome_name=genome_name,
        branch_taxon=branch_taxon,
    )
    source_repeat_calls = list(
        RepeatCall.objects.select_related("pipeline_run", "genome", "sequence", "protein", "taxon")
        .filter(genome_id__in=source_genomes.values("pk"))
        .order_by("genome__accession", "protein__protein_name", "method", "start", "call_id")
    )
    collapsed_call_groups = _collapsed_repeat_call_groups(source_repeat_calls)
    protein_groups = _merged_protein_groups_from_repeat_calls(source_repeat_calls)

    collapsed_calls_by_accession = Counter(group["accession"] for group in collapsed_call_groups)
    proteins_by_accession = Counter(group["accession"] for group in protein_groups)
    method_summary = Counter(group["method"] for group in collapsed_call_groups)
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
                group["raw_repeat_calls_count"] - collapsed_calls_by_accession.get(accession, 0)
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
        "duplicate_source_repeat_calls_count": len(source_repeat_calls) - len(collapsed_call_groups),
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


def merged_repeat_call_groups(
    *,
    current_run=None,
    branch_taxon: Taxon | None = None,
    search_query: str = "",
    gene_symbol: str = "",
    accession_query: str = "",
    genome_id: str = "",
    protein_id: str = "",
    method: str = "",
    residue: str = "",
    length_min: str = "",
    length_max: str = "",
    purity_min: str = "",
    purity_max: str = "",
):
    return _collapsed_repeat_call_groups(
        list(
            source_repeat_call_queryset(
                current_run=current_run,
                branch_taxon=branch_taxon,
                search_query=search_query,
                gene_symbol=gene_symbol,
                accession_query=accession_query,
                genome_id=genome_id,
                protein_id=protein_id,
                method=method,
                residue=residue,
                length_min=length_min,
                length_max=length_max,
                purity_min=purity_min,
                purity_max=purity_max,
            )
        )
    )


def normalize_purity(value) -> str:
    return format(Decimal(str(value)).quantize(PURITY_QUANTUM, rounding=ROUND_HALF_UP), "f")


def _merged_protein_groups_from_repeat_calls(source_repeat_calls):
    grouped_proteins = OrderedDict()

    for repeat_call in source_repeat_calls:
        key = (
            repeat_call.genome.accession,
            repeat_call.protein.protein_name,
            repeat_call.protein.protein_length,
        )
        if key not in grouped_proteins:
            grouped_proteins[key] = {
                "accession": repeat_call.genome.accession,
                "protein_name": repeat_call.protein.protein_name,
                "protein_length": repeat_call.protein.protein_length,
                "gene_symbols": set(),
                "source_runs": set(),
                "source_proteins": set(),
                "collapsed_call_keys": set(),
                "source_repeat_calls_count": 0,
            }

        grouped_proteins[key]["source_repeat_calls_count"] += 1
        if repeat_call.protein.gene_symbol:
            grouped_proteins[key]["gene_symbols"].add(repeat_call.protein.gene_symbol)
        grouped_proteins[key]["source_runs"].add(repeat_call.pipeline_run.run_id)
        grouped_proteins[key]["source_proteins"].add((repeat_call.pipeline_run.run_id, repeat_call.protein.protein_id))
        grouped_proteins[key]["collapsed_call_keys"].add(_collapsed_repeat_call_key(repeat_call))

    protein_groups = list(grouped_proteins.values())
    for protein_group in protein_groups:
        protein_group["gene_symbols"] = sorted(protein_group["gene_symbols"])
        protein_group["gene_symbol_label"] = ", ".join(protein_group["gene_symbols"]) if protein_group["gene_symbols"] else "-"
        protein_group["source_runs"] = sorted(protein_group["source_runs"])
        protein_group["source_runs_count"] = len(protein_group["source_runs"])
        protein_group["source_proteins_count"] = len(protein_group["source_proteins"])
        protein_group["collapsed_repeat_calls_count"] = len(protein_group["collapsed_call_keys"])
        protein_group.pop("source_proteins")
        protein_group.pop("collapsed_call_keys")

    return protein_groups


def _collapsed_repeat_call_groups(source_repeat_calls):
    grouped_calls = OrderedDict()

    for repeat_call in source_repeat_calls:
        key = _collapsed_repeat_call_key(repeat_call)
        if key not in grouped_calls:
            grouped_calls[key] = {
                "accession": repeat_call.genome.accession,
                "protein_name": repeat_call.protein.protein_name,
                "protein_length": repeat_call.protein.protein_length,
                "method": repeat_call.method,
                "start": repeat_call.start,
                "end": repeat_call.end,
                "repeat_residue": repeat_call.repeat_residue,
                "length": repeat_call.length,
                "normalized_purity": normalize_purity(repeat_call.purity),
                "source_repeat_calls": [],
                "source_runs": set(),
                "source_taxa": set(),
                "gene_symbols": set(),
            }

        grouped_calls[key]["source_repeat_calls"].append(repeat_call)
        grouped_calls[key]["source_runs"].add(repeat_call.pipeline_run.run_id)
        grouped_calls[key]["source_taxa"].add(repeat_call.taxon.taxon_name)
        if repeat_call.protein.gene_symbol:
            grouped_calls[key]["gene_symbols"].add(repeat_call.protein.gene_symbol)

    collapsed_groups = list(grouped_calls.values())
    for group in collapsed_groups:
        group["source_repeat_calls"] = sorted(
            group["source_repeat_calls"],
            key=lambda repeat_call: (
                repeat_call.pipeline_run.run_id,
                repeat_call.call_id,
            ),
        )
        group["source_runs"] = sorted(group["source_runs"])
        group["source_runs_count"] = len(group["source_runs"])
        group["source_taxa"] = sorted(group["source_taxa"])
        group["source_taxa_label"] = ", ".join(group["source_taxa"]) if group["source_taxa"] else "-"
        group["gene_symbols"] = sorted(group["gene_symbols"])
        group["gene_symbol_label"] = ", ".join(group["gene_symbols"]) if group["gene_symbols"] else "-"
        group["source_count"] = len(group["source_repeat_calls"])

    collapsed_groups.sort(
        key=lambda group: (
            group["method"],
            group["protein_name"],
            group["start"],
            group["end"],
            group["repeat_residue"],
            group["normalized_purity"],
        )
    )
    return collapsed_groups


def _collapsed_repeat_call_key(repeat_call):
    return (
        repeat_call.genome.accession,
        repeat_call.protein.protein_name,
        repeat_call.protein.protein_length,
        repeat_call.method,
        repeat_call.start,
        repeat_call.end,
        repeat_call.repeat_residue,
        repeat_call.length,
        normalize_purity(repeat_call.purity),
    )


def _branch_taxon_ids(taxon: Taxon):
    return TaxonClosure.objects.filter(ancestor=taxon).order_by().values_list("descendant_id", flat=True)


def _parse_positive_int(value: str):
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    if parsed < 0:
        return None
    return parsed


def _parse_float(value: str):
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _counter_summary(counter):
    return [
        {"label": label, "count": count}
        for label, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]
