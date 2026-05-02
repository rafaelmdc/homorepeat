from importlib import import_module

from django.db.models import Exists, OuterRef, Prefetch
from django.db.models import Q
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

from ...exports import (
    BrowserTSVExportMixin,
    FASTAMetadataField,
    FASTARecordBuilder,
    TSVColumn,
    clean_fasta_record_id_part,
    stream_fasta_response,
)
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

HOMOREPEAT_AA_FASTA_FIELDS = BIOLOGICAL_REPEAT_LIST_FIELDS + (
    "protein_id",
    "protein__id",
    "protein__amino_acid_sequence",
)

HOMOREPEAT_DNA_FASTA_FIELDS = REPEAT_CALL_LIST_FIELDS + (
    "sequence_id",
    "sequence__id",
    "sequence__sequence_length",
    "sequence__nucleotide_sequence",
    "repeat_count",
    "non_repeat_count",
)


def repeat_call_source_id(repeat_call):
    latest_repeat_call = getattr(repeat_call, "latest_repeat_call", None)
    return repeat_call.source_call_id or getattr(latest_repeat_call, "call_id", "")


def homorepeat_fasta_record_id(repeat_call):
    return f"homorepeat={clean_fasta_record_id_part(repeat_call.pk)}"


def homorepeat_protein_span(repeat_call):
    if repeat_call.start is None or repeat_call.end is None:
        return ""
    return f"{repeat_call.start}-{repeat_call.end}"


def homorepeat_protein_percent(repeat_call):
    if repeat_call.start is None or repeat_call.end is None or not repeat_call.protein_length:
        return ""
    midpoint = (repeat_call.start + repeat_call.end) / 2
    return round((midpoint / repeat_call.protein_length) * 100)


def homorepeat_dna_start(repeat_call):
    if repeat_call.start is None:
        return ""
    return ((repeat_call.start - 1) * 3) + 1


def homorepeat_dna_end(repeat_call):
    if repeat_call.end is None:
        return ""
    return repeat_call.end * 3


def homorepeat_dna_length(repeat_call):
    if repeat_call.length is None:
        return ""
    return repeat_call.length * 3


HOMOREPEAT_FASTA_METADATA_FIELDS = (
    FASTAMetadataField("organism", "taxon.taxon_name"),
    FASTAMetadataField("taxon_id", "taxon.taxon_id"),
    FASTAMetadataField("assembly", "accession"),
    FASTAMetadataField("gene", "gene_symbol"),
    FASTAMetadataField("protein", "protein_name"),
    FASTAMetadataField("repeat_class", "repeat_residue"),
    FASTAMetadataField("purity", "purity"),
    FASTAMetadataField("method", "method"),
    FASTAMetadataField("repeat_count", "repeat_count"),
    FASTAMetadataField("non_repeat_count", "non_repeat_count"),
    FASTAMetadataField("latest_run", "latest_pipeline_run.run_id"),
)

HOMOREPEAT_AA_FASTA_METADATA_FIELDS = HOMOREPEAT_FASTA_METADATA_FIELDS[:6] + (
    FASTAMetadataField("start", "start"),
    FASTAMetadataField("end", "end"),
    FASTAMetadataField("length", "length"),
    FASTAMetadataField("position_percent", homorepeat_protein_percent),
    FASTAMetadataField("sequence_length", "protein_length"),
    FASTAMetadataField("repeat_pattern", lambda repeat_call: format_repeat_pattern(repeat_call.aa_sequence)),
    *HOMOREPEAT_FASTA_METADATA_FIELDS[6:],
)

HOMOREPEAT_DNA_FASTA_METADATA_FIELDS = HOMOREPEAT_FASTA_METADATA_FIELDS[:6] + (
    FASTAMetadataField("start", homorepeat_dna_start),
    FASTAMetadataField("end", homorepeat_dna_end),
    FASTAMetadataField("length", homorepeat_dna_length),
    FASTAMetadataField("sequence_length", "sequence.sequence_length"),
    *HOMOREPEAT_FASTA_METADATA_FIELDS[6:],
)


def homorepeat_fasta_builder(*, seq_type: str, sequence: str):
    metadata_fields = (
        HOMOREPEAT_AA_FASTA_METADATA_FIELDS
        if seq_type.startswith("aa_")
        else HOMOREPEAT_DNA_FASTA_METADATA_FIELDS
    )
    return FASTARecordBuilder(
        record_id=homorepeat_fasta_record_id,
        sequence=sequence,
        metadata_fields=(
            FASTAMetadataField("seq_type", lambda repeat_call: seq_type),
            *metadata_fields,
        ),
    )


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
        run_choices = PipelineRun.objects.active().order_by("-imported_at", "run_id")
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
    fasta_chunk_size = 2000
    fasta_downloads = {
        "aa_fasta": {
            "label": "AA FASTA",
            "filename": "homorepeat_homorepeats.faa",
            "builder": homorepeat_fasta_builder(seq_type="aa_protein", sequence="protein.amino_acid_sequence"),
        },
        "dna_fasta": {
            "label": "DNA FASTA",
            "filename": "homorepeat_homorepeats.fna",
            "builder": homorepeat_fasta_builder(seq_type="dna_sequence", sequence="sequence.nucleotide_sequence"),
        },
    }
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

    def dispatch(self, request, *args, **kwargs):
        requested_download = request.GET.get(self.download_param, "").strip()
        if requested_download in self.fasta_downloads:
            return self.render_fasta_response(requested_download)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.only(*BIOLOGICAL_REPEAT_LIST_FIELDS)

    def prepare_tsv_queryset(self, queryset):
        return queryset.only(*BIOLOGICAL_REPEAT_TSV_FIELDS)

    def prepare_fasta_queryset(self, queryset, download_value):
        if download_value == "dna_fasta":
            return queryset.select_related("sequence").order_by("pk").only(*HOMOREPEAT_DNA_FASTA_FIELDS)
        return queryset.select_related("protein").order_by("pk").only(*HOMOREPEAT_AA_FASTA_FIELDS)

    def get_fasta_queryset(self, download_value):
        return self.prepare_fasta_queryset(self.get_queryset(), download_value)

    def iter_fasta_records(self, download_value):
        fasta_definition = self.fasta_downloads[download_value]
        builder = fasta_definition["builder"]
        rows = self.get_fasta_queryset(download_value)
        if hasattr(rows, "iterator"):
            rows = rows.iterator(chunk_size=self.fasta_chunk_size)
        for obj in rows:
            yield builder.build_record(obj)

    def render_fasta_response(self, download_value):
        fasta_definition = self.fasta_downloads[download_value]
        return stream_fasta_response(
            fasta_definition["filename"],
            self.iter_fasta_records(download_value),
        )

    def get_download_actions(self):
        return [
            self.get_download_action(self.download_value, "Filtered TSV"),
            *[
                self.get_download_action(download_value, definition["label"])
                for download_value, definition in self.fasta_downloads.items()
            ],
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not self.is_virtual_scroll_fragment_request():
            context["download_actions"] = self.get_download_actions()
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
    fasta_downloads = {}
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


CODON_USAGE_ROW_LIST_FIELDS = (
    "id",
    "repeat_call_id",
    "amino_acid",
    "codon",
    "codon_count",
    "codon_fraction",
    "repeat_call__id",
    "repeat_call__latest_pipeline_run_id",
    "repeat_call__latest_pipeline_run__id",
    "repeat_call__latest_pipeline_run__run_id",
    "repeat_call__latest_repeat_call_id",
    "repeat_call__latest_repeat_call__id",
    "repeat_call__latest_repeat_call__call_id",
    "repeat_call__latest_repeat_call__protein_id",
    "repeat_call__latest_repeat_call__genome_id",
    "repeat_call__latest_repeat_call__sequence_id",
    "repeat_call__taxon_id",
    "repeat_call__taxon__id",
    "repeat_call__taxon__taxon_id",
    "repeat_call__taxon__taxon_name",
    "repeat_call__source_call_id",
    "repeat_call__method",
    "repeat_call__accession",
    "repeat_call__gene_symbol",
    "repeat_call__protein_name",
    "repeat_call__start",
    "repeat_call__end",
    "repeat_call__length",
    "repeat_call__repeat_residue",
    "repeat_call__purity",
)


class CodonUsageRowListView(BrowserTSVExportMixin, VirtualScrollListView):
    model = CanonicalRepeatCallCodonUsage
    template_name = "browser/codon_usage_row_list.html"
    context_object_name = "codon_usage_rows"
    virtual_scroll_row_template_name = "browser/includes/codon_usage_row_list_rows.html"
    virtual_scroll_colspan = 11
    tsv_filename_slug = "codon_usage_rows"
    download_tsv_label = "Download Codon Usage Rows TSV"
    tsv_columns = (
        TSVColumn("Organism", "repeat_call.taxon.taxon_name"),
        TSVColumn("Genome / Assembly", "repeat_call.accession"),
        TSVColumn("Gene", "repeat_call.gene_symbol"),
        TSVColumn("Protein", "repeat_call.protein_name"),
        TSVColumn("Repeat class", "repeat_call.repeat_residue"),
        TSVColumn("Amino acid", "amino_acid"),
        TSVColumn("Codon", "codon"),
        TSVColumn("Codon count", "codon_count"),
        TSVColumn("Codon fraction", "codon_fraction"),
        TSVColumn("Method", "repeat_call.method"),
        TSVColumn("Source call", lambda codon_usage: repeat_call_source_id(codon_usage.repeat_call)),
        TSVColumn("Start", "repeat_call.start"),
        TSVColumn("End", "repeat_call.end"),
        TSVColumn("Latest run", "repeat_call.latest_pipeline_run.run_id"),
    )
    ordering_map = {
        "organism": ("repeat_call__taxon__taxon_name", "repeat_call__accession", "repeat_call__protein_name", "repeat_call__start", "amino_acid", "codon", "id"),
        "-organism": ("-repeat_call__taxon__taxon_name", "repeat_call__accession", "repeat_call__protein_name", "repeat_call__start", "amino_acid", "codon", "id"),
        "genome": ("repeat_call__accession", "repeat_call__protein_name", "repeat_call__start", "amino_acid", "codon", "id"),
        "-genome": ("-repeat_call__accession", "repeat_call__protein_name", "repeat_call__start", "amino_acid", "codon", "id"),
        "gene_symbol": ("repeat_call__gene_symbol", "repeat_call__accession", "repeat_call__protein_name", "repeat_call__start", "amino_acid", "codon", "id"),
        "-gene_symbol": ("-repeat_call__gene_symbol", "repeat_call__accession", "repeat_call__protein_name", "repeat_call__start", "amino_acid", "codon", "id"),
        "residue": ("repeat_call__repeat_residue", "repeat_call__accession", "repeat_call__protein_name", "repeat_call__start", "amino_acid", "codon", "id"),
        "-residue": ("-repeat_call__repeat_residue", "repeat_call__accession", "repeat_call__protein_name", "repeat_call__start", "amino_acid", "codon", "id"),
        "amino_acid": ("amino_acid", "codon", "repeat_call__accession", "repeat_call__protein_name", "repeat_call__start", "id"),
        "-amino_acid": ("-amino_acid", "codon", "repeat_call__accession", "repeat_call__protein_name", "repeat_call__start", "id"),
        "codon": ("codon", "amino_acid", "repeat_call__accession", "repeat_call__protein_name", "repeat_call__start", "id"),
        "-codon": ("-codon", "amino_acid", "repeat_call__accession", "repeat_call__protein_name", "repeat_call__start", "id"),
        "count": ("codon_count", "repeat_call__accession", "repeat_call__protein_name", "repeat_call__start", "amino_acid", "codon", "id"),
        "-count": ("-codon_count", "repeat_call__accession", "repeat_call__protein_name", "repeat_call__start", "amino_acid", "codon", "id"),
        "fraction": ("codon_fraction", "repeat_call__accession", "repeat_call__protein_name", "repeat_call__start", "amino_acid", "codon", "id"),
        "-fraction": ("-codon_fraction", "repeat_call__accession", "repeat_call__protein_name", "repeat_call__start", "amino_acid", "codon", "id"),
        "method": ("repeat_call__method", "repeat_call__accession", "repeat_call__protein_name", "repeat_call__start", "amino_acid", "codon", "id"),
        "-method": ("-repeat_call__method", "repeat_call__accession", "repeat_call__protein_name", "repeat_call__start", "amino_acid", "codon", "id"),
        "run": ("repeat_call__latest_pipeline_run__run_id", "repeat_call__accession", "repeat_call__protein_name", "repeat_call__start", "amino_acid", "codon", "id"),
        "-run": ("-repeat_call__latest_pipeline_run__run_id", "repeat_call__accession", "repeat_call__protein_name", "repeat_call__start", "amino_acid", "codon", "id"),
    }
    default_ordering = (
        "repeat_call__latest_pipeline_run_id",
        "repeat_call__accession",
        "repeat_call__protein_name",
        "repeat_call__start",
        "amino_acid",
        "codon",
        "id",
    )

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
        self.current_amino_acid = self.request.GET.get("amino_acid", "").strip().upper()
        self.current_codon = self.request.GET.get("codon", "").strip().upper()

    def get_queryset(self):
        self._load_filter_state()
        queryset = CanonicalRepeatCallCodonUsage.objects.select_related(
            "repeat_call",
            "repeat_call__latest_pipeline_run",
            "repeat_call__latest_repeat_call",
            "repeat_call__taxon",
        )
        query = self.get_search_query()
        if query:
            queryset = queryset.filter(
                Q(repeat_call__source_call_id__istartswith=query)
                | Q(repeat_call__accession__istartswith=query)
                | Q(repeat_call__protein_name__istartswith=query)
                | Q(repeat_call__gene_symbol__istartswith=query)
                | Q(codon__istartswith=query)
            )
        if self.current_run is not None:
            queryset = queryset.filter(repeat_call__latest_pipeline_run=self.current_run)
        if self.current_accession:
            queryset = queryset.filter(repeat_call__accession__istartswith=self.current_accession)
        if self.current_genome:
            queryset = queryset.filter(repeat_call__genome__genome_id=self.current_genome)
        if self.current_sequence:
            queryset = queryset.filter(repeat_call__sequence__sequence_id=self.current_sequence)
        if self.current_protein:
            queryset = queryset.filter(repeat_call__protein__protein_id=self.current_protein)
        if self.current_method:
            queryset = queryset.filter(repeat_call__method=self.current_method)
        if self.current_residue:
            queryset = queryset.filter(repeat_call__repeat_residue=self.current_residue)
        if self.current_gene_symbol:
            queryset = queryset.filter(repeat_call__gene_symbol__istartswith=self.current_gene_symbol)
        if self.current_length_min:
            length_min = _parse_positive_int(self.current_length_min)
            if length_min is not None:
                queryset = queryset.filter(repeat_call__length__gte=length_min)
        if self.current_length_max:
            length_max = _parse_positive_int(self.current_length_max)
            if length_max is not None:
                queryset = queryset.filter(repeat_call__length__lte=length_max)
        if self.current_purity_min:
            purity_min = _parse_float(self.current_purity_min)
            if purity_min is not None:
                queryset = queryset.filter(repeat_call__purity__gte=purity_min)
        if self.current_purity_max:
            purity_max = _parse_float(self.current_purity_max)
            if purity_max is not None:
                queryset = queryset.filter(repeat_call__purity__lte=purity_max)
        if self.current_amino_acid:
            queryset = queryset.filter(amino_acid__iexact=self.current_amino_acid)
        if self.current_codon:
            queryset = queryset.filter(codon__istartswith=self.current_codon)
        if self.branch_scope["branch_taxa_ids"] is not None:
            queryset = queryset.filter(repeat_call__taxon_id__in=self.branch_scope["branch_taxa_ids"])

        ordering = self.get_ordering()
        if ordering:
            queryset = queryset.order_by(*ordering)
        return queryset.only(*CODON_USAGE_ROW_LIST_FIELDS)

    def prepare_tsv_queryset(self, queryset):
        return queryset.only(*CODON_USAGE_ROW_LIST_FIELDS)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.is_virtual_scroll_fragment_request():
            return context
        current_run = getattr(self, "current_run", None)
        run_choices = PipelineRun.objects.active().order_by("-imported_at", "run_id")
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
        context["current_amino_acid"] = getattr(self, "current_amino_acid", "")
        context["current_codon"] = getattr(self, "current_codon", "")
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
