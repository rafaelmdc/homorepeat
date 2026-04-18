def build_ranked_length_chart_payload(summary_rows):
    if not summary_rows:
        return {
            "rows": [],
            "visibleTaxaCount": 0,
            "x_min": 0,
            "x_max": 0,
            "max_observation_count": 0,
        }

    return {
        "rows": [
            {
                "taxonId": row["taxon_id"],
                "taxonName": row["taxon_name"],
                "rank": row["rank"],
                "observationCount": row["observation_count"],
                "min": row["min_length"],
                "q1": row["q1"],
                "median": row["median"],
                "q3": row["q3"],
                "max": row["max_length"],
                **(
                    {"taxonDetailUrl": row["taxon_detail_url"]}
                    if row.get("taxon_detail_url")
                    else {}
                ),
                **(
                    {"branchExplorerUrl": row["branch_explorer_url"]}
                    if row.get("branch_explorer_url")
                    else {}
                ),
            }
            for row in summary_rows
        ],
        "visibleTaxaCount": len(summary_rows),
        "x_min": min(row["min_length"] for row in summary_rows),
        "x_max": max(row["max_length"] for row in summary_rows),
        "max_observation_count": max(row["observation_count"] for row in summary_rows),
    }

def build_ranked_codon_composition_chart_payload(summary_rows, *, visible_codons):
    if not summary_rows or not visible_codons:
        return {
            "rows": [],
            "visibleTaxaCount": 0,
            "visibleCodons": list(visible_codons),
            "maxObservationCount": 0,
        }

    return {
        "rows": [
            {
                "taxonId": row["taxon_id"],
                "taxonName": row["taxon_name"],
                "rank": row["rank"],
                "observationCount": row["observation_count"],
                "codonShares": [share_row["share"] for share_row in row["codon_shares"]],
                **(
                    {"taxonDetailUrl": row["taxon_detail_url"]}
                    if row.get("taxon_detail_url")
                    else {}
                ),
                **(
                    {"branchExplorerUrl": row["branch_explorer_url"]}
                    if row.get("branch_explorer_url")
                    else {}
                ),
            }
            for row in summary_rows
        ],
        "visibleTaxaCount": len(summary_rows),
        "visibleCodons": list(visible_codons),
        "maxObservationCount": max(row["observation_count"] for row in summary_rows),
    }


def build_codon_composition_heatmap_payload(summary_rows, *, visible_codons):
    if not summary_rows or not visible_codons:
        return {
            "taxa": [],
            "codons": [],
            "cells": [],
            "seriesData": [],
            "visibleTaxaCount": 0,
            "visibleCodonCount": 0,
            "maxObservationCount": 0,
            "valueMin": 0,
            "valueMax": 0,
        }

    taxon_rows = [
        {
            "taxon_id": row["taxon_id"],
            "taxon_name": row["taxon_name"],
            "rank": row["rank"],
            "observation_count": row["observation_count"],
            "codon_shares": row["codon_shares"],
        }
        for row in summary_rows
    ]
    taxon_index_by_id = {
        row["taxon_id"]: index
        for index, row in enumerate(taxon_rows)
    }
    codon_index_by_value = {
        codon: index
        for index, codon in enumerate(visible_codons)
    }

    cells = sorted(
        [
            {
                "taxonId": row["taxon_id"],
                "taxonName": row["taxon_name"],
                "rank": row["rank"],
                "taxonIndex": taxon_index_by_id[row["taxon_id"]],
                "codon": share_row["codon"],
                "codonIndex": codon_index_by_value[share_row["codon"]],
                "observationCount": row["observation_count"],
                "value": share_row["share"],
            }
            for row in taxon_rows
            for share_row in row["codon_shares"]
        ],
        key=lambda row: (row["taxonIndex"], row["codonIndex"]),
    )

    return {
        "taxa": [
            {
                "taxonId": row["taxon_id"],
                "taxonName": row["taxon_name"],
                "rank": row["rank"],
                "observationCount": row["observation_count"],
                "rowIndex": index,
            }
            for index, row in enumerate(taxon_rows)
        ],
        "codons": [
            {
                "codon": codon,
                "columnIndex": index,
            }
            for index, codon in enumerate(visible_codons)
        ],
        "cells": cells,
        "seriesData": [
            [cell["codonIndex"], cell["taxonIndex"], cell["value"]]
            for cell in cells
        ],
        "visibleTaxaCount": len(taxon_rows),
        "visibleCodonCount": len(visible_codons),
        "maxObservationCount": max(cell["observationCount"] for cell in cells),
        "valueMin": min(cell["value"] for cell in cells),
        "valueMax": max(cell["value"] for cell in cells),
    }


def build_codon_composition_inspect_payload(bundle, *, scope_label: str):
    visible_codons = bundle.get("visible_codons", []) if bundle else []
    codon_shares = bundle.get("codon_shares", []) if bundle else []
    observation_count = bundle.get("observation_count", 0) if bundle else 0

    return {
        "scopeLabel": scope_label,
        "observationCount": observation_count,
        "visibleCodons": list(visible_codons),
        "codonShares": [
            {
                "codon": row["codon"],
                "share": row["share"],
            }
            for row in codon_shares
        ],
        "maxShare": max((row["share"] for row in codon_shares), default=0),
    }
