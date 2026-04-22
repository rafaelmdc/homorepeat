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


def build_codon_length_inspect_payload(
    bundle,
    *,
    scope_label: str,
    comparison_bundle=None,
    comparison_scope_label: str = "",
) -> dict:
    observation_count = bundle.get("observation_count", 0) if bundle else 0
    visible_codons = list(bundle.get("visible_codons", [])) if bundle else []
    bin_rows = list(bundle.get("bin_rows", [])) if bundle else []

    if observation_count == 0 or not bin_rows:
        return {
            "scopeLabel": scope_label,
            "observationCount": observation_count,
            "available": False,
            "visibleCodons": visible_codons,
            "visibleBins": list(bundle.get("visible_bins", [])) if bundle else [],
            "binRows": [],
        }

    payload_bin_rows = _build_inspect_bin_rows(bin_rows, visible_codons)

    result = {
        "scopeLabel": scope_label,
        "observationCount": observation_count,
        "available": True,
        "visibleCodons": visible_codons,
        "visibleBins": list(bundle.get("visible_bins", [])),
        "binRows": payload_bin_rows,
        "maxObservationCount": max((row["observation_count"] for row in bin_rows), default=0),
    }

    if comparison_bundle and comparison_bundle.get("bin_rows"):
        comparison_bin_rows = _build_inspect_bin_rows(
            comparison_bundle["bin_rows"],
            visible_codons,
        )
        if comparison_bin_rows:
            result["comparisonBinRows"] = comparison_bin_rows
            result["comparisonScopeLabel"] = comparison_scope_label
            result["comparisonObservationCount"] = comparison_bundle.get("observation_count", 0)

    return result


def _build_inspect_bin_rows(bin_rows: list, visible_codons: list) -> list:
    payload_bin_rows = []
    previous_shares: dict[str, float] | None = None
    for bin_row in bin_rows:
        current_shares = {s["codon"]: s["share"] for s in bin_row["codon_shares"]}
        delta = None
        if previous_shares is not None:
            if len(visible_codons) == 2:
                codon_a = visible_codons[0]
                delta = round(abs(current_shares.get(codon_a, 0) - previous_shares.get(codon_a, 0)), 6)
            else:
                delta = round(
                    sum(
                        abs(current_shares.get(c, 0) - previous_shares.get(c, 0))
                        for c in visible_codons
                    ),
                    6,
                )
        payload_bin_rows.append(
            {
                "binLabel": bin_row["bin"]["label"],
                "binStart": bin_row["bin"]["start"],
                "observationCount": bin_row["observation_count"],
                "speciesCount": bin_row["species_count"],
                "dominantCodon": bin_row["dominant_codon"],
                "dominanceMargin": round(bin_row["dominance_margin"], 6),
                "codonShares": [
                    {
                        "codon": s["codon"],
                        "share": s["share"],
                        "codonCount": s.get("codon_count", 0),
                    }
                    for s in bin_row["codon_shares"]
                ],
                "delta": delta,
            }
        )
        previous_shares = current_shares
    return payload_bin_rows


def build_codon_length_preference_overview_payload(bundle):
    visible_codons = list(bundle.get("visible_codons", [])) if bundle else []
    matrix_rows = list(bundle.get("matrix_rows", [])) if bundle else []
    if len(visible_codons) != 2:
        return _empty_codon_length_overview_payload(
            "preference",
            visible_codons=visible_codons,
            visible_bins=bundle.get("visible_bins", []) if bundle else [],
            value_min=-1,
            value_max=1,
        )

    codon_a, codon_b = visible_codons
    cells = []
    for row_index, row in enumerate(matrix_rows):
        for bin_row in row["bin_rows"]:
            shares_by_codon = _codon_share_lookup(bin_row)
            preference = round(shares_by_codon.get(codon_a, 0) - shares_by_codon.get(codon_b, 0), 6)
            cells.append(
                {
                    "rowIndex": row_index,
                    "binIndex": _codon_length_bin_index(bundle, bin_row),
                    "binStart": bin_row["bin"]["start"],
                    "binLabel": bin_row["bin"]["label"],
                    "value": preference,
                    "preference": preference,
                    "codonA": codon_a,
                    "codonAShare": shares_by_codon.get(codon_a, 0),
                    "codonB": codon_b,
                    "codonBShare": shares_by_codon.get(codon_b, 0),
                    "codonShares": _codon_length_codon_shares(bin_row),
                    **_codon_length_support_fields(bin_row),
                }
            )

    return _codon_length_overview_payload(
        "preference",
        bundle,
        cells=cells,
        value_min=-1,
        value_max=1,
        extra={
            "codonA": codon_a,
            "codonB": codon_b,
            "metricLabel": f"{codon_a} - {codon_b}",
        },
    )


def build_codon_length_dominance_overview_payload(bundle):
    visible_codons = list(bundle.get("visible_codons", [])) if bundle else []
    matrix_rows = list(bundle.get("matrix_rows", [])) if bundle else []
    if len(visible_codons) < 3:
        return _empty_codon_length_overview_payload(
            "dominance",
            visible_codons=visible_codons,
            visible_bins=bundle.get("visible_bins", []) if bundle else [],
            value_min=0,
            value_max=1,
        )

    codon_index = {
        codon: index
        for index, codon in enumerate(visible_codons)
    }
    cells = []
    for row_index, row in enumerate(matrix_rows):
        for bin_row in row["bin_rows"]:
            dominant_codon = bin_row["dominant_codon"]
            dominance_margin = bin_row["dominance_margin"]
            cells.append(
                {
                    "rowIndex": row_index,
                    "binIndex": _codon_length_bin_index(bundle, bin_row),
                    "binStart": bin_row["bin"]["start"],
                    "binLabel": bin_row["bin"]["label"],
                    "value": dominance_margin,
                    "dominantCodon": dominant_codon,
                    "dominantCodonIndex": codon_index.get(dominant_codon, -1),
                    "dominanceMargin": dominance_margin,
                    "codonShares": _codon_length_codon_shares(bin_row),
                    **_codon_length_support_fields(bin_row),
                }
            )

    return _codon_length_overview_payload(
        "dominance",
        bundle,
        cells=cells,
        value_min=0,
        value_max=max((cell["dominanceMargin"] for cell in cells), default=1),
        extra={"metricLabel": "Dominance margin"},
    )


def build_codon_length_shift_overview_payload(bundle):
    visible_codons = list(bundle.get("visible_codons", [])) if bundle else []
    matrix_rows = list(bundle.get("matrix_rows", [])) if bundle else []
    if len(visible_codons) < 2:
        return _empty_codon_length_overview_payload(
            "shift",
            visible_codons=visible_codons,
            visible_bins=bundle.get("visible_bins", []) if bundle else [],
            value_min=0,
            value_max=1,
            transitions=[],
        )

    transitions = _codon_length_transitions(bundle)
    transition_index = {
        (transition["previousBin"]["start"], transition["nextBin"]["start"]): index
        for index, transition in enumerate(transitions)
    }
    cells = []
    codon_a = visible_codons[0]
    for row_index, row in enumerate(matrix_rows):
        bin_rows_by_start = {
            bin_row["bin"]["start"]: bin_row
            for bin_row in row["bin_rows"]
        }
        for transition in transitions:
            previous_start = transition["previousBin"]["start"]
            next_start = transition["nextBin"]["start"]
            previous_bin_row = bin_rows_by_start.get(previous_start)
            next_bin_row = bin_rows_by_start.get(next_start)
            if previous_bin_row is None or next_bin_row is None:
                continue

            previous_shares = _codon_share_lookup(previous_bin_row)
            next_shares = _codon_share_lookup(next_bin_row)
            if len(visible_codons) == 2:
                shift_value = abs(next_shares.get(codon_a, 0) - previous_shares.get(codon_a, 0))
            else:
                shift_value = sum(
                    abs(next_shares.get(codon, 0) - previous_shares.get(codon, 0))
                    for codon in visible_codons
                )
            shift_value = round(shift_value, 6)
            cells.append(
                {
                    "rowIndex": row_index,
                    "transitionIndex": transition_index[(previous_start, next_start)],
                    "value": shift_value,
                    "shift": shift_value,
                    "previousBin": transition["previousBin"],
                    "nextBin": transition["nextBin"],
                    "previousSupport": _codon_length_support_fields(previous_bin_row),
                    "nextSupport": _codon_length_support_fields(next_bin_row),
                    "previousCodonShares": _codon_length_codon_shares(previous_bin_row),
                    "nextCodonShares": _codon_length_codon_shares(next_bin_row),
                }
            )

    return _codon_length_overview_payload(
        "shift",
        bundle,
        cells=cells,
        value_min=0,
        value_max=max((cell["shift"] for cell in cells), default=1),
        extra={
            "metricLabel": "Adjacent-bin shift",
            "transitions": transitions,
        },
    )


def build_codon_length_pairwise_overview_payload(bundle):
    visible_codons = list(bundle.get("visible_codons", [])) if bundle else []
    matrix_rows = list(bundle.get("matrix_rows", [])) if bundle else []
    visible_bins = list(bundle.get("visible_bins", [])) if bundle else []

    if len(visible_codons) < 2 or len(matrix_rows) < 2:
        payload = _build_pairwise_overview_payload(
            [],
            mode="pairwise_similarity_matrix",
            divergence_matrix=[],
            value_min=0,
            value_max=1,
            visible_codons=visible_codons,
            display_metric="divergence",
            include_display_metric_when_empty=True,
        )
        payload["available"] = False
        return payload

    taxon_rows = [
        {
            "taxon_id": row["taxon_id"],
            "taxon_name": row["taxon_name"],
            "rank": row["rank"],
            "observation_count": row["observation_count"],
            "species_count": row.get("species_count", row["observation_count"]),
        }
        for row in matrix_rows
    ]

    bin_vectors_per_taxon = []
    for row in matrix_rows:
        shares_by_bin = {}
        for bin_row in row["bin_rows"]:
            codon_lookup = _codon_share_lookup(bin_row)
            shares_by_bin[bin_row["bin"]["start"]] = [
                codon_lookup.get(codon, 0) for codon in visible_codons
            ]
        bin_vectors_per_taxon.append(shares_by_bin)

    divergence_matrix = _build_trajectory_divergence_matrix(bin_vectors_per_taxon, visible_bins)
    value_min, value_max = _matrix_value_range(divergence_matrix, default_min=0, default_max=1)

    payload = _build_pairwise_overview_payload(
        taxon_rows,
        mode="pairwise_similarity_matrix",
        divergence_matrix=divergence_matrix,
        value_min=value_min,
        value_max=value_max,
        visible_codons=visible_codons,
        display_metric="divergence",
        extra_taxon_fields=("columnIndex",),
    )
    payload["available"] = True
    return payload


def _build_trajectory_divergence_matrix(bin_vectors_per_taxon, visible_bins):
    n = len(bin_vectors_per_taxon)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = _trajectory_divergence(bin_vectors_per_taxon[i], bin_vectors_per_taxon[j], visible_bins)
            matrix[i][j] = d
            matrix[j][i] = d
    return matrix


def _trajectory_divergence(vectors_i, vectors_j, visible_bins):
    total = 0.0
    shared = 0
    for visible_bin in visible_bins:
        bin_start = visible_bin["start"]
        v_i = vectors_i.get(bin_start)
        v_j = vectors_j.get(bin_start)
        if v_i is None or v_j is None:
            continue
        total += _jensen_shannon_divergence(v_i, v_j)
        shared += 1
    if shared == 0:
        return 1.0
    return round(total / shared, 6)


def build_codon_length_browse_payload(bundle, *, window_size=12):
    visible_codons = list(bundle.get("visible_codons", [])) if bundle else []
    visible_bins = list(bundle.get("visible_bins", [])) if bundle else []
    matrix_rows = list(bundle.get("matrix_rows", [])) if bundle else []
    if len(visible_codons) < 2 or not visible_bins or not matrix_rows:
        return {
            "available": False,
            "visibleCodons": visible_codons,
            "visibleBins": visible_bins,
            "panels": [],
            "visibleTaxaCount": len(matrix_rows),
            "shownTaxaCount": 0,
            "windowSize": window_size,
            "maxObservationCount": 0,
        }

    panels = []
    max_observation_count = 0
    for row_index, row in enumerate(matrix_rows):
        bin_rows_by_start = {
            bin_row["bin"]["start"]: bin_row
            for bin_row in row["bin_rows"]
        }
        bins = []
        for bin_index, visible_bin in enumerate(visible_bins):
            bin_row = bin_rows_by_start.get(visible_bin["start"])
            if bin_row is None:
                bins.append(
                    {
                        "binIndex": bin_index,
                        "bin": visible_bin,
                        "occupied": False,
                        "codonShares": [
                            {"codon": codon, "share": None}
                            for codon in visible_codons
                        ],
                        "observationCount": 0,
                        "speciesCount": 0,
                        "supportTier": "missing",
                    }
                )
                continue
            support_fields = _codon_length_support_fields(bin_row)
            max_observation_count = max(
                max_observation_count,
                support_fields["observationCount"],
            )
            shares_by_codon = _codon_share_lookup(bin_row)
            bins.append(
                {
                    "binIndex": bin_index,
                    "bin": visible_bin,
                    "occupied": True,
                    "codonShares": [
                        {
                            "codon": codon,
                            "share": shares_by_codon.get(codon, 0),
                        }
                        for codon in visible_codons
                    ],
                    **support_fields,
                }
            )
        panels.append(
            {
                "rowIndex": row_index,
                "taxonId": row["taxon_id"],
                "taxonName": row["taxon_name"],
                "rank": row["rank"],
                "observationCount": row["observation_count"],
                "speciesCount": row.get("species_count", row["observation_count"]),
                "bins": bins,
            }
        )

    return {
        "available": bool(panels),
        "visibleCodons": visible_codons,
        "visibleBins": visible_bins,
        "panels": panels,
        "visibleTaxaCount": len(matrix_rows),
        "shownTaxaCount": min(len(panels), window_size),
        "windowSize": window_size,
        "maxObservationCount": max_observation_count,
        "mode": "two_codon_area" if len(visible_codons) == 2 else "stacked_composition",
    }


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


def _empty_codon_length_overview_payload(
    mode,
    *,
    visible_codons,
    visible_bins,
    value_min,
    value_max,
    transitions=None,
):
    payload = {
        "mode": mode,
        "available": False,
        "visibleCodons": list(visible_codons),
        "visibleBins": list(visible_bins),
        "taxa": [],
        "cells": [],
        "visibleTaxaCount": 0,
        "maxObservationCount": 0,
        "maxSpeciesCount": 0,
        "valueMin": value_min,
        "valueMax": value_max,
    }
    if transitions is not None:
        payload["transitions"] = list(transitions)
    return payload


def _codon_length_overview_payload(
    mode,
    bundle,
    *,
    cells,
    value_min,
    value_max,
    extra=None,
):
    matrix_rows = list(bundle.get("matrix_rows", []))
    bin_rows = [
        bin_row
        for matrix_row in matrix_rows
        for bin_row in matrix_row["bin_rows"]
    ]
    return {
        "mode": mode,
        "available": bool(cells),
        "visibleCodons": list(bundle.get("visible_codons", [])),
        "visibleBins": list(bundle.get("visible_bins", [])),
        "taxa": [
            {
                "taxonId": row["taxon_id"],
                "taxonName": row["taxon_name"],
                "rank": row["rank"],
                "observationCount": row["observation_count"],
                "speciesCount": row.get("species_count", row["observation_count"]),
                "rowIndex": index,
            }
            for index, row in enumerate(matrix_rows)
        ],
        "cells": cells,
        "visibleTaxaCount": len(matrix_rows),
        "maxObservationCount": max((row["observation_count"] for row in bin_rows), default=0),
        "maxSpeciesCount": max((row.get("species_count", row["observation_count"]) for row in bin_rows), default=0),
        "valueMin": value_min,
        "valueMax": value_max,
        **(extra or {}),
    }


def _codon_length_bin_index(bundle, bin_row):
    bin_start = bin_row["bin"]["start"]
    for index, visible_bin in enumerate(bundle.get("visible_bins", [])):
        if visible_bin["start"] == bin_start:
            return index
    return -1


def _codon_share_lookup(bin_row):
    return {
        codon_share["codon"]: codon_share["share"]
        for codon_share in bin_row["codon_shares"]
    }


def _codon_length_codon_shares(bin_row):
    return [
        {
            "codon": codon_share["codon"],
            "share": codon_share["share"],
        }
        for codon_share in bin_row["codon_shares"]
    ]


def _codon_length_support_fields(bin_row):
    observation_count = int(bin_row["observation_count"])
    species_count = int(bin_row.get("species_count", observation_count))
    if observation_count >= 20:
        support_tier = "high"
    elif observation_count >= 5:
        support_tier = "medium"
    else:
        support_tier = "low"
    return {
        "observationCount": observation_count,
        "speciesCount": species_count,
        "supportTier": support_tier,
    }


def _codon_length_transitions(bundle):
    visible_bins = list(bundle.get("visible_bins", []))
    return [
        {
            "transitionIndex": index,
            "label": f"{visible_bins[index]['label']} -> {visible_bins[index + 1]['label']}",
            "previousBin": visible_bins[index],
            "nextBin": visible_bins[index + 1],
        }
        for index in range(max(0, len(visible_bins) - 1))
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
