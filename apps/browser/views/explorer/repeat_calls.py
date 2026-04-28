from importlib import import_module

from django.db.models import Exists, OuterRef, Prefetch
from django.http import Http404
from django.urls import reverse
from django.views.generic import TemplateView

from apps.browser.explorer.canonical import (
    build_canonical_repeat_call_detail_context,
    scoped_canonical_repeat_calls,
)
from apps.browser.presentation import (
    format_protein_position,
    format_repeat_pattern,
    summarize_target_codon_usage,
)

from ...exports import BrowserTSVExportMixin, TSVColumn
from ...models import CanonicalRepeatCall, CanonicalRepeatCallCodonUsage, PipelineRun, RepeatCall
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


REPEAT_CALL_LIST_FIELDS = (
    "id",
    "latest_pipeline_run_id",
    "latest_pipeline_run__id",
    "latest_pipeline_run__run_id",
    "latest_repeat_call_id",
    "latest_repeat_call__id",
    "latest_repeat_call__call_id",
    "latest_repeat_call__protein_id",
    "latest_repeat_call__genome_id",
    "latest_repeat_call__sequence_id",
    "taxon_id",
    "taxon__id",
    "taxon__taxon_id",
    "taxon__taxon_name",
    "source_call_id",
    "method",
    "accession",
    "gene_symbol",
    "protein_name",
    "protein_length",
    "start",
    "end",
    "length",
    "repeat_residue",
    "purity",
)

BIOLOGICAL_REPEAT_LIST_FIELDS = REPEAT_CALL_LIST_FIELDS + (
    "aa_sequence",
    "repeat_count",
    "non_repeat_count",
)

BIOLOGICAL_REPEAT_TSV_FIELDS = BIOLOGICAL_REPEAT_LIST_FIELDS + (
    "codon_sequence",
)


def repeat_call_source_id(repeat_call):
    latest_repeat_call = getattr(repeat_call, "latest_repeat_call", None)
    return repeat_call.source_call_id or getattr(latest_repeat_call, "call_id", "")


def _codon_usage_prefetch():
    return Prefetch(
        "codon_usages",
        queryset=CanonicalRepeatCallCodonUsage.objects.only(
            "id",
            "repeat_call_id",
            "amino_acid",
            "codon",
            "codon_count",
            "codon_fraction",
        ),
    )


def _target_codon_usage_rows(repeat_call):
    prefetched = getattr(repeat_call, "_prefetched_objects_cache", {}).get("codon_usages")
    if prefetched is not None:
        codon_usages = prefetched
    else:
        codon_usages = repeat_call.codon_usages.all()
    target_residue = (repeat_call.repeat_residue or "").upper()
    return [
        codon_usage
        for codon_usage in codon_usages
        if (codon_usage.amino_acid or "").upper() == target_residue
    ]


def _attach_repeat_display_fields(repeat_call):
    repeat_call.repeat_pattern = format_repeat_pattern(repeat_call.aa_sequence)
    repeat_call.protein_position = format_protein_position(
        repeat_call.start,
        repeat_call.end,
        repeat_call.protein_length,
    )
    return repeat_call


def _attach_codon_usage_display_fields(repeat_call):
    if hasattr(repeat_call, "codon_profile"):
        return repeat_call
    _attach_repeat_display_fields(repeat_call)
    profile = summarize_target_codon_usage(
        _target_codon_usage_rows(repeat_call),
        repeat_call.repeat_residue,
        repeat_call.repeat_count,
    )
    repeat_call.codon_coverage = profile["coverage"]
    repeat_call.codon_profile = profile["profile"]
    repeat_call.codon_counts = profile["counts"]
    repeat_call.dominant_codon = profile["dominant_codon"]
    repeat_call.codon_counts_export = profile["parseable_counts"]
    repeat_call.codon_fractions_export = profile["parseable_fractions"]
    repeat_call.codon_covered_count = profile["covered_count"]
    repeat_call.target_residue_count = profile["target_count"]
    return repeat_call


def _codon_usage_attr(name: str):
    def accessor(repeat_call):
        return getattr(_attach_codon_usage_display_fields(repeat_call), name)

    return accessor


class RepeatCallListView(BrowserTSVExportMixin, VirtualScrollListView):
    model = CanonicalRepeatCall
    template_name = "browser/repeatcall_list.html"
    context_object_name = "repeat_calls"
    virtual_scroll_row_template_name = "browser/includes/repeatcall_list_rows.html"
    virtual_scroll_colspan = 10
    tsv_filename_slug = "repeat_calls"
    tsv_columns = (
        TSVColumn("Call", repeat_call_source_id),
        TSVColumn("Accession", "accession"),
        TSVColumn("Protein", "protein_name"),
        TSVColumn("Gene", "gene_symbol"),
        TSVColumn("Taxon id", "taxon.taxon_id"),
        TSVColumn("Taxon", "taxon.taxon_name"),
        TSVColumn("Method", "method"),
        TSVColumn("Residue", "repeat_residue"),
        TSVColumn("Start", "start"),
        TSVColumn("End", "end"),
        TSVColumn("Length", "length"),
        TSVColumn("Purity", "purity"),
        TSVColumn("Latest run", "latest_pipeline_run.run_id"),
    )
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


class HomorepeatListView(RepeatCallListView):
    template_name = "browser/homorepeat_list.html"
    context_object_name = "homorepeats"
    virtual_scroll_row_template_name = "browser/includes/homorepeat_list_rows.html"
    virtual_scroll_colspan = 9
    tsv_filename_slug = "homorepeats"
    download_tsv_label = "Download Homorepeats TSV"
    tsv_columns = (
        TSVColumn("Organism", "taxon.taxon_name"),
        TSVColumn("Genome / Assembly", "accession"),
        TSVColumn("Gene", "gene_symbol"),
        TSVColumn("Protein", "protein_name"),
        TSVColumn("Repeat class", "repeat_residue"),
        TSVColumn("Length", "length"),
        TSVColumn("Pattern", lambda repeat_call: format_repeat_pattern(repeat_call.aa_sequence)),
        TSVColumn("Purity", "purity"),
        TSVColumn(
            "Position",
            lambda repeat_call: format_protein_position(
                repeat_call.start,
                repeat_call.end,
                repeat_call.protein_length,
            ),
        ),
        TSVColumn("Method", "method"),
        TSVColumn("Source call", repeat_call_source_id),
        TSVColumn("Start", "start"),
        TSVColumn("End", "end"),
        TSVColumn("Repeat count", "repeat_count"),
        TSVColumn("Non-repeat count", "non_repeat_count"),
        TSVColumn("Repeat sequence", "aa_sequence"),
        TSVColumn("Codon sequence", "codon_sequence"),
        TSVColumn("Latest run", "latest_pipeline_run.run_id"),
    )
    ordering_map = {
        "organism": ("taxon__taxon_name", "accession", "protein_name", "start", "id"),
        "-organism": ("-taxon__taxon_name", "accession", "protein_name", "start", "id"),
        "genome": ("accession", "protein_name", "start", "id"),
        "-genome": ("-accession", "protein_name", "start", "id"),
        "protein_name": ("protein_name", "accession", "start", "id"),
        "-protein_name": ("-protein_name", "accession", "start", "id"),
        "gene_symbol": ("gene_symbol", "accession", "protein_name", "start", "id"),
        "-gene_symbol": ("-gene_symbol", "accession", "protein_name", "start", "id"),
        "residue": ("repeat_residue", "accession", "protein_name", "start", "id"),
        "-residue": ("-repeat_residue", "accession", "protein_name", "start", "id"),
        "length": ("length", "accession", "protein_name", "start", "id"),
        "-length": ("-length", "accession", "protein_name", "start", "id"),
        "purity": ("purity", "accession", "protein_name", "start", "id"),
        "-purity": ("-purity", "accession", "protein_name", "start", "id"),
        "position": ("start", "end", "accession", "protein_name", "id"),
        "-position": ("-start", "-end", "accession", "protein_name", "id"),
        "method": ("method", "accession", "protein_name", "start", "id"),
        "-method": ("-method", "accession", "protein_name", "start", "id"),
    }
    default_ordering = ("accession", "protein_name", "start", "id")

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.only(*BIOLOGICAL_REPEAT_LIST_FIELDS)

    def prepare_tsv_queryset(self, queryset):
        return queryset.only(*BIOLOGICAL_REPEAT_TSV_FIELDS)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        homorepeats = context.get("homorepeats")
        if homorepeats is not None:
            for homorepeat in homorepeats:
                _attach_repeat_display_fields(homorepeat)
        return context


class CodonUsageListView(HomorepeatListView):
    template_name = "browser/codon_usage_list.html"
    context_object_name = "codon_usage_profiles"
    virtual_scroll_row_template_name = "browser/includes/codon_usage_list_rows.html"
    virtual_scroll_colspan = 11
    tsv_filename_slug = "codon_usage"
    download_tsv_label = "Download Codon Usage TSV"
    tsv_columns = (
        TSVColumn("Organism", "taxon.taxon_name"),
        TSVColumn("Genome / Assembly", "accession"),
        TSVColumn("Protein", "protein_name"),
        TSVColumn("Gene", "gene_symbol"),
        TSVColumn("Repeat class", "repeat_residue"),
        TSVColumn("Length", "length"),
        TSVColumn("Pattern", lambda repeat_call: format_repeat_pattern(repeat_call.aa_sequence)),
        TSVColumn("Codon coverage", _codon_usage_attr("codon_coverage")),
        TSVColumn("Codon profile", _codon_usage_attr("codon_profile")),
        TSVColumn("Codon counts", _codon_usage_attr("codon_counts")),
        TSVColumn("Dominant codon", _codon_usage_attr("dominant_codon")),
        TSVColumn("Method", "method"),
        TSVColumn("Repeat sequence", "aa_sequence"),
        TSVColumn("Codon sequence", "codon_sequence"),
        TSVColumn("Parseable codon counts", _codon_usage_attr("codon_counts_export")),
        TSVColumn("Parseable codon fractions", _codon_usage_attr("codon_fractions_export")),
        TSVColumn("Target residue count", "repeat_count"),
        TSVColumn("Source call", repeat_call_source_id),
        TSVColumn("Latest run", "latest_pipeline_run.run_id"),
    )

    def get_queryset(self):
        queryset = RepeatCallListView.get_queryset(self)
        target_codon_usage_exists = CanonicalRepeatCallCodonUsage.objects.filter(
            repeat_call_id=OuterRef("pk"),
            amino_acid=OuterRef("repeat_residue"),
        )
        return (
            queryset.annotate(has_target_codon_usage=Exists(target_codon_usage_exists))
            .filter(has_target_codon_usage=True)
            .only(*BIOLOGICAL_REPEAT_LIST_FIELDS)
            .prefetch_related(_codon_usage_prefetch())
        )

    def prepare_tsv_queryset(self, queryset):
        return queryset.only(*BIOLOGICAL_REPEAT_TSV_FIELDS)

    def get_context_data(self, **kwargs):
        context = RepeatCallListView.get_context_data(self, **kwargs)
        codon_usage_profiles = context.get("codon_usage_profiles")
        if codon_usage_profiles is not None:
            for codon_usage_profile in codon_usage_profiles:
                _attach_codon_usage_display_fields(codon_usage_profile)
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
