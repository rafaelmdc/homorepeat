from __future__ import annotations

import bisect
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
    lengths_by_taxon = defaultdict(list)
    visible_bin_starts = set()
    for display_taxon_id, length in grouped_lengths:
        normalized_length = int(length)
        lengths_by_taxon[display_taxon_id].append(normalized_length)
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
        lengths = lengths_by_taxon.get(taxon_id, [])
        if not lengths:
            continue

        counts_by_bin_start = defaultdict(int)
        for length in lengths:
            counts_by_bin_start[build_length_bin_definition(length).start] += 1

        observation_count = max(int(row["observation_count"]), 1)
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
                "raw_lengths": sorted(lengths),
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


def _compute_wasserstein1_distance(lengths_a, lengths_b, l_cap=50):
    if not lengths_a or not lengths_b:
        return 0.0
    clamped_a = sorted(min(x, l_cap) for x in lengths_a)
    clamped_b = sorted(min(x, l_cap) for x in lengths_b)
    n_a = len(clamped_a)
    n_b = len(clamped_b)
    all_vals = sorted(set(clamped_a) | set(clamped_b) | {l_cap})
    w1 = 0.0
    for i in range(len(all_vals) - 1):
        x = all_vals[i]
        next_x = all_vals[i + 1]
        cdf_a = bisect.bisect_right(clamped_a, x) / n_a
        cdf_b = bisect.bisect_right(clamped_b, x) / n_b
        w1 += abs(cdf_a - cdf_b) * (next_x - x)
    return round(w1 / l_cap, 6)


def _compute_tail_feature_vector(lengths, l_cap=50):
    n = len(lengths)
    if n == 0:
        return [0.0, 0.0, 0.0, 0.0]
    p_gt_20 = sum(1 for l in lengths if l > 20) / n
    p_gt_30 = sum(1 for l in lengths if l > 30) / n
    p_gt_50 = sum(1 for l in lengths if l > 50) / n
    q95 = _linear_quantile(sorted(lengths), 0.95)
    q95_norm = min(q95 / l_cap, 1.0)
    return [round(p_gt_20, 6), round(p_gt_30, 6), round(p_gt_50, 6), round(q95_norm, 6)]


def _compute_l1_tail_distance(tail_a, tail_b):
    if not tail_a or not tail_b:
        return 0.0
    return round(sum(abs(a - b) for a, b in zip(tail_a, tail_b)) / len(tail_a), 6)


def build_wasserstein_pairwise_matrix(profile_rows, l_cap=50):
    n = len(profile_rows)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = _compute_wasserstein1_distance(
                profile_rows[i]["raw_lengths"], profile_rows[j]["raw_lengths"], l_cap
            )
            matrix[i][j] = d
            matrix[j][i] = d
    return matrix


def build_tail_pairwise_matrix(profile_rows, l_cap=50):
    tail_vectors = [_compute_tail_feature_vector(row["raw_lengths"], l_cap) for row in profile_rows]
    n = len(tail_vectors)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = _compute_l1_tail_distance(tail_vectors[i], tail_vectors[j])
            matrix[i][j] = d
            matrix[j][i] = d
    return matrix
