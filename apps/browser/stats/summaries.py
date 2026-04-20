from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from math import ceil, floor

from .bins import build_length_bin_definition, build_visible_length_bins


def build_length_summary(lengths):
    return _build_numeric_summary(
        lengths,
        min_field_name="min_length",
        max_field_name="max_length",
    )


def summarize_ranked_length_groups(group_rows, grouped_lengths):
    return _summarize_ranked_numeric_groups(
        group_rows,
        grouped_lengths,
        summary_builder=build_length_summary,
    )


def summarize_length_profile_vectors(summary_rows, grouped_lengths, *, species_count_by_taxon_id=None):
    length_counts_by_taxon = defaultdict(lambda: defaultdict(int))
    visible_bin_starts = set()
    for grouped_row in grouped_lengths:
        if len(grouped_row) == 2:
            display_taxon_id, length = grouped_row
            length_count = 1
        else:
            display_taxon_id, length, length_count = grouped_row
        normalized_length = int(length)
        normalized_length_count = int(length_count)
        if normalized_length_count <= 0:
            continue
        length_counts_by_taxon[display_taxon_id][normalized_length] += normalized_length_count
        visible_bin_starts.add(build_length_bin_definition(normalized_length).start)

    visible_bins = build_visible_length_bins(visible_bin_starts)
    if not visible_bins:
        return {
            "visible_bins": [],
            "profile_rows": [],
        }

    visible_bin_starts_in_order = [length_bin.start for length_bin in visible_bins]
    visible_bins_by_start = {
        length_bin.start: length_bin
        for length_bin in visible_bins
    }

    profile_rows = []
    for row in summary_rows:
        taxon_id = row["taxon_id"]
        counts_by_length = length_counts_by_taxon.get(taxon_id)
        if not counts_by_length:
            continue

        counts_by_bin_start = defaultdict(int)
        for length, length_count in counts_by_length.items():
            counts_by_bin_start[build_length_bin_definition(length).start] += length_count

        observation_count = max(
            int(sum(counts_by_length.values()) or row["observation_count"]),
            1,
        )
        sorted_length_counts = [
            {"length": length, "count": counts_by_length[length]}
            for length in sorted(counts_by_length)
        ]
        profile_rows.append(
            {
                "taxon_id": taxon_id,
                "taxon_name": row["taxon_name"],
                "rank": row["rank"],
                "observation_count": row["observation_count"],
                "species_count": (
                    species_count_by_taxon_id.get(taxon_id, row["observation_count"])
                    if species_count_by_taxon_id is not None
                    else row.get("species_count", row["observation_count"])
                ),
                "length_profile": [
                    round(counts_by_bin_start.get(bin_start, 0) / observation_count, 6)
                    for bin_start in visible_bin_starts_in_order
                ],
                "bin_counts": [
                    {
                        "bin": asdict(visible_bins_by_start[bin_start]),
                        "count": counts_by_bin_start.get(bin_start, 0),
                    }
                    for bin_start in visible_bin_starts_in_order
                ],
                "length_counts": sorted_length_counts,
            }
        )

    return {
        "visible_bins": [asdict(length_bin) for length_bin in visible_bins],
        "profile_rows": profile_rows,
    }


def summarize_ranked_codon_composition_groups(group_rows, grouped_species_call_codon_fractions, *, visible_codons):
    call_fractions_by_taxon = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    for display_taxon_id, species_taxon_id, repeat_call_id, codon, codon_fraction in grouped_species_call_codon_fractions:
        call_fractions_by_taxon[display_taxon_id][species_taxon_id][repeat_call_id][codon] = float(codon_fraction)

    summary_rows = []
    for row in group_rows:
        species_count = row.get("species_count", 0)
        if species_count <= 0:
            continue
        species_call_rows = call_fractions_by_taxon[row["display_taxon_id"]]
        summary_rows.append(
            {
                "taxon_id": row["display_taxon_id"],
                "taxon_name": row["display_taxon_name"],
                "rank": row["display_taxon_rank"],
                "observation_count": row["observation_count"],
                "species_count": species_count,
                "codon_shares": [
                    {
                        "codon": codon,
                        "share": normalize_numeric_summary_value(
                            sum(
                                sum(call_rows[repeat_call_id].get(codon, 0.0) for repeat_call_id in call_rows)
                                / len(call_rows)
                                for call_rows in species_call_rows.values()
                            ) / species_count
                        ),
                    }
                    for codon in visible_codons
                ],
            }
        )
    return summary_rows


def summarize_codon_length_composition_rows(
    summary_rows,
    grouped_species_length_call_counts,
    grouped_species_length_codon_fraction_sums,
    *,
    visible_codons,
):
    call_counts_by_taxon_bin_species = defaultdict(lambda: defaultdict(int))
    codon_sums_by_taxon_bin_species = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    visible_bin_starts = set()

    for display_taxon_id, species_taxon_id, length, call_count in grouped_species_length_call_counts:
        bin_start = build_length_bin_definition(length).start
        normalized_call_count = int(call_count)
        if normalized_call_count <= 0:
            continue
        call_counts_by_taxon_bin_species[(display_taxon_id, bin_start)][species_taxon_id] += (
            normalized_call_count
        )
        visible_bin_starts.add(bin_start)

    for display_taxon_id, species_taxon_id, length, codon, codon_fraction_sum in (
        grouped_species_length_codon_fraction_sums
    ):
        bin_start = build_length_bin_definition(length).start
        codon_sums_by_taxon_bin_species[(display_taxon_id, bin_start)][species_taxon_id][codon] += float(
            codon_fraction_sum
        )
        visible_bin_starts.add(bin_start)

    visible_bins = build_visible_length_bins(visible_bin_starts)
    if not visible_bins:
        return {
            "visible_bins": [],
            "matrix_rows": [],
        }

    visible_bins_by_start = {
        length_bin.start: length_bin
        for length_bin in visible_bins
    }

    matrix_rows = []
    for row in summary_rows:
        taxon_id = row["taxon_id"]
        bin_rows = []
        for length_bin in visible_bins:
            species_call_counts = call_counts_by_taxon_bin_species.get((taxon_id, length_bin.start))
            if not species_call_counts:
                continue

            observation_count = sum(species_call_counts.values())
            species_count = len(species_call_counts)
            codon_shares = []
            for codon in visible_codons:
                species_weighted_share_sum = 0.0
                for species_taxon_id, call_count in species_call_counts.items():
                    if call_count <= 0:
                        continue
                    species_weighted_share_sum += (
                        codon_sums_by_taxon_bin_species[(taxon_id, length_bin.start)][species_taxon_id].get(
                            codon,
                            0.0,
                        )
                        / call_count
                    )
                share = (
                    species_weighted_share_sum / species_count
                    if species_count > 0
                    else 0.0
                )
                codon_shares.append(
                    {
                        "codon": codon,
                        "share": normalize_numeric_summary_value(share),
                    }
                )

            dominant_codon, dominance_margin = _build_dominance_summary(codon_shares)
            bin_rows.append(
                {
                    "bin": asdict(visible_bins_by_start[length_bin.start]),
                    "observation_count": observation_count,
                    "species_count": species_count,
                    "codon_shares": codon_shares,
                    "dominant_codon": dominant_codon,
                    "dominance_margin": dominance_margin,
                }
            )

        if not bin_rows:
            continue

        matrix_rows.append(
            {
                "taxon_id": taxon_id,
                "taxon_name": row["taxon_name"],
                "rank": row["rank"],
                "observation_count": row["observation_count"],
                "species_count": row.get("species_count", row["observation_count"]),
                "bin_rows": bin_rows,
            }
        )

    return {
        "visible_bins": [asdict(length_bin) for length_bin in visible_bins],
        "matrix_rows": matrix_rows,
    }


def _summarize_ranked_numeric_groups(group_rows, grouped_values, *, summary_builder):
    lengths_by_taxon = defaultdict(list)
    for display_taxon_id, value in grouped_values:
        lengths_by_taxon[display_taxon_id].append(value)

    summary_rows = []
    for row in group_rows:
        summary = summary_builder(lengths_by_taxon[row["display_taxon_id"]])
        if summary is None:
            continue
        summary_rows.append(
            {
                "taxon_id": row["display_taxon_id"],
                "taxon_name": row["display_taxon_name"],
                "rank": row["display_taxon_rank"],
                "observation_count": row["observation_count"],
                "species_count": row.get("species_count"),
                **summary,
            }
        )
    return summary_rows


def _build_numeric_summary(values, *, min_field_name: str, max_field_name: str):
    if not values:
        return None

    sorted_values = sorted(values)
    return {
        min_field_name: normalize_numeric_summary_value(sorted_values[0]),
        "q1": normalize_numeric_summary_value(_linear_quantile(sorted_values, 0.25)),
        "median": normalize_numeric_summary_value(_linear_quantile(sorted_values, 0.5)),
        "q3": normalize_numeric_summary_value(_linear_quantile(sorted_values, 0.75)),
        max_field_name: normalize_numeric_summary_value(sorted_values[-1]),
    }


def _linear_quantile(sorted_values, quantile: float) -> float:
    if len(sorted_values) == 1:
        return float(sorted_values[0])

    position = (len(sorted_values) - 1) * quantile
    lower_index = floor(position)
    upper_index = ceil(position)
    if lower_index == upper_index:
        return float(sorted_values[lower_index])

    lower_value = sorted_values[lower_index]
    upper_value = sorted_values[upper_index]
    fraction = position - lower_index
    return lower_value + ((upper_value - lower_value) * fraction)


def build_ccdf_points(sorted_lengths, *, max_points=300):
    n = len(sorted_lengths)
    if n == 0:
        return []

    unique_pairs = []
    for v in sorted_lengths:
        if unique_pairs and unique_pairs[-1][0] == v:
            unique_pairs[-1][1] += 1
        else:
            unique_pairs.append([v, 1])

    total_unique = len(unique_pairs)
    if total_unique <= max_points:
        selected_indices = set(range(total_unique))
    else:
        step = max(1, (total_unique - 1) // (max_points - 2))
        selected_indices = set(range(0, total_unique, step))
        selected_indices.add(total_unique - 1)

    ccdf_points = []
    cumulative_before = 0
    for i, (v, c) in enumerate(unique_pairs):
        if i in selected_indices:
            ccdf_points.append({"x": v, "y": round((n - cumulative_before) / n, 6)})
        cumulative_before += c

    return ccdf_points


def build_length_inspect_summary(sorted_lengths):
    n = len(sorted_lengths)
    if n == 0:
        return None
    return {
        "observation_count": n,
        "ccdf_points": build_ccdf_points(sorted_lengths),
        "median": normalize_length_summary_value(_linear_quantile(sorted_lengths, 0.5)),
        "q90": normalize_length_summary_value(_linear_quantile(sorted_lengths, 0.90)),
        "q95": normalize_length_summary_value(_linear_quantile(sorted_lengths, 0.95)),
        "max": sorted_lengths[-1],
    }


def normalize_numeric_summary_value(value: float):
    rounded = round(value, 3)
    if float(rounded).is_integer():
        return int(rounded)
    return rounded


def normalize_length_summary_value(value: float):
    return normalize_numeric_summary_value(value)


def _build_dominance_summary(codon_shares):
    if not codon_shares:
        return "", 0

    ranked_codon_shares = sorted(
        codon_shares,
        key=lambda row: (-float(row["share"]), row["codon"]),
    )
    leading_share = float(ranked_codon_shares[0]["share"])
    second_share = float(ranked_codon_shares[1]["share"]) if len(ranked_codon_shares) > 1 else 0.0
    return (
        ranked_codon_shares[0]["codon"],
        normalize_numeric_summary_value(max(0.0, leading_share - second_share)),
    )


def _build_length_count_pairs(lengths):
    if not lengths:
        return []

    counts_by_length = defaultdict(int)
    for length in lengths:
        counts_by_length[int(length)] += 1
    return [
        (length, counts_by_length[length])
        for length in sorted(counts_by_length)
    ]


def _coerce_length_count_pairs(length_source):
    if not length_source:
        return []

    first_value = length_source[0]
    if isinstance(first_value, dict):
        return [
            (int(row["length"]), int(row["count"]))
            for row in length_source
            if int(row["count"]) > 0
        ]
    if isinstance(first_value, (tuple, list)) and len(first_value) == 2:
        return [
            (int(length), int(count))
            for length, count in length_source
            if int(count) > 0
        ]
    return _build_length_count_pairs(length_source)


def _clamp_length_count_pairs(length_count_pairs, *, l_cap):
    clamped_counts = defaultdict(int)
    for length, count in length_count_pairs:
        clamped_counts[min(int(length), l_cap)] += int(count)
    return [
        (length, clamped_counts[length])
        for length in sorted(clamped_counts)
    ]


def _value_at_index(length_count_pairs, index):
    cumulative_count = 0
    for length, count in length_count_pairs:
        cumulative_count += count
        if index < cumulative_count:
            return float(length)
    return float(length_count_pairs[-1][0])


def _linear_quantile_from_length_count_pairs(length_count_pairs, quantile: float) -> float:
    total_count = sum(count for _, count in length_count_pairs)
    if total_count <= 0:
        return 0.0
    if total_count == 1:
        return float(length_count_pairs[0][0])

    position = (total_count - 1) * quantile
    lower_index = floor(position)
    upper_index = ceil(position)
    if lower_index == upper_index:
        return _value_at_index(length_count_pairs, lower_index)

    lower_value = _value_at_index(length_count_pairs, lower_index)
    upper_value = _value_at_index(length_count_pairs, upper_index)
    fraction = position - lower_index
    return lower_value + ((upper_value - lower_value) * fraction)


def _compute_wasserstein1_distance(lengths_a, lengths_b, l_cap=50):
    length_count_pairs_a = _coerce_length_count_pairs(lengths_a)
    length_count_pairs_b = _coerce_length_count_pairs(lengths_b)
    if not length_count_pairs_a or not length_count_pairs_b:
        return 0.0

    clamped_a = _clamp_length_count_pairs(length_count_pairs_a, l_cap=l_cap)
    clamped_b = _clamp_length_count_pairs(length_count_pairs_b, l_cap=l_cap)
    n_a = sum(count for _, count in clamped_a)
    n_b = sum(count for _, count in clamped_b)
    all_vals = sorted({length for length, _ in clamped_a} | {length for length, _ in clamped_b} | {l_cap})
    w1 = 0.0
    cumulative_a = 0
    cumulative_b = 0
    index_a = 0
    index_b = 0
    for i in range(len(all_vals) - 1):
        x = all_vals[i]
        next_x = all_vals[i + 1]
        while index_a < len(clamped_a) and clamped_a[index_a][0] <= x:
            cumulative_a += clamped_a[index_a][1]
            index_a += 1
        while index_b < len(clamped_b) and clamped_b[index_b][0] <= x:
            cumulative_b += clamped_b[index_b][1]
            index_b += 1
        cdf_a = cumulative_a / n_a
        cdf_b = cumulative_b / n_b
        w1 += abs(cdf_a - cdf_b) * (next_x - x)
    return round(w1 / l_cap, 6)


def _compute_tail_feature_vector(lengths, l_cap=50):
    length_count_pairs = _coerce_length_count_pairs(lengths)
    n = sum(count for _, count in length_count_pairs)
    if n <= 0:
        return [0.0, 0.0, 0.0, 0.0]
    p_gt_20 = sum(count for length, count in length_count_pairs if length > 20) / n
    p_gt_30 = sum(count for length, count in length_count_pairs if length > 30) / n
    p_gt_50 = sum(count for length, count in length_count_pairs if length > 50) / n
    q95 = _linear_quantile_from_length_count_pairs(length_count_pairs, 0.95)
    q95_norm = min(q95 / l_cap, 1.0)
    return [round(p_gt_20, 6), round(p_gt_30, 6), round(p_gt_50, 6), round(q95_norm, 6)]


def _compute_l1_tail_distance(tail_a, tail_b):
    if not tail_a or not tail_b:
        return 0.0
    return round(sum(abs(a - b) for a, b in zip(tail_a, tail_b)) / len(tail_a), 6)


def build_wasserstein_pairwise_matrix(profile_rows, l_cap=50):
    length_count_pairs_by_row = [
        row.get("length_counts") or _build_length_count_pairs(row.get("raw_lengths", []))
        for row in profile_rows
    ]
    n = len(profile_rows)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = _compute_wasserstein1_distance(
                length_count_pairs_by_row[i],
                length_count_pairs_by_row[j],
                l_cap,
            )
            matrix[i][j] = d
            matrix[j][i] = d
    return matrix


def build_tail_pairwise_matrix(profile_rows, l_cap=50):
    tail_vectors = [
        _compute_tail_feature_vector(
            row.get("length_counts") or row.get("raw_lengths", []),
            l_cap,
        )
        for row in profile_rows
    ]
    n = len(tail_vectors)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = _compute_l1_tail_distance(tail_vectors[i], tail_vectors[j])
            matrix[i][j] = d
            matrix[j][i] = d
    return matrix
