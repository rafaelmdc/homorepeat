from math import log2

from .summaries import build_tail_pairwise_matrix, build_wasserstein_pairwise_matrix


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


def build_typical_length_overview_payload(profile_rows):
    if not profile_rows:
        return _build_pairwise_overview_payload(
            [],
            mode="pairwise_similarity_matrix",
            divergence_matrix=[],
            value_min=0,
            value_max=1,
            display_metric="divergence",
            include_display_metric_when_empty=True,
        )
    divergence_matrix = build_wasserstein_pairwise_matrix(profile_rows)
    value_min, value_max = _matrix_value_range(divergence_matrix, default_min=0, default_max=1)
    return _build_pairwise_overview_payload(
        profile_rows,
        mode="pairwise_similarity_matrix",
        divergence_matrix=divergence_matrix,
        value_min=value_min,
        value_max=value_max,
        display_metric="divergence",
        extra_taxon_fields=("columnIndex",),
    )


def build_tail_burden_overview_payload(profile_rows):
    if not profile_rows:
        return _build_pairwise_overview_payload(
            [],
            mode="pairwise_similarity_matrix",
            divergence_matrix=[],
            value_min=0,
            value_max=1,
            display_metric="divergence",
            include_display_metric_when_empty=True,
        )
    divergence_matrix = build_tail_pairwise_matrix(profile_rows)
    value_min, value_max = _matrix_value_range(divergence_matrix, default_min=0, default_max=1)
    return _build_pairwise_overview_payload(
        profile_rows,
        mode="pairwise_similarity_matrix",
        divergence_matrix=divergence_matrix,
        value_min=value_min,
        value_max=value_max,
        display_metric="divergence",
        extra_taxon_fields=("columnIndex",),
    )


def build_codon_similarity_matrix_payload(summary_rows, *, visible_codons=None, display_metric="similarity"):
    if not summary_rows:
        return _build_pairwise_overview_payload(
            [],
            mode="pairwise_similarity_matrix",
            divergence_matrix=[],
            value_min=0,
            value_max=1,
            visible_codons=visible_codons,
            display_metric=display_metric,
            include_display_metric_when_empty=True,
        )

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

    return _build_pairwise_overview_payload(
        taxon_rows,
        mode="pairwise_similarity_matrix",
        divergence_matrix=divergence_matrix,
        value_min=value_min,
        value_max=value_max,
        visible_codons=visible_codons,
        display_metric=display_metric,
        extra_taxon_fields=("columnIndex",),
    )


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
    return _build_pairwise_overview_payload(
        taxon_rows,
        mode="signed_preference_map",
        divergence_matrix=divergence_matrix,
        value_min=-bounded_max_abs_score,
        value_max=bounded_max_abs_score,
        visible_codons=visible_codons,
        display_metric="signed_difference",
        extra_payload={
            "codonOne": codon_one,
            "codonTwo": codon_two,
            "scoreLabel": f"{codon_two} - {codon_one}",
        },
        extra_taxon_fields=("score", "codonOneShare", "codonTwoShare"),
    )


def build_length_inspect_payload(bundle, *, scope_label: str):
    if not bundle or bundle.get("observation_count", 0) == 0:
        return {
            "scopeLabel": scope_label,
            "observationCount": 0,
            "ccdfPoints": [],
            "median": None,
            "q90": None,
            "q95": None,
            "max": None,
        }
    return {
        "scopeLabel": scope_label,
        "observationCount": bundle["observation_count"],
        "ccdfPoints": bundle["ccdf_points"],
        "median": bundle["median"],
        "q90": bundle["q90"],
        "q95": bundle["q95"],
        "max": bundle["max"],
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


def _build_pairwise_overview_payload(
    taxon_rows,
    *,
    mode,
    divergence_matrix,
    value_min,
    value_max,
    visible_codons=None,
    display_metric=None,
    include_display_metric_when_empty=False,
    extra_payload=None,
    extra_taxon_fields=(),
):
    payload = {
        "mode": mode,
        "visibleCodons": list(visible_codons or []),
        "taxa": [],
        "divergenceMatrix": divergence_matrix,
        "visibleTaxaCount": len(taxon_rows),
        "maxObservationCount": 0,
        "maxSpeciesCount": 0,
        "valueMin": value_min,
        "valueMax": value_max,
        **(extra_payload or {}),
    }
    if display_metric is not None and (taxon_rows or include_display_metric_when_empty):
        payload["displayMetric"] = display_metric
    if not taxon_rows:
        return payload

    payload["taxa"] = [
        {
            "taxonId": row.get("taxon_id", row.get("taxonId")),
            "taxonName": row.get("taxon_name", row.get("taxonName")),
            "rank": row["rank"],
            "observationCount": row.get("observation_count", row.get("observationCount")),
            "speciesCount": row.get("species_count", row.get("speciesCount")),
            "rowIndex": index,
            **{
                field_name: (
                    index
                    if field_name == "columnIndex"
                    else row[field_name]
                )
                for field_name in extra_taxon_fields
            },
        }
        for index, row in enumerate(taxon_rows)
    ]
    payload["maxObservationCount"] = max(
        row.get("observation_count", row.get("observationCount"))
        for row in taxon_rows
    )
    payload["maxSpeciesCount"] = max(
        row.get("species_count", row.get("speciesCount"))
        for row in taxon_rows
    )
    return payload


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
