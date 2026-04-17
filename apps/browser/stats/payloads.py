from .bins import build_visible_length_bins
from .ordering import order_taxon_rows_by_lineage


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


def build_ranked_codon_chart_payload(summary_rows):
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
                "min": row["min_codon_ratio"],
                "q1": row["q1"],
                "median": row["median"],
                "q3": row["q3"],
                "max": row["max_codon_ratio"],
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
        "x_min": min(row["min_codon_ratio"] for row in summary_rows),
        "x_max": max(row["max_codon_ratio"] for row in summary_rows),
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

    taxon_rows = order_taxon_rows_by_lineage(
        [
            {
                "taxon_id": row["taxon_id"],
                "taxon_name": row["taxon_name"],
                "rank": row["rank"],
                "observation_count": row["observation_count"],
                "codon_shares": row["codon_shares"],
            }
            for row in summary_rows
        ]
    )
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


def build_codon_heatmap_payload(summary_rows):
    if not summary_rows:
        return {
            "taxa": [],
            "bins": [],
            "cells": [],
            "seriesData": [],
            "visibleTaxaCount": 0,
            "visibleBinCount": 0,
            "maxObservationCount": 0,
            "valueMin": 0,
            "valueMax": 0,
        }

    taxon_rows = order_taxon_rows_by_lineage(
        list(
            {
                row["taxon_id"]: {
                    "taxon_id": row["taxon_id"],
                    "taxon_name": row["taxon_name"],
                    "rank": row["rank"],
                    "observation_count": row["taxon_observation_count"],
                }
                for row in summary_rows
            }.values()
        )
    )
    visible_bins = build_visible_length_bins(row["length_bin_start"] for row in summary_rows)
    taxon_index_by_id = {
        row["taxon_id"]: index
        for index, row in enumerate(taxon_rows)
    }
    bin_index_by_start = {
        length_bin.start: index
        for index, length_bin in enumerate(visible_bins)
    }

    cells = sorted(
        [
            {
                "taxonId": row["taxon_id"],
                "taxonName": row["taxon_name"],
                "rank": row["rank"],
                "taxonIndex": taxon_index_by_id[row["taxon_id"]],
                "binKey": row["length_bin_key"],
                "binLabel": row["length_bin_label"],
                "binStart": row["length_bin_start"],
                "binEnd": row["length_bin_end"],
                "binIndex": bin_index_by_start[row["length_bin_start"]],
                "observationCount": row["observation_count"],
                "min": row["min_codon_ratio"],
                "q1": row["q1"],
                "median": row["median"],
                "q3": row["q3"],
                "max": row["max_codon_ratio"],
                "value": row["median"],
            }
            for row in summary_rows
        ],
        key=lambda row: (row["taxonIndex"], row["binIndex"]),
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
        "bins": [
            {
                "key": length_bin.key,
                "label": length_bin.label,
                "start": length_bin.start,
                "end": length_bin.end,
                "columnIndex": index,
            }
            for index, length_bin in enumerate(visible_bins)
        ],
        "cells": cells,
        "seriesData": [
            [cell["binIndex"], cell["taxonIndex"], cell["value"]]
            for cell in cells
        ],
        "visibleTaxaCount": len(taxon_rows),
        "visibleBinCount": len(visible_bins),
        "maxObservationCount": max(cell["observationCount"] for cell in cells),
        "valueMin": min(cell["value"] for cell in cells),
        "valueMax": max(cell["value"] for cell in cells),
    }


def build_codon_inspect_payload(bundle, *, scope_label: str):
    summary = bundle.get("summary") if bundle else None
    histogram_bins = bundle.get("histogram_bins") if bundle else []
    observation_count = bundle.get("observation_count", 0) if bundle else 0

    if not summary:
        return {
            "scopeLabel": scope_label,
            "observationCount": observation_count,
            "summary": None,
            "histogramBins": [],
            "xMin": 0,
            "xMax": 0,
            "maxBinCount": 0,
        }

    return {
        "scopeLabel": scope_label,
        "observationCount": observation_count,
        "summary": {
            "min": summary["min_codon_ratio"],
            "q1": summary["q1"],
            "median": summary["median"],
            "q3": summary["q3"],
            "max": summary["max_codon_ratio"],
        },
        "histogramBins": [
            {
                "label": histogram_bin["label"],
                "start": histogram_bin["start"],
                "end": histogram_bin["end"],
                "count": histogram_bin["count"],
                "midpoint": histogram_bin["midpoint"],
            }
            for histogram_bin in histogram_bins
        ],
        "xMin": summary["min_codon_ratio"],
        "xMax": summary["max_codon_ratio"],
        "maxBinCount": max((histogram_bin["count"] for histogram_bin in histogram_bins), default=0),
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
