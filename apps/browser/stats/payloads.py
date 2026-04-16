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
