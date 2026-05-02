from ...models import (
    AccessionCallCount,
    AccessionStatus,
    AcquisitionBatch,
    DownloadManifestEntry,
    NormalizationWarning,
    PipelineRun,
)
from ...exports import BrowserTSVExportMixin, TSVColumn
from ..filters import _resolve_batch_filter, _resolve_current_run
from ..pagination import VirtualScrollListView


class NormalizationWarningListView(BrowserTSVExportMixin, VirtualScrollListView):
    model = NormalizationWarning
    template_name = "browser/normalizationwarning_list.html"
    context_object_name = "warnings"
    virtual_scroll_row_template_name = "browser/includes/normalizationwarning_list_rows.html"
    virtual_scroll_colspan = 8
    tsv_filename_slug = "normalization_warnings"
    tsv_columns = (
        TSVColumn("Run", "pipeline_run.run_id"),
        TSVColumn("Batch", "batch.batch_id"),
        TSVColumn("Warning code", "warning_code"),
        TSVColumn("Warning scope", "warning_scope"),
        TSVColumn("Message", "warning_message"),
        TSVColumn("Accession", "assembly_accession"),
        TSVColumn("Genome id", "genome_id"),
        TSVColumn("Sequence id", "sequence_id"),
        TSVColumn("Protein id", "protein_id"),
        TSVColumn("Source file", "source_file"),
        TSVColumn("Source record id", "source_record_id"),
    )
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
        "genome": ("genome_id", "warning_code", "assembly_accession", "pipeline_run__run_id"),
        "-genome": ("-genome_id", "warning_code", "assembly_accession", "pipeline_run__run_id"),
        "sequence": ("sequence_id", "warning_code", "assembly_accession", "pipeline_run__run_id"),
        "-sequence": ("-sequence_id", "warning_code", "assembly_accession", "pipeline_run__run_id"),
        "protein": ("protein_id", "warning_code", "assembly_accession", "pipeline_run__run_id"),
        "-protein": ("-protein_id", "warning_code", "assembly_accession", "pipeline_run__run_id"),
        "run": ("pipeline_run__run_id", "batch__batch_id", "warning_code", "assembly_accession"),
        "-run": ("-pipeline_run__run_id", "batch__batch_id", "warning_code", "assembly_accession"),
        "message": ("warning_message", "warning_code", "assembly_accession", "pipeline_run__run_id"),
        "-message": ("-warning_message", "warning_code", "assembly_accession", "pipeline_run__run_id"),
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
        context["run_choices"] = PipelineRun.objects.active().order_by("-imported_at", "run_id")
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


class AccessionStatusListView(BrowserTSVExportMixin, VirtualScrollListView):
    model = AccessionStatus
    template_name = "browser/accessionstatus_list.html"
    context_object_name = "status_rows"
    virtual_scroll_row_template_name = "browser/includes/accessionstatus_list_rows.html"
    virtual_scroll_colspan = 10
    tsv_filename_slug = "accession_status"
    tsv_columns = (
        TSVColumn("Run", "pipeline_run.run_id"),
        TSVColumn("Batch", "batch.batch_id"),
        TSVColumn("Accession", "assembly_accession"),
        TSVColumn("Download status", "download_status"),
        TSVColumn("Normalize status", "normalize_status"),
        TSVColumn("Translate status", "translate_status"),
        TSVColumn("Detect status", "detect_status"),
        TSVColumn("Finalize status", "finalize_status"),
        TSVColumn("Terminal status", "terminal_status"),
        TSVColumn("Failure stage", "failure_stage"),
        TSVColumn("Failure reason", "failure_reason"),
        TSVColumn("Genomes", "n_genomes"),
        TSVColumn("Proteins", "n_proteins"),
        TSVColumn("Repeat calls", "n_repeat_calls"),
        TSVColumn("Notes", "notes"),
    )
    search_fields = ("assembly_accession", "failure_stage", "failure_reason", "notes")
    ordering_map = {
        "accession": ("assembly_accession", "pipeline_run__run_id", "batch__batch_id"),
        "-accession": ("-assembly_accession", "pipeline_run__run_id", "batch__batch_id"),
        "batch": ("batch__batch_id", "assembly_accession"),
        "-batch": ("-batch__batch_id", "assembly_accession"),
        "download_status": ("download_status", "assembly_accession"),
        "-download_status": ("-download_status", "assembly_accession"),
        "normalize_status": ("normalize_status", "assembly_accession"),
        "-normalize_status": ("-normalize_status", "assembly_accession"),
        "translate_status": ("translate_status", "assembly_accession"),
        "-translate_status": ("-translate_status", "assembly_accession"),
        "detect_status": ("detect_status", "assembly_accession"),
        "-detect_status": ("-detect_status", "assembly_accession"),
        "finalize_status": ("finalize_status", "assembly_accession"),
        "-finalize_status": ("-finalize_status", "assembly_accession"),
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
        context["run_choices"] = PipelineRun.objects.active().order_by("-imported_at", "run_id")
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


class AccessionCallCountListView(BrowserTSVExportMixin, VirtualScrollListView):
    model = AccessionCallCount
    template_name = "browser/accessioncallcount_list.html"
    context_object_name = "call_count_rows"
    virtual_scroll_row_template_name = "browser/includes/accessioncallcount_list_rows.html"
    virtual_scroll_colspan = 8
    tsv_filename_slug = "accession_call_counts"
    tsv_columns = (
        TSVColumn("Run", "pipeline_run.run_id"),
        TSVColumn("Batch", "batch.batch_id"),
        TSVColumn("Accession", "assembly_accession"),
        TSVColumn("Method", "method"),
        TSVColumn("Residue", "repeat_residue"),
        TSVColumn("Detect status", "detect_status"),
        TSVColumn("Finalize status", "finalize_status"),
        TSVColumn("Repeat calls", "n_repeat_calls"),
    )
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
        "detect_status": ("detect_status", "assembly_accession", "method", "repeat_residue"),
        "-detect_status": ("-detect_status", "assembly_accession", "method", "repeat_residue"),
        "finalize_status": ("finalize_status", "assembly_accession", "method", "repeat_residue"),
        "-finalize_status": ("-finalize_status", "assembly_accession", "method", "repeat_residue"),
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
        context["run_choices"] = PipelineRun.objects.active().order_by("-imported_at", "run_id")
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


class DownloadManifestEntryListView(BrowserTSVExportMixin, VirtualScrollListView):
    model = DownloadManifestEntry
    template_name = "browser/downloadmanifest_list.html"
    context_object_name = "download_entries"
    virtual_scroll_row_template_name = "browser/includes/downloadmanifest_list_rows.html"
    virtual_scroll_colspan = 8
    tsv_filename_slug = "download_manifest"
    tsv_columns = (
        TSVColumn("Run", "pipeline_run.run_id"),
        TSVColumn("Batch", "batch.batch_id"),
        TSVColumn("Accession", "assembly_accession"),
        TSVColumn("Download status", "download_status"),
        TSVColumn("Package mode", "package_mode"),
        TSVColumn("File size bytes", "file_size_bytes"),
        TSVColumn("Checksum", "checksum"),
        TSVColumn("Download path", "download_path"),
        TSVColumn("Rehydrated path", "rehydrated_path"),
        TSVColumn("Download started", "download_started_at"),
        TSVColumn("Download finished", "download_finished_at"),
        TSVColumn("Notes", "notes"),
    )
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
        "checksum": ("checksum", "assembly_accession"),
        "-checksum": ("-checksum", "assembly_accession"),
        "paths": ("download_path", "rehydrated_path", "assembly_accession"),
        "-paths": ("-download_path", "-rehydrated_path", "assembly_accession"),
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
        context["run_choices"] = PipelineRun.objects.active().order_by("-imported_at", "run_id")
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
