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
    queryset = _merged_repeat_call_queryset().exclude(accession="")

    if current_run is not None:
        queryset = queryset.filter(pipeline_run=current_run)

    if branch_taxon is not None:
        queryset = queryset.filter(taxon_id__in=_branch_taxon_ids(branch_taxon))

    if search_query:
        queryset = queryset.filter(
            Q(call_id__icontains=search_query)
            | Q(protein_name__icontains=search_query)
            | Q(protein__protein_id__icontains=search_query)
            | Q(gene_symbol__icontains=search_query)
            | Q(accession__icontains=search_query)
        )

    if gene_symbol:
        queryset = queryset.filter(
            Q(gene_symbol__icontains=gene_symbol) | Q(sequence__gene_symbol__icontains=gene_symbol)
        )

    if accession_query:
        queryset = queryset.filter(accession__icontains=accession_query)

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

    return queryset.order_by("accession", "protein_name", "method", "start", "call_id")


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
    return _identity_merged_residue_groups_from_repeat_calls(
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


def _merged_repeat_call_queryset():
    return (
        RepeatCall.objects.select_related("pipeline_run", "genome", "protein", "taxon")
        .defer(
            "codon_sequence",
            "codon_metric_name",
            "codon_metric_value",
            "window_definition",
            "template_name",
            "merge_rule",
            "score",
            "protein__amino_acid_sequence",
        )
        .only(
            "id",
            "pipeline_run_id",
            "pipeline_run__id",
            "pipeline_run__run_id",
            "pipeline_run__imported_at",
            "genome_id",
            "genome__id",
            "genome__accession",
            "protein_id",
            "protein__id",
            "protein__protein_id",
            "protein__protein_name",
            "protein__protein_length",
            "protein__gene_symbol",
            "taxon_id",
            "taxon__id",
            "taxon__taxon_name",
            "call_id",
            "method",
            "accession",
            "gene_symbol",
            "protein_name",
            "protein_length",
            "start",
            "end",
            "length",
            "repeat_residue",
            "purity",
            "aa_sequence",
        )
    )


def _trusted_accession(repeat_call):
    accession = (repeat_call.genome.accession or repeat_call.accession or "").strip()
    return accession or None


def _trusted_protein_id(repeat_call):
    protein_id = (repeat_call.protein.protein_id or "").strip()
    return protein_id or None


def _trusted_method(repeat_call):
    method = (repeat_call.method or "").strip()
    return method or None


def _trusted_residue(repeat_call):
    residue = (repeat_call.repeat_residue or "").strip().upper()
    return residue or None


def _protein_identity_key(repeat_call):
    accession = _trusted_accession(repeat_call)
    protein_id = _trusted_protein_id(repeat_call)
    method = _trusted_method(repeat_call)
    if accession is None or protein_id is None or method is None:
        return None
    return accession, protein_id, method


def _protein_residue_identity_key(repeat_call):
    protein_key = _protein_identity_key(repeat_call)
    residue = _trusted_residue(repeat_call)
    if protein_key is None or residue is None:
        return None
    return protein_key + (residue,)


def _identity_merged_protein_groups_from_repeat_calls(source_repeat_calls):
    grouped_proteins = OrderedDict()

    for repeat_call in source_repeat_calls:
        key = _protein_identity_key(repeat_call)
        if key is None:
            continue

        if key not in grouped_proteins:
            grouped_proteins[key] = {
                "accession": key[0],
                "protein_id": key[1],
                "method": key[2],
                "source_repeat_calls": [],
                "source_runs": set(),
                "gene_symbols": set(),
                "residue_keys": set(),
                "collapsed_call_keys": set(),
                "methods": set(),
                "repeat_residues": set(),
                "coordinates": set(),
                "protein_lengths": set(),
            }

        grouped_proteins[key]["source_repeat_calls"].append(repeat_call)
        grouped_proteins[key]["source_runs"].add(repeat_call.pipeline_run.run_id)
        if repeat_call.protein.gene_symbol:
            grouped_proteins[key]["gene_symbols"].add(repeat_call.protein.gene_symbol)
        residue_key = _protein_residue_identity_key(repeat_call)
        if residue_key is not None:
            grouped_proteins[key]["residue_keys"].add(residue_key)
        grouped_proteins[key]["collapsed_call_keys"].add(_collapsed_repeat_call_key(repeat_call))
        grouped_proteins[key]["methods"].add(repeat_call.method)
        residue = _trusted_residue(repeat_call)
        if residue is not None:
            grouped_proteins[key]["repeat_residues"].add(residue)
        grouped_proteins[key]["coordinates"].add((repeat_call.start, repeat_call.end))
        if repeat_call.protein.protein_length:
            grouped_proteins[key]["protein_lengths"].add(repeat_call.protein.protein_length)

    protein_groups = []
    for protein_group in grouped_proteins.values():
        representative_repeat_call = _representative_repeat_call(protein_group["source_repeat_calls"])
        protein_group["representative_repeat_call"] = representative_repeat_call
        protein_group["protein_name"] = representative_repeat_call.protein.protein_name
        protein_group["protein_length"] = representative_repeat_call.protein.protein_length
        protein_group["gene_symbols"] = sorted(protein_group["gene_symbols"])
        protein_group["gene_symbol_label"] = ", ".join(protein_group["gene_symbols"]) if protein_group["gene_symbols"] else "-"
        protein_group["source_repeat_calls"] = _sorted_source_repeat_calls(protein_group["source_repeat_calls"])
        protein_group["source_run_records"] = _sorted_source_runs(protein_group["source_repeat_calls"])
        protein_group["source_proteins"] = _sorted_source_proteins(protein_group["source_repeat_calls"])
        protein_group["source_runs"] = sorted(protein_group["source_runs"])
        protein_group["source_runs_count"] = len(protein_group["source_runs"])
        protein_group["source_proteins_count"] = len(protein_group["source_proteins"])
        protein_group["source_repeat_calls_count"] = len(protein_group["source_repeat_calls"])
        protein_group["residue_groups_count"] = len(protein_group["residue_keys"])
        protein_group["collapsed_repeat_calls_count"] = len(protein_group["collapsed_call_keys"])
        protein_group["methods"] = sorted(protein_group["methods"])
        protein_group["methods_label"] = _summary_label(protein_group["methods"])
        protein_group["repeat_residues"] = sorted(protein_group["repeat_residues"])
        protein_group["repeat_residues_label"] = _summary_label(protein_group["repeat_residues"])
        protein_group["coordinate_label"] = _coordinate_label(protein_group["coordinates"])
        protein_group["protein_length_label"] = _summary_label(sorted(protein_group["protein_lengths"], key=int))
        protein_group.pop("residue_keys")
        protein_group.pop("collapsed_call_keys")
        protein_group.pop("coordinates")
        protein_group.pop("protein_lengths")
        protein_groups.append(protein_group)

    return sorted(protein_groups, key=lambda group: (group["accession"], group["protein_id"], group["method"]))


def _identity_merged_residue_groups_from_repeat_calls(source_repeat_calls):
    grouped_residues = OrderedDict()

    for repeat_call in source_repeat_calls:
        key = _protein_residue_identity_key(repeat_call)
        if key is None:
            continue

        if key not in grouped_residues:
            grouped_residues[key] = {
                "accession": key[0],
                "protein_id": key[1],
                "method": key[2],
                "repeat_residue": key[3],
                "source_repeat_calls": [],
                "source_runs": set(),
                "source_taxa": set(),
                "gene_symbols": set(),
                "methods": set(),
                "coordinates": set(),
                "protein_lengths": set(),
                "lengths": set(),
                "purities": set(),
            }

        grouped_residues[key]["source_repeat_calls"].append(repeat_call)
        grouped_residues[key]["source_runs"].add(repeat_call.pipeline_run.run_id)
        grouped_residues[key]["source_taxa"].add(repeat_call.taxon.taxon_name)
        if repeat_call.protein.gene_symbol:
            grouped_residues[key]["gene_symbols"].add(repeat_call.protein.gene_symbol)
        grouped_residues[key]["methods"].add(repeat_call.method)
        grouped_residues[key]["coordinates"].add((repeat_call.start, repeat_call.end))
        if repeat_call.protein.protein_length:
            grouped_residues[key]["protein_lengths"].add(repeat_call.protein.protein_length)
        grouped_residues[key]["lengths"].add(repeat_call.length)
        grouped_residues[key]["purities"].add(normalize_purity(repeat_call.purity))

    residue_groups = []
    for residue_group in grouped_residues.values():
        representative_repeat_call = _representative_repeat_call(residue_group["source_repeat_calls"])
        residue_group["representative_repeat_call"] = representative_repeat_call
        residue_group["protein_name"] = representative_repeat_call.protein.protein_name
        residue_group["protein_length"] = representative_repeat_call.protein.protein_length
        residue_group["method"] = representative_repeat_call.method
        residue_group["methods"] = sorted(residue_group["methods"])
        residue_group["methods_label"] = _summary_label(residue_group["methods"])
        residue_group["start"] = representative_repeat_call.start
        residue_group["end"] = representative_repeat_call.end
        residue_group["coordinate_label"] = _coordinate_label(residue_group["coordinates"])
        residue_group["length"] = representative_repeat_call.length
        residue_group["length_label"] = _summary_label(sorted(residue_group["lengths"], key=int))
        residue_group["normalized_purity"] = normalize_purity(representative_repeat_call.purity)
        residue_group["purity_label"] = _summary_label(residue_group["purities"])
        residue_group["source_repeat_calls"] = _sorted_source_repeat_calls(residue_group["source_repeat_calls"])
        residue_group["source_run_records"] = _sorted_source_runs(residue_group["source_repeat_calls"])
        residue_group["source_proteins"] = _sorted_source_proteins(residue_group["source_repeat_calls"])
        residue_group["source_runs"] = sorted(residue_group["source_runs"])
        residue_group["source_runs_count"] = len(residue_group["source_runs"])
        residue_group["source_taxa"] = sorted(residue_group["source_taxa"])
        residue_group["source_taxa_label"] = ", ".join(residue_group["source_taxa"]) if residue_group["source_taxa"] else "-"
        residue_group["gene_symbols"] = sorted(residue_group["gene_symbols"])
        residue_group["gene_symbol_label"] = ", ".join(residue_group["gene_symbols"]) if residue_group["gene_symbols"] else "-"
        residue_group["source_proteins_count"] = len(residue_group["source_proteins"])
        residue_group["protein_length_label"] = _summary_label(sorted(residue_group["protein_lengths"], key=int))
        residue_group["source_count"] = len(residue_group["source_repeat_calls"])
        residue_group.pop("coordinates")
        residue_group.pop("protein_lengths")
        residue_group.pop("lengths")
        residue_group.pop("purities")
        residue_groups.append(residue_group)

    return sorted(
        residue_groups,
        key=lambda group: (group["accession"], group["protein_id"], group["method"], group["repeat_residue"]),
    )


def _sorted_source_repeat_calls(source_repeat_calls):
    return sorted(
        source_repeat_calls,
        key=lambda repeat_call: (
            repeat_call.pipeline_run.run_id,
            repeat_call.call_id,
        ),
    )


def _sorted_source_runs(source_repeat_calls):
    unique_runs = {repeat_call.pipeline_run.pk: repeat_call.pipeline_run for repeat_call in source_repeat_calls}
    return sorted(unique_runs.values(), key=lambda pipeline_run: (pipeline_run.run_id, pipeline_run.pk))


def _sorted_source_proteins(source_repeat_calls):
    unique_proteins = {}
    for repeat_call in source_repeat_calls:
        unique_proteins[repeat_call.protein.pk] = {
            "pk": repeat_call.protein.pk,
            "protein_id": repeat_call.protein.protein_id,
            "protein_name": repeat_call.protein.protein_name,
            "run_id": repeat_call.pipeline_run.run_id,
        }
    return sorted(
        unique_proteins.values(),
        key=lambda protein: (protein["run_id"], protein["protein_id"], protein["pk"]),
    )


def _representative_repeat_call(source_repeat_calls):
    return max(source_repeat_calls, key=_representative_repeat_call_key)


def _representative_repeat_call_key(repeat_call):
    protein_name = repeat_call.protein.protein_name or repeat_call.protein_name
    gene_symbol = repeat_call.protein.gene_symbol or repeat_call.gene_symbol
    protein_length = repeat_call.protein.protein_length or repeat_call.protein_length or 0

    return (
        int(bool(protein_name)),
        int(bool(gene_symbol)),
        int(protein_length > 0),
        int(bool(repeat_call.aa_sequence)),
        int(bool(repeat_call.method)),
        int(bool(_trusted_residue(repeat_call))),
        protein_length,
        repeat_call.length,
        float(repeat_call.purity),
        repeat_call.pipeline_run.imported_at,
        repeat_call.pipeline_run.run_id,
        repeat_call.call_id,
    )


def _summary_label(values):
    normalized_values = [str(value) for value in values if str(value)]
    unique_values = sorted(set(normalized_values))
    if not unique_values:
        return "-"
    if len(unique_values) == 1:
        return unique_values[0]
    return ", ".join(unique_values)


def _coordinate_label(coordinates):
    ordered_coordinates = sorted(coordinates)
    if not ordered_coordinates:
        return "-"
    if len(ordered_coordinates) == 1:
        start, end = ordered_coordinates[0]
        return f"{start}-{end}"
    return ", ".join(f"{start}-{end}" for start, end in ordered_coordinates)


def _identity_audit(source_repeat_calls, identity_key):
    included_by_accession = Counter()
    excluded_by_accession = Counter()

    for repeat_call in source_repeat_calls:
        accession = _trusted_accession(repeat_call)
        if identity_key(repeat_call) is None:
            if accession is not None:
                excluded_by_accession[accession] += 1
            continue
        if accession is not None:
            included_by_accession[accession] += 1

    return {
        "included_count": sum(included_by_accession.values()),
        "excluded_count": sum(excluded_by_accession.values()),
        "included_by_accession": included_by_accession,
        "excluded_by_accession": excluded_by_accession,
    }


def _merged_protein_groups_from_repeat_calls(source_repeat_calls):
    return _identity_merged_protein_groups_from_repeat_calls(source_repeat_calls)


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
