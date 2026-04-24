from django.urls import reverse
from django.views.generic import TemplateView

from apps.browser.stats import (
    apply_stats_filter_context,
    build_codon_length_browse_payload,
    build_codon_length_composition_bundle,
    build_codon_length_dominance_overview_payload,
    build_codon_length_inspect_bundle,
    build_codon_length_inspect_payload,
    build_codon_length_pairwise_overview_payload,
    build_codon_length_parent_comparison_bundle,
    build_codon_length_preference_overview_payload,
    build_codon_length_shift_overview_payload,
    build_filtered_repeat_call_queryset,
    build_matching_repeat_calls_with_codon_usage_count,
    build_stats_filter_state,
    build_taxonomy_gutter_payload,
)
from apps.browser.stats.policy import StatsPayloadType
from apps.browser.stats.params import ALLOWED_STATS_RANKS

from ...metadata import resolve_browser_facets
from ...models import PipelineRun
from ...exports import StatsTSVExportMixin
from ..navigation import _url_with_query


class CodonCompositionLengthExplorerView(StatsTSVExportMixin, TemplateView):
    template_name = "browser/codon_composition_length_explorer.html"
    tsv_filename_slug = "codon_composition_length"
    stats_tsv_dataset_keys = (
        "summary",
        "preference",
        "dominance",
        "shift",
        "similarity",
        "browse",
        "inspect",
        "comparison",
    )

    def get_summary_tsv_headers(self):
        return self._long_form_summary_headers()

    def get_preference_tsv_headers(self):
        return (
            "Taxon",
            "Length bin",
            "Preference value",
            "Codon A share",
            "Codon B share",
            "Support",
        )

    def get_dominance_tsv_headers(self):
        return (
            "Taxon",
            "Length bin",
            "Dominant codon",
            "Dominance margin",
            "Codon share",
            "Support",
        )

    def get_shift_tsv_headers(self):
        return (
            "Taxon",
            "Previous length bin",
            "Next length bin",
            "Shift value",
            "Previous support",
            "Next support",
        )

    def get_similarity_tsv_headers(self):
        return ("Row taxon", "Column taxon", "Trajectory Jensen-Shannon divergence")

    def get_browse_tsv_headers(self):
        return self._long_form_summary_headers()

    def get_inspect_tsv_headers(self):
        return (
            "Scope",
            "Length bin",
            "Support",
            "Dominant codon",
            "Codon",
            "Codon share",
            "Shift from previous",
        )

    def get_comparison_tsv_headers(self):
        return self.get_inspect_tsv_headers()

    def is_inspect_tsv_available(self) -> bool:
        return self._inspect_scope_active()

    def is_comparison_tsv_available(self) -> bool:
        return self._inspect_scope_active() and self._get_comparison_bundle() is not None

    def _long_form_summary_headers(self):
        return (
            "Taxon id",
            "Taxon",
            "Rank",
            "Length bin",
            "Observations",
            "Species",
            "Dominant codon",
            "Dominance margin",
            "Codon",
            "Codon share",
        )

    def iter_summary_tsv_rows(self):
        yield from self._iter_long_form_summary_rows()

    def iter_preference_tsv_rows(self):
        payload = self._build_payload(
            StatsPayloadType.CODON_LENGTH_OVERVIEW_PREFERENCE,
            lambda: build_codon_length_preference_overview_payload(self._get_summary_bundle()),
        )
        taxa = payload["taxa"]
        for cell in payload["cells"]:
            taxon = taxa[cell["rowIndex"]]
            yield (
                taxon["taxonName"],
                cell["binLabel"],
                cell["preference"],
                cell["codonAShare"],
                cell["codonBShare"],
                cell["observationCount"],
            )

    def iter_dominance_tsv_rows(self):
        payload = self._build_payload(
            StatsPayloadType.CODON_LENGTH_OVERVIEW_DOMINANCE,
            lambda: build_codon_length_dominance_overview_payload(self._get_summary_bundle()),
        )
        taxa = payload["taxa"]
        for cell in payload["cells"]:
            taxon = taxa[cell["rowIndex"]]
            dominant_share = next(
                (
                    codon_share["share"]
                    for codon_share in cell["codonShares"]
                    if codon_share["codon"] == cell["dominantCodon"]
                ),
                0,
            )
            yield (
                taxon["taxonName"],
                cell["binLabel"],
                cell["dominantCodon"],
                cell["dominanceMargin"],
                dominant_share,
                cell["observationCount"],
            )

    def iter_shift_tsv_rows(self):
        payload = self._build_payload(
            StatsPayloadType.CODON_LENGTH_OVERVIEW_SHIFT,
            lambda: build_codon_length_shift_overview_payload(self._get_summary_bundle()),
        )
        taxa = payload["taxa"]
        for cell in payload["cells"]:
            taxon = taxa[cell["rowIndex"]]
            yield (
                taxon["taxonName"],
                cell["previousBin"]["label"],
                cell["nextBin"]["label"],
                cell["shift"],
                cell["previousSupport"]["observationCount"],
                cell["nextSupport"]["observationCount"],
            )

    def iter_similarity_tsv_rows(self):
        yield from self._iter_pairwise_similarity_rows(
            self._build_payload(
                StatsPayloadType.CODON_LENGTH_OVERVIEW_SIMILARITY,
                lambda: build_codon_length_pairwise_overview_payload(self._get_summary_bundle()),
            )
        )

    def iter_browse_tsv_rows(self):
        yield from self._iter_long_form_summary_rows()

    def iter_inspect_tsv_rows(self):
        yield from self._iter_inspect_payload_rows("binRows")

    def iter_comparison_tsv_rows(self):
        yield from self._iter_inspect_payload_rows("comparisonBinRows")

    def _iter_long_form_summary_rows(self):
        for matrix_row in self._get_summary_bundle()["matrix_rows"]:
            for bin_row in matrix_row["bin_rows"]:
                for codon_share in bin_row["codon_shares"]:
                    yield (
                        matrix_row["taxon_id"],
                        matrix_row["taxon_name"],
                        matrix_row["rank"],
                        bin_row["bin"]["label"],
                        bin_row["observation_count"],
                        bin_row["species_count"],
                        bin_row["dominant_codon"],
                        bin_row["dominance_margin"],
                        codon_share["codon"],
                        codon_share["share"],
                    )

    def _iter_pairwise_similarity_rows(self, payload):
        taxa = payload["taxa"]
        divergence_matrix = payload["divergenceMatrix"]
        for row_index, row_taxon in enumerate(taxa):
            for column_index, column_taxon in enumerate(taxa):
                yield (
                    row_taxon["taxonName"],
                    column_taxon["taxonName"],
                    divergence_matrix[row_index][column_index],
                )

    def _iter_inspect_payload_rows(self, key: str):
        inspect_bundle = self._get_inspect_bundle()
        if inspect_bundle is None:
            return
        payload = self._build_payload(
            StatsPayloadType.CODON_LENGTH_INSPECT,
            lambda: build_codon_length_inspect_payload(
                inspect_bundle,
                scope_label=self._inspect_scope_label(),
                comparison_bundle=self._get_comparison_bundle(),
                comparison_scope_label=self._comparison_scope_label(),
            ),
        )
        scope_label = (
            payload.get("comparisonScopeLabel", "")
            if key == "comparisonBinRows"
            else payload["scopeLabel"]
        )
        for bin_row in payload.get(key, []):
            for codon_share in bin_row["codonShares"]:
                yield (
                    scope_label,
                    bin_row["binLabel"],
                    bin_row["observationCount"],
                    bin_row["dominantCodon"],
                    codon_share["codon"],
                    codon_share["share"],
                    bin_row["delta"],
                )

    def _get_filter_state(self):
        if not hasattr(self, "_filter_state"):
            self._filter_state = build_stats_filter_state(self.request)
        return self._filter_state

    def _build_payload(self, payload_type: StatsPayloadType, build_fn):
        return build_fn()

    def _get_matching_repeat_calls_count(self) -> int:
        if not hasattr(self, "_matching_repeat_calls_count"):
            filter_state = self._get_filter_state()
            if filter_state.residue:
                self._matching_repeat_calls_count = self._get_summary_bundle()[
                    "matching_repeat_calls_count"
                ]
            else:
                self._matching_repeat_calls_count = build_filtered_repeat_call_queryset(
                    filter_state
                ).count()
        return self._matching_repeat_calls_count

    def _get_matching_repeat_calls_with_codon_usage_count(self) -> int:
        if not hasattr(self, "_matching_repeat_calls_with_codon_usage_count"):
            filter_state = self._get_filter_state()
            if not filter_state.residue:
                self._matching_repeat_calls_with_codon_usage_count = 0
            else:
                self._matching_repeat_calls_with_codon_usage_count = self._build_payload(
                    StatsPayloadType.CODON_USAGE_COUNT,
                    lambda: build_matching_repeat_calls_with_codon_usage_count(filter_state),
                )
        return self._matching_repeat_calls_with_codon_usage_count

    def _get_summary_bundle(self) -> dict[str, object]:
        if not hasattr(self, "_summary_bundle"):
            bundle = self._build_payload(
                StatsPayloadType.CODON_LENGTH_SUMMARY,
                lambda: build_codon_length_composition_bundle(self._get_filter_state()),
            )
            self._summary_bundle = {
                **bundle,
                "summary_rows": [self._with_row_links(row) for row in self._flatten_summary_rows(bundle)],
            }
        return self._summary_bundle

    def _get_facet_choices(self) -> dict[str, list[str]]:
        if not hasattr(self, "_facet_choices"):
            filter_state = self._get_filter_state()
            if filter_state.current_run is not None:
                self._facet_choices = resolve_browser_facets(pipeline_run=filter_state.current_run)
            else:
                self._facet_choices = resolve_browser_facets()
        return self._facet_choices

    def _scope_items(self) -> list[dict[str, str]]:
        filter_state = self._get_filter_state()
        length_range = "Any length"
        if filter_state.length_min is not None or filter_state.length_max is not None:
            length_range = (
                f"{filter_state.length_min if filter_state.length_min is not None else 0} "
                f"to {filter_state.length_max if filter_state.length_max is not None else 'any'}"
            )

        return [
            {
                "label": "Display rank",
                "value": filter_state.rank,
            },
            {
                "label": "Target search",
                "value": filter_state.q or "Any gene, protein, or accession prefix",
            },
            {
                "label": "Method",
                "value": filter_state.method or "All methods",
            },
            {
                "label": "Residue",
                "value": filter_state.residue or "Select one residue",
            },
            {
                "label": "Length range",
                "value": length_range,
            },
            {
                "label": "Minimum observations",
                "value": str(filter_state.min_count),
            },
            {
                "label": "Visible taxa limit",
                "value": str(filter_state.top_n),
            },
        ]

    def _summary_empty_reason(self) -> str:
        filter_state = self._get_filter_state()
        if not filter_state.residue:
            return "Select a residue to summarize codon composition by length."
        matching_repeat_calls_count = self._get_matching_repeat_calls_count()
        matching_repeat_calls_with_codon_usage_count = (
            self._get_matching_repeat_calls_with_codon_usage_count()
        )
        if matching_repeat_calls_count > 0 and matching_repeat_calls_with_codon_usage_count == 0:
            return (
                "Canonical repeat calls matched these filters, but no codon-usage rows "
                "were available for the selected residue."
            )
        if matching_repeat_calls_count > 0 and not self._get_summary_bundle()["summary_rows"]:
            return "No taxa reached the current display rank and minimum observation threshold."
        return "No canonical repeat calls matched these filters."

    def _flatten_summary_rows(self, bundle: dict[str, object]) -> list[dict[str, object]]:
        summary_rows = []
        for matrix_row in bundle["matrix_rows"]:
            for bin_row in matrix_row["bin_rows"]:
                summary_rows.append(
                    {
                        "taxon_id": matrix_row["taxon_id"],
                        "taxon_name": matrix_row["taxon_name"],
                        "rank": matrix_row["rank"],
                        "bin": bin_row["bin"],
                        "observation_count": bin_row["observation_count"],
                        "species_count": bin_row["species_count"],
                        "dominant_codon": bin_row["dominant_codon"],
                        "dominance_margin": bin_row["dominance_margin"],
                        "codon_shares": bin_row["codon_shares"],
                    }
                )
        return summary_rows

    def _with_row_links(self, row: dict[str, object]) -> dict[str, object]:
        filter_state = self._get_filter_state()
        return {
            **row,
            "taxon_detail_url": _url_with_query(
                reverse("browser:taxon-detail", args=[row["taxon_id"]]),
                run=filter_state.current_run_id,
            ),
        }

    def _inspect_scope_active(self) -> bool:
        return self._get_filter_state().branch_scope_active

    def _inspect_scope_label(self) -> str:
        filter_state = self._get_filter_state()
        if filter_state.selected_branch_taxon is not None:
            branch_rank = filter_state.selected_branch_taxon.rank or filter_state.branch_scope_noun
            return f"{branch_rank.title()} {filter_state.selected_branch_taxon.taxon_name}"
        if filter_state.branch_scope_active:
            return f"{filter_state.branch_scope_noun.title()} {filter_state.branch_scope_label}"
        return "Current filtered scope"

    def _get_inspect_bundle(self) -> dict[str, object] | None:
        if not self._inspect_scope_active():
            return None
        if not hasattr(self, "_inspect_bundle"):
            self._inspect_bundle = self._build_payload(
                StatsPayloadType.CODON_LENGTH_INSPECT,
                lambda: build_codon_length_inspect_bundle(self._get_filter_state()),
            )
        return self._inspect_bundle

    def _get_comparison_taxon(self):
        filter_state = self._get_filter_state()
        if filter_state.selected_branch_taxon is not None:
            return filter_state.selected_branch_taxon.parent_taxon
        if filter_state.current_branch_q:
            from apps.browser.views.filters import _match_branch_taxa
            matched = list(_match_branch_taxa(filter_state.current_branch_q)[:2])
            if len(matched) == 1:
                return matched[0].parent_taxon
        return None

    def _get_comparison_bundle(self) -> dict[str, object] | None:
        comparison_taxon = self._get_comparison_taxon()
        if comparison_taxon is None:
            return None
        if not hasattr(self, "_comparison_bundle"):
            self._comparison_bundle = self._build_payload(
                StatsPayloadType.CODON_LENGTH_COMPARISON,
                lambda: build_codon_length_parent_comparison_bundle(
                    self._get_filter_state(),
                    parent_taxon=comparison_taxon,
                ),
            )
        return self._comparison_bundle

    def _comparison_scope_label(self) -> str:
        taxon = self._get_comparison_taxon()
        if taxon is None:
            return ""
        rank = taxon.rank.title() if taxon.rank else "Parent"
        return f"{rank} {taxon.taxon_name}"

    def _default_overview_mode(self, summary_bundle: dict[str, object]) -> str:
        visible_codon_count = len(summary_bundle["visible_codons"])
        if visible_codon_count == 2:
            return "preference"
        if visible_codon_count >= 3:
            return "dominance"
        return "preference"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filter_state = self._get_filter_state()
        facet_choices = self._get_facet_choices()
        summary_bundle = self._get_summary_bundle()

        apply_stats_filter_context(context, filter_state)
        context["matching_repeat_calls_count"] = self._get_matching_repeat_calls_count()
        context["matching_repeat_calls_with_codon_usage_count"] = (
            self._get_matching_repeat_calls_with_codon_usage_count()
        )
        context["total_taxa_count"] = summary_bundle["total_taxa_count"]
        context["visible_taxa_count"] = summary_bundle["visible_taxa_count"]
        context["summary_rows"] = summary_bundle["summary_rows"]
        context["visible_codons"] = summary_bundle["visible_codons"]
        context["overview_default_mode"] = self._default_overview_mode(summary_bundle)
        context["overview_preference_payload"] = self._build_payload(
            StatsPayloadType.CODON_LENGTH_OVERVIEW_PREFERENCE,
            lambda: build_codon_length_preference_overview_payload(summary_bundle),
        )
        context["overview_dominance_payload"] = self._build_payload(
            StatsPayloadType.CODON_LENGTH_OVERVIEW_DOMINANCE,
            lambda: build_codon_length_dominance_overview_payload(summary_bundle),
        )
        context["overview_shift_payload"] = self._build_payload(
            StatsPayloadType.CODON_LENGTH_OVERVIEW_SHIFT,
            lambda: build_codon_length_shift_overview_payload(summary_bundle),
        )
        pairwise_payload = self._build_payload(
            StatsPayloadType.CODON_LENGTH_OVERVIEW_SIMILARITY,
            lambda: build_codon_length_pairwise_overview_payload(summary_bundle),
        )
        overview_taxonomy_gutter_payload = self._build_payload(
            StatsPayloadType.TAXONOMY_GUTTER,
            lambda: build_taxonomy_gutter_payload(
                summary_bundle.get("matrix_rows", []),
                filter_state=filter_state,
                collapse_rank=filter_state.rank,
            ),
        )
        context["overview_taxonomy_gutter_payload"] = overview_taxonomy_gutter_payload
        context["overview_pairwise_payload"] = pairwise_payload
        context["overview_pairwise_taxonomy_gutter_payload"] = overview_taxonomy_gutter_payload
        context["browse_payload"] = self._build_payload(
            StatsPayloadType.CODON_LENGTH_BROWSE,
            lambda: build_codon_length_browse_payload(summary_bundle),
        )
        context["overview_preference_payload_id"] = (
            "codon-composition-length-preference-overview-payload"
        )
        context["overview_dominance_payload_id"] = (
            "codon-composition-length-dominance-overview-payload"
        )
        context["overview_shift_payload_id"] = "codon-composition-length-shift-overview-payload"
        context["overview_pairwise_payload_id"] = "codon-composition-length-pairwise-overview-payload"
        context["overview_pairwise_taxonomy_gutter_payload_id"] = (
            "codon-composition-length-pairwise-taxonomy-gutter-payload"
        )
        context["overview_taxonomy_gutter_payload_id"] = (
            "codon-composition-length-overview-taxonomy-gutter-payload"
        )
        context["overview_container_id"] = "codon-composition-length-overview-chart"
        context["overview_pairwise_container_id"] = "codon-composition-length-pairwise-chart"
        context["browse_payload_id"] = "codon-composition-length-browse-payload"
        context["browse_container_id"] = "codon-composition-length-browse"
        context["run_choices"] = PipelineRun.objects.order_by("-imported_at", "run_id")
        context["rank_choices"] = [
            {"value": rank, "label": rank}
            for rank in ALLOWED_STATS_RANKS
        ]
        context["method_choices"] = facet_choices["methods"]
        context["residue_choices"] = facet_choices["residues"]
        context["scope_items"] = self._scope_items()
        context["reset_url"] = reverse("browser:codon-composition-length")
        context["overview_download_tsv_actions"] = self.get_tsv_download_actions(
            {
                "dataset_key": "preference",
                "label": "Download Preference TSV",
                "available": bool(context["overview_preference_payload"].get("available")),
            },
            {
                "dataset_key": "dominance",
                "label": "Download Dominance TSV",
                "available": bool(context["overview_dominance_payload"].get("available")),
            },
            {
                "dataset_key": "shift",
                "label": "Download Shift TSV",
                "available": bool(context["overview_shift_payload"].get("available")),
            },
            {
                "dataset_key": "similarity",
                "label": "Download Similarity TSV",
                "available": bool(context["overview_pairwise_payload"].get("available")),
            },
        )
        context["browse_download_tsv_actions"] = self.get_tsv_download_actions(
            {
                "dataset_key": "browse",
                "label": "Download Browse TSV",
                "available": bool(context["browse_payload"].get("available")),
            }
        )
        context["summary_download_tsv_actions"] = self.get_tsv_download_actions(
            {
                "dataset_key": "summary",
                "label": "Download Summary TSV",
            }
        )
        context["summary_empty_reason"] = self._summary_empty_reason()
        context["inspect_scope_active"] = self._inspect_scope_active()
        inspect_bundle = self._get_inspect_bundle()
        if inspect_bundle is not None:
            comparison_bundle = self._get_comparison_bundle()
            comparison_scope_label = self._comparison_scope_label()
            context["inspect_download_tsv_actions"] = self.get_tsv_download_actions(
                {
                    "dataset_key": "inspect",
                    "label": "Download Inspect TSV",
                }
            )
            inspect_payload = self._build_payload(
                StatsPayloadType.CODON_LENGTH_INSPECT,
                lambda: build_codon_length_inspect_payload(
                    inspect_bundle,
                    scope_label=self._inspect_scope_label(),
                    comparison_bundle=comparison_bundle,
                    comparison_scope_label=comparison_scope_label,
                ),
            )
            context["inspect_payload"] = inspect_payload
            context["inspect_payload_id"] = "codon-composition-length-inspect-payload"
            context["inspect_chart_container_id"] = "codon-composition-length-inspect-chart"
            context["inspect_observation_count"] = inspect_bundle["observation_count"]
            context["inspect_scope_label"] = self._inspect_scope_label()
            context["inspect_bin_rows"] = inspect_payload["binRows"]
            context["inspect_has_comparison"] = bool(inspect_payload.get("comparisonBinRows"))
            context["inspect_comparison_scope_label"] = comparison_scope_label
            context["inspect_comparison_bin_rows"] = inspect_payload.get("comparisonBinRows", [])
            context["comparison_download_tsv_actions"] = self.get_tsv_download_actions(
                {
                    "dataset_key": "comparison",
                    "label": "Download Comparison TSV",
                    "available": bool(inspect_payload.get("comparisonBinRows")),
                }
            )
            context["inspect_empty_reason"] = (
                "No canonical repeat calls with codon-usage rows matched the current branch scope."
                if not inspect_payload["available"]
                else ""
            )
        return context
