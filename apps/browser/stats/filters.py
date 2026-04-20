from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from ..models import PipelineRun, Taxon
from .params import (
    normalize_min_count,
    normalize_rank,
    normalize_residue,
    normalize_text,
    normalize_top_n,
    parse_float,
    parse_non_negative_int,
)


@dataclass(frozen=True)
class StatsFilterState:
    current_run: PipelineRun | None
    current_run_id: str
    branch_scope: dict[str, object]
    current_branch: str
    current_branch_q: str
    current_branch_input: str
    selected_branch_taxon: Taxon | None
    branch_taxa_ids: object
    branch_scope_active: bool
    branch_scope_label: str
    branch_scope_noun: str
    rank: str
    q: str
    method: str
    residue: str
    length_min: int | None
    length_max: int | None
    purity_min: float | None
    purity_max: float | None
    min_count: int
    top_n: int

    def cache_key_data(self) -> dict[str, object]:
        return {
            "run": self.current_run_id,
            "branch": self.current_branch,
            "branch_q": self.current_branch_q,
            "rank": self.rank,
            "q": self.q,
            "method": self.method,
            "residue": self.residue,
            "length_min": self.length_min,
            "length_max": self.length_max,
            "purity_min": self.purity_min,
            "purity_max": self.purity_max,
            "min_count": self.min_count,
            "top_n": self.top_n,
        }

    def cache_key(self) -> str:
        return _hash_cache_key_payload(self.cache_key_data())


def _hash_cache_key_payload(payload_data: dict[str, object]) -> str:
    payload = json.dumps(payload_data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def build_stats_filter_state(request) -> StatsFilterState:
    from apps.browser.views.filters import _resolve_branch_scope, _resolve_current_run

    current_run = _resolve_current_run(request)
    branch_scope = _resolve_branch_scope(request)
    rank = normalize_rank(
        request.GET.get("rank", ""),
        branch_scope_active=bool(branch_scope["branch_scope_active"]),
    )

    return StatsFilterState(
        current_run=current_run,
        current_run_id=current_run.run_id if current_run else "",
        branch_scope=branch_scope,
        current_branch=branch_scope["current_branch"],
        current_branch_q=branch_scope["current_branch_q"],
        current_branch_input=branch_scope["current_branch_input"],
        selected_branch_taxon=branch_scope["selected_branch_taxon"],
        branch_taxa_ids=branch_scope["branch_taxa_ids"],
        branch_scope_active=branch_scope["branch_scope_active"],
        branch_scope_label=branch_scope["branch_scope_label"],
        branch_scope_noun=branch_scope["branch_scope_noun"],
        rank=rank,
        q=normalize_text(request.GET.get("q", "")),
        method=normalize_text(request.GET.get("method", "")),
        residue=normalize_residue(request.GET.get("residue", "")),
        length_min=parse_non_negative_int(request.GET.get("length_min", "")),
        length_max=parse_non_negative_int(request.GET.get("length_max", "")),
        purity_min=parse_float(request.GET.get("purity_min", "")),
        purity_max=parse_float(request.GET.get("purity_max", "")),
        min_count=normalize_min_count(request.GET.get("min_count", "")),
        top_n=normalize_top_n(request.GET.get("top_n", "")),
    )


def apply_stats_filter_context(context: dict[str, object], filter_state: StatsFilterState) -> dict[str, object]:
    context["current_run"] = filter_state.current_run
    context["current_run_id"] = filter_state.current_run_id
    context["current_branch"] = filter_state.current_branch
    context["current_branch_q"] = filter_state.current_branch_q
    context["current_branch_input"] = filter_state.current_branch_input
    context["selected_branch_taxon"] = filter_state.selected_branch_taxon
    context["branch_scope_active"] = filter_state.branch_scope_active
    context["branch_scope_label"] = filter_state.branch_scope_label
    context["branch_scope_noun"] = filter_state.branch_scope_noun
    context["current_rank"] = filter_state.rank
    context["current_q"] = filter_state.q
    context["current_method"] = filter_state.method
    context["current_residue"] = filter_state.residue
    context["current_length_min"] = filter_state.length_min
    context["current_length_max"] = filter_state.length_max
    context["current_purity_min"] = filter_state.purity_min
    context["current_purity_max"] = filter_state.purity_max
    context["current_min_count"] = filter_state.min_count
    context["current_top_n"] = filter_state.top_n
    return context
