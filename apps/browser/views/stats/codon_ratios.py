from django.urls import reverse
from django.views.generic import TemplateView

from apps.browser.stats import (
    apply_stats_filter_context,
    build_codon_composition_heatmap_payload,
    build_codon_composition_inspect_bundle,
    build_codon_composition_inspect_payload,
    build_filtered_codon_usage_queryset,
    build_filtered_repeat_call_queryset,
    build_ranked_codon_composition_chart_payload,
    build_ranked_codon_composition_summary_bundle,
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
            summary_bundle = build_ranked_codon_composition_summary_bundle(self._get_filter_state())
            self._summary_bundle = {
                **summary_bundle,
                "summary_rows": [self._with_row_links(row) for row in summary_bundle["summary_rows"]],
            }
        return self._summary_bundle

    def _get_matching_repeat_calls_with_codon_usage_count(self) -> int:
        if not hasattr(self, "_matching_repeat_calls_with_codon_usage_count"):
            self._matching_repeat_calls_with_codon_usage_count = (
                build_filtered_codon_usage_queryset(self._get_filter_state())
                .values("repeat_call_id")
                .distinct()
                .count()
            )
        return self._matching_repeat_calls_with_codon_usage_count

    def _get_matching_repeat_calls_count(self) -> int:
        if not hasattr(self, "_matching_repeat_calls_count"):
            self._matching_repeat_calls_count = build_filtered_repeat_call_queryset(
                self._get_filter_state()
            ).count()
        return self._matching_repeat_calls_count

    def _inspect_scope_active(self) -> bool:
        return self._get_filter_state().branch_scope_active

    def _get_inspect_bundle(self) -> dict[str, object] | None:
        if not self._inspect_scope_active():
            return None
        if not hasattr(self, "_inspect_bundle"):
            self._inspect_bundle = build_codon_composition_inspect_bundle(self._get_filter_state())
        return self._inspect_bundle

    def _inspect_scope_label(self) -> str:
        filter_state = self._get_filter_state()
        if filter_state.selected_branch_taxon is not None:
            branch_rank = filter_state.selected_branch_taxon.rank or filter_state.branch_scope_noun
            return f"{branch_rank.title()} {filter_state.selected_branch_taxon.taxon_name}"
        if filter_state.branch_scope_active:
            return f"{filter_state.branch_scope_noun.title()} {filter_state.branch_scope_label}"
        return "Current filtered scope"

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
        summary_bundle = self._get_summary_bundle()
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
                "label": "Visible codons",
                "value": ", ".join(summary_bundle["visible_codons"]) or "None in scope",
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
        visible_codons = summary_bundle["visible_codons"]
        matching_repeat_calls_count = self._get_matching_repeat_calls_count()
        matching_repeat_calls_with_codon_usage_count = self._get_matching_repeat_calls_with_codon_usage_count()

        apply_stats_filter_context(context, filter_state)
        context["matching_repeat_calls_count"] = matching_repeat_calls_count
        context["matching_repeat_calls_with_codon_usage_count"] = matching_repeat_calls_with_codon_usage_count
        context["summary_rows"] = summary_rows
        context["visible_codons"] = visible_codons
        context["total_taxa_count"] = summary_bundle["total_taxa_count"]
        context["visible_taxa_count"] = summary_bundle["visible_taxa_count"]
        context["overview_payload"] = build_codon_composition_heatmap_payload(
            summary_rows,
            visible_codons=visible_codons,
        )
        context["overview_payload_id"] = "codon-composition-overview-payload"
        context["overview_container_id"] = "codon-composition-overview"
        context["chart_payload"] = build_ranked_codon_composition_chart_payload(
            summary_rows,
            visible_codons=visible_codons,
        )
        context["chart_payload_id"] = "codon-composition-chart-payload"
        context["chart_container_id"] = "codon-composition-chart"
        context["run_choices"] = PipelineRun.objects.order_by("-imported_at", "run_id")
        context["rank_choices"] = [
            {"value": rank, "label": rank}
            for rank in ALLOWED_STATS_RANKS
        ]
        context["method_choices"] = facet_choices["methods"]
        context["residue_choices"] = facet_choices["residues"]
        context["scope_items"] = self._scope_items()
        context["reset_url"] = reverse("browser:codon-ratios")
        context["inspect_scope_active"] = self._inspect_scope_active()
        inspect_bundle = self._get_inspect_bundle()
        if inspect_bundle is not None:
            context["inspect_payload"] = build_codon_composition_inspect_payload(
                inspect_bundle,
                scope_label=self._inspect_scope_label(),
            )
            context["inspect_visible_codons"] = inspect_bundle["visible_codons"]
            context["inspect_codon_shares"] = inspect_bundle["codon_shares"]
            context["inspect_payload_id"] = "codon-composition-inspect-payload"
            context["inspect_chart_container_id"] = "codon-composition-inspect-chart"
            context["inspect_empty_reason"] = self._inspect_empty_reason(
                observation_count=inspect_bundle["observation_count"],
                has_visible_codons=bool(inspect_bundle["visible_codons"]),
            )
        context["summary_empty_reason"] = self._summary_empty_reason(
            matching_repeat_calls_count=matching_repeat_calls_count,
            matching_repeat_calls_with_codon_usage_count=matching_repeat_calls_with_codon_usage_count,
            has_summary_rows=bool(summary_rows),
        )
        return context

    def _summary_empty_reason(
        self,
        *,
        matching_repeat_calls_count: int,
        matching_repeat_calls_with_codon_usage_count: int,
        has_summary_rows: bool,
    ) -> str:
        filter_state = self._get_filter_state()

        if not filter_state.residue:
            return "Select a residue to browse codon composition."
        if matching_repeat_calls_count > 0 and matching_repeat_calls_with_codon_usage_count == 0:
            return (
                "Canonical repeat calls matched these filters, but no codon-usage rows "
                "were available for the selected residue."
            )
        if matching_repeat_calls_count > 0 and not has_summary_rows:
            return "No taxa reached the current display rank and minimum observation threshold."
        return "No canonical repeat calls matched these filters."

    def _inspect_empty_reason(self, *, observation_count: int, has_visible_codons: bool) -> str:
        filter_state = self._get_filter_state()
        if not filter_state.residue:
            return "Select a residue to inspect codon composition."
        if observation_count == 0:
            return "No canonical repeat calls matched the current branch scope."
        if not has_visible_codons:
            return "No codon-usage rows were available for the selected residue inside the current branch scope."
        return ""
