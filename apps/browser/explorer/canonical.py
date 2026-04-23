from django.db.models import Count, Exists, IntegerField, Max, Min, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce

from ..models import (
    CanonicalGenome,
    CanonicalProtein,
    CanonicalRepeatCall,
    CanonicalSequence,
    Genome,
    Protein,
    RepeatCall,
    Sequence,
    TaxonClosure,
)


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
        _annotated_source_genomes(
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


def scoped_canonical_sequences(
    *,
    current_run=None,
    search_query: str = "",
    accession_query: str = "",
    gene_symbol: str = "",
    genome_id: str = "",
    branch_taxa_ids=None,
):
    queryset = (
        CanonicalSequence.objects.select_related("latest_pipeline_run", "taxon")
        .defer("nucleotide_sequence")
        .only(
            "id",
            "latest_pipeline_run_id",
            "latest_pipeline_run__id",
            "latest_pipeline_run__run_id",
            "genome_id",
            "taxon_id",
            "taxon__id",
            "taxon__taxon_id",
            "taxon__taxon_name",
            "sequence_id",
            "sequence_name",
            "sequence_length",
            "gene_symbol",
            "assembly_accession",
        )
    )
    if current_run is not None:
        queryset = queryset.filter(latest_pipeline_run=current_run)
    if search_query:
        queryset = queryset.filter(
            Q(sequence_id__istartswith=search_query)
            | Q(sequence_name__istartswith=search_query)
            | Q(gene_symbol__istartswith=search_query)
            | Q(assembly_accession__istartswith=search_query)
        )
    if accession_query:
        queryset = queryset.filter(
            Q(assembly_accession__istartswith=accession_query)
            | Q(genome__accession__istartswith=accession_query)
        )
    if gene_symbol:
        queryset = queryset.filter(gene_symbol__istartswith=gene_symbol)
    if genome_id:
        queryset = queryset.filter(genome__genome_id=genome_id)
    if branch_taxa_ids is not None:
        queryset = queryset.filter(taxon_id__in=branch_taxa_ids)
    return queryset


def annotate_canonical_sequence_browser_metrics(queryset):
    return queryset.annotate(
        latest_source_sequence_pk=_latest_raw_pk_subquery(
            Sequence.objects.filter(
                genome__accession=OuterRef("genome__accession"),
                sequence_id=OuterRef("sequence_id"),
                pipeline_run_id=OuterRef("latest_pipeline_run_id"),
            )
        ),
        latest_source_genome_pk=_latest_raw_pk_subquery(
            Genome.objects.filter(
                accession=OuterRef("genome__accession"),
                pipeline_run_id=OuterRef("latest_pipeline_run_id"),
            )
        ),
        proteins_count=Coalesce(_count_subquery(CanonicalProtein, "sequence"), Value(0)),
        repeat_calls_count=Coalesce(_count_subquery(CanonicalRepeatCall, "sequence"), Value(0)),
    )


def build_canonical_sequence_detail_context(*, accession: str, sequence_id: str) -> dict:
    sequence = (
        CanonicalSequence.objects.select_related(
            "latest_pipeline_run",
            "latest_import_batch",
            "taxon",
            "genome",
        )
        .filter(genome__accession=accession, sequence_id=sequence_id)
        .first()
    )
    if sequence is None:
        raise CanonicalSequence.DoesNotExist(
            f"No canonical sequence found for accession {accession} and sequence {sequence_id}."
        )

    source_sequences = list(
        Sequence.objects.filter(
            genome__accession=accession,
            sequence_id=sequence_id,
        )
        .select_related("pipeline_run", "genome", "taxon")
        .annotate(
            proteins_count=Count("proteins", distinct=True),
            repeat_calls_count=Count("repeat_calls", distinct=True),
        )
        .order_by("-pipeline_run__imported_at", "-pipeline_run_id", "pk")
    )

    latest_source_sequence = next(
        (
            source_sequence
            for source_sequence in source_sequences
            if source_sequence.pipeline_run_id == sequence.latest_pipeline_run_id
        ),
        source_sequences[0] if source_sequences else None,
    )

    current_proteins = list(sequence.proteins.order_by("protein_name", "protein_id")[:12])
    latest_raw_proteins_by_id = {
        protein.protein_id: protein
        for protein in Protein.objects.filter(
            pipeline_run=sequence.latest_pipeline_run,
            accession=accession,
            sequence__sequence_id=sequence.sequence_id,
            protein_id__in=[protein.protein_id for protein in current_proteins],
        ).only("id", "protein_id")
    }
    protein_preview = [
        {
            "protein": protein,
            "latest_protein": latest_raw_proteins_by_id.get(protein.protein_id),
        }
        for protein in current_proteins
    ]

    repeat_call_preview = list(
        sequence.repeat_calls.select_related("latest_repeat_call").order_by("protein_name", "start", "id")[:12]
    )
    source_runs = {
        source_sequence.pipeline_run.pk: source_sequence.pipeline_run
        for source_sequence in source_sequences
    }

    return {
        "sequence": sequence,
        "current_proteins_count": sequence.proteins.count(),
        "current_repeat_calls_count": sequence.repeat_calls.count(),
        "protein_preview": protein_preview,
        "repeat_call_preview": repeat_call_preview,
        "source_sequences": source_sequences,
        "source_sequences_count": len(source_sequences),
        "source_runs": sorted(source_runs.values(), key=lambda run: run.run_id),
        "source_runs_count": len(source_runs),
        "latest_source_sequence": latest_source_sequence,
        "source_repeat_calls_count": RepeatCall.objects.filter(
            sequence__genome__accession=accession,
            sequence__sequence_id=sequence.sequence_id,
        ).count(),
    }


def scoped_canonical_proteins(
    *,
    current_run=None,
    search_query: str = "",
    accession_query: str = "",
    gene_symbol: str = "",
    genome_id: str = "",
    sequence_id: str = "",
    branch_taxa_ids=None,
    method: str = "",
    residue: str = "",
    length_min=None,
    length_max=None,
    purity_min=None,
    purity_max=None,
):
    queryset = (
        CanonicalProtein.objects.select_related("latest_pipeline_run", "taxon")
        .defer("amino_acid_sequence")
        .only(
            "id",
            "latest_pipeline_run_id",
            "latest_pipeline_run__id",
            "latest_pipeline_run__run_id",
            "genome_id",
            "taxon_id",
            "taxon__id",
            "taxon__taxon_id",
            "taxon__taxon_name",
            "protein_id",
            "protein_name",
            "protein_length",
            "accession",
            "gene_symbol",
            "repeat_call_count",
        )
    )
    if current_run is not None:
        queryset = queryset.filter(latest_pipeline_run=current_run)
    if search_query:
        queryset = queryset.filter(
            Q(protein_id__istartswith=search_query)
            | Q(protein_name__istartswith=search_query)
            | Q(gene_symbol__istartswith=search_query)
            | Q(accession__istartswith=search_query)
        )
    if accession_query:
        queryset = queryset.filter(accession__istartswith=accession_query)
    if gene_symbol:
        queryset = queryset.filter(gene_symbol__istartswith=gene_symbol)
    if genome_id:
        queryset = queryset.filter(genome__genome_id=genome_id)
    if sequence_id:
        queryset = queryset.filter(sequence__sequence_id=sequence_id)
    if branch_taxa_ids is not None:
        queryset = queryset.filter(taxon_id__in=branch_taxa_ids)

    call_filters = Q()
    if method:
        call_filters &= Q(method=method)
    if residue:
        call_filters &= Q(repeat_residue=residue)
    if length_min is not None:
        call_filters &= Q(length__gte=length_min)
    if length_max is not None:
        call_filters &= Q(length__lte=length_max)
    if purity_min is not None:
        call_filters &= Q(purity__gte=purity_min)
    if purity_max is not None:
        call_filters &= Q(purity__lte=purity_max)
    if call_filters.children:
        queryset = queryset.annotate(
            has_matching_call=Exists(
                CanonicalRepeatCall.objects.filter(protein=OuterRef("pk")).filter(call_filters)
            )
        ).filter(has_matching_call=True)

    return queryset


def annotate_canonical_protein_browser_metrics(queryset):
    return queryset.annotate(
        latest_source_protein_pk=_latest_raw_pk_subquery(
            Protein.objects.filter(
                accession=OuterRef("accession"),
                protein_id=OuterRef("protein_id"),
                pipeline_run_id=OuterRef("latest_pipeline_run_id"),
            )
        ),
        latest_source_genome_pk=_latest_raw_pk_subquery(
            Genome.objects.filter(
                accession=OuterRef("accession"),
                pipeline_run_id=OuterRef("latest_pipeline_run_id"),
            )
        ),
    )


def build_canonical_protein_detail_context(*, accession: str, protein_id: str) -> dict:
    protein = (
        CanonicalProtein.objects.select_related(
            "latest_pipeline_run",
            "latest_import_batch",
            "taxon",
            "genome",
            "sequence",
        )
        .filter(accession=accession, protein_id=protein_id)
        .first()
    )
    if protein is None:
        raise CanonicalProtein.DoesNotExist(
            f"No canonical protein found for accession {accession} and protein {protein_id}."
        )

    source_proteins = list(
        Protein.objects.filter(accession=accession, protein_id=protein_id)
        .select_related("pipeline_run", "genome", "sequence", "taxon")
        .annotate(repeat_calls_count=Count("repeat_calls", distinct=True))
        .order_by("-pipeline_run__imported_at", "-pipeline_run_id", "pk")
    )
    latest_source_protein = next(
        (
            source_protein
            for source_protein in source_proteins
            if source_protein.pipeline_run_id == protein.latest_pipeline_run_id
        ),
        source_proteins[0] if source_proteins else None,
    )
    repeat_calls = protein.repeat_calls.select_related("latest_repeat_call").order_by(
        "method",
        "repeat_residue",
        "start",
        "id",
    )
    source_runs = {
        source_protein.pipeline_run.pk: source_protein.pipeline_run
        for source_protein in source_proteins
    }

    return {
        "protein": protein,
        "current_repeat_calls_count": repeat_calls.count(),
        "call_summaries": (
            repeat_calls.values("method", "repeat_residue")
            .annotate(
                total=Count("pk"),
                min_length=Min("length"),
                max_length=Max("length"),
            )
            .order_by("method", "repeat_residue")
        ),
        "repeat_call_preview": list(repeat_calls[:12]),
        "source_proteins": source_proteins,
        "source_proteins_count": len(source_proteins),
        "source_runs": sorted(source_runs.values(), key=lambda run: run.run_id),
        "source_runs_count": len(source_runs),
        "latest_source_protein": latest_source_protein,
    }


def scoped_canonical_repeat_calls(
    *,
    current_run=None,
    search_query: str = "",
    accession_query: str = "",
    gene_symbol: str = "",
    genome_id: str = "",
    sequence_id: str = "",
    protein_id: str = "",
    branch_taxa_ids=None,
    method: str = "",
    residue: str = "",
    length_min=None,
    length_max=None,
    purity_min=None,
    purity_max=None,
):
    queryset = (
        CanonicalRepeatCall.objects.select_related("latest_pipeline_run", "taxon", "latest_repeat_call")
        .defer("aa_sequence", "codon_sequence")
        .only(
            "id",
            "latest_pipeline_run_id",
            "latest_pipeline_run__id",
            "latest_pipeline_run__run_id",
            "latest_repeat_call_id",
            "latest_repeat_call__id",
            "latest_repeat_call__call_id",
            "latest_repeat_call__protein_id",
            "latest_repeat_call__genome_id",
            "latest_repeat_call__sequence_id",
            "taxon_id",
            "taxon__id",
            "taxon__taxon_id",
            "taxon__taxon_name",
            "source_call_id",
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
        )
    )
    if current_run is not None:
        queryset = queryset.filter(latest_pipeline_run=current_run)
    if search_query:
        queryset = queryset.filter(
            Q(source_call_id__istartswith=search_query)
            | Q(accession__istartswith=search_query)
            | Q(protein_name__istartswith=search_query)
            | Q(gene_symbol__istartswith=search_query)
        )
    if accession_query:
        queryset = queryset.filter(accession__istartswith=accession_query)
    if genome_id:
        queryset = queryset.filter(genome__genome_id=genome_id)
    if sequence_id:
        queryset = queryset.filter(sequence__sequence_id=sequence_id)
    if protein_id:
        queryset = queryset.filter(protein__protein_id=protein_id)
    if method:
        queryset = queryset.filter(method=method)
    if residue:
        queryset = queryset.filter(repeat_residue=residue)
    if gene_symbol:
        queryset = queryset.filter(gene_symbol__istartswith=gene_symbol)
    if length_min is not None:
        queryset = queryset.filter(length__gte=length_min)
    if length_max is not None:
        queryset = queryset.filter(length__lte=length_max)
    if purity_min is not None:
        queryset = queryset.filter(purity__gte=purity_min)
    if purity_max is not None:
        queryset = queryset.filter(purity__lte=purity_max)
    if branch_taxa_ids is not None:
        queryset = queryset.filter(taxon_id__in=branch_taxa_ids)
    return queryset


def build_canonical_repeat_call_detail_context(
    *,
    accession: str,
    sequence_id: str,
    protein_id: str,
    method: str,
    repeat_residue: str,
    start: int,
    end: int,
) -> dict:
    repeat_call = (
        CanonicalRepeatCall.objects.select_related(
            "latest_pipeline_run",
            "latest_import_batch",
            "taxon",
            "genome",
            "sequence",
            "protein",
            "latest_repeat_call",
            "latest_repeat_call__pipeline_run",
            "latest_repeat_call__genome",
            "latest_repeat_call__sequence",
            "latest_repeat_call__protein",
            "latest_repeat_call__taxon",
        )
        .filter(
            accession=accession,
            sequence__sequence_id=sequence_id,
            protein__protein_id=protein_id,
            method=method,
            repeat_residue=repeat_residue,
            start=start,
            end=end,
        )
        .first()
    )
    if repeat_call is None:
        raise CanonicalRepeatCall.DoesNotExist("No canonical repeat call found for the requested identity.")

    source_repeat_calls = list(
        RepeatCall.objects.filter(
            accession=accession,
            sequence__sequence_id=sequence_id,
            protein__protein_id=protein_id,
            method=method,
            repeat_residue=repeat_residue,
            start=start,
            end=end,
        )
        .select_related("pipeline_run", "genome", "sequence", "protein", "taxon")
        .order_by("-pipeline_run__imported_at", "-pipeline_run_id", "pk")
    )
    source_runs = {
        source_repeat_call.pipeline_run.pk: source_repeat_call.pipeline_run
        for source_repeat_call in source_repeat_calls
    }

    return {
        "repeat_call": repeat_call,
        "source_repeat_calls": source_repeat_calls,
        "source_repeat_calls_count": len(source_repeat_calls),
        "source_runs": sorted(source_runs.values(), key=lambda run: run.run_id),
        "source_runs_count": len(source_runs),
    }


def _annotated_source_genomes(queryset=None):
    if queryset is None:
        queryset = Genome.objects.all()
    return queryset.annotate(
        sequences_count=Coalesce(_count_subquery(Sequence, "genome"), Value(0)),
        proteins_count=Coalesce(_count_subquery(Protein, "genome"), Value(0)),
        repeat_calls_count=Coalesce(_count_subquery(RepeatCall, "genome"), Value(0)),
    )


def _count_per_accession_subquery(queryset, *, field_name="pk", distinct=False):
    return Subquery(
        queryset.filter(accession=OuterRef("accession"))
        .order_by()
        .values("accession")
        .annotate(total=Count(field_name, distinct=distinct))
        .values("total")[:1],
        output_field=IntegerField(),
    )


def _latest_raw_pk_subquery(queryset):
    return Subquery(
        queryset.order_by("pk").values("pk")[:1],
        output_field=IntegerField(),
    )


def _count_subquery(model, field_name, *, group_field_name=None):
    if group_field_name is None:
        group_field_name = field_name
    return Subquery(
        model.objects.filter(**{field_name: OuterRef("pk")})
        .order_by()
        .values(group_field_name)
        .annotate(total=Count("pk"))
        .values("total")[:1],
        output_field=IntegerField(),
    )
