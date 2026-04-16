from __future__ import annotations

from collections import defaultdict
from math import ceil, floor


def build_length_summary(lengths):
    if not lengths:
        return None

    sorted_lengths = sorted(lengths)
    return {
        "min_length": sorted_lengths[0],
        "q1": _normalize_quantile(_linear_quantile(sorted_lengths, 0.25)),
        "median": _normalize_quantile(_linear_quantile(sorted_lengths, 0.5)),
        "q3": _normalize_quantile(_linear_quantile(sorted_lengths, 0.75)),
        "max_length": sorted_lengths[-1],
    }


def summarize_ranked_length_groups(group_rows, grouped_lengths):
    lengths_by_taxon = defaultdict(list)
    for display_taxon_id, length in grouped_lengths:
        lengths_by_taxon[display_taxon_id].append(length)

    summary_rows = []
    for row in group_rows:
        summary = build_length_summary(lengths_by_taxon[row["display_taxon_id"]])
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


def _normalize_quantile(value: float):
    rounded = round(value, 3)
    if float(rounded).is_integer():
        return int(rounded)
    return rounded
