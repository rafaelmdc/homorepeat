from ..models import Taxon
from .identity import _merged_protein_groups_from_repeat_calls
from .repeat_calls import source_repeat_call_queryset


def merged_protein_groups(
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
    return _merged_protein_groups_from_repeat_calls(
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
