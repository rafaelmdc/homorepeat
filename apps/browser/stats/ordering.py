from __future__ import annotations

from collections import defaultdict

from ..models import TaxonClosure


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
        lineage_parts[closure_row.descendant_id].append(closure_row.ancestor.taxon_id)
    return {
        taxon_id: tuple(parts)
        for taxon_id, parts in lineage_parts.items()
    }


def _taxon_id_for_row(row):
    return row.get("taxon_id", row.get("display_taxon_id"))


def _taxon_name_for_row(row):
    return row.get("taxon_name", row.get("display_taxon_name", ""))
