from django.db.models import Q

from ..models import RepeatCall, Taxon, TaxonClosure
from .identity import _identity_merged_residue_groups_from_repeat_calls
from .metrics import _parse_float, _parse_positive_int


def merged_repeat_call_groups(
    *,
    current_run=None,
    branch_taxon: Taxon | None = None,
    branch_taxa_ids=None,
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
                branch_taxa_ids=branch_taxa_ids,
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


def source_repeat_call_queryset(
    *,
    current_run=None,
    branch_taxon: Taxon | None = None,
    branch_taxa_ids=None,
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

    resolved_branch_taxa_ids = _resolved_branch_taxa_ids(
        branch_taxon=branch_taxon,
        branch_taxa_ids=branch_taxa_ids,
    )
    if resolved_branch_taxa_ids is not None:
        queryset = queryset.filter(taxon_id__in=resolved_branch_taxa_ids)

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


def _resolved_branch_taxa_ids(*, branch_taxon: Taxon | None = None, branch_taxa_ids=None):
    if branch_taxa_ids is not None:
        return branch_taxa_ids
    if branch_taxon is not None:
        return _branch_taxon_ids(branch_taxon)
    return None


def _branch_taxon_ids(taxon: Taxon):
    return TaxonClosure.objects.filter(ancestor=taxon).order_by().values_list("descendant_id", flat=True)
