from django.db.models import Q
from django.urls import reverse
from django.views.generic import DetailView

from ...models import Genome, PipelineRun, Protein, RepeatCall, Taxon, TaxonClosure
from ..filters import (
    _apply_branch_scope_filter,
    _branch_taxon_ids,
    _resolve_branch_scope,
    _resolve_current_run,
    _run_taxon_ids,
    _update_branch_scope_context,
)
from ..navigation import _url_with_query
from ..pagination import VirtualScrollListView


class TaxonListView(VirtualScrollListView):
    model = Taxon
    template_name = "browser/taxon_list.html"
    context_object_name = "taxa"
    virtual_scroll_row_template_name = "browser/includes/taxon_list_rows.html"
    virtual_scroll_colspan = 4
    search_fields = ("taxon_name",)
    ordering_map = {
        "taxon_name": ("taxon_name", "taxon_id"),
        "-taxon_name": ("-taxon_name", "taxon_id"),
        "taxon_id": ("taxon_id",),
        "-taxon_id": ("-taxon_id",),
        "rank": ("rank", "taxon_name"),
        "-rank": ("-rank", "taxon_name"),
        "parent": ("parent_taxon__taxon_name", "taxon_name", "taxon_id"),
        "-parent": ("-parent_taxon__taxon_name", "taxon_name", "taxon_id"),
    }
    default_ordering = ("taxon_name", "taxon_id")

    def get_base_queryset(self):
        return Taxon.objects.select_related("parent_taxon")

    def apply_search(self, queryset):
        query = self.get_search_query()
        if not query:
            return queryset
        search_filter = Q(taxon_name__icontains=query)
        if query.isdigit():
            search_filter |= Q(taxon_id=int(query))
        return queryset.filter(search_filter)

    def apply_filters(self, queryset):
        self.current_run = _resolve_current_run(self.request)
        self.branch_scope = _resolve_branch_scope(self.request)
        self.selected_branch_taxon = self.branch_scope["selected_branch_taxon"]
        self.current_rank = self.request.GET.get("rank", "").strip()

        if self.current_run:
            queryset = queryset.filter(pk__in=_run_taxon_ids(self.current_run))

        queryset = _apply_branch_scope_filter(queryset, branch_scope=self.branch_scope, field_name="pk")

        if self.current_rank:
            queryset = queryset.filter(rank=self.current_rank)

        return queryset.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_run = getattr(self, "current_run", None)
        context["current_run"] = current_run
        context["current_run_id"] = current_run.run_id if current_run else ""
        context["run_choices"] = PipelineRun.objects.order_by("-imported_at", "run_id")
        context["current_rank"] = getattr(self, "current_rank", "")
        context["rank_choices"] = (
            Taxon.objects.exclude(rank="")
            .order_by("rank")
            .values_list("rank", flat=True)
            .distinct()
        )
        _update_branch_scope_context(context, getattr(self, "branch_scope", _resolve_branch_scope(self.request)))
        return context


class TaxonDetailView(DetailView):
    model = Taxon
    template_name = "browser/taxon_detail.html"
    context_object_name = "taxon"

    def get_queryset(self):
        return Taxon.objects.select_related("parent_taxon")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        taxon = self.object
        current_run = _resolve_current_run(self.request)
        branch_ids = _branch_taxon_ids(taxon)
        branch_genomes = Genome.objects.filter(taxon_id__in=branch_ids).select_related("pipeline_run", "taxon")
        branch_proteins = Protein.objects.filter(taxon_id__in=branch_ids)
        branch_repeat_calls = RepeatCall.objects.filter(taxon_id__in=branch_ids)

        if current_run:
            branch_genomes = branch_genomes.filter(pipeline_run=current_run)
            branch_proteins = branch_proteins.filter(pipeline_run=current_run)
            branch_repeat_calls = branch_repeat_calls.filter(pipeline_run=current_run)

        context["current_run"] = current_run
        context["current_run_id"] = current_run.run_id if current_run else ""
        context["lineage"] = (
            TaxonClosure.objects.filter(descendant=taxon)
            .select_related("ancestor")
            .order_by("-depth", "ancestor__taxon_name")
        )
        context["descendant_count"] = TaxonClosure.objects.filter(ancestor=taxon, depth__gt=0).count()
        context["child_taxa"] = taxon.children.order_by("taxon_name")[:12]
        context["branch_genomes_count"] = branch_genomes.count()
        context["branch_proteins_count"] = branch_proteins.count()
        context["branch_repeat_calls_count"] = branch_repeat_calls.count()
        context["linked_genomes"] = branch_genomes.order_by("accession", "pipeline_run__run_id")[:10]
        context["genome_branch_url"] = _url_with_query(
            reverse("browser:genome-list"),
            run=current_run.run_id if current_run else None,
            branch=taxon.pk,
        )
        context["length_branch_url"] = _url_with_query(
            reverse("browser:lengths"),
            run=current_run.run_id if current_run else None,
            branch=taxon.pk,
        )
        context["codon_ratio_branch_url"] = _url_with_query(
            reverse("browser:codon-ratios"),
            run=current_run.run_id if current_run else None,
            branch=taxon.pk,
        )
        context["protein_branch_url"] = _url_with_query(
            reverse("browser:protein-list"),
            run=current_run.run_id if current_run else None,
            branch=taxon.pk,
        )
        context["repeatcall_branch_url"] = _url_with_query(
            reverse("browser:repeatcall-list"),
            run=current_run.run_id if current_run else None,
            branch=taxon.pk,
        )
        context["accession_branch_url"] = _url_with_query(
            reverse("browser:accession-list"),
            run=current_run.run_id if current_run else None,
            branch=taxon.pk,
        )
        context["run_detail_url"] = reverse("browser:run-detail", args=[current_run.pk]) if current_run else ""
        return context
