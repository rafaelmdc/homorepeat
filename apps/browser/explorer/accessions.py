from django.db.models import Count

from ..models import CanonicalProtein, CanonicalRepeatCall, CanonicalSequence


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
