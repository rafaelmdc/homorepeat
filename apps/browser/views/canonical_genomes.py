from django.db.models import Count, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce

from ..models import (
    CanonicalGenome,
    CanonicalProtein,
    CanonicalRepeatCall,
    CanonicalSequence,
    Genome,
    Protein,
    RepeatCall,
    TaxonClosure,
)
from .querysets import _annotated_genomes, _count_subquery


def scoped_canonical_genomes(
    *,
    current_run=None,
    search_query: str = "",
    accession_query: str = "",
    genome_name: str = "",
    branch_taxa_ids=None,
):
    queryset = CanonicalGenome.objects.exclude(accession="").select_related(
        "latest_pipeline_run",
        "latest_import_batch",
        "taxon",
    )
    if current_run is not None:
        queryset = queryset.filter(latest_pipeline_run=current_run)
    if search_query:
        queryset = queryset.filter(
            Q(accession__icontains=search_query) | Q(genome_name__icontains=search_query)
        )
    if accession_query:
        queryset = queryset.filter(accession__istartswith=accession_query)
    if genome_name:
        queryset = queryset.filter(genome_name__istartswith=genome_name)
    if branch_taxa_ids is not None:
        queryset = queryset.filter(taxon_id__in=branch_taxa_ids)
    return queryset


def scoped_source_genomes(
    *,
    current_run=None,
    search_query: str = "",
    accession_query: str = "",
    genome_name: str = "",
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
        queryset = queryset.filter(accession__istartswith=accession_query)
    if genome_name:
        queryset = queryset.filter(genome_name__istartswith=genome_name)
    if branch_taxa_ids is not None:
        queryset = queryset.filter(taxon_id__in=branch_taxa_ids)
    return queryset


def annotate_canonical_genome_browser_metrics(queryset, *, source_genomes, source_repeat_calls):
    return queryset.annotate(
        latest_source_genome_pk=Subquery(
            Genome.objects.filter(
                accession=OuterRef("accession"),
                pipeline_run_id=OuterRef("latest_pipeline_run_id"),
            )
            .order_by("pk")
            .values("pk")[:1],
            output_field=IntegerField(),
        ),
        source_genomes_count=Coalesce(_count_per_accession_subquery(source_genomes), Value(0)),
        source_runs_count=Coalesce(
            _count_per_accession_subquery(source_genomes, field_name="pipeline_run", distinct=True),
            Value(0),
        ),
        source_repeat_calls_count=Coalesce(_count_per_accession_subquery(source_repeat_calls), Value(0)),
        sequences_count=Coalesce(_count_subquery(CanonicalSequence, "genome"), Value(0)),
        proteins_count=Coalesce(_count_subquery(CanonicalProtein, "genome"), Value(0)),
        repeat_calls_count=Coalesce(_count_subquery(CanonicalRepeatCall, "genome"), Value(0)),
    )


def build_canonical_genome_detail_context(accession: str) -> dict:
    genome = (
        CanonicalGenome.objects.select_related(
            "latest_pipeline_run",
            "latest_import_batch",
            "taxon",
        )
        .filter(accession=accession)
        .first()
    )
    if genome is None:
        raise CanonicalGenome.DoesNotExist(f"No canonical genome found for accession {accession}.")

    source_genomes = list(
        _annotated_genomes(
            Genome.objects.filter(accession=accession).select_related("pipeline_run", "taxon")
        ).order_by("-pipeline_run__imported_at", "-pipeline_run_id", "genome_id")
    )
    if not source_genomes:
        raise Genome.DoesNotExist(f"No imported genomes found for accession {accession}.")

    source_runs = {}
    source_taxa = {}
    for source_genome in source_genomes:
        source_runs[source_genome.pipeline_run.pk] = source_genome.pipeline_run
        source_taxa[source_genome.taxon.pk] = source_genome.taxon

    latest_source_genome = next(
        (
            source_genome
            for source_genome in source_genomes
            if source_genome.pipeline_run_id == genome.latest_pipeline_run_id
        ),
        source_genomes[0],
    )

    protein_preview_rows = []
    current_proteins = list(genome.proteins.order_by("protein_name", "protein_id")[:10])
    latest_raw_proteins_by_id = {
        protein.protein_id: protein
        for protein in Protein.objects.filter(
            pipeline_run=genome.latest_pipeline_run,
            genome__accession=genome.accession,
            protein_id__in=[protein.protein_id for protein in current_proteins],
        ).only("id", "protein_id")
    }
    for protein in current_proteins:
        protein_preview_rows.append(
            {
                "protein": protein,
                "latest_protein": latest_raw_proteins_by_id.get(protein.protein_id),
            }
        )

    repeat_call_preview = list(
        genome.repeat_calls.select_related("latest_repeat_call").order_by("protein_name", "start", "id")[:10]
    )

    return {
        "genome": genome,
        "lineage": (
            TaxonClosure.objects.filter(descendant=genome.taxon)
            .select_related("ancestor")
            .order_by("-depth", "ancestor__taxon_name")
        ),
        "current_sequences_count": genome.sequences.count(),
        "current_proteins_count": genome.proteins.count(),
        "current_repeat_calls_count": genome.repeat_calls.count(),
        "protein_preview": protein_preview_rows,
        "repeat_call_preview": repeat_call_preview,
        "latest_source_genome": latest_source_genome,
        "source_genomes": source_genomes,
        "source_runs": sorted(source_runs.values(), key=lambda run: run.run_id),
        "source_taxa": sorted(source_taxa.values(), key=lambda taxon: (taxon.taxon_name, taxon.taxon_id)),
        "source_genomes_count": len(source_genomes),
        "source_runs_count": len(source_runs),
        "source_repeat_calls_count": RepeatCall.objects.filter(accession=accession).count(),
    }


def build_accession_list_summary(canonical_genomes, *, source_genomes):
    canonical_repeat_calls = CanonicalRepeatCall.objects.filter(genome_id__in=canonical_genomes.values("pk"))
    method_summary = list(
        canonical_repeat_calls.order_by()
        .values("method")
        .annotate(count=Count("pk"))
        .order_by("method")
    )
    residue_summary = list(
        canonical_repeat_calls.order_by()
        .values("repeat_residue")
        .annotate(count=Count("pk"))
        .order_by("repeat_residue")
    )
    return {
        "accession_groups_count": canonical_genomes.count(),
        "current_sequences_count": CanonicalSequence.objects.filter(genome_id__in=canonical_genomes.values("pk")).count(),
        "current_proteins_count": CanonicalProtein.objects.filter(genome_id__in=canonical_genomes.values("pk")).count(),
        "current_repeat_calls_count": canonical_repeat_calls.count(),
        "source_genomes_count": source_genomes.count(),
        "source_runs_count": source_genomes.order_by().values("pipeline_run_id").distinct().count(),
        "method_summary": [
            {"label": row["method"], "count": row["count"]}
            for row in method_summary
        ],
        "residue_summary": [
            {"label": row["repeat_residue"], "count": row["count"]}
            for row in residue_summary
        ],
    }


def _count_per_accession_subquery(queryset, *, field_name="pk", distinct=False):
    return Subquery(
        queryset.filter(accession=OuterRef("accession"))
        .order_by()
        .values("accession")
        .annotate(total=Count(field_name, distinct=distinct))
        .values("total")[:1],
        output_field=IntegerField(),
    )
