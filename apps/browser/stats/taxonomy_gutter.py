from __future__ import annotations

import hashlib
import json

from django.db.models import Count

from ..models import Taxon, TaxonClosure
from ._cache import build_or_get_cached
from .filters import StatsFilterState
from .params import ALLOWED_STATS_RANKS, next_lower_rank
from .queries import build_filtered_repeat_call_queryset

_CACHE_VERSION = "v3"
_IRREGULAR_RANK_PLURALS = {
    "family": "families",
    "genus": "genera",
    "phylum": "phyla",
    "species": "species",
}
_ALLOWED_GUTTER_RANKS = set(ALLOWED_STATS_RANKS)


def build_taxonomy_gutter_payload(
    taxon_rows,
    *,
    filter_state: StatsFilterState,
    collapse_rank: str | None = None,
):
    resolved_collapse_rank = _resolve_collapse_rank(collapse_rank, filter_state.rank)
    empty_payload = _empty_taxonomy_gutter_payload(collapse_rank=resolved_collapse_rank)
    if not taxon_rows:
        return empty_payload

    visible_taxon_ids = [row["taxon_id"] for row in taxon_rows]
    cache_key = _taxonomy_gutter_cache_key(
        filter_state=filter_state,
        visible_taxon_ids=visible_taxon_ids,
        collapse_rank=resolved_collapse_rank,
    )
    def _build() -> dict[str, object]:
        ancestor_chains = _build_ancestor_chains(visible_taxon_ids)
        if not ancestor_chains:
            return empty_payload
        root_taxon_id = _lowest_common_ancestor_id(ancestor_chains)
        if root_taxon_id is None:
            return empty_payload
        raw_nodes = _build_raw_visible_tree(
            ancestor_chains=ancestor_chains,
            root_taxon_id=root_taxon_id,
            taxon_rows=taxon_rows,
        )
        _annotate_raw_visible_tree_rows(raw_nodes, root_taxon_id)
        preserved_taxon_ids = _select_preserved_taxa(raw_nodes, root_taxon_id)
        nodes, edges, root_node_id, max_depth = _build_preserved_visible_tree(
            raw_nodes,
            root_taxon_id=root_taxon_id,
            preserved_taxon_ids=preserved_taxon_ids,
        )
        nodes_by_id = {node["nodeId"]: node for node in nodes}
        collapsed_child_rank = _collapsed_child_rank(resolved_collapse_rank)
        child_counts_by_taxon_id = _build_scope_descendant_counts_by_taxon(
            filter_state=filter_state,
            visible_taxon_ids=visible_taxon_ids,
            collapse_rank=resolved_collapse_rank,
            collapsed_child_rank=collapsed_child_rank,
        )
        leaves = []
        for row_index, row in enumerate(taxon_rows):
            taxon_child_count = child_counts_by_taxon_id.get(row["taxon_id"], 0)
            brace_label = _brace_label(taxon_child_count, collapsed_child_rank)
            leaves.append(
                {
                    "nodeId": _node_id(row["taxon_id"]),
                    "axisValue": str(row["taxon_id"]),
                    "rowIndex": row_index,
                    "taxonId": row["taxon_id"],
                    "taxonName": row["taxon_name"],
                    "rank": row["rank"],
                    "branchExplorerUrl": row.get("branch_explorer_url", ""),
                    "taxonDetailUrl": row.get("taxon_detail_url", ""),
                    "braceCount": taxon_child_count,
                    "braceLabel": brace_label,
                    "showBrace": bool(brace_label),
                }
            )
        root_node = nodes_by_id.get(root_node_id)
        return {
            "root": {
                "nodeId": root_node["nodeId"],
                "taxonId": root_node["taxonId"],
                "taxonName": root_node["taxonName"],
                "rank": root_node["rank"],
                "depth": root_node["depth"],
            }
            if root_node
            else None,
            "nodes": nodes,
            "edges": edges,
            "leaves": leaves,
            "maxDepth": max_depth,
            "collapseRank": resolved_collapse_rank,
            "collapsedChildRank": collapsed_child_rank,
        }
    return build_or_get_cached(cache_key, _build)


def _empty_taxonomy_gutter_payload(*, collapse_rank: str):
    return {
        "root": None,
        "nodes": [],
        "edges": [],
        "leaves": [],
        "maxDepth": 0,
        "collapseRank": collapse_rank,
        "collapsedChildRank": _collapsed_child_rank(collapse_rank),
    }


def _taxonomy_gutter_cache_key(*, filter_state: StatsFilterState, visible_taxon_ids, collapse_rank: str) -> str:
    payload = json.dumps(
        {
            "version": _CACHE_VERSION,
            "filter_state": filter_state.cache_key_data(),
            "visible_taxon_ids": list(visible_taxon_ids),
            "collapse_rank": collapse_rank,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"browser:stats:taxonomy-gutter:{hashlib.sha1(payload.encode('utf-8')).hexdigest()}"


def _resolve_collapse_rank(collapse_rank: str | None, default_rank: str) -> str:
    candidate = (collapse_rank or default_rank or "").strip().lower()
    if candidate in ALLOWED_STATS_RANKS:
        return candidate
    return default_rank


def _collapsed_child_rank(collapse_rank: str) -> str | None:
    if collapse_rank not in ALLOWED_STATS_RANKS:
        return None
    if collapse_rank == ALLOWED_STATS_RANKS[-1]:
        return None
    next_rank = next_lower_rank(collapse_rank)
    return next_rank if next_rank != collapse_rank else None


def _build_ancestor_chains(visible_taxon_ids):
    ancestor_chains = {}
    closure_rows = (
        TaxonClosure.objects.filter(descendant_id__in=visible_taxon_ids)
        .select_related("ancestor")
        .order_by("descendant_id", "-depth", "ancestor__taxon_id")
    )
    for closure_row in closure_rows:
        ancestor_chains.setdefault(closure_row.descendant_id, []).append(
            {
                "taxonId": closure_row.ancestor_id,
                "taxonName": closure_row.ancestor.taxon_name,
                "rank": closure_row.ancestor.rank,
            }
        )
    return ancestor_chains


def _lowest_common_ancestor_id(ancestor_chains):
    if not ancestor_chains:
        return None

    ordered_chains = list(ancestor_chains.values())
    first_chain = ordered_chains[0]
    if not first_chain:
        return None

    other_taxon_id_sets = [
        {node["taxonId"] for node in chain}
        for chain in ordered_chains[1:]
    ]
    lowest_common_ancestor_id = first_chain[0]["taxonId"]
    for node in first_chain:
        if all(node["taxonId"] in taxon_id_set for taxon_id_set in other_taxon_id_sets):
            lowest_common_ancestor_id = node["taxonId"]
            continue
        break
    return lowest_common_ancestor_id


def _build_raw_visible_tree(*, ancestor_chains, root_taxon_id: int, taxon_rows):
    leaf_row_index_by_taxon_id = {
        row["taxon_id"]: row_index
        for row_index, row in enumerate(taxon_rows)
    }
    raw_nodes = {}

    for visible_taxon_id, chain in ancestor_chains.items():
        path = _project_browser_rank_path(
            _path_from_root_taxon(chain, root_taxon_id),
            root_taxon_id=root_taxon_id,
            visible_taxon_id=visible_taxon_id,
        )
        if not path:
            continue

        for index, taxon_detail in enumerate(path):
            raw_node = raw_nodes.setdefault(
                taxon_detail["taxonId"],
                {
                    "taxonId": taxon_detail["taxonId"],
                    "taxonName": taxon_detail["taxonName"],
                    "rank": taxon_detail["rank"],
                    "parentTaxonId": None,
                    "childTaxonIds": set(),
                    "orderedChildTaxonIds": [],
                    "isVisibleLeaf": False,
                    "leafRowIndex": None,
                    "rowStart": None,
                    "rowEnd": None,
                },
            )

            if index > 0:
                parent_taxon_id = path[index - 1]["taxonId"]
                raw_nodes[parent_taxon_id]["childTaxonIds"].add(taxon_detail["taxonId"])
                raw_node["parentTaxonId"] = parent_taxon_id

        leaf_node = raw_nodes.get(visible_taxon_id)
        if leaf_node is not None:
            leaf_node["isVisibleLeaf"] = True
            leaf_node["leafRowIndex"] = leaf_row_index_by_taxon_id[visible_taxon_id]

    return raw_nodes


def _path_from_root_taxon(chain, root_taxon_id: int):
    for index, taxon_detail in enumerate(chain):
        if taxon_detail["taxonId"] == root_taxon_id:
            return chain[index:]
    return []


def _project_browser_rank_path(path, *, root_taxon_id: int, visible_taxon_id: int):
    projected_path = []
    for taxon_detail in path:
        if (
            taxon_detail["taxonId"] != root_taxon_id
            and taxon_detail["taxonId"] != visible_taxon_id
            and taxon_detail["rank"] not in _ALLOWED_GUTTER_RANKS
        ):
            continue
        if projected_path and projected_path[-1]["taxonId"] == taxon_detail["taxonId"]:
            continue
        projected_path.append(taxon_detail)
    return projected_path


def _annotate_raw_visible_tree_rows(raw_nodes, root_taxon_id: int):
    def walk(taxon_id: int):
        raw_node = raw_nodes[taxon_id]
        if raw_node["isVisibleLeaf"]:
            raw_node["rowStart"] = raw_node["leafRowIndex"]
            raw_node["rowEnd"] = raw_node["leafRowIndex"]
            raw_node["orderedChildTaxonIds"] = []
            return raw_node["rowStart"], raw_node["rowEnd"]

        child_bounds = []
        for child_taxon_id in raw_node["childTaxonIds"]:
            child_bounds.append((child_taxon_id, *walk(child_taxon_id)))

        ordered_children = sorted(
            child_bounds,
            key=lambda row: (
                row[1],
                raw_nodes[row[0]]["taxonName"].casefold(),
                row[0],
            ),
        )
        raw_node["orderedChildTaxonIds"] = [row[0] for row in ordered_children]
        raw_node["rowStart"] = min(row[1] for row in ordered_children)
        raw_node["rowEnd"] = max(row[2] for row in ordered_children)
        return raw_node["rowStart"], raw_node["rowEnd"]

    walk(root_taxon_id)


def _select_preserved_taxa(raw_nodes, root_taxon_id: int):
    branching_taxon_ids = {
        taxon_id
        for taxon_id, raw_node in raw_nodes.items()
        if len(raw_node["orderedChildTaxonIds"]) >= 2
    }
    preserved_taxon_ids = {root_taxon_id}
    preserved_taxon_ids.update(
        taxon_id
        for taxon_id, raw_node in raw_nodes.items()
        if raw_node["isVisibleLeaf"]
    )
    preserved_taxon_ids.update(branching_taxon_ids)
    for branching_taxon_id in branching_taxon_ids:
        preserved_taxon_ids.update(raw_nodes[branching_taxon_id]["orderedChildTaxonIds"])
    return preserved_taxon_ids


def _build_preserved_visible_tree(raw_nodes, *, root_taxon_id: int, preserved_taxon_ids):
    nodes = []
    edges = []
    max_depth = 0

    def visit(taxon_id: int, *, parent_node_id: str | None, depth: int):
        nonlocal max_depth

        raw_node = raw_nodes[taxon_id]
        node_id = _node_id(taxon_id)
        child_taxon_ids = _preserved_children(raw_nodes, taxon_id, preserved_taxon_ids)
        nodes.append(
            {
                "nodeId": node_id,
                "taxonId": raw_node["taxonId"],
                "taxonName": raw_node["taxonName"],
                "rank": raw_node["rank"],
                "parentNodeId": parent_node_id,
                "depth": depth,
                "isLeaf": raw_node["isVisibleLeaf"],
                "isPreservedSplit": len(child_taxon_ids) >= 2,
                "rowStart": raw_node["rowStart"],
                "rowEnd": raw_node["rowEnd"],
            }
        )
        max_depth = max(max_depth, depth)

        for child_taxon_id in child_taxon_ids:
            child_node_id = _node_id(child_taxon_id)
            edges.append(
                {
                    "parentNodeId": node_id,
                    "childNodeId": child_node_id,
                }
            )
            visit(child_taxon_id, parent_node_id=node_id, depth=depth + 1)

    visit(root_taxon_id, parent_node_id=None, depth=0)
    return nodes, edges, _node_id(root_taxon_id), max_depth


def _preserved_children(raw_nodes, taxon_id: int, preserved_taxon_ids):
    preserved_child_taxon_ids = []
    for child_taxon_id in raw_nodes[taxon_id]["orderedChildTaxonIds"]:
        preserved_child_taxon_ids.extend(
            _first_preserved_descendants(raw_nodes, child_taxon_id, preserved_taxon_ids)
        )
    return preserved_child_taxon_ids


def _first_preserved_descendants(raw_nodes, taxon_id: int, preserved_taxon_ids):
    if taxon_id in preserved_taxon_ids:
        return [taxon_id]

    preserved_descendants = []
    for child_taxon_id in raw_nodes[taxon_id]["orderedChildTaxonIds"]:
        preserved_descendants.extend(
            _first_preserved_descendants(raw_nodes, child_taxon_id, preserved_taxon_ids)
        )
    return preserved_descendants


def _build_scope_descendant_counts_by_taxon(
    *,
    filter_state: StatsFilterState,
    visible_taxon_ids,
    collapse_rank: str,
    collapsed_child_rank: str | None,
):
    if not visible_taxon_ids or not collapsed_child_rank:
        return {}

    filtered_taxon_ids = build_filtered_repeat_call_queryset(filter_state).order_by().values_list(
        "taxon_id",
        flat=True,
    ).distinct()
    if not filtered_taxon_ids:
        return {}

    count_rows = (
        Taxon.objects.filter(
            rank=collapsed_child_rank,
            closure_descendants__descendant_id__in=filtered_taxon_ids,
            closure_ancestors__ancestor_id__in=visible_taxon_ids,
            closure_ancestors__ancestor__rank=collapse_rank,
        )
        .values("closure_ancestors__ancestor_id")
        .annotate(descendant_count=Count("pk", distinct=True))
    )
    return {
        row["closure_ancestors__ancestor_id"]: row["descendant_count"]
        for row in count_rows
    }


def _node_id(taxon_id: int) -> str:
    return f"taxon-{taxon_id}"


def _brace_label(count: int, child_rank: str | None) -> str:
    if count < 1 or not child_rank:
        return ""
    label = child_rank if count == 1 else _IRREGULAR_RANK_PLURALS.get(child_rank, f"{child_rank}s")
    return f"{count} {label}"
