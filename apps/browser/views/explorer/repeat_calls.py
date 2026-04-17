from importlib import import_module

from django.http import Http404
from django.urls import reverse
from django.views.generic import TemplateView

from apps.browser.explorer.canonical import (
    build_canonical_repeat_call_detail_context,
    scoped_canonical_repeat_calls,
)

from ...models import CanonicalRepeatCall, PipelineRun, RepeatCall
from ..filters import (
    _resolve_branch_scope,
    _resolve_current_run,
    _resolve_genome_filter,
    _resolve_protein_filter,
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


class RepeatCallListView(VirtualScrollListView):
    model = CanonicalRepeatCall
    template_name = "browser/repeatcall_list.html"
    context_object_name = "repeat_calls"
    virtual_scroll_row_template_name = "browser/includes/repeatcall_list_rows.html"
    virtual_scroll_colspan = 10
    ordering_map = {
        "call_id": ("latest_pipeline_run__run_id", "source_call_id", "id"),
        "-call_id": ("latest_pipeline_run__run_id", "-source_call_id", "id"),
        "protein_name": ("latest_pipeline_run__run_id", "protein_name", "accession", "start", "id"),
        "-protein_name": ("latest_pipeline_run__run_id", "-protein_name", "accession", "start", "id"),
        "gene_symbol": ("latest_pipeline_run__run_id", "gene_symbol", "accession", "protein_name", "start", "id"),
        "-gene_symbol": ("latest_pipeline_run__run_id", "-gene_symbol", "accession", "protein_name", "start", "id"),
        "genome": ("latest_pipeline_run__run_id", "accession", "protein_name", "start", "id"),
        "-genome": ("latest_pipeline_run__run_id", "-accession", "protein_name", "start", "id"),
        "taxon": ("latest_pipeline_run__run_id", "taxon__taxon_name", "accession", "protein_name", "start", "id"),
        "-taxon": ("latest_pipeline_run__run_id", "-taxon__taxon_name", "accession", "protein_name", "start", "id"),
        "method": ("method", "latest_pipeline_run__run_id", "accession", "protein_name", "start", "id"),
        "-method": ("-method", "latest_pipeline_run__run_id", "accession", "protein_name", "start", "id"),
        "residue": ("repeat_residue", "latest_pipeline_run__run_id", "accession", "protein_name", "start", "id"),
        "-residue": ("-repeat_residue", "latest_pipeline_run__run_id", "accession", "protein_name", "start", "id"),
        "length": ("length", "latest_pipeline_run__run_id", "accession", "protein_name", "start", "id"),
        "-length": ("-length", "latest_pipeline_run__run_id", "accession", "protein_name", "start", "id"),
        "purity": ("purity", "latest_pipeline_run__run_id", "accession", "protein_name", "start", "id"),
        "-purity": ("-purity", "latest_pipeline_run__run_id", "accession", "protein_name", "start", "id"),
        "run": ("latest_pipeline_run__run_id", "accession", "protein_name", "start", "id"),
        "-run": ("-latest_pipeline_run__run_id", "accession", "protein_name", "start", "id"),
    }
    default_ordering = ("latest_pipeline_run_id", "accession", "protein_name", "start", "id")

    def include_virtual_scroll_count(self, *, context=None, page_obj=None):
        return False

    def use_cursor_pagination(self, queryset):
        return hasattr(queryset, "filter") and self.uses_fast_default_ordering()

    def _load_filter_state(self):
        self.current_run = _resolve_current_run(self.request)
        self.branch_scope = _resolve_branch_scope(self.request)
        self.selected_branch_taxon = self.branch_scope["selected_branch_taxon"]
        self.current_accession = self.request.GET.get("accession", "").strip()
        self.current_method = self.request.GET.get("method", "").strip()
        self.current_residue = self.request.GET.get("residue", "").strip().upper()
        self.current_gene_symbol = self.request.GET.get("gene_symbol", "").strip()
        self.current_length_min = self.request.GET.get("length_min", "").strip()
        self.current_length_max = self.request.GET.get("length_max", "").strip()
        self.current_purity_min = self.request.GET.get("purity_min", "").strip()
        self.current_purity_max = self.request.GET.get("purity_max", "").strip()
        self.current_genome = self.request.GET.get("genome", "").strip()
        self.current_sequence = self.request.GET.get("sequence", "").strip()
        self.current_protein = self.request.GET.get("protein", "").strip()

    def get_queryset(self):
        self._load_filter_state()
        queryset = scoped_canonical_repeat_calls(
            current_run=self.current_run,
            search_query=self.get_search_query(),
            accession_query=self.current_accession,
            gene_symbol=self.current_gene_symbol,
            genome_id=self.current_genome,
            sequence_id=self.current_sequence,
            protein_id=self.current_protein,
            branch_taxa_ids=self.branch_scope["branch_taxa_ids"],
            method=self.current_method,
            residue=self.current_residue,
            length_min=_parse_positive_int(self.current_length_min),
            length_max=_parse_positive_int(self.current_length_max),
            purity_min=_parse_float(self.current_purity_min),
            purity_max=_parse_float(self.current_purity_max),
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
        context["current_method"] = getattr(self, "current_method", "")
        context["current_residue"] = getattr(self, "current_residue", "")
        context["current_gene_symbol"] = getattr(self, "current_gene_symbol", "")
        context["current_length_min"] = getattr(self, "current_length_min", "")
        context["current_length_max"] = getattr(self, "current_length_max", "")
        context["current_purity_min"] = getattr(self, "current_purity_min", "")
        context["current_purity_max"] = getattr(self, "current_purity_max", "")
        context["current_genome"] = getattr(self, "current_genome", "")
        context["current_sequence"] = getattr(self, "current_sequence", "")
        context["current_protein"] = getattr(self, "current_protein", "")
        context["selected_genome"] = _resolve_genome_filter(current_run, context["current_genome"])
        context["selected_sequence"] = _resolve_sequence_filter(current_run, context["current_sequence"])
        context["selected_protein"] = _resolve_protein_filter(current_run, context["current_protein"])
        context["method_choices"] = facet_choices["methods"]
        context["residue_choices"] = facet_choices["residues"]
        return context


class RepeatCallDetailView(TemplateView):
    template_name = "browser/repeatcall_detail.html"

    def _resolve_identity(self):
        raw_repeat_call = (
            RepeatCall.objects.select_related("sequence", "protein")
            .only(
                "accession",
                "sequence__sequence_id",
                "protein__protein_id",
                "method",
                "repeat_residue",
                "start",
                "end",
            )
            .filter(pk=self.kwargs["pk"])
            .first()
        )
        if raw_repeat_call is not None:
            return {
                "accession": raw_repeat_call.accession,
                "sequence_id": raw_repeat_call.sequence.sequence_id,
                "protein_id": raw_repeat_call.protein.protein_id,
                "method": raw_repeat_call.method,
                "repeat_residue": raw_repeat_call.repeat_residue,
                "start": raw_repeat_call.start,
                "end": raw_repeat_call.end,
            }

        canonical_repeat_call = (
            CanonicalRepeatCall.objects.select_related("sequence", "protein")
            .only(
                "accession",
                "sequence__sequence_id",
                "protein__protein_id",
                "method",
                "repeat_residue",
                "start",
                "end",
            )
            .filter(pk=self.kwargs["pk"])
            .first()
        )
        if canonical_repeat_call is not None:
            return {
                "accession": canonical_repeat_call.accession,
                "sequence_id": canonical_repeat_call.sequence.sequence_id,
                "protein_id": canonical_repeat_call.protein.protein_id,
                "method": canonical_repeat_call.method,
                "repeat_residue": canonical_repeat_call.repeat_residue,
                "start": canonical_repeat_call.start,
                "end": canonical_repeat_call.end,
            }

        raise Http404("No repeat call found for the requested identifier.")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        identity = self._resolve_identity()

        try:
            detail_context = build_canonical_repeat_call_detail_context(**identity)
        except CanonicalRepeatCall.DoesNotExist as exc:
            raise Http404(str(exc)) from exc

        repeat_call = detail_context["repeat_call"]
        latest_repeat_call = repeat_call.latest_repeat_call
        context.update(detail_context)
        context["taxon_detail_url"] = _url_with_query(
            reverse("browser:taxon-detail", args=[repeat_call.taxon.pk]),
            run=repeat_call.latest_pipeline_run.run_id,
        )
        context["length_explorer_url"] = _url_with_query(
            reverse("browser:lengths"),
            run=repeat_call.latest_pipeline_run.run_id,
            branch=repeat_call.taxon.pk,
            q=(
                repeat_call.gene_symbol
                or repeat_call.protein.protein_id
                or repeat_call.protein_name
                or repeat_call.accession
            ),
            method=repeat_call.method,
            residue=repeat_call.repeat_residue,
        )
        context["codon_ratio_explorer_url"] = _url_with_query(
            reverse("browser:codon-ratios"),
            run=repeat_call.latest_pipeline_run.run_id,
            branch=repeat_call.taxon.pk,
            q=(
                repeat_call.gene_symbol
                or repeat_call.protein.protein_id
                or repeat_call.protein_name
                or repeat_call.accession
            ),
            method=repeat_call.method,
            residue=repeat_call.repeat_residue,
            codon_metric_name=repeat_call.codon_metric_name,
        )
        context["repeatcall_list_url"] = _url_with_query(
            reverse("browser:repeatcall-list"),
            run=repeat_call.latest_pipeline_run.run_id,
            protein=repeat_call.protein.protein_id,
        )
        context["sequence_detail_url"] = reverse("browser:sequence-detail", args=[latest_repeat_call.sequence_id])
        context["run_detail_url"] = reverse("browser:run-detail", args=[repeat_call.latest_pipeline_run.pk])
        context["protein_detail_url"] = reverse("browser:protein-detail", args=[latest_repeat_call.protein_id])
        context["genome_detail_url"] = reverse("browser:genome-detail", args=[latest_repeat_call.genome_id])
        return context
