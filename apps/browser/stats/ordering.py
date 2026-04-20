from __future__ import annotations

from collections import defaultdict

from ..models import TaxonClosure

_METAZOA_BACKBONE = {
    "root": (
        "metazoa",
        "porifera",
        "eumetazoa",
        "cnidaria",
        "bilateria",
        "protostomia",
        "platyhelminthes",
        "nematoda",
        "annelida",
        "mollusca",
        "arthropoda",
        "deuterostomia",
        "echinodermata",
        "chordata",
    ),
    "metazoa": (
        "porifera",
        "eumetazoa",
        "cnidaria",
        "bilateria",
        "protostomia",
        "platyhelminthes",
        "nematoda",
        "annelida",
        "mollusca",
        "arthropoda",
        "deuterostomia",
        "echinodermata",
        "chordata",
    ),
    "eumetazoa": (
        "cnidaria",
        "bilateria",
        "protostomia",
        "platyhelminthes",
        "nematoda",
        "annelida",
        "mollusca",
        "arthropoda",
        "deuterostomia",
        "echinodermata",
        "chordata",
    ),
    "bilateria": (
        "protostomia",
        "platyhelminthes",
        "nematoda",
        "annelida",
        "mollusca",
        "arthropoda",
        "deuterostomia",
        "echinodermata",
        "chordata",
    ),
    "protostomia": (
        "platyhelminthes",
        "nematoda",
        "annelida",
        "mollusca",
        "arthropoda",
    ),
    "deuterostomia": (
        "echinodermata",
        "chordata",
    ),
}
_METAZOA_CHILD_PRIORITIES = {
    ancestor_name: {
        child_name: child_index
        for child_index, child_name in enumerate(children)
    }
    for ancestor_name, children in _METAZOA_BACKBONE.items()
}


def order_taxon_rows_by_lineage(taxon_rows):
    taxon_ids = [_taxon_id_for_row(row) for row in taxon_rows]
    lineage_keys = _build_lineage_sort_keys(taxon_ids)

    return sorted(
        taxon_rows,
        key=lambda row: (
            lineage_keys.get(_taxon_id_for_row(row), (_taxon_id_for_row(row),)),
            _taxon_name_for_row(row).casefold(),
            _taxon_id_for_row(row),
        ),
    )


def _build_lineage_sort_keys(taxon_ids):
    lineage_parts = defaultdict(list)
    closure_rows = (
        TaxonClosure.objects.filter(descendant_id__in=taxon_ids)
        .select_related("ancestor")
        .order_by("descendant_id", "-depth", "ancestor__taxon_name", "ancestor__taxon_id")
    )
    for closure_row in closure_rows:
        lineage_parts[closure_row.descendant_id].append(
            {
                "taxon_id": closure_row.ancestor.taxon_id,
                "taxon_name": closure_row.ancestor.taxon_name,
                "rank": closure_row.ancestor.rank,
            }
        )
    return {
        taxon_id: _lineage_sort_key(parts)
        for taxon_id, parts in lineage_parts.items()
    }


def _taxon_id_for_row(row):
    return row.get("taxon_id", row.get("display_taxon_id"))


def _taxon_name_for_row(row):
    return row.get("taxon_name", row.get("display_taxon_name", ""))


def _lineage_sort_key(lineage_parts):
    if not lineage_parts:
        return ()

    return tuple(
        _child_sort_key(parent_part, child_part)
        for parent_part, child_part in zip(lineage_parts, lineage_parts[1:], strict=False)
    )


def _child_sort_key(parent_part, child_part):
    child_name = _normalized_taxon_name(child_part["taxon_name"])
    child_priority = _curated_child_priority(parent_part, child_name)
    if child_priority is not None:
        return (0, child_priority, child_name, child_part["taxon_id"])
    return (1, child_part["taxon_id"], child_name)


def _curated_child_priority(parent_part, child_name):
    parent_name = _normalized_taxon_name(parent_part["taxon_name"])
    direct_priorities = _METAZOA_CHILD_PRIORITIES.get(parent_name)
    if direct_priorities and child_name in direct_priorities:
        return direct_priorities[child_name]

    if _normalized_taxon_rank(parent_part["rank"]) in {"no rank", "cellular root"}:
        root_priorities = _METAZOA_CHILD_PRIORITIES["root"]
        return root_priorities.get(child_name)
    return None


def _normalized_taxon_name(name):
    return str(name or "").strip().casefold()


def _normalized_taxon_rank(rank):
    return str(rank or "").strip().casefold()
