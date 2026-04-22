from django.http import Http404
from django.urls import reverse
from django.views.generic import TemplateView

from apps.browser.explorer.canonical import (
    annotate_canonical_sequence_browser_metrics,
    build_canonical_sequence_detail_context,
    scoped_canonical_sequences,
)

from ...exports import BrowserTSVExportMixin, TSVColumn
from ...models import CanonicalSequence, PipelineRun, Sequence
from ..filters import (
    _resolve_branch_scope,
    _resolve_current_run,
    _resolve_genome_filter,
    _update_branch_scope_context,
)
from ..navigation import _url_with_query
from ..pagination import VirtualScrollListView


class SequenceListView(BrowserTSVExportMixin, VirtualScrollListView):
    model = CanonicalSequence
    template_name = "browser/sequence_list.html"
    context_object_name = "sequences"
    virtual_scroll_row_template_name = "browser/includes/sequence_list_rows.html"
    virtual_scroll_colspan = 7
    tsv_filename_slug = "sequences"
    tsv_columns = (
        TSVColumn("Sequence id", "sequence_id"),
        TSVColumn("Sequence", "sequence_name"),
        TSVColumn("Gene", "gene_symbol"),
        TSVColumn("Genome accession", "assembly_accession"),
        TSVColumn("Taxon id", "taxon.taxon_id"),
        TSVColumn("Taxon", "taxon.taxon_name"),
        TSVColumn("Latest run", "latest_pipeline_run.run_id"),
        TSVColumn("Sequence length", "sequence_length"),
        TSVColumn("Proteins", "proteins_count"),
        TSVColumn("Repeat calls", "repeat_calls_count"),
    )
    ordering_map = {
        "sequence_name": ("latest_pipeline_run__run_id", "sequence_name", "sequence_id"),
        "-sequence_name": ("latest_pipeline_run__run_id", "-sequence_name", "sequence_id"),
        "gene_symbol": ("latest_pipeline_run__run_id", "gene_symbol", "sequence_name", "sequence_id"),
        "-gene_symbol": ("latest_pipeline_run__run_id", "-gene_symbol", "sequence_name", "sequence_id"),
        "genome": ("assembly_accession", "latest_pipeline_run__run_id", "sequence_name", "sequence_id"),
        "-genome": ("-assembly_accession", "latest_pipeline_run__run_id", "sequence_name", "sequence_id"),
        "taxon": ("taxon__taxon_name", "latest_pipeline_run__run_id", "sequence_name", "sequence_id"),
        "-taxon": ("-taxon__taxon_name", "latest_pipeline_run__run_id", "sequence_name", "sequence_id"),
        "run": ("latest_pipeline_run__run_id", "sequence_name", "sequence_id"),
        "-run": ("-latest_pipeline_run__run_id", "sequence_name", "sequence_id"),
        "proteins": ("-proteins_count", "latest_pipeline_run__run_id", "sequence_name", "sequence_id"),
        "-proteins": ("proteins_count", "latest_pipeline_run__run_id", "sequence_name", "sequence_id"),
        "calls": ("-repeat_calls_count", "latest_pipeline_run__run_id", "sequence_name", "sequence_id"),
        "-calls": ("repeat_calls_count", "latest_pipeline_run__run_id", "sequence_name", "sequence_id"),
    }
    default_ordering = ("latest_pipeline_run_id", "assembly_accession", "sequence_name", "id")

    def include_virtual_scroll_count(self, *, context=None, page_obj=None):
        return False

    def use_cursor_pagination(self, queryset):
        return hasattr(queryset, "filter") and self.uses_fast_default_ordering()

    def _load_filter_state(self):
        self.current_run = _resolve_current_run(self.request)
        self.branch_scope = _resolve_branch_scope(self.request)
        self.selected_branch_taxon = self.branch_scope["selected_branch_taxon"]
        self.current_accession = self.request.GET.get("accession", "").strip()
        self.current_gene_symbol = self.request.GET.get("gene_symbol", "").strip()
        self.current_genome = self.request.GET.get("genome", "").strip()

    def get_queryset(self):
        self._load_filter_state()
        queryset = annotate_canonical_sequence_browser_metrics(
            scoped_canonical_sequences(
                current_run=self.current_run,
                search_query=self.get_search_query(),
                accession_query=self.current_accession,
                gene_symbol=self.current_gene_symbol,
                genome_id=self.current_genome,
                branch_taxa_ids=self.branch_scope["branch_taxa_ids"],
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
        context["current_run"] = current_run
        context["current_run_id"] = current_run.run_id if current_run else ""
        context["run_choices"] = PipelineRun.objects.order_by("-imported_at", "run_id")
        _update_branch_scope_context(context, getattr(self, "branch_scope", _resolve_branch_scope(self.request)))
        context["current_accession"] = getattr(self, "current_accession", "")
        context["current_gene_symbol"] = getattr(self, "current_gene_symbol", "")
        context["current_genome"] = getattr(self, "current_genome", "")
        context["selected_genome"] = _resolve_genome_filter(current_run, context["current_genome"])
        return context


class SequenceDetailView(TemplateView):
    template_name = "browser/sequence_detail.html"

    def _resolve_identity(self):
        raw_sequence = (
            Sequence.objects.select_related("genome")
            .only("sequence_id", "genome__accession")
            .filter(pk=self.kwargs["pk"])
            .first()
        )
        if raw_sequence is not None:
            return raw_sequence.genome.accession, raw_sequence.sequence_id

        canonical_sequence = (
            CanonicalSequence.objects.select_related("genome")
            .only("sequence_id", "genome__accession")
            .filter(pk=self.kwargs["pk"])
            .first()
        )
        if canonical_sequence is not None:
            return canonical_sequence.genome.accession, canonical_sequence.sequence_id

        raise Http404("No sequence found for the requested identifier.")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        accession, sequence_id = self._resolve_identity()

        try:
            detail_context = build_canonical_sequence_detail_context(
                accession=accession,
                sequence_id=sequence_id,
            )
        except CanonicalSequence.DoesNotExist as exc:
            raise Http404(str(exc)) from exc

        sequence = detail_context["sequence"]
        latest_source_sequence = detail_context["latest_source_sequence"]
        context.update(detail_context)
        context["taxon_detail_url"] = _url_with_query(
            reverse("browser:taxon-detail", args=[sequence.taxon.pk]),
            run=sequence.latest_pipeline_run.run_id,
        )
        context["protein_browser_url"] = _url_with_query(
            reverse("browser:protein-list"),
            run=sequence.latest_pipeline_run.run_id,
            sequence=sequence.sequence_id,
        )
        context["repeatcall_browser_url"] = _url_with_query(
            reverse("browser:repeatcall-list"),
            run=sequence.latest_pipeline_run.run_id,
            sequence=sequence.sequence_id,
        )
        context["sequence_list_url"] = _url_with_query(
            reverse("browser:sequence-list"),
            run=sequence.latest_pipeline_run.run_id,
            genome=sequence.genome.genome_id,
        )
        context["run_detail_url"] = reverse("browser:run-detail", args=[sequence.latest_pipeline_run.pk])
        context["genome_detail_url"] = reverse("browser:genome-detail", args=[latest_source_sequence.genome_id])
        return context
