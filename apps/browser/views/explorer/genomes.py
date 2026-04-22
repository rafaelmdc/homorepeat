from django.http import Http404
from django.urls import reverse
from django.views.generic import TemplateView

from apps.browser.explorer.canonical import (
    annotate_canonical_genome_browser_metrics,
    build_canonical_genome_detail_context,
    scoped_canonical_genomes,
    scoped_source_genomes,
)

from ...exports import BrowserTSVExportMixin, TSVColumn
from ...models import CanonicalGenome, Genome, PipelineRun, RepeatCall
from ..filters import _resolve_branch_scope, _resolve_current_run, _update_branch_scope_context
from ..formatting import _ordering_label
from ..navigation import _url_with_query
from ..pagination import VirtualScrollListView


class GenomeListView(BrowserTSVExportMixin, VirtualScrollListView):
    model = CanonicalGenome
    template_name = "browser/genome_list.html"
    context_object_name = "genomes"
    virtual_scroll_row_template_name = "browser/includes/genome_list_rows.html"
    virtual_scroll_colspan = 7
    tsv_filename_slug = "genomes"
    tsv_columns = (
        TSVColumn("Accession", "accession"),
        TSVColumn("Genome id", "genome_id"),
        TSVColumn("Genome", "genome_name"),
        TSVColumn("Taxon id", "taxon.taxon_id"),
        TSVColumn("Taxon", "taxon.taxon_name"),
        TSVColumn("Latest run", "latest_pipeline_run.run_id"),
        TSVColumn("Sequences", "sequences_count"),
        TSVColumn("Proteins", "proteins_count"),
        TSVColumn("Repeat calls", "repeat_calls_count"),
    )
    ordering_map = {
        "accession": ("accession",),
        "-accession": ("-accession",),
        "genome_name": ("genome_name", "accession"),
        "-genome_name": ("-genome_name", "accession"),
        "taxon": ("taxon__taxon_name", "accession"),
        "-taxon": ("-taxon__taxon_name", "accession"),
        "run": ("latest_pipeline_run__run_id", "accession"),
        "-run": ("-latest_pipeline_run__run_id", "accession"),
        "sequences": ("-sequences_count", "accession"),
        "-sequences": ("sequences_count", "accession"),
        "proteins": ("-proteins_count", "accession"),
        "-proteins": ("proteins_count", "accession"),
        "repeat_calls": ("-repeat_calls_count", "accession"),
        "-repeat_calls": ("repeat_calls_count", "accession"),
    }
    default_ordering = ("accession",)

    def _load_filter_state(self):
        self.current_run = _resolve_current_run(self.request)
        self.branch_scope = _resolve_branch_scope(self.request)
        self.selected_branch_taxon = self.branch_scope["selected_branch_taxon"]
        self.current_accession = self.request.GET.get("accession", "").strip()
        self.current_genome_name = self.request.GET.get("genome_name", "").strip()

    def _get_source_genomes_queryset(self):
        if not hasattr(self, "_source_genomes_queryset"):
            self._source_genomes_queryset = scoped_source_genomes(
                current_run=getattr(self, "current_run", None),
                accession_query=getattr(self, "current_accession", ""),
                genome_name=getattr(self, "current_genome_name", ""),
                branch_taxa_ids=getattr(self, "branch_scope", {}).get("branch_taxa_ids"),
            )
        return self._source_genomes_queryset

    def _get_canonical_genomes_queryset(self):
        if not hasattr(self, "_canonical_genomes_queryset"):
            source_genomes = self._get_source_genomes_queryset()
            source_repeat_calls = RepeatCall.objects.filter(genome_id__in=source_genomes.values("pk"))
            self._canonical_genomes_queryset = annotate_canonical_genome_browser_metrics(
                scoped_canonical_genomes(
                    current_run=getattr(self, "current_run", None),
                    accession_query=getattr(self, "current_accession", ""),
                    genome_name=getattr(self, "current_genome_name", ""),
                    branch_taxa_ids=getattr(self, "branch_scope", {}).get("branch_taxa_ids"),
                ),
                source_genomes=source_genomes,
                source_repeat_calls=source_repeat_calls,
            )
        return self._canonical_genomes_queryset

    def get_queryset(self):
        self._load_filter_state()
        queryset = self._get_canonical_genomes_queryset()
        ordering = self.get_ordering()
        if ordering:
            queryset = queryset.order_by(*ordering)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_run = getattr(self, "current_run", None)
        context["current_run"] = current_run
        context["current_run_id"] = current_run.run_id if current_run else ""
        context["run_choices"] = PipelineRun.objects.order_by("-imported_at", "run_id")
        _update_branch_scope_context(context, getattr(self, "branch_scope", _resolve_branch_scope(self.request)))
        context["current_accession"] = getattr(self, "current_accession", "")
        context["current_genome_name"] = getattr(self, "current_genome_name", "")
        context["ordering_options"] = [
            {"value": value, "label": _ordering_label(value)}
            for value in self.ordering_map.keys()
        ]
        return context


class GenomeDetailView(TemplateView):
    template_name = "browser/genome_detail.html"

    def _resolve_accession(self) -> str:
        raw_genome = Genome.objects.filter(pk=self.kwargs["pk"]).only("accession").first()
        if raw_genome is not None:
            return raw_genome.accession

        canonical_genome = CanonicalGenome.objects.filter(pk=self.kwargs["pk"]).only("accession").first()
        if canonical_genome is not None:
            return canonical_genome.accession

        raise Http404("No genome found for the requested identifier.")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        accession = self._resolve_accession()

        try:
            detail_context = build_canonical_genome_detail_context(accession)
        except CanonicalGenome.DoesNotExist as exc:
            raise Http404(str(exc)) from exc

        genome = detail_context["genome"]
        latest_source_genome = detail_context["latest_source_genome"]
        context.update(detail_context)
        context["run_detail_url"] = reverse("browser:run-detail", args=[genome.latest_pipeline_run.pk])
        context["taxon_detail_url"] = _url_with_query(
            reverse("browser:taxon-detail", args=[genome.taxon.pk]),
            run=genome.latest_pipeline_run.run_id,
        )
        context["sequence_browser_url"] = _url_with_query(
            reverse("browser:sequence-list"),
            run=genome.latest_pipeline_run.run_id,
            genome=genome.genome_id,
        )
        context["protein_browser_url"] = _url_with_query(
            reverse("browser:protein-list"),
            run=genome.latest_pipeline_run.run_id,
            genome=genome.genome_id,
        )
        context["repeatcall_browser_url"] = _url_with_query(
            reverse("browser:repeatcall-list"),
            run=genome.latest_pipeline_run.run_id,
            genome=genome.genome_id,
        )
        context["accession_detail_url"] = reverse("browser:accession-detail", args=[genome.accession])
        context["current_genome_url"] = reverse("browser:genome-detail", args=[latest_source_genome.pk])
        return context
