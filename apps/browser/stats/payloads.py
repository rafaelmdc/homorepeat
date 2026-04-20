from math import log2


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
                "speciesCount": row.get("species_count", row["observation_count"]),
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


def build_codon_overview_payload(summary_rows, *, visible_codons):
    if len(visible_codons) == 2:
        return build_two_codon_preference_map_payload(
            summary_rows,
            visible_codons=visible_codons,
        )
    return build_codon_similarity_matrix_payload(summary_rows, visible_codons=visible_codons)


def build_codon_similarity_matrix_payload(summary_rows, *, visible_codons=None, display_metric="similarity"):
    if not summary_rows:
        return {
            "mode": "pairwise_similarity_matrix",
            "displayMetric": display_metric,
            "visibleCodons": list(visible_codons or []),
            "taxa": [],
            "divergenceMatrix": [],
            "visibleTaxaCount": 0,
            "maxObservationCount": 0,
            "maxSpeciesCount": 0,
            "valueMin": 0,
            "valueMax": 1,
        }

    taxon_rows = [
        {
            "taxon_id": row["taxon_id"],
            "taxon_name": row["taxon_name"],
            "rank": row["rank"],
            "observation_count": row["observation_count"],
            "species_count": row.get("species_count", row["observation_count"]),
            "codon_shares": row["codon_shares"],
        }
        for row in summary_rows
    ]
    divergence_matrix = _build_pairwise_divergence_matrix(
        [
            [share_row["share"] for share_row in row["codon_shares"]]
            for row in taxon_rows
        ]
    )
    value_min, value_max = _matrix_value_range(
        divergence_matrix,
        transform=(
            None
            if display_metric == "divergence"
            else lambda value: round(max(0.0, 1.0 - value), 6)
        ),
        default_min=0,
        default_max=1,
    )

    return {
        "mode": "pairwise_similarity_matrix",
        "displayMetric": display_metric,
        "visibleCodons": list(visible_codons or []),
        "taxa": [
            {
                "taxonId": row["taxon_id"],
                "taxonName": row["taxon_name"],
                "rank": row["rank"],
                "observationCount": row["observation_count"],
                "speciesCount": row["species_count"],
                "rowIndex": index,
                "columnIndex": index,
            }
            for index, row in enumerate(taxon_rows)
        ],
        "divergenceMatrix": divergence_matrix,
        "visibleTaxaCount": len(taxon_rows),
        "maxObservationCount": max(row["observation_count"] for row in taxon_rows),
        "maxSpeciesCount": max(row["species_count"] for row in taxon_rows),
        "valueMin": value_min,
        "valueMax": value_max,
    }


def build_two_codon_preference_map_payload(summary_rows, *, visible_codons):
    codon_one, codon_two = visible_codons
    if not summary_rows:
        return {
            "mode": "signed_preference_map",
            "visibleCodons": list(visible_codons),
            "codonOne": codon_one,
            "codonTwo": codon_two,
            "scoreLabel": f"{codon_two} - {codon_one}",
            "taxa": [],
            "divergenceMatrix": [],
            "visibleTaxaCount": 0,
            "maxObservationCount": 0,
            "maxSpeciesCount": 0,
            "valueMin": -1,
            "valueMax": 1,
        }

    taxon_rows = []
    for row in summary_rows:
        shares_by_codon = {
            share_row["codon"]: share_row["share"]
            for share_row in row["codon_shares"]
        }
        codon_one_share = shares_by_codon.get(codon_one, 0)
        codon_two_share = shares_by_codon.get(codon_two, 0)
        score = round(codon_two_share - codon_one_share, 6)
        taxon_rows.append(
            {
                "taxonId": row["taxon_id"],
                "taxonName": row["taxon_name"],
                "rank": row["rank"],
                "observationCount": row["observation_count"],
                "speciesCount": row.get("species_count", row["observation_count"]),
                "codonOne": codon_one,
                "codonOneShare": codon_one_share,
                "codonTwo": codon_two,
                "codonTwoShare": codon_two_share,
                "score": score,
            }
        )

    divergence_matrix = _build_pairwise_divergence_matrix(
        [
            [row["codonOneShare"], row["codonTwoShare"]]
            for row in taxon_rows
        ]
    )
    scores = [row["score"] for row in taxon_rows]
    bounded_max_abs_score = round(max(max(scores) - min(scores), 0.05), 6)
    return {
        "mode": "signed_preference_map",
        "visibleCodons": list(visible_codons),
        "codonOne": codon_one,
        "codonTwo": codon_two,
        "scoreLabel": f"{codon_two} - {codon_one}",
        "displayMetric": "signed_difference",
        "taxa": [
            {
                "taxonId": row["taxonId"],
                "taxonName": row["taxonName"],
                "rank": row["rank"],
                "observationCount": row["observationCount"],
                "speciesCount": row["speciesCount"],
                "score": row["score"],
                "codonOneShare": row["codonOneShare"],
                "codonTwoShare": row["codonTwoShare"],
                "rowIndex": index,
            }
            for index, row in enumerate(taxon_rows)
        ],
        "divergenceMatrix": divergence_matrix,
        "visibleTaxaCount": len(taxon_rows),
        "maxObservationCount": max(row["observationCount"] for row in taxon_rows),
        "maxSpeciesCount": max(row["speciesCount"] for row in taxon_rows),
        "valueMin": -bounded_max_abs_score,
        "valueMax": bounded_max_abs_score,
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


def _jensen_shannon_divergence(left_vector, right_vector):
    midpoint = [
        (left_value + right_value) / 2
        for left_value, right_value in zip(left_vector, right_vector, strict=False)
    ]
    return round(
        (
            (_kullback_leibler_divergence(left_vector, midpoint) / 2)
            + (_kullback_leibler_divergence(right_vector, midpoint) / 2)
        ),
        6,
    )


def _build_pairwise_divergence_matrix(vectors):
    return [
        [
            _jensen_shannon_divergence(row_vector, column_vector)
            for column_vector in vectors
        ]
        for row_vector in vectors
    ]


def _matrix_value_range(matrix, *, transform=None, default_min=0, default_max=1):
    minimum_value = None
    maximum_value = None
    for row in matrix:
        for value in row:
            resolved_value = transform(value) if transform is not None else value
            if minimum_value is None or resolved_value < minimum_value:
                minimum_value = resolved_value
            if maximum_value is None or resolved_value > maximum_value:
                maximum_value = resolved_value
    if minimum_value is None or maximum_value is None:
        return default_min, default_max
    return minimum_value, maximum_value


def _kullback_leibler_divergence(left_vector, right_vector):
    divergence = 0.0
    for left_value, right_value in zip(left_vector, right_vector, strict=False):
        if left_value <= 0 or right_value <= 0:
            continue
        divergence += left_value * log2(left_value / right_value)
    return divergence
