from django.http import Http404
from django.urls import reverse
from django.views.generic import TemplateView

from apps.browser.explorer.accessions import build_accession_list_summary
from apps.browser.explorer.canonical import (
    annotate_canonical_genome_browser_metrics,
    build_canonical_genome_detail_context,
    scoped_canonical_genomes,
    scoped_source_genomes,
)

from ...exports import BrowserTSVExportMixin, TSVColumn
from ...models import CanonicalGenome, PipelineRun, RepeatCall
from ..filters import _resolve_branch_scope, _resolve_current_run, _update_branch_scope_context
from ..formatting import _ordering_label
from ..navigation import _url_with_query
from ..pagination import VirtualScrollListView


class AccessionsListView(BrowserTSVExportMixin, VirtualScrollListView):
    model = CanonicalGenome
    template_name = "browser/accession_list.html"
    context_object_name = "accession_groups"
    virtual_scroll_row_template_name = "browser/includes/accession_list_rows.html"
    virtual_scroll_colspan = 6
    paginate_by = 20
    tsv_filename_slug = "accessions"
    tsv_columns = (
        TSVColumn("Accession", "accession"),
        TSVColumn("Latest genome id", "genome_id"),
        TSVColumn("Latest run", "latest_pipeline_run.run_id"),
        TSVColumn("Imported observations", "source_genomes_count"),
        TSVColumn("Supporting runs", "source_runs_count"),
        TSVColumn("Current repeat calls", "repeat_calls_count"),
        TSVColumn("Current proteins", "proteins_count"),
        TSVColumn("Analyzed proteins", "analyzed_protein_count"),
    )
    ordering_map = {
        "accession": ("accession",),
        "-accession": ("-accession",),
        "runs": ("-source_runs_count", "accession"),
        "-runs": ("source_runs_count", "accession"),
        "genomes": ("-source_genomes_count", "accession"),
        "-genomes": ("source_genomes_count", "accession"),
        "calls": ("-repeat_calls_count", "accession"),
        "-calls": ("repeat_calls_count", "accession"),
        "collapsed_calls": ("-repeat_calls_count", "accession"),
        "-collapsed_calls": ("repeat_calls_count", "accession"),
        "proteins": ("-proteins_count", "accession"),
        "-proteins": ("proteins_count", "accession"),
        "derived_proteins": ("-proteins_count", "accession"),
        "-derived_proteins": ("proteins_count", "accession"),
        "analyzed_proteins": ("-analyzed_protein_count", "accession"),
        "-analyzed_proteins": ("analyzed_protein_count", "accession"),
    }
    default_ordering = ("accession",)

    def _load_filter_state(self):
        self.current_run = _resolve_current_run(self.request)
        self.branch_scope = _resolve_branch_scope(self.request)
        self.selected_branch_taxon = self.branch_scope["selected_branch_taxon"]

    def _get_source_genomes_queryset(self):
        if not hasattr(self, "_source_genomes_queryset"):
            self._source_genomes_queryset = scoped_source_genomes(
                current_run=getattr(self, "current_run", None),
                search_query=self.get_search_query(),
                branch_taxa_ids=getattr(self, "branch_scope", {}).get("branch_taxa_ids"),
            )
        return self._source_genomes_queryset

    def _get_accession_groups_queryset(self):
        if not hasattr(self, "_accession_groups_queryset"):
            source_genomes = self._get_source_genomes_queryset()
            source_repeat_calls = RepeatCall.objects.filter(genome_id__in=source_genomes.values("pk"))
            self._accession_groups_queryset = annotate_canonical_genome_browser_metrics(
                scoped_canonical_genomes(
                    current_run=getattr(self, "current_run", None),
                    search_query=self.get_search_query(),
                    branch_taxa_ids=getattr(self, "branch_scope", {}).get("branch_taxa_ids"),
                ),
                source_genomes=source_genomes,
                source_repeat_calls=source_repeat_calls,
            )
        return self._accession_groups_queryset

    def get_queryset(self):
        self._load_filter_state()
        queryset = self._get_accession_groups_queryset()
        ordering = self.get_ordering()
        if ordering:
            queryset = queryset.order_by(*ordering)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        accession_groups = self._get_accession_groups_queryset()
        context["summary"] = build_accession_list_summary(
            accession_groups,
            source_genomes=self._get_source_genomes_queryset(),
        )
        current_run = getattr(self, "current_run", None)
        context["current_run"] = current_run
        context["current_run_id"] = current_run.run_id if current_run else ""
        context["run_choices"] = PipelineRun.objects.order_by("-imported_at", "run_id")
        context["ordering_options"] = [
            {"value": value, "label": _ordering_label(value)}
            for value in self.ordering_map.keys()
        ]
        _update_branch_scope_context(context, getattr(self, "branch_scope", _resolve_branch_scope(self.request)))
        return context


class AccessionDetailView(TemplateView):
    template_name = "browser/accession_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        accession = kwargs["accession"]

        try:
            detail_context = build_canonical_genome_detail_context(accession)
        except CanonicalGenome.DoesNotExist as exc:
            raise Http404(str(exc)) from exc

        genome = detail_context["genome"]
        latest_source_genome = detail_context["latest_source_genome"]
        context.update(detail_context)
        context["accession"] = accession
        context["accession_list_url"] = reverse("browser:accession-list")
        context["genome_detail_url"] = reverse("browser:genome-detail", args=[latest_source_genome.pk])
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
        context["protein_list_url"] = _url_with_query(
            reverse("browser:protein-list"),
            run=genome.latest_pipeline_run.run_id,
            genome=genome.genome_id,
        )
        context["repeatcall_list_url"] = _url_with_query(
            reverse("browser:repeatcall-list"),
            run=genome.latest_pipeline_run.run_id,
            genome=genome.genome_id,
        )
        return context
