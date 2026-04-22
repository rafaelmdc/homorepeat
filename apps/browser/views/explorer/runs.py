from django.db.models import Count, Sum, Value
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.views.generic import DetailView

from apps.imports.models import ImportBatch

from ...exports import BrowserTSVExportMixin, TSVColumn
from ...metadata import resolve_run_browser_metadata
from ...models import PipelineRun
from ..filters import _run_distinct_taxa_count, _run_import_batches
from ..formatting import _mapping_items
from ..navigation import _url_with_query
from ..pagination import VirtualScrollListView
from ..querysets import _annotated_batches, _annotated_runs, _summary_runs


class RunListView(BrowserTSVExportMixin, VirtualScrollListView):
    model = PipelineRun
    template_name = "browser/run_list.html"
    context_object_name = "runs"
    virtual_scroll_row_template_name = "browser/includes/run_list_rows.html"
    virtual_scroll_colspan = 8
    tsv_filename_slug = "runs"
    tsv_columns = (
        TSVColumn("Run", "run_id"),
        TSVColumn("Status", "status"),
        TSVColumn("Profile", "profile"),
        TSVColumn("Imported genomes", "genomes_count"),
        TSVColumn("Imported sequences", "sequences_count"),
        TSVColumn("Imported proteins", "proteins_count"),
        TSVColumn("Imported repeat calls", "repeat_calls_count"),
        TSVColumn("Imported", "imported_at"),
    )
    search_fields = ("run_id", "status", "profile", "git_revision")
    ordering_map = {
        "run_id": ("run_id",),
        "-run_id": ("-run_id",),
        "status": ("status", "run_id"),
        "-status": ("-status", "run_id"),
        "profile": ("profile", "run_id"),
        "-profile": ("-profile", "run_id"),
        "genomes": ("-genomes_count", "run_id"),
        "-genomes": ("genomes_count", "run_id"),
        "sequences": ("-sequences_count", "run_id"),
        "-sequences": ("sequences_count", "run_id"),
        "proteins": ("-proteins_count", "run_id"),
        "-proteins": ("proteins_count", "run_id"),
        "repeat_calls": ("-repeat_calls_count", "run_id"),
        "-repeat_calls": ("repeat_calls_count", "run_id"),
        "started": ("started_at_utc", "run_id"),
        "-started": ("-started_at_utc", "run_id"),
        "finished": ("finished_at_utc", "run_id"),
        "-finished": ("-finished_at_utc", "run_id"),
        "imported": ("imported_at", "run_id"),
        "-imported": ("-imported_at", "run_id"),
    }
    default_ordering = ("-imported_at", "run_id")

    def apply_filters(self, queryset):
        status = self.request.GET.get("status", "").strip()
        if status:
            queryset = queryset.filter(status=status)
        return queryset

    def get_base_queryset(self):
        return _summary_runs()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_status"] = self.request.GET.get("status", "").strip()
        context["status_choices"] = PipelineRun.objects.order_by("status").values_list("status", flat=True).distinct()
        return context


class RunDetailView(DetailView):
    model = PipelineRun
    template_name = "browser/run_detail.html"
    context_object_name = "pipeline_run"

    def get_queryset(self):
        return _annotated_runs()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pipeline_run = self.object
        import_batches = _run_import_batches(pipeline_run)
        active_import_batch = import_batches.filter(
            status__in=[ImportBatch.Status.PENDING, ImportBatch.Status.RUNNING]
        ).order_by("-started_at", "-pk").first()
        latest_import_batch = import_batches.order_by("-started_at", "-pk").first()
        latest_completed_import_batch = import_batches.filter(status=ImportBatch.Status.COMPLETED).order_by(
            "-finished_at",
            "-started_at",
            "-pk",
        ).first()
        context["distinct_taxa_count"] = _run_distinct_taxa_count(pipeline_run)
        context["linked_sections"] = [
            {
                "title": "Taxa",
                "description": "Lineage-aware taxon view scoped to this run.",
                "url_name": "browser:taxon-list",
            },
            {
                "title": "Genomes",
                "description": "Genome-level browser scoped to this run.",
                "url_name": "browser:genome-list",
            },
            {
                "title": "Sequences",
                "description": "Call-linked sequence subset stored for browsing and provenance.",
                "url_name": "browser:sequence-list",
            },
            {
                "title": "Proteins",
                "description": "Protein-level browser scoped to this run.",
                "url_name": "browser:protein-list",
            },
            {
                "title": "Repeat calls",
                "description": "Canonical repeat-call browser scoped to this run.",
                "url_name": "browser:repeatcall-list",
            },
            {
                "title": "Accession status",
                "description": "Accession-level operational status rows imported for this run.",
                "url_name": "browser:accessionstatus-list",
            },
            {
                "title": "Method/residue status",
                "description": "Per-accession method and residue call-count rows imported for this run.",
                "url_name": "browser:accessioncallcount-list",
            },
            {
                "title": "Download manifest",
                "description": "Batch-scoped download provenance rows imported from raw acquisition outputs.",
                "url_name": "browser:downloadmanifest-list",
            },
            {
                "title": "Normalization warnings",
                "description": "Operational warning rows imported from raw acquisition and normalization outputs.",
                "url_name": "browser:normalizationwarning-list",
            },
        ]
        run_facets = resolve_run_browser_metadata(pipeline_run)["facets"]
        context["methods"] = run_facets["methods"]
        context["repeat_residues"] = run_facets["residues"]
        context["method_residue_summary"] = list(
            pipeline_run.accession_call_count_rows.values("method", "repeat_residue")
            .annotate(
                accession_total=Count("pk"),
                repeat_calls_total=Coalesce(Sum("n_repeat_calls"), Value(0)),
            )
            .order_by("method", "repeat_residue")
        )
        context["terminal_status_summary"] = list(
            pipeline_run.accession_status_rows.values("terminal_status")
            .annotate(total=Count("pk"))
            .order_by("terminal_status")
        )
        context["warning_summary"] = list(
            pipeline_run.normalization_warnings.values("warning_code", "warning_scope")
            .annotate(total=Count("pk"))
            .order_by("-total", "warning_code", "warning_scope")
        )
        context["warning_browser_url"] = _url_with_query(
            reverse("browser:normalizationwarning-list"),
            run=pipeline_run.run_id,
        )
        context["taxon_browser_url"] = _url_with_query(
            reverse("browser:taxon-list"),
            run=pipeline_run.run_id,
        )
        context["genome_browser_url"] = _url_with_query(
            reverse("browser:genome-list"),
            run=pipeline_run.run_id,
        )
        context["sequence_browser_url"] = _url_with_query(
            reverse("browser:sequence-list"),
            run=pipeline_run.run_id,
        )
        context["protein_browser_url"] = _url_with_query(
            reverse("browser:protein-list"),
            run=pipeline_run.run_id,
        )
        context["repeatcall_browser_url"] = _url_with_query(
            reverse("browser:repeatcall-list"),
            run=pipeline_run.run_id,
        )
        context["accession_browser_url"] = _url_with_query(
            reverse("browser:accession-list"),
            run=pipeline_run.run_id,
        )
        context["accession_status_browser_url"] = _url_with_query(
            reverse("browser:accessionstatus-list"),
            run=pipeline_run.run_id,
        )
        context["accession_call_count_browser_url"] = _url_with_query(
            reverse("browser:accessioncallcount-list"),
            run=pipeline_run.run_id,
        )
        context["download_manifest_browser_url"] = _url_with_query(
            reverse("browser:downloadmanifest-list"),
            run=pipeline_run.run_id,
        )
        context["batch_preview"] = _annotated_batches(
            pipeline_run.acquisition_batches.order_by("batch_id")
        )[:12]
        context["batch_preview_is_truncated"] = pipeline_run.acquisition_batches_count > len(context["batch_preview"])
        context["active_import_batch"] = active_import_batch
        context["has_active_import_batches"] = active_import_batch is not None
        context["enable_import_auto_refresh"] = active_import_batch is not None
        context["active_import_progress_items"] = _mapping_items(
            active_import_batch.progress_payload if active_import_batch else {},
            exclude_keys={"message", "current", "total", "percent", "unit", "processed"},
        )
        context["latest_import_batch"] = latest_import_batch
        context["latest_completed_import_batch"] = latest_completed_import_batch
        context["latest_import_row_count_items"] = _mapping_items(
            latest_completed_import_batch.row_counts if latest_completed_import_batch else {}
        )
        context["recent_import_batches"] = list(import_batches.order_by("-started_at", "-pk")[:5])
        context["imports_history_url"] = reverse("imports:history")
        return context
