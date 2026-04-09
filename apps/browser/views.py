from urllib.parse import urlencode

from django.http import Http404
from django.db.models import Count, Exists, IntegerField, Max, Min, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.views.generic import DetailView, ListView, TemplateView

from apps.imports.models import ImportBatch

from .merged import (
    accession_group_queryset,
    build_accession_summary,
    build_accession_analytics,
    merged_protein_groups,
    merged_repeat_call_groups,
)
from .models import (
    AccessionCallCount,
    AccessionStatus,
    AcquisitionBatch,
    DownloadManifestEntry,
    Genome,
    NormalizationWarning,
    PipelineRun,
    Protein,
    RepeatCall,
    RunParameter,
    Sequence,
    Taxon,
    TaxonClosure,
)


class BrowserHomeView(TemplateView):
    template_name = "browser/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cards"] = [
            {
                "title": "Imported runs",
                "count": PipelineRun.objects.count(),
                "description": "Browse imported pipeline runs and inspect their provenance and counts.",
                "url_name": "browser:run-list",
            },
            {
                "title": "Taxa",
                "count": Taxon.objects.count(),
                "description": "Lineage-aware taxon browser backed by imported taxonomy and closure rows.",
                "url_name": "browser:taxon-list",
            },
            {
                "title": "Genomes",
                "count": Genome.objects.count(),
                "description": "Genome-level browser with accession-aware identity and run provenance.",
                "url_name": "browser:genome-list",
            },
            {
                "title": "Proteins",
                "count": Protein.objects.count(),
                "description": "Protein browser keyed to imported repeat-bearing proteins and linked repeat calls.",
                "url_name": "browser:protein-list",
            },
            {
                "title": "Repeat calls",
                "count": RepeatCall.objects.count(),
                "description": "Canonical merged repeat-call records with run and protein provenance.",
                "url_name": "browser:repeatcall-list",
            },
            {
                "title": "Merged analytics",
                "count": Genome.objects.exclude(accession="").order_by().values("accession").distinct().count(),
                "description": "Derived accession-group analytics with collapsed calls and denominator-safe merged percentages.",
                "url_name": "browser:accession-list",
            },
        ]
        context["recent_runs"] = _annotated_runs()[:5]
        return context


class BrowserListView(ListView):
    paginate_by = 20
    ordering_map = {}
    default_ordering = ()
    search_fields = ()

    def get_base_queryset(self):
        return super().get_queryset()

    def get_search_query(self):
        return self.request.GET.get("q", "").strip()

    def get_ordering(self):
        requested_ordering = self.request.GET.get("order_by", "").strip()
        if requested_ordering in self.ordering_map:
            return self.ordering_map[requested_ordering]
        return self.default_ordering

    def apply_search(self, queryset):
        query = self.get_search_query()
        if not query or not self.search_fields:
            return queryset

        search_filter = Q()
        for field_name in self.search_fields:
            search_filter |= Q(**{f"{field_name}__icontains": query})
        return queryset.filter(search_filter)

    def apply_filters(self, queryset):
        return queryset

    def get_queryset(self):
        queryset = self.get_base_queryset()
        queryset = self.apply_search(queryset)
        queryset = self.apply_filters(queryset)
        ordering = self.get_ordering()
        if ordering:
            queryset = queryset.order_by(*ordering)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_query"] = self.get_search_query()
        context["current_order_by"] = self.request.GET.get("order_by", "").strip()
        context["ordering_options"] = [
            {"value": value, "label": _ordering_label(value)}
            for value in self.ordering_map.keys()
        ]
        page_query = self.request.GET.copy()
        page_query.pop("page", None)
        context["page_query"] = page_query.urlencode()
        return context


class RunListView(BrowserListView):
    model = PipelineRun
    template_name = "browser/run_list.html"
    context_object_name = "runs"
    search_fields = ("run_id", "status", "profile", "git_revision")
    ordering_map = {
        "run_id": ("run_id",),
        "-run_id": ("-run_id",),
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

    def get_queryset(self):
        queryset = super().get_queryset()
        return _annotated_runs(queryset)

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
        method_values = set(pipeline_run.run_parameters.values_list("method", flat=True))
        method_values.update(pipeline_run.accession_call_count_rows.values_list("method", flat=True))
        method_values.update(pipeline_run.repeat_calls.values_list("method", flat=True))
        residue_values = {
            residue
            for residue in pipeline_run.run_parameters.values_list("repeat_residue", flat=True)
            if residue
        }
        residue_values.update(
            residue
            for residue in pipeline_run.accession_call_count_rows.values_list("repeat_residue", flat=True)
            if residue
        )
        residue_values.update(
            residue
            for residue in pipeline_run.repeat_calls.values_list("repeat_residue", flat=True)
            if residue
        )
        context["methods"] = sorted(method_values)
        context["repeat_residues"] = sorted(residue_values)
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
        context["active_import_progress_items"] = _mapping_items(
            active_import_batch.progress_payload if active_import_batch else {},
            exclude_keys={"message"},
        )
        context["latest_import_batch"] = latest_import_batch
        context["latest_completed_import_batch"] = latest_completed_import_batch
        context["latest_import_row_count_items"] = _mapping_items(
            latest_completed_import_batch.row_counts if latest_completed_import_batch else {}
        )
        context["recent_import_batches"] = list(import_batches.order_by("-started_at", "-pk")[:5])
        context["imports_history_url"] = reverse("imports:history")
        return context


class NormalizationWarningListView(BrowserListView):
    model = NormalizationWarning
    template_name = "browser/normalizationwarning_list.html"
    context_object_name = "warnings"
    search_fields = (
        "warning_code",
        "warning_message",
        "assembly_accession",
        "genome_id",
        "sequence_id",
        "protein_id",
        "source_record_id",
    )
    ordering_map = {
        "warning_code": ("warning_code", "pipeline_run__run_id", "batch__batch_id", "assembly_accession"),
        "-warning_code": ("-warning_code", "pipeline_run__run_id", "batch__batch_id", "assembly_accession"),
        "warning_scope": ("warning_scope", "warning_code", "pipeline_run__run_id", "batch__batch_id"),
        "-warning_scope": ("-warning_scope", "warning_code", "pipeline_run__run_id", "batch__batch_id"),
        "accession": ("assembly_accession", "warning_code", "pipeline_run__run_id", "batch__batch_id"),
        "-accession": ("-assembly_accession", "warning_code", "pipeline_run__run_id", "batch__batch_id"),
        "batch": ("batch__batch_id", "warning_code", "assembly_accession"),
        "-batch": ("-batch__batch_id", "warning_code", "assembly_accession"),
        "run": ("pipeline_run__run_id", "batch__batch_id", "warning_code", "assembly_accession"),
        "-run": ("-pipeline_run__run_id", "batch__batch_id", "warning_code", "assembly_accession"),
    }
    default_ordering = ("pipeline_run__run_id", "batch__batch_id", "warning_code", "assembly_accession")

    def get_base_queryset(self):
        return NormalizationWarning.objects.select_related("pipeline_run", "batch")

    def _load_filter_state(self):
        self.current_run = _resolve_current_run(self.request)
        self.current_batch = self.request.GET.get("batch", "").strip()
        self.current_accession = self.request.GET.get("accession", "").strip()
        self.current_warning_code = self.request.GET.get("warning_code", "").strip()
        self.current_warning_scope = self.request.GET.get("warning_scope", "").strip()

    def apply_filters(self, queryset):
        self._load_filter_state()

        if self.current_run:
            queryset = queryset.filter(pipeline_run=self.current_run)

        if self.current_batch:
            queryset = queryset.filter(batch__pk=self.current_batch)

        if self.current_accession:
            queryset = queryset.filter(assembly_accession__icontains=self.current_accession)

        if self.current_warning_code:
            queryset = queryset.filter(warning_code=self.current_warning_code)

        if self.current_warning_scope:
            queryset = queryset.filter(warning_scope=self.current_warning_scope)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_run = getattr(self, "current_run", None)
        current_batch = getattr(self, "current_batch", "")

        filter_choices = NormalizationWarning.objects.all()
        batch_choices = AcquisitionBatch.objects.select_related("pipeline_run")
        if current_run:
            filter_choices = filter_choices.filter(pipeline_run=current_run)
            batch_choices = batch_choices.filter(pipeline_run=current_run)
        if current_batch:
            filter_choices = filter_choices.filter(batch__pk=current_batch)

        context["current_run"] = current_run
        context["current_run_id"] = current_run.run_id if current_run else ""
        context["selected_batch"] = _resolve_batch_filter(current_run, current_batch)
        context["current_batch"] = current_batch
        context["current_accession"] = getattr(self, "current_accession", "")
        context["current_warning_code"] = getattr(self, "current_warning_code", "")
        context["current_warning_scope"] = getattr(self, "current_warning_scope", "")
        context["run_choices"] = PipelineRun.objects.order_by("-imported_at", "run_id")
        context["batch_choices"] = batch_choices.order_by("pipeline_run__run_id", "batch_id")
        context["warning_code_choices"] = filter_choices.order_by("warning_code").values_list(
            "warning_code",
            flat=True,
        ).distinct()
        context["warning_scope_choices"] = (
            filter_choices.exclude(warning_scope="")
            .order_by("warning_scope")
            .values_list("warning_scope", flat=True)
            .distinct()
        )
        return context


class AccessionStatusListView(BrowserListView):
    model = AccessionStatus
    template_name = "browser/accessionstatus_list.html"
    context_object_name = "status_rows"
    search_fields = ("assembly_accession", "failure_stage", "failure_reason", "notes")
    ordering_map = {
        "accession": ("assembly_accession", "pipeline_run__run_id", "batch__batch_id"),
        "-accession": ("-assembly_accession", "pipeline_run__run_id", "batch__batch_id"),
        "batch": ("batch__batch_id", "assembly_accession"),
        "-batch": ("-batch__batch_id", "assembly_accession"),
        "run": ("pipeline_run__run_id", "batch__batch_id", "assembly_accession"),
        "-run": ("-pipeline_run__run_id", "batch__batch_id", "assembly_accession"),
        "terminal_status": ("terminal_status", "assembly_accession"),
        "-terminal_status": ("-terminal_status", "assembly_accession"),
        "repeat_calls": ("-n_repeat_calls", "assembly_accession"),
        "-repeat_calls": ("n_repeat_calls", "assembly_accession"),
    }
    default_ordering = ("pipeline_run__run_id", "batch__batch_id", "assembly_accession")

    def get_base_queryset(self):
        return AccessionStatus.objects.select_related("pipeline_run", "batch")

    def _load_filter_state(self):
        self.current_run = _resolve_current_run(self.request)
        self.current_batch = self.request.GET.get("batch", "").strip()
        self.current_accession = self.request.GET.get("accession", "").strip()
        self.current_terminal_status = self.request.GET.get("terminal_status", "").strip()
        self.current_detect_status = self.request.GET.get("detect_status", "").strip()
        self.current_finalize_status = self.request.GET.get("finalize_status", "").strip()

    def apply_filters(self, queryset):
        self._load_filter_state()

        if self.current_run:
            queryset = queryset.filter(pipeline_run=self.current_run)

        if self.current_batch:
            queryset = queryset.filter(batch__pk=self.current_batch)

        if self.current_accession:
            queryset = queryset.filter(assembly_accession__icontains=self.current_accession)

        if self.current_terminal_status:
            queryset = queryset.filter(terminal_status=self.current_terminal_status)

        if self.current_detect_status:
            queryset = queryset.filter(detect_status=self.current_detect_status)

        if self.current_finalize_status:
            queryset = queryset.filter(finalize_status=self.current_finalize_status)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_run = getattr(self, "current_run", None)
        current_batch = getattr(self, "current_batch", "")

        filter_choices = AccessionStatus.objects.all()
        batch_choices = AcquisitionBatch.objects.select_related("pipeline_run")
        if current_run:
            filter_choices = filter_choices.filter(pipeline_run=current_run)
            batch_choices = batch_choices.filter(pipeline_run=current_run)
        if current_batch:
            filter_choices = filter_choices.filter(batch__pk=current_batch)

        context["current_run"] = current_run
        context["current_run_id"] = current_run.run_id if current_run else ""
        context["selected_batch"] = _resolve_batch_filter(current_run, current_batch)
        context["current_batch"] = current_batch
        context["current_accession"] = getattr(self, "current_accession", "")
        context["current_terminal_status"] = getattr(self, "current_terminal_status", "")
        context["current_detect_status"] = getattr(self, "current_detect_status", "")
        context["current_finalize_status"] = getattr(self, "current_finalize_status", "")
        context["run_choices"] = PipelineRun.objects.order_by("-imported_at", "run_id")
        context["batch_choices"] = batch_choices.order_by("pipeline_run__run_id", "batch_id")
        context["terminal_status_choices"] = (
            filter_choices.exclude(terminal_status="")
            .order_by("terminal_status")
            .values_list("terminal_status", flat=True)
            .distinct()
        )
        context["detect_status_choices"] = (
            filter_choices.exclude(detect_status="")
            .order_by("detect_status")
            .values_list("detect_status", flat=True)
            .distinct()
        )
        context["finalize_status_choices"] = (
            filter_choices.exclude(finalize_status="")
            .order_by("finalize_status")
            .values_list("finalize_status", flat=True)
            .distinct()
        )
        return context


class AccessionCallCountListView(BrowserListView):
    model = AccessionCallCount
    template_name = "browser/accessioncallcount_list.html"
    context_object_name = "call_count_rows"
    search_fields = ("assembly_accession",)
    ordering_map = {
        "accession": ("assembly_accession", "method", "repeat_residue"),
        "-accession": ("-assembly_accession", "method", "repeat_residue"),
        "batch": ("batch__batch_id", "assembly_accession", "method", "repeat_residue"),
        "-batch": ("-batch__batch_id", "assembly_accession", "method", "repeat_residue"),
        "run": ("pipeline_run__run_id", "batch__batch_id", "assembly_accession"),
        "-run": ("-pipeline_run__run_id", "batch__batch_id", "assembly_accession"),
        "method": ("method", "repeat_residue", "assembly_accession"),
        "-method": ("-method", "repeat_residue", "assembly_accession"),
        "residue": ("repeat_residue", "method", "assembly_accession"),
        "-residue": ("-repeat_residue", "method", "assembly_accession"),
        "repeat_calls": ("-n_repeat_calls", "assembly_accession", "method", "repeat_residue"),
        "-repeat_calls": ("n_repeat_calls", "assembly_accession", "method", "repeat_residue"),
    }
    default_ordering = ("pipeline_run__run_id", "batch__batch_id", "assembly_accession", "method", "repeat_residue")

    def get_base_queryset(self):
        return AccessionCallCount.objects.select_related("pipeline_run", "batch")

    def _load_filter_state(self):
        self.current_run = _resolve_current_run(self.request)
        self.current_batch = self.request.GET.get("batch", "").strip()
        self.current_accession = self.request.GET.get("accession", "").strip()
        self.current_method = self.request.GET.get("method", "").strip()
        self.current_residue = self.request.GET.get("residue", "").strip().upper()
        self.current_detect_status = self.request.GET.get("detect_status", "").strip()
        self.current_finalize_status = self.request.GET.get("finalize_status", "").strip()

    def apply_filters(self, queryset):
        self._load_filter_state()

        if self.current_run:
            queryset = queryset.filter(pipeline_run=self.current_run)

        if self.current_batch:
            queryset = queryset.filter(batch__pk=self.current_batch)

        if self.current_accession:
            queryset = queryset.filter(assembly_accession__icontains=self.current_accession)

        if self.current_method:
            queryset = queryset.filter(method=self.current_method)

        if self.current_residue:
            queryset = queryset.filter(repeat_residue=self.current_residue)

        if self.current_detect_status:
            queryset = queryset.filter(detect_status=self.current_detect_status)

        if self.current_finalize_status:
            queryset = queryset.filter(finalize_status=self.current_finalize_status)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_run = getattr(self, "current_run", None)
        current_batch = getattr(self, "current_batch", "")

        filter_choices = AccessionCallCount.objects.all()
        batch_choices = AcquisitionBatch.objects.select_related("pipeline_run")
        if current_run:
            filter_choices = filter_choices.filter(pipeline_run=current_run)
            batch_choices = batch_choices.filter(pipeline_run=current_run)
        if current_batch:
            filter_choices = filter_choices.filter(batch__pk=current_batch)

        context["current_run"] = current_run
        context["current_run_id"] = current_run.run_id if current_run else ""
        context["selected_batch"] = _resolve_batch_filter(current_run, current_batch)
        context["current_batch"] = current_batch
        context["current_accession"] = getattr(self, "current_accession", "")
        context["current_method"] = getattr(self, "current_method", "")
        context["current_residue"] = getattr(self, "current_residue", "")
        context["current_detect_status"] = getattr(self, "current_detect_status", "")
        context["current_finalize_status"] = getattr(self, "current_finalize_status", "")
        context["run_choices"] = PipelineRun.objects.order_by("-imported_at", "run_id")
        context["batch_choices"] = batch_choices.order_by("pipeline_run__run_id", "batch_id")
        context["method_choices"] = filter_choices.order_by("method").values_list("method", flat=True).distinct()
        context["residue_choices"] = (
            filter_choices.exclude(repeat_residue="")
            .order_by("repeat_residue")
            .values_list("repeat_residue", flat=True)
            .distinct()
        )
        context["detect_status_choices"] = (
            filter_choices.exclude(detect_status="")
            .order_by("detect_status")
            .values_list("detect_status", flat=True)
            .distinct()
        )
        context["finalize_status_choices"] = (
            filter_choices.exclude(finalize_status="")
            .order_by("finalize_status")
            .values_list("finalize_status", flat=True)
            .distinct()
        )
        return context


class DownloadManifestEntryListView(BrowserListView):
    model = DownloadManifestEntry
    template_name = "browser/downloadmanifest_list.html"
    context_object_name = "download_entries"
    search_fields = (
        "assembly_accession",
        "download_path",
        "rehydrated_path",
        "checksum",
        "notes",
    )
    ordering_map = {
        "accession": ("assembly_accession", "pipeline_run__run_id", "batch__batch_id"),
        "-accession": ("-assembly_accession", "pipeline_run__run_id", "batch__batch_id"),
        "batch": ("batch__batch_id", "assembly_accession"),
        "-batch": ("-batch__batch_id", "assembly_accession"),
        "run": ("pipeline_run__run_id", "batch__batch_id", "assembly_accession"),
        "-run": ("-pipeline_run__run_id", "batch__batch_id", "assembly_accession"),
        "download_status": ("download_status", "assembly_accession"),
        "-download_status": ("-download_status", "assembly_accession"),
        "package_mode": ("package_mode", "assembly_accession"),
        "-package_mode": ("-package_mode", "assembly_accession"),
        "file_size_bytes": ("file_size_bytes", "assembly_accession"),
        "-file_size_bytes": ("-file_size_bytes", "assembly_accession"),
    }
    default_ordering = ("pipeline_run__run_id", "batch__batch_id", "assembly_accession")

    def get_base_queryset(self):
        return DownloadManifestEntry.objects.select_related("pipeline_run", "batch")

    def _load_filter_state(self):
        self.current_run = _resolve_current_run(self.request)
        self.current_batch = self.request.GET.get("batch", "").strip()
        self.current_accession = self.request.GET.get("accession", "").strip()
        self.current_download_status = self.request.GET.get("download_status", "").strip()
        self.current_package_mode = self.request.GET.get("package_mode", "").strip()

    def apply_filters(self, queryset):
        self._load_filter_state()

        if self.current_run:
            queryset = queryset.filter(pipeline_run=self.current_run)

        if self.current_batch:
            queryset = queryset.filter(batch__pk=self.current_batch)

        if self.current_accession:
            queryset = queryset.filter(assembly_accession__icontains=self.current_accession)

        if self.current_download_status:
            queryset = queryset.filter(download_status=self.current_download_status)

        if self.current_package_mode:
            queryset = queryset.filter(package_mode=self.current_package_mode)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_run = getattr(self, "current_run", None)
        current_batch = getattr(self, "current_batch", "")

        filter_choices = DownloadManifestEntry.objects.all()
        batch_choices = AcquisitionBatch.objects.select_related("pipeline_run")
        if current_run:
            filter_choices = filter_choices.filter(pipeline_run=current_run)
            batch_choices = batch_choices.filter(pipeline_run=current_run)
        if current_batch:
            filter_choices = filter_choices.filter(batch__pk=current_batch)

        context["current_run"] = current_run
        context["current_run_id"] = current_run.run_id if current_run else ""
        context["selected_batch"] = _resolve_batch_filter(current_run, current_batch)
        context["current_batch"] = current_batch
        context["current_accession"] = getattr(self, "current_accession", "")
        context["current_download_status"] = getattr(self, "current_download_status", "")
        context["current_package_mode"] = getattr(self, "current_package_mode", "")
        context["run_choices"] = PipelineRun.objects.order_by("-imported_at", "run_id")
        context["batch_choices"] = batch_choices.order_by("pipeline_run__run_id", "batch_id")
        context["download_status_choices"] = (
            filter_choices.exclude(download_status="")
            .order_by("download_status")
            .values_list("download_status", flat=True)
            .distinct()
        )
        context["package_mode_choices"] = (
            filter_choices.exclude(package_mode="")
            .order_by("package_mode")
            .values_list("package_mode", flat=True)
            .distinct()
        )
        return context


class TaxonListView(BrowserListView):
    model = Taxon
    template_name = "browser/taxon_list.html"
    context_object_name = "taxa"
    search_fields = ("taxon_name",)
    ordering_map = {
        "taxon_name": ("taxon_name", "taxon_id"),
        "-taxon_name": ("-taxon_name", "taxon_id"),
        "taxon_id": ("taxon_id",),
        "-taxon_id": ("-taxon_id",),
        "rank": ("rank", "taxon_name"),
        "-rank": ("-rank", "taxon_name"),
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
        self.selected_branch_taxon = _resolve_branch_taxon(self.request)
        self.current_rank = self.request.GET.get("rank", "").strip()
        self.current_mode = _resolve_browser_mode(self.request)

        if self.current_run:
            queryset = queryset.filter(pk__in=_run_taxon_ids(self.current_run))

        if self.selected_branch_taxon:
            queryset = queryset.filter(pk__in=_branch_taxon_ids(self.selected_branch_taxon))

        if self.current_rank:
            queryset = queryset.filter(rank=self.current_rank)

        return queryset.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_run = getattr(self, "current_run", None)
        selected_branch_taxon = getattr(self, "selected_branch_taxon", None)
        context["current_run"] = current_run
        context["current_run_id"] = current_run.run_id if current_run else ""
        context["current_mode"] = getattr(self, "current_mode", "run")
        context["run_choices"] = PipelineRun.objects.order_by("-imported_at", "run_id")
        context["current_rank"] = getattr(self, "current_rank", "")
        context["rank_choices"] = (
            Taxon.objects.exclude(rank="")
            .order_by("rank")
            .values_list("rank", flat=True)
            .distinct()
        )
        branch_choices = Taxon.objects.order_by("taxon_name")
        if current_run:
            branch_choices = branch_choices.filter(pk__in=_run_taxon_ids(current_run))
        context["branch_choices"] = branch_choices.distinct()
        context["current_branch"] = self.request.GET.get("branch", "").strip()
        context["selected_branch_taxon"] = selected_branch_taxon
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
        current_mode = _resolve_browser_mode(self.request)
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
        context["current_mode"] = current_mode
        context["lineage"] = (
            TaxonClosure.objects.filter(descendant=taxon)
            .select_related("ancestor")
            .order_by("-depth", "ancestor__taxon_name")
        )
        context["descendant_count"] = TaxonClosure.objects.filter(ancestor=taxon, depth__gt=0).count()
        context["child_taxa"] = taxon.children.order_by("taxon_name")[:12]
        if current_mode == "merged":
            linked_accessions = list(
                accession_group_queryset(current_run=current_run, branch_taxon=taxon).order_by("accession")[:10]
            )
            context["branch_genomes_count"] = accession_group_queryset(
                current_run=current_run,
                branch_taxon=taxon,
            ).count()
            context["branch_proteins_count"] = len(
                merged_protein_groups(current_run=current_run, branch_taxon=taxon)
            )
            context["branch_repeat_calls_count"] = len(
                merged_repeat_call_groups(current_run=current_run, branch_taxon=taxon)
            )
            context["linked_accessions"] = linked_accessions
        else:
            context["branch_genomes_count"] = branch_genomes.count()
            context["branch_proteins_count"] = branch_proteins.count()
            context["branch_repeat_calls_count"] = branch_repeat_calls.count()
            context["linked_genomes"] = branch_genomes.order_by("accession", "pipeline_run__run_id")[:10]
        context["genome_branch_url"] = _url_with_query(
            reverse("browser:genome-list"),
            run=current_run.run_id if current_run else None,
            branch=taxon.pk,
            mode=current_mode,
        )
        context["protein_branch_url"] = _url_with_query(
            reverse("browser:protein-list"),
            run=current_run.run_id if current_run else None,
            branch=taxon.pk,
            mode=current_mode,
        )
        context["repeatcall_branch_url"] = _url_with_query(
            reverse("browser:repeatcall-list"),
            run=current_run.run_id if current_run else None,
            branch=taxon.pk,
            mode=current_mode,
        )
        return context


class GenomeListView(BrowserListView):
    model = Genome
    template_name = "browser/genome_list.html"
    context_object_name = "genomes"
    ordering_map = {
        "accession": ("accession", "pipeline_run__run_id"),
        "-accession": ("-accession", "pipeline_run__run_id"),
        "genome_name": ("genome_name", "accession"),
        "-genome_name": ("-genome_name", "accession"),
        "run": ("pipeline_run__run_id", "accession"),
        "-run": ("-pipeline_run__run_id", "accession"),
        "proteins": ("-proteins_count", "accession"),
        "-proteins": ("proteins_count", "accession"),
    }
    default_ordering = ("accession", "pipeline_run__run_id")

    def get_base_queryset(self):
        return _annotated_genomes(Genome.objects.select_related("pipeline_run", "taxon"))

    def _load_filter_state(self):
        self.current_run = _resolve_current_run(self.request)
        self.selected_branch_taxon = _resolve_branch_taxon(self.request)
        self.current_accession = self.request.GET.get("accession", "").strip()
        self.current_genome_name = self.request.GET.get("genome_name", "").strip()
        self.current_mode = _resolve_browser_mode(self.request)

    def apply_filters(self, queryset):
        self._load_filter_state()

        if self.current_run:
            queryset = queryset.filter(pipeline_run=self.current_run)

        if self.selected_branch_taxon:
            queryset = queryset.filter(taxon_id__in=_branch_taxon_ids(self.selected_branch_taxon))

        if self.current_accession:
            queryset = queryset.filter(accession__icontains=self.current_accession)

        if self.current_genome_name:
            queryset = queryset.filter(genome_name__icontains=self.current_genome_name)

        return queryset

    def get_queryset(self):
        self._load_filter_state()
        if self.current_mode == "merged":
            queryset = accession_group_queryset(
                current_run=self.current_run,
                accession_query=self.current_accession,
                genome_name=self.current_genome_name,
                branch_taxon=self.selected_branch_taxon,
            )
            ordering = self.get_ordering()
            if ordering:
                queryset = queryset.order_by(*ordering)
            return queryset
        return super().get_queryset()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_run = getattr(self, "current_run", None)
        selected_branch_taxon = getattr(self, "selected_branch_taxon", None)
        branch_choices = Taxon.objects.filter(genomes__isnull=False)
        if current_run:
            branch_choices = branch_choices.filter(genomes__pipeline_run=current_run)

        context["current_run"] = current_run
        context["current_run_id"] = current_run.run_id if current_run else ""
        context["current_mode"] = getattr(self, "current_mode", "run")
        context["run_choices"] = PipelineRun.objects.order_by("-imported_at", "run_id")
        context["branch_choices"] = branch_choices.distinct().order_by("taxon_name")
        context["current_branch"] = self.request.GET.get("branch", "").strip()
        context["selected_branch_taxon"] = selected_branch_taxon
        context["current_accession"] = getattr(self, "current_accession", "")
        context["current_genome_name"] = getattr(self, "current_genome_name", "")
        return context


class GenomeDetailView(DetailView):
    model = Genome
    template_name = "browser/genome_detail.html"
    context_object_name = "genome"

    def get_queryset(self):
        return Genome.objects.select_related("pipeline_run", "taxon")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        genome = self.object
        proteins = genome.proteins.order_by("protein_name", "protein_id")
        repeat_calls = genome.repeat_calls.select_related("protein").order_by("protein__protein_name", "start", "call_id")

        context["lineage"] = (
            TaxonClosure.objects.filter(descendant=genome.taxon)
            .select_related("ancestor")
            .order_by("-depth", "ancestor__taxon_name")
        )
        context["sequences_count"] = genome.sequences.count()
        context["proteins_count"] = proteins.count()
        context["repeat_calls_count"] = repeat_calls.count()
        context["protein_preview"] = proteins[:10]
        context["repeat_call_preview"] = repeat_calls[:10]
        context["taxon_detail_url"] = _url_with_query(
            reverse("browser:taxon-detail", args=[genome.taxon.pk]),
            run=genome.pipeline_run.run_id,
        )
        context["protein_browser_url"] = _url_with_query(
            reverse("browser:protein-list"),
            run=genome.pipeline_run.run_id,
            genome=genome.genome_id,
        )
        context["repeatcall_browser_url"] = _url_with_query(
            reverse("browser:repeatcall-list"),
            run=genome.pipeline_run.run_id,
            genome=genome.genome_id,
        )
        context["merged_accession_url"] = reverse("browser:accession-detail", args=[genome.accession])
        context["related_accession_genomes_count"] = Genome.objects.filter(accession=genome.accession).count()
        return context


class AccessionsListView(ListView):
    template_name = "browser/accession_list.html"
    context_object_name = "accession_groups"
    paginate_by = 20
    ordering_map = {
        "accession": ("accession",),
        "-accession": ("-accession",),
        "runs": ("-source_runs_count", "accession"),
        "-runs": ("source_runs_count", "accession"),
        "genomes": ("-source_genomes_count", "accession"),
        "-genomes": ("source_genomes_count", "accession"),
        "calls": ("-raw_repeat_calls_count", "accession"),
        "-calls": ("raw_repeat_calls_count", "accession"),
    }
    default_ordering = ("accession",)

    def get_search_query(self):
        return self.request.GET.get("q", "").strip()

    def _load_filter_state(self):
        self.current_run = _resolve_current_run(self.request)
        self.selected_branch_taxon = _resolve_branch_taxon(self.request)

    def get_ordering(self):
        requested_ordering = self.request.GET.get("order_by", "").strip()
        if requested_ordering in self.ordering_map:
            return self.ordering_map[requested_ordering]
        return self.default_ordering

    def get_queryset(self):
        self._load_filter_state()
        queryset = accession_group_queryset(
            current_run=self.current_run,
            search_query=self.get_search_query(),
            branch_taxon=self.selected_branch_taxon,
        )
        ordering = self.get_ordering()
        if ordering:
            queryset = queryset.order_by(*ordering)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        summary = build_accession_analytics(
            current_run=getattr(self, "current_run", None),
            search_query=self.get_search_query(),
            branch_taxon=getattr(self, "selected_branch_taxon", None),
        )
        for accession_group in context["accession_groups"]:
            accession_group.update(summary["accession_metrics"][accession_group["accession"]])

        current_run = getattr(self, "current_run", None)
        context["summary"] = summary
        context["current_query"] = self.get_search_query()
        context["current_run"] = current_run
        context["current_run_id"] = current_run.run_id if current_run else ""
        context["run_choices"] = PipelineRun.objects.order_by("-imported_at", "run_id")
        context["current_order_by"] = self.request.GET.get("order_by", "").strip()
        context["ordering_options"] = [
            {"value": value, "label": _ordering_label(value)}
            for value in self.ordering_map.keys()
        ]
        branch_choices = Taxon.objects.filter(genomes__isnull=False)
        if current_run:
            branch_choices = branch_choices.filter(genomes__pipeline_run=current_run)
        context["branch_choices"] = branch_choices.distinct().order_by("taxon_name")
        context["current_branch"] = self.request.GET.get("branch", "").strip()
        context["selected_branch_taxon"] = getattr(self, "selected_branch_taxon", None)
        page_query = self.request.GET.copy()
        page_query.pop("page", None)
        context["page_query"] = page_query.urlencode()
        return context


class AccessionDetailView(TemplateView):
    template_name = "browser/accession_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        accession = kwargs["accession"]

        try:
            summary = build_accession_summary(accession)
        except Genome.DoesNotExist as exc:
            raise Http404(str(exc)) from exc

        context.update(summary)
        context["genome_list_url"] = _url_with_query(reverse("browser:genome-list"), accession=accession)
        context["accession_list_url"] = reverse("browser:accession-list")
        return context


class ProteinListView(BrowserListView):
    model = Protein
    template_name = "browser/protein_list.html"
    context_object_name = "proteins"
    search_fields = ("protein_name", "protein_id", "gene_symbol")
    ordering_map = {
        "protein_name": ("protein_name", "protein_id"),
        "-protein_name": ("-protein_name", "protein_id"),
        "gene_symbol": ("gene_symbol", "protein_name"),
        "-gene_symbol": ("-gene_symbol", "protein_name"),
        "protein_length": ("protein_length", "protein_name"),
        "-protein_length": ("-protein_length", "protein_name"),
        "run": ("pipeline_run__run_id", "protein_name"),
        "-run": ("-pipeline_run__run_id", "protein_name"),
        "calls": ("-repeat_calls_count", "protein_name"),
        "-calls": ("repeat_calls_count", "protein_name"),
    }
    default_ordering = ("protein_name", "protein_id")

    def get_base_queryset(self):
        return _annotated_proteins(
            Protein.objects.select_related("pipeline_run", "genome", "taxon").defer("amino_acid_sequence")
        )

    def _load_filter_state(self):
        self.current_run = _resolve_current_run(self.request)
        self.selected_branch_taxon = _resolve_branch_taxon(self.request)
        self.current_gene_symbol = self.request.GET.get("gene_symbol", "").strip()
        self.current_method = self.request.GET.get("method", "").strip()
        self.current_residue = self.request.GET.get("residue", "").strip().upper()
        self.current_length_min = self.request.GET.get("length_min", "").strip()
        self.current_length_max = self.request.GET.get("length_max", "").strip()
        self.current_purity_min = self.request.GET.get("purity_min", "").strip()
        self.current_purity_max = self.request.GET.get("purity_max", "").strip()
        self.current_genome = self.request.GET.get("genome", "").strip()
        self.current_mode = _resolve_browser_mode(self.request)

    def apply_filters(self, queryset):
        self._load_filter_state()

        if self.current_run:
            queryset = queryset.filter(pipeline_run=self.current_run)

        if self.selected_branch_taxon:
            queryset = queryset.filter(taxon_id__in=_branch_taxon_ids(self.selected_branch_taxon))

        if self.current_gene_symbol:
            queryset = queryset.filter(gene_symbol__icontains=self.current_gene_symbol)

        if self.current_genome:
            queryset = queryset.filter(genome__genome_id=self.current_genome)

        call_filters = _repeat_call_filter_q(
            method=self.current_method,
            residue=self.current_residue,
            length_min=self.current_length_min,
            length_max=self.current_length_max,
            purity_min=self.current_purity_min,
            purity_max=self.current_purity_max,
        )
        if call_filters is not None:
            matching_calls = RepeatCall.objects.filter(protein=OuterRef("pk")).filter(call_filters)
            queryset = queryset.annotate(has_matching_call=Exists(matching_calls)).filter(has_matching_call=True)

        return queryset.distinct()

    def get_queryset(self):
        self._load_filter_state()
        if self.current_mode == "merged":
            records = merged_protein_groups(
                current_run=self.current_run,
                branch_taxon=self.selected_branch_taxon,
                search_query=self.get_search_query(),
                gene_symbol=self.current_gene_symbol,
                genome_id=self.current_genome,
                method=self.current_method,
                residue=self.current_residue,
                length_min=self.current_length_min,
                length_max=self.current_length_max,
                purity_min=self.current_purity_min,
                purity_max=self.current_purity_max,
            )
            return _sort_dict_records(
                records,
                requested_ordering=self.request.GET.get("order_by", "").strip(),
                default_ordering="protein_name",
                key_map={
                    "protein_name": lambda record: (record["protein_name"], record["accession"]),
                    "gene_symbol": lambda record: (record["gene_symbol_label"], record["protein_name"], record["accession"]),
                    "protein_length": lambda record: (record["protein_length"], record["protein_name"], record["accession"]),
                    "run": lambda record: (record["source_runs_count"], record["protein_name"], record["accession"]),
                    "calls": lambda record: (
                        record["collapsed_repeat_calls_count"],
                        record["protein_name"],
                        record["accession"],
                    ),
                },
            )
        return super().get_queryset()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_run = getattr(self, "current_run", None)
        selected_branch_taxon = getattr(self, "selected_branch_taxon", None)
        branch_choices = Taxon.objects.filter(proteins__isnull=False)
        if current_run:
            branch_choices = branch_choices.filter(proteins__pipeline_run=current_run)

        scoped_repeat_calls = _scoped_repeat_calls(
            current_run=current_run,
            selected_branch_taxon=selected_branch_taxon,
            genome_id=getattr(self, "current_genome", ""),
        )

        context["current_run"] = current_run
        context["current_run_id"] = current_run.run_id if current_run else ""
        context["current_mode"] = getattr(self, "current_mode", "run")
        context["run_choices"] = PipelineRun.objects.order_by("-imported_at", "run_id")
        context["branch_choices"] = branch_choices.distinct().order_by("taxon_name")
        context["current_branch"] = self.request.GET.get("branch", "").strip()
        context["selected_branch_taxon"] = selected_branch_taxon
        context["current_gene_symbol"] = getattr(self, "current_gene_symbol", "")
        context["current_method"] = getattr(self, "current_method", "")
        context["current_residue"] = getattr(self, "current_residue", "")
        context["current_length_min"] = getattr(self, "current_length_min", "")
        context["current_length_max"] = getattr(self, "current_length_max", "")
        context["current_purity_min"] = getattr(self, "current_purity_min", "")
        context["current_purity_max"] = getattr(self, "current_purity_max", "")
        context["current_genome"] = getattr(self, "current_genome", "")
        context["selected_genome"] = _resolve_genome_filter(current_run, context["current_genome"])
        context["method_choices"] = scoped_repeat_calls.order_by("method").values_list("method", flat=True).distinct()
        context["residue_choices"] = (
            scoped_repeat_calls.exclude(repeat_residue="")
            .order_by("repeat_residue")
            .values_list("repeat_residue", flat=True)
            .distinct()
        )
        return context


class ProteinDetailView(DetailView):
    model = Protein
    template_name = "browser/protein_detail.html"
    context_object_name = "protein"

    def get_queryset(self):
        return Protein.objects.select_related("pipeline_run", "genome", "sequence", "taxon")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        protein = self.object
        repeat_calls = protein.repeat_calls.select_related("taxon").order_by("method", "repeat_residue", "start", "call_id")

        context["repeat_calls_count"] = repeat_calls.count()
        context["call_summaries"] = (
            repeat_calls.values("method", "repeat_residue")
            .annotate(
                total=Count("pk"),
                min_length=Min("length"),
                max_length=Max("length"),
            )
            .order_by("method", "repeat_residue")
        )
        context["repeat_call_preview"] = repeat_calls[:12]
        context["taxon_detail_url"] = _url_with_query(
            reverse("browser:taxon-detail", args=[protein.taxon.pk]),
            run=protein.pipeline_run.run_id,
        )
        context["repeatcall_browser_url"] = _url_with_query(
            reverse("browser:repeatcall-list"),
            run=protein.pipeline_run.run_id,
            protein=protein.protein_id,
        )
        context["protein_list_url"] = _url_with_query(
            reverse("browser:protein-list"),
            run=protein.pipeline_run.run_id,
            genome=protein.genome.genome_id,
        )
        return context


class RepeatCallListView(BrowserListView):
    model = RepeatCall
    template_name = "browser/repeatcall_list.html"
    context_object_name = "repeat_calls"
    search_fields = (
        "call_id",
        "protein__protein_name",
        "protein__protein_id",
        "protein__gene_symbol",
        "genome__accession",
    )
    ordering_map = {
        "call_id": ("call_id",),
        "-call_id": ("-call_id",),
        "method": ("method", "call_id"),
        "-method": ("-method", "call_id"),
        "residue": ("repeat_residue", "call_id"),
        "-residue": ("-repeat_residue", "call_id"),
        "length": ("length", "call_id"),
        "-length": ("-length", "call_id"),
        "purity": ("purity", "call_id"),
        "-purity": ("-purity", "call_id"),
        "run": ("pipeline_run__run_id", "call_id"),
        "-run": ("-pipeline_run__run_id", "call_id"),
    }
    default_ordering = ("pipeline_run__run_id", "protein__protein_name", "start", "call_id")

    def get_base_queryset(self):
        return RepeatCall.objects.select_related("pipeline_run", "genome", "protein", "taxon").defer(
            "aa_sequence",
            "codon_sequence",
            "protein__amino_acid_sequence",
        )

    def _load_filter_state(self):
        self.current_run = _resolve_current_run(self.request)
        self.selected_branch_taxon = _resolve_branch_taxon(self.request)
        self.current_method = self.request.GET.get("method", "").strip()
        self.current_residue = self.request.GET.get("residue", "").strip().upper()
        self.current_gene_symbol = self.request.GET.get("gene_symbol", "").strip()
        self.current_length_min = self.request.GET.get("length_min", "").strip()
        self.current_length_max = self.request.GET.get("length_max", "").strip()
        self.current_purity_min = self.request.GET.get("purity_min", "").strip()
        self.current_purity_max = self.request.GET.get("purity_max", "").strip()
        self.current_genome = self.request.GET.get("genome", "").strip()
        self.current_protein = self.request.GET.get("protein", "").strip()
        self.current_mode = _resolve_browser_mode(self.request)

    def apply_filters(self, queryset):
        self._load_filter_state()

        if self.current_run:
            queryset = queryset.filter(pipeline_run=self.current_run)

        if self.selected_branch_taxon:
            queryset = queryset.filter(taxon_id__in=_branch_taxon_ids(self.selected_branch_taxon))

        if self.current_genome:
            queryset = queryset.filter(genome__genome_id=self.current_genome)

        if self.current_protein:
            queryset = queryset.filter(protein__protein_id=self.current_protein)

        if self.current_method:
            queryset = queryset.filter(method=self.current_method)

        if self.current_residue:
            queryset = queryset.filter(repeat_residue=self.current_residue)

        if self.current_gene_symbol:
            queryset = queryset.filter(
                Q(protein__gene_symbol__icontains=self.current_gene_symbol)
                | Q(sequence__gene_symbol__icontains=self.current_gene_symbol)
            )

        length_min = _parse_positive_int(self.current_length_min)
        if length_min is not None:
            queryset = queryset.filter(length__gte=length_min)

        length_max = _parse_positive_int(self.current_length_max)
        if length_max is not None:
            queryset = queryset.filter(length__lte=length_max)

        purity_min = _parse_float(self.current_purity_min)
        if purity_min is not None:
            queryset = queryset.filter(purity__gte=purity_min)

        purity_max = _parse_float(self.current_purity_max)
        if purity_max is not None:
            queryset = queryset.filter(purity__lte=purity_max)

        return queryset.distinct()

    def get_queryset(self):
        self._load_filter_state()
        if self.current_mode == "merged":
            records = merged_repeat_call_groups(
                current_run=self.current_run,
                branch_taxon=self.selected_branch_taxon,
                search_query=self.get_search_query(),
                gene_symbol=self.current_gene_symbol,
                genome_id=self.current_genome,
                protein_id=self.current_protein,
                method=self.current_method,
                residue=self.current_residue,
                length_min=self.current_length_min,
                length_max=self.current_length_max,
                purity_min=self.current_purity_min,
                purity_max=self.current_purity_max,
            )
            return _sort_dict_records(
                records,
                requested_ordering=self.request.GET.get("order_by", "").strip(),
                default_ordering="call_id",
                key_map={
                    "call_id": lambda record: (
                        record["accession"],
                        record["protein_name"],
                        record["start"],
                        record["end"],
                        record["method"],
                    ),
                    "method": lambda record: (
                        record["method"],
                        record["accession"],
                        record["protein_name"],
                        record["start"],
                    ),
                    "residue": lambda record: (
                        record["repeat_residue"],
                        record["accession"],
                        record["protein_name"],
                        record["start"],
                    ),
                    "length": lambda record: (
                        record["length"],
                        record["accession"],
                        record["protein_name"],
                        record["start"],
                    ),
                    "purity": lambda record: (
                        float(record["normalized_purity"]),
                        record["accession"],
                        record["protein_name"],
                        record["start"],
                    ),
                    "run": lambda record: (
                        record["source_runs_count"],
                        record["accession"],
                        record["protein_name"],
                        record["start"],
                    ),
                },
            )
        return super().get_queryset()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_run = getattr(self, "current_run", None)
        selected_branch_taxon = getattr(self, "selected_branch_taxon", None)
        branch_choices = Taxon.objects.filter(repeat_calls__isnull=False)
        if current_run:
            branch_choices = branch_choices.filter(repeat_calls__pipeline_run=current_run)

        scoped_repeat_calls = _scoped_repeat_calls(
            current_run=current_run,
            selected_branch_taxon=selected_branch_taxon,
            genome_id=getattr(self, "current_genome", ""),
            protein_id=getattr(self, "current_protein", ""),
        )

        context["current_run"] = current_run
        context["current_run_id"] = current_run.run_id if current_run else ""
        context["current_mode"] = getattr(self, "current_mode", "run")
        context["run_choices"] = PipelineRun.objects.order_by("-imported_at", "run_id")
        context["branch_choices"] = branch_choices.distinct().order_by("taxon_name")
        context["current_branch"] = self.request.GET.get("branch", "").strip()
        context["selected_branch_taxon"] = selected_branch_taxon
        context["current_method"] = getattr(self, "current_method", "")
        context["current_residue"] = getattr(self, "current_residue", "")
        context["current_gene_symbol"] = getattr(self, "current_gene_symbol", "")
        context["current_length_min"] = getattr(self, "current_length_min", "")
        context["current_length_max"] = getattr(self, "current_length_max", "")
        context["current_purity_min"] = getattr(self, "current_purity_min", "")
        context["current_purity_max"] = getattr(self, "current_purity_max", "")
        context["current_genome"] = getattr(self, "current_genome", "")
        context["current_protein"] = getattr(self, "current_protein", "")
        context["selected_genome"] = _resolve_genome_filter(current_run, context["current_genome"])
        context["selected_protein"] = _resolve_protein_filter(current_run, context["current_protein"])
        context["method_choices"] = scoped_repeat_calls.order_by("method").values_list("method", flat=True).distinct()
        context["residue_choices"] = (
            scoped_repeat_calls.exclude(repeat_residue="")
            .order_by("repeat_residue")
            .values_list("repeat_residue", flat=True)
            .distinct()
        )
        return context


class RepeatCallDetailView(DetailView):
    model = RepeatCall
    template_name = "browser/repeatcall_detail.html"
    context_object_name = "repeat_call"

    def get_queryset(self):
        return RepeatCall.objects.select_related("pipeline_run", "genome", "sequence", "protein", "taxon")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        repeat_call = self.object
        context["taxon_detail_url"] = _url_with_query(
            reverse("browser:taxon-detail", args=[repeat_call.taxon.pk]),
            run=repeat_call.pipeline_run.run_id,
        )
        context["repeatcall_list_url"] = _url_with_query(
            reverse("browser:repeatcall-list"),
            run=repeat_call.pipeline_run.run_id,
            protein=repeat_call.protein.protein_id,
        )
        return context


def _annotated_runs(queryset=None):
    if queryset is None:
        queryset = PipelineRun.objects.all()
    return queryset.annotate(
        acquisition_batches_count=Coalesce(_count_subquery(AcquisitionBatch, "pipeline_run"), Value(0)),
        download_manifest_entries_count=Coalesce(_count_subquery(DownloadManifestEntry, "pipeline_run"), Value(0)),
        genomes_count=Coalesce(_count_subquery(Genome, "pipeline_run"), Value(0)),
        normalization_warnings_count=Coalesce(_count_subquery(NormalizationWarning, "pipeline_run"), Value(0)),
        sequences_count=Coalesce(_count_subquery(Sequence, "pipeline_run"), Value(0)),
        proteins_count=Coalesce(_count_subquery(Protein, "pipeline_run"), Value(0)),
        repeat_calls_count=Coalesce(_count_subquery(RepeatCall, "pipeline_run"), Value(0)),
        accession_status_rows_count=Coalesce(_count_subquery(AccessionStatus, "pipeline_run"), Value(0)),
        accession_call_count_rows_count=Coalesce(_count_subquery(AccessionCallCount, "pipeline_run"), Value(0)),
        run_parameters_count=Coalesce(_count_subquery(RunParameter, "pipeline_run"), Value(0)),
    )


def _annotated_batches(queryset=None):
    if queryset is None:
        queryset = AcquisitionBatch.objects.all()
    return queryset.annotate(
        genomes_count=Coalesce(_count_subquery(Genome, "batch"), Value(0)),
        sequences_count=Coalesce(_count_subquery(Sequence, "genome__batch", group_field_name="genome__batch"), Value(0)),
        proteins_count=Coalesce(_count_subquery(Protein, "genome__batch", group_field_name="genome__batch"), Value(0)),
        repeat_calls_count=Coalesce(
            _count_subquery(RepeatCall, "genome__batch", group_field_name="genome__batch"),
            Value(0),
        ),
        download_manifest_entries_count=Coalesce(_count_subquery(DownloadManifestEntry, "batch"), Value(0)),
        normalization_warnings_count=Coalesce(_count_subquery(NormalizationWarning, "batch"), Value(0)),
        accession_status_rows_count=Coalesce(_count_subquery(AccessionStatus, "batch"), Value(0)),
        accession_call_count_rows_count=Coalesce(_count_subquery(AccessionCallCount, "batch"), Value(0)),
    )


def _annotated_genomes(queryset=None):
    if queryset is None:
        queryset = Genome.objects.all()
    return queryset.annotate(
        sequences_count=Coalesce(_count_subquery(Sequence, "genome"), Value(0)),
        proteins_count=Coalesce(_count_subquery(Protein, "genome"), Value(0)),
        repeat_calls_count=Coalesce(_count_subquery(RepeatCall, "genome"), Value(0)),
    )


def _annotated_proteins(queryset=None):
    if queryset is None:
        queryset = Protein.objects.all()
    return queryset.annotate(
        repeat_calls_count=Coalesce(_count_subquery(RepeatCall, "protein"), Value(0)),
    )


def _resolve_current_run(request):
    run_id = request.GET.get("run", "").strip()
    if not run_id:
        return None
    return PipelineRun.objects.filter(run_id=run_id).first()


def _resolve_branch_taxon(request):
    branch = request.GET.get("branch", "").strip()
    if not branch:
        return None
    return Taxon.objects.filter(pk=branch).first()


def _resolve_batch_filter(current_run, batch_pk):
    if not batch_pk:
        return None
    queryset = AcquisitionBatch.objects.select_related("pipeline_run").filter(pk=batch_pk)
    if current_run:
        queryset = queryset.filter(pipeline_run=current_run)
    return queryset.first()


def _resolve_browser_mode(request):
    requested_mode = request.GET.get("mode", "").strip()
    if requested_mode == "merged":
        return "merged"
    return "run"


def _resolve_genome_filter(current_run, genome_id):
    if not genome_id:
        return None
    queryset = Genome.objects.select_related("pipeline_run").filter(genome_id=genome_id)
    if current_run:
        queryset = queryset.filter(pipeline_run=current_run)
    return queryset.first()


def _resolve_protein_filter(current_run, protein_id):
    if not protein_id:
        return None
    queryset = Protein.objects.select_related("pipeline_run", "genome").filter(protein_id=protein_id)
    if current_run:
        queryset = queryset.filter(pipeline_run=current_run)
    return queryset.first()


def _branch_taxon_ids(taxon: Taxon):
    return TaxonClosure.objects.filter(ancestor=taxon).order_by().values_list("descendant_id", flat=True)


def _repeat_call_filter_q(
    *,
    method: str,
    residue: str,
    length_min: str,
    length_max: str,
    purity_min: str,
    purity_max: str,
):
    filters = Q()
    has_filters = False

    if method:
        filters &= Q(method=method)
        has_filters = True

    if residue:
        filters &= Q(repeat_residue=residue)
        has_filters = True

    parsed_length_min = _parse_positive_int(length_min)
    if parsed_length_min is not None:
        filters &= Q(length__gte=parsed_length_min)
        has_filters = True

    parsed_length_max = _parse_positive_int(length_max)
    if parsed_length_max is not None:
        filters &= Q(length__lte=parsed_length_max)
        has_filters = True

    parsed_purity_min = _parse_float(purity_min)
    if parsed_purity_min is not None:
        filters &= Q(purity__gte=parsed_purity_min)
        has_filters = True

    parsed_purity_max = _parse_float(purity_max)
    if parsed_purity_max is not None:
        filters &= Q(purity__lte=parsed_purity_max)
        has_filters = True

    if not has_filters:
        return None
    return filters


def _scoped_repeat_calls(*, current_run=None, selected_branch_taxon=None, genome_id="", protein_id=""):
    queryset = RepeatCall.objects.all()
    if current_run:
        queryset = queryset.filter(pipeline_run=current_run)
    if selected_branch_taxon:
        queryset = queryset.filter(taxon_id__in=_branch_taxon_ids(selected_branch_taxon))
    if genome_id:
        queryset = queryset.filter(genome__genome_id=genome_id)
    if protein_id:
        queryset = queryset.filter(protein__protein_id=protein_id)
    return queryset


def _run_distinct_taxa_count(pipeline_run: PipelineRun) -> int:
    referenced_taxon_ids = _referenced_taxon_ids(pipeline_run)
    return Taxon.objects.filter(pk__in=referenced_taxon_ids).count()


def _run_taxon_ids(pipeline_run: PipelineRun):
    referenced_taxon_ids = _referenced_taxon_ids(pipeline_run)
    return (
        TaxonClosure.objects.filter(descendant_id__in=referenced_taxon_ids)
        .order_by()
        .values_list("ancestor_id", flat=True)
        .distinct()
    )


def _referenced_taxon_ids(pipeline_run: PipelineRun):
    return Genome.objects.filter(pipeline_run=pipeline_run).order_by().values_list("taxon_id", flat=True).union(
        Sequence.objects.filter(pipeline_run=pipeline_run).order_by().values_list("taxon_id", flat=True),
        Protein.objects.filter(pipeline_run=pipeline_run).order_by().values_list("taxon_id", flat=True),
        RepeatCall.objects.filter(pipeline_run=pipeline_run).order_by().values_list("taxon_id", flat=True),
    )


def _run_import_batches(pipeline_run: PipelineRun):
    filters = Q(pipeline_run=pipeline_run)
    if pipeline_run.publish_root:
        filters |= Q(source_path=pipeline_run.publish_root)
    return ImportBatch.objects.filter(filters)


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


def _mapping_items(mapping: dict[str, object], *, exclude_keys: set[str] | None = None):
    items = []
    excluded = exclude_keys or set()
    for key, value in mapping.items():
        if key in excluded or value in ("", None):
            continue
        items.append(
            {
                "key": key,
                "label": key.replace("_", " ").capitalize(),
                "value": value,
            }
        )
    return items


def _ordering_label(value: str) -> str:
    direction = "ascending"
    field_name = value
    if value.startswith("-"):
        direction = "descending"
        field_name = value[1:]
    return f"{field_name.replace('_', ' ').title()} ({direction})"


def _url_with_query(base_url: str, **params) -> str:
    cleaned_params = {key: value for key, value in params.items() if value not in ("", None)}
    if not cleaned_params:
        return base_url
    return f"{base_url}?{urlencode(cleaned_params)}"


def _sort_dict_records(records, *, requested_ordering: str, default_ordering: str, key_map: dict):
    ordering_value = requested_ordering or default_ordering
    reverse = ordering_value.startswith("-")
    key_name = ordering_value[1:] if reverse else ordering_value
    key_func = key_map.get(key_name)
    if key_func is None:
        return records
    return sorted(records, key=key_func, reverse=reverse)


def _parse_positive_int(value: str):
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    if parsed < 0:
        return None
    return parsed


def _parse_float(value: str):
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None
