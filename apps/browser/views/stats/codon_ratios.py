from django.urls import reverse
from django.views.generic import TemplateView

from apps.browser.stats import (
    apply_stats_filter_context,
    build_available_codon_metric_names,
    build_filtered_repeat_call_queryset,
    build_ranked_codon_chart_payload,
    build_ranked_codon_summary_bundle,
    build_stats_filter_state,
)
from apps.browser.stats.params import ALLOWED_STATS_RANKS, next_lower_rank

from ...metadata import resolve_browser_facets
from ...models import PipelineRun
from ..navigation import _url_with_query


class CodonRatioExplorerView(TemplateView):
    template_name = "browser/codon_ratio_explorer.html"

    def _get_filter_state(self):
        if not hasattr(self, "_filter_state"):
            self._filter_state = build_stats_filter_state(self.request)
        return self._filter_state

    def _get_summary_bundle(self) -> dict[str, object]:
        if not hasattr(self, "_summary_bundle"):
            summary_bundle = build_ranked_codon_summary_bundle(self._get_filter_state())
            self._summary_bundle = {
                **summary_bundle,
                "summary_rows": [self._with_row_links(row) for row in summary_bundle["summary_rows"]],
            }
        return self._summary_bundle

    def _get_matching_repeat_calls_without_codon_count(self) -> int:
        if not hasattr(self, "_matching_repeat_calls_without_codon_count"):
            self._matching_repeat_calls_without_codon_count = build_filtered_repeat_call_queryset(
                self._get_filter_state()
            ).count()
        return self._matching_repeat_calls_without_codon_count

    def _get_facet_choices(self) -> dict[str, list[str]]:
        if not hasattr(self, "_facet_choices"):
            filter_state = self._get_filter_state()
            if filter_state.current_run is not None:
                self._facet_choices = resolve_browser_facets(pipeline_run=filter_state.current_run)
            else:
                self._facet_choices = resolve_browser_facets()
        return self._facet_choices

    def _get_available_codon_metric_names(self) -> list[str]:
        if not hasattr(self, "_available_codon_metric_names"):
            self._available_codon_metric_names = build_available_codon_metric_names(self._get_filter_state())
        return self._available_codon_metric_names

    def _current_codon_metric_scope_label(self) -> str:
        filter_state = self._get_filter_state()
        available_codon_metric_names = self._get_available_codon_metric_names()

        if filter_state.codon_metric_name:
            return filter_state.codon_metric_name
        if len(available_codon_metric_names) == 1:
            return available_codon_metric_names[0]
        if len(available_codon_metric_names) > 1:
            return "All numeric metrics in scope"
        return "Any numeric metric"

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
                "label": "Codon metric",
                "value": self._current_codon_metric_scope_label(),
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
                reverse("browser:codon-ratios"),
                run=filter_state.current_run_id,
                branch=row["taxon_id"],
                rank=drilldown_rank,
                q=filter_state.q,
                method=filter_state.method,
                residue=filter_state.residue,
                codon_metric_name=filter_state.codon_metric_name,
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
        available_codon_metric_names = self._get_available_codon_metric_names()
        matching_repeat_calls_without_codon_count = self._get_matching_repeat_calls_without_codon_count()

        apply_stats_filter_context(context, filter_state)
        context["matching_repeat_calls_count"] = summary_bundle["matching_repeat_calls_count"]
        context["matching_repeat_calls_without_codon_count"] = matching_repeat_calls_without_codon_count
        context["summary_rows"] = summary_rows
        context["total_taxa_count"] = summary_bundle["total_taxa_count"]
        context["visible_taxa_count"] = summary_bundle["visible_taxa_count"]
        context["chart_payload"] = build_ranked_codon_chart_payload(summary_rows)
        context["chart_payload_id"] = "codon-ratio-chart-payload"
        context["chart_container_id"] = "codon-ratio-chart"
        context["run_choices"] = PipelineRun.objects.order_by("-imported_at", "run_id")
        context["rank_choices"] = [
            {"value": rank, "label": rank}
            for rank in ALLOWED_STATS_RANKS
        ]
        context["method_choices"] = facet_choices["methods"]
        context["residue_choices"] = facet_choices["residues"]
        context["available_codon_metric_names"] = available_codon_metric_names
        context["show_codon_metric_selector"] = len(available_codon_metric_names) > 1
        context["scope_items"] = self._scope_items()
        context["reset_url"] = reverse("browser:codon-ratios")
        context["summary_empty_reason"] = self._summary_empty_reason(
            matching_repeat_calls_count=context["matching_repeat_calls_count"],
            matching_repeat_calls_without_codon_count=matching_repeat_calls_without_codon_count,
            has_summary_rows=bool(summary_rows),
        )
        return context

    def _summary_empty_reason(
        self,
        *,
        matching_repeat_calls_count: int,
        matching_repeat_calls_without_codon_count: int,
        has_summary_rows: bool,
    ) -> str:
        filter_state = self._get_filter_state()

        if matching_repeat_calls_count > 0 and not has_summary_rows:
            return "No taxa reached the current display rank and minimum observation threshold."
        if matching_repeat_calls_without_codon_count > 0:
            if filter_state.codon_metric_name:
                return (
                    "Canonical repeat calls matched these filters, but none carried "
                    "numeric values for the selected codon metric."
                )
            return "Canonical repeat calls matched these filters, but none carried numeric codon ratios."
        return "No canonical repeat calls matched these filters."
