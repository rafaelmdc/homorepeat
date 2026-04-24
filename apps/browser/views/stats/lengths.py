from django.urls import reverse
from django.views.generic import TemplateView

from apps.browser.stats import (
    apply_stats_filter_context,
    build_length_inspect_bundle,
    build_length_inspect_payload,
    build_length_profile_vector_bundle,
    build_ranked_length_chart_payload,
    build_ranked_length_summary_bundle,
    build_stats_filter_state,
    build_tail_burden_overview_payload,
    build_taxonomy_gutter_payload,
    build_typical_length_overview_payload,
)
from apps.browser.stats.policy import StatsPayloadType
from apps.browser.stats.params import ALLOWED_STATS_RANKS, next_lower_rank

from ...metadata import resolve_browser_facets
from ...models import PipelineRun
from ...exports import StatsTSVExportMixin
from ..navigation import _url_with_query


class RepeatLengthExplorerView(StatsTSVExportMixin, TemplateView):
    template_name = "browser/repeat_length_explorer.html"
    tsv_filename_slug = "repeat_lengths"
    stats_tsv_dataset_keys = ("summary", "overview_typical", "overview_tail", "inspect")

    def get_summary_tsv_headers(self):
        return (
            "Taxon id",
            "Taxon",
            "Rank",
            "Observations",
            "Species",
            "Min",
            "Q1",
            "Median",
            "Q3",
            "Max",
        )

    def get_overview_typical_tsv_headers(self):
        return ("Row taxon", "Column taxon", "Wasserstein-1 distance")

    def get_overview_tail_tsv_headers(self):
        return ("Row taxon", "Column taxon", "Tail-burden distance")

    def get_inspect_tsv_headers(self):
        return (
            "Scope",
            "Observations",
            "Median",
            "Q90",
            "Q95",
            "Max",
            "CCDF length",
            "CCDF survival fraction",
        )

    def is_inspect_tsv_available(self) -> bool:
        return self._inspect_scope_active()

    def iter_summary_tsv_rows(self):
        for row in self._get_summary_bundle()["summary_rows"]:
            yield (
                row["taxon_id"],
                row["taxon_name"],
                row["rank"],
                row["observation_count"],
                row["species_count"],
                row["min_length"],
                row["q1"],
                row["median"],
                row["q3"],
                row["max_length"],
            )

    def iter_overview_typical_tsv_rows(self):
        yield from self._iter_pairwise_overview_tsv_rows(
            self._build_payload(
                StatsPayloadType.REPEAT_LENGTH_OVERVIEW_TYPICAL,
                lambda: build_typical_length_overview_payload(self._get_overview_bundle()["profile_rows"]),
            )
        )

    def iter_overview_tail_tsv_rows(self):
        yield from self._iter_pairwise_overview_tsv_rows(
            self._build_payload(
                StatsPayloadType.REPEAT_LENGTH_OVERVIEW_TAIL,
                lambda: build_tail_burden_overview_payload(self._get_overview_bundle()["profile_rows"]),
            )
        )

    def iter_inspect_tsv_rows(self):
        payload = self._build_payload(
            StatsPayloadType.REPEAT_LENGTH_INSPECT,
            lambda: build_length_inspect_payload(
                self._get_inspect_bundle(),
                scope_label=self._inspect_scope_label(),
            ),
        )
        for point in payload["ccdfPoints"]:
            yield (
                payload["scopeLabel"],
                payload["observationCount"],
                payload["median"],
                payload["q90"],
                payload["q95"],
                payload["max"],
                point["x"],
                point["y"],
            )

    def _iter_pairwise_overview_tsv_rows(self, payload):
        taxa = payload["taxa"]
        divergence_matrix = payload["divergenceMatrix"]
        for row_index, row_taxon in enumerate(taxa):
            for column_index, column_taxon in enumerate(taxa):
                yield (
                    row_taxon["taxonName"],
                    column_taxon["taxonName"],
                    divergence_matrix[row_index][column_index],
                )

    def _get_filter_state(self):
        if not hasattr(self, "_filter_state"):
            self._filter_state = build_stats_filter_state(self.request)
        return self._filter_state

    def _build_payload(self, payload_type: StatsPayloadType, build_fn):
        return build_fn()

    def _inspect_scope_active(self) -> bool:
        return self._get_filter_state().branch_scope_active

    def _get_inspect_bundle(self) -> dict[str, object] | None:
        if not self._inspect_scope_active():
            return None
        if not hasattr(self, "_inspect_bundle"):
            self._inspect_bundle = self._build_payload(
                StatsPayloadType.REPEAT_LENGTH_INSPECT,
                lambda: build_length_inspect_bundle(self._get_filter_state()),
            )
        return self._inspect_bundle

    def _inspect_scope_label(self) -> str:
        filter_state = self._get_filter_state()
        if filter_state.selected_branch_taxon is not None:
            branch_rank = filter_state.selected_branch_taxon.rank or filter_state.branch_scope_noun
            return f"{branch_rank.title()} {filter_state.selected_branch_taxon.taxon_name}"
        if filter_state.branch_scope_active:
            return f"{filter_state.branch_scope_noun.title()} {filter_state.branch_scope_label}"
        return "Current filtered scope"

    def _get_overview_bundle(self) -> dict[str, object]:
        if not hasattr(self, "_overview_bundle"):
            self._overview_bundle = self._build_payload(
                StatsPayloadType.REPEAT_LENGTH_OVERVIEW_TYPICAL,
                lambda: build_length_profile_vector_bundle(self._get_filter_state()),
            )
        return self._overview_bundle

    def _get_summary_bundle(self) -> dict[str, object]:
        if not hasattr(self, "_summary_bundle"):
            summary_bundle = self._build_payload(
                StatsPayloadType.REPEAT_LENGTH_SUMMARY,
                lambda: build_ranked_length_summary_bundle(self._get_filter_state()),
            )
            self._summary_bundle = {
                **summary_bundle,
                "summary_rows": [self._with_row_links(row) for row in summary_bundle["summary_rows"]],
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
            length_range = f"{filter_state.length_min if filter_state.length_min is not None else 0} to {filter_state.length_max if filter_state.length_max is not None else 'any'}"

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
                "value": filter_state.residue or "All residues",
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

    def _with_row_links(self, row: dict[str, object]) -> dict[str, object]:
        filter_state = self._get_filter_state()
        drilldown_rank = next_lower_rank(row["rank"])
        return {
            **row,
            "taxon_detail_url": _url_with_query(
                reverse("browser:taxon-detail", args=[row["taxon_id"]]),
                run=filter_state.current_run_id,
            ),
            "branch_explorer_url": _url_with_query(
                reverse("browser:lengths"),
                run=filter_state.current_run_id,
                branch=row["taxon_id"],
                rank=drilldown_rank,
                q=filter_state.q,
                method=filter_state.method,
                residue=filter_state.residue,
                length_min=filter_state.length_min,
                length_max=filter_state.length_max,
                purity_min=filter_state.purity_min,
                purity_max=filter_state.purity_max,
                min_count=filter_state.min_count,
                top_n=filter_state.top_n,
            ),
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filter_state = self._get_filter_state()
        facet_choices = self._get_facet_choices()
        summary_bundle = self._get_summary_bundle()
        summary_rows = summary_bundle["summary_rows"]

        overview_bundle = self._get_overview_bundle()
        overview_rows = overview_bundle["profile_rows"]

        apply_stats_filter_context(context, filter_state)
        context["matching_repeat_calls_count"] = summary_bundle["matching_repeat_calls_count"]
        context["summary_rows"] = summary_rows
        context["total_taxa_count"] = summary_bundle["total_taxa_count"]
        context["visible_taxa_count"] = summary_bundle["visible_taxa_count"]
        context["overview_visible_taxa_count"] = len(overview_rows)
        context["overview_typical_payload"] = self._build_payload(
            StatsPayloadType.REPEAT_LENGTH_OVERVIEW_TYPICAL,
            lambda: build_typical_length_overview_payload(overview_rows),
        )
        context["overview_typical_payload_id"] = "length-overview-typical-payload"
        context["overview_tail_payload"] = self._build_payload(
            StatsPayloadType.REPEAT_LENGTH_OVERVIEW_TAIL,
            lambda: build_tail_burden_overview_payload(overview_rows),
        )
        context["overview_tail_payload_id"] = "length-overview-tail-payload"
        context["overview_container_id"] = "length-overview"
        context["overview_taxonomy_gutter_payload"] = self._build_payload(
            StatsPayloadType.TAXONOMY_GUTTER,
            lambda: build_taxonomy_gutter_payload(
                overview_rows,
                filter_state=filter_state,
                collapse_rank=filter_state.rank,
            ),
        )
        context["overview_taxonomy_gutter_payload_id"] = "length-overview-taxonomy-gutter-payload"
        context["chart_payload"] = self._build_payload(
            StatsPayloadType.REPEAT_LENGTH_SUMMARY,
            lambda: build_ranked_length_chart_payload(summary_rows),
        )
        context["chart_payload_id"] = "repeat-length-chart-payload"
        context["chart_container_id"] = "repeat-length-chart"
        context["run_choices"] = PipelineRun.objects.order_by("-imported_at", "run_id")
        context["rank_choices"] = [
            {"value": rank, "label": rank}
            for rank in ALLOWED_STATS_RANKS
        ]
        context["method_choices"] = facet_choices["methods"]
        context["residue_choices"] = facet_choices["residues"]
        context["scope_items"] = self._scope_items()
        context["reset_url"] = reverse("browser:lengths")
        context["overview_download_tsv_actions"] = self.get_tsv_download_actions(
            {
                "dataset_key": "overview_typical",
                "label": "Download Typical TSV",
                "available": bool(overview_rows),
            },
            {
                "dataset_key": "overview_tail",
                "label": "Download Tail TSV",
                "available": bool(overview_rows),
            },
        )
        context["browse_download_tsv_actions"] = self.get_tsv_download_actions(
            {
                "dataset_key": "summary",
                "label": "Download Summary TSV",
            }
        )
        context["summary_download_tsv_actions"] = self.get_tsv_download_actions(
            {
                "dataset_key": "summary",
                "label": "Download Summary TSV",
            }
        )
        context["inspect_scope_active"] = self._inspect_scope_active()
        inspect_bundle = self._get_inspect_bundle()
        if inspect_bundle is not None:
            context["inspect_download_tsv_actions"] = self.get_tsv_download_actions(
                {
                    "dataset_key": "inspect",
                    "label": "Download Inspect TSV",
                }
            )
            context["inspect_payload"] = self._build_payload(
                StatsPayloadType.REPEAT_LENGTH_INSPECT,
                lambda: build_length_inspect_payload(
                    inspect_bundle,
                    scope_label=self._inspect_scope_label(),
                ),
            )
            context["inspect_payload_id"] = "length-inspect-payload"
            context["inspect_chart_container_id"] = "length-inspect-chart"
            context["inspect_observation_count"] = inspect_bundle["observation_count"]
            context["inspect_median"] = inspect_bundle["median"]
            context["inspect_q90"] = inspect_bundle["q90"]
            context["inspect_q95"] = inspect_bundle["q95"]
            context["inspect_max"] = inspect_bundle["max"]
            context["inspect_empty_reason"] = (
                "No canonical repeat calls matched the current branch scope."
                if inspect_bundle["observation_count"] == 0
                else ""
            )
        context["summary_empty_reason"] = (
            "No taxa reached the current display rank and minimum observation threshold."
            if context["matching_repeat_calls_count"] > 0 and not summary_rows
            else "No canonical repeat calls matched these filters."
        )
        return context
