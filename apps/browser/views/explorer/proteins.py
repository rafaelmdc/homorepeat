from importlib import import_module

from django.http import Http404
from django.urls import reverse
from django.views.generic import TemplateView

from apps.browser.explorer.canonical import (
    annotate_canonical_protein_browser_metrics,
    build_canonical_protein_detail_context,
    scoped_canonical_proteins,
)

from ...models import CanonicalProtein, PipelineRun, Protein
from ..filters import (
    _resolve_branch_scope,
    _resolve_current_run,
    _resolve_genome_filter,
    _resolve_sequence_filter,
    _update_branch_scope_context,
)
from ..formatting import _parse_float, _parse_positive_int
from ..navigation import _url_with_query
from ..pagination import VirtualScrollListView


def resolve_browser_facets(*, pipeline_run=None, pipeline_runs=None):
    return import_module("apps.browser.views").resolve_browser_facets(
        pipeline_run=pipeline_run,
        pipeline_runs=pipeline_runs,
    )


class ProteinListView(VirtualScrollListView):
    model = CanonicalProtein
    template_name = "browser/protein_list.html"
    context_object_name = "proteins"
    virtual_scroll_row_template_name = "browser/includes/protein_list_rows.html"
    virtual_scroll_colspan = 6
    ordering_map = {
        "protein_name": ("latest_pipeline_run__run_id", "accession", "protein_name", "protein_id"),
        "-protein_name": ("latest_pipeline_run__run_id", "accession", "-protein_name", "protein_id"),
        "gene_symbol": (
            "latest_pipeline_run__run_id",
            "gene_symbol",
            "accession",
            "protein_name",
            "protein_id",
        ),
        "-gene_symbol": (
            "latest_pipeline_run__run_id",
            "-gene_symbol",
            "accession",
            "protein_name",
            "protein_id",
        ),
        "protein_length": (
            "latest_pipeline_run__run_id",
            "protein_length",
            "accession",
            "protein_name",
            "protein_id",
        ),
        "-protein_length": (
            "latest_pipeline_run__run_id",
            "-protein_length",
            "accession",
            "protein_name",
            "protein_id",
        ),
        "accession": ("latest_pipeline_run__run_id", "accession", "protein_name", "protein_id"),
        "-accession": ("latest_pipeline_run__run_id", "-accession", "protein_name", "protein_id"),
        "taxon": ("taxon__taxon_name", "latest_pipeline_run__run_id", "accession", "protein_name", "protein_id"),
        "-taxon": ("-taxon__taxon_name", "latest_pipeline_run__run_id", "accession", "protein_name", "protein_id"),
        "run": ("latest_pipeline_run__run_id", "accession", "protein_name", "protein_id"),
        "-run": ("-latest_pipeline_run__run_id", "accession", "protein_name", "protein_id"),
        "calls": ("-repeat_call_count", "latest_pipeline_run__run_id", "accession", "protein_name", "protein_id"),
        "-calls": ("repeat_call_count", "latest_pipeline_run__run_id", "accession", "protein_name", "protein_id"),
    }
    default_ordering = ("latest_pipeline_run_id", "accession", "protein_name", "id")

    def _load_filter_state(self):
        self.current_run = _resolve_current_run(self.request)
        self.branch_scope = _resolve_branch_scope(self.request)
        self.selected_branch_taxon = self.branch_scope["selected_branch_taxon"]
        self.current_accession = self.request.GET.get("accession", "").strip()
        self.current_gene_symbol = self.request.GET.get("gene_symbol", "").strip()
        self.current_method = self.request.GET.get("method", "").strip()
        self.current_residue = self.request.GET.get("residue", "").strip().upper()
        self.current_length_min = self.request.GET.get("length_min", "").strip()
        self.current_length_max = self.request.GET.get("length_max", "").strip()
        self.current_purity_min = self.request.GET.get("purity_min", "").strip()
        self.current_purity_max = self.request.GET.get("purity_max", "").strip()
        self.current_genome = self.request.GET.get("genome", "").strip()
        self.current_sequence = self.request.GET.get("sequence", "").strip()

    def use_cursor_pagination(self, queryset):
        return hasattr(queryset, "filter") and self.uses_fast_default_ordering()

    def include_virtual_scroll_count(self, *, context=None, page_obj=None):
        return False

    def get_queryset(self):
        self._load_filter_state()
        queryset = annotate_canonical_protein_browser_metrics(
            scoped_canonical_proteins(
                current_run=self.current_run,
                search_query=self.get_search_query(),
                accession_query=self.current_accession,
                gene_symbol=self.current_gene_symbol,
                genome_id=self.current_genome,
                sequence_id=self.current_sequence,
                branch_taxa_ids=self.branch_scope["branch_taxa_ids"],
                method=self.current_method,
                residue=self.current_residue,
                length_min=_parse_positive_int(self.current_length_min),
                length_max=_parse_positive_int(self.current_length_max),
                purity_min=_parse_float(self.current_purity_min),
                purity_max=_parse_float(self.current_purity_max),
            )
        )
        ordering = self.get_ordering()
        if ordering:
            queryset = queryset.order_by(*ordering)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.is_virtual_scroll_fragment_request():
            return context

        current_run = getattr(self, "current_run", None)
        run_choices = PipelineRun.objects.order_by("-imported_at", "run_id")
        facet_choices = resolve_browser_facets(
            pipeline_run=current_run,
            pipeline_runs=run_choices,
        )

        context["current_run"] = current_run
        context["current_run_id"] = current_run.run_id if current_run else ""
        context["run_choices"] = run_choices
        _update_branch_scope_context(context, getattr(self, "branch_scope", _resolve_branch_scope(self.request)))
        context["current_accession"] = getattr(self, "current_accession", "")
        context["current_gene_symbol"] = getattr(self, "current_gene_symbol", "")
        context["current_method"] = getattr(self, "current_method", "")
        context["current_residue"] = getattr(self, "current_residue", "")
        context["current_length_min"] = getattr(self, "current_length_min", "")
        context["current_length_max"] = getattr(self, "current_length_max", "")
        context["current_purity_min"] = getattr(self, "current_purity_min", "")
        context["current_purity_max"] = getattr(self, "current_purity_max", "")
        context["current_genome"] = getattr(self, "current_genome", "")
        context["current_sequence"] = getattr(self, "current_sequence", "")
        context["selected_genome"] = _resolve_genome_filter(current_run, context["current_genome"])
        context["selected_sequence"] = _resolve_sequence_filter(current_run, context["current_sequence"])
        context["method_choices"] = facet_choices["methods"]
        context["residue_choices"] = facet_choices["residues"]
        return context


class ProteinDetailView(TemplateView):
    template_name = "browser/protein_detail.html"

    def _resolve_identity(self):
        raw_protein = (
            Protein.objects.only("accession", "protein_id")
            .filter(pk=self.kwargs["pk"])
            .first()
        )
        if raw_protein is not None:
            return raw_protein.accession, raw_protein.protein_id

        canonical_protein = (
            CanonicalProtein.objects.only("accession", "protein_id")
            .filter(pk=self.kwargs["pk"])
            .first()
        )
        if canonical_protein is not None:
            return canonical_protein.accession, canonical_protein.protein_id

        raise Http404("No protein found for the requested identifier.")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        accession, protein_id = self._resolve_identity()

        try:
            detail_context = build_canonical_protein_detail_context(
                accession=accession,
                protein_id=protein_id,
            )
        except CanonicalProtein.DoesNotExist as exc:
            raise Http404(str(exc)) from exc

        protein = detail_context["protein"]
        latest_source_protein = detail_context["latest_source_protein"]
        context.update(detail_context)
        context["taxon_detail_url"] = _url_with_query(
            reverse("browser:taxon-detail", args=[protein.taxon.pk]),
            run=protein.latest_pipeline_run.run_id,
        )
        context["repeatcall_browser_url"] = _url_with_query(
            reverse("browser:repeatcall-list"),
            run=protein.latest_pipeline_run.run_id,
            protein=protein.protein_id,
        )
        context["length_explorer_url"] = _url_with_query(
            reverse("browser:lengths"),
            run=protein.latest_pipeline_run.run_id,
            branch=protein.taxon.pk,
            q=protein.gene_symbol or protein.protein_id or protein.protein_name or protein.accession,
        )
        context["codon_ratio_explorer_url"] = _url_with_query(
            reverse("browser:codon-ratios"),
            run=protein.latest_pipeline_run.run_id,
            branch=protein.taxon.pk,
            q=protein.gene_symbol or protein.protein_id or protein.protein_name or protein.accession,
        )
        context["sequence_detail_url"] = reverse("browser:sequence-detail", args=[latest_source_protein.sequence_id])
        context["protein_list_url"] = _url_with_query(
            reverse("browser:protein-list"),
            run=protein.latest_pipeline_run.run_id,
            genome=protein.genome.genome_id,
        )
        context["run_detail_url"] = reverse("browser:run-detail", args=[protein.latest_pipeline_run.pk])
        context["genome_detail_url"] = reverse("browser:genome-detail", args=[latest_source_protein.genome_id])
        return context
