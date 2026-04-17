from __future__ import annotations

from collections import defaultdict
from math import ceil, floor, sqrt

from .bins import build_length_bin_definition


def build_length_summary(lengths):
    return _build_numeric_summary(
        lengths,
        min_field_name="min_length",
        max_field_name="max_length",
    )


def build_codon_ratio_summary(codon_ratio_values):
    return _build_numeric_summary(
        codon_ratio_values,
        min_field_name="min_codon_ratio",
        max_field_name="max_codon_ratio",
    )


def summarize_ranked_length_groups(group_rows, grouped_lengths):
    return _summarize_ranked_numeric_groups(
        group_rows,
        grouped_lengths,
        summary_builder=build_length_summary,
    )


def summarize_ranked_codon_ratio_groups(group_rows, grouped_codon_ratio_values):
    return _summarize_ranked_numeric_groups(
        group_rows,
        grouped_codon_ratio_values,
        summary_builder=build_codon_ratio_summary,
    )


def summarize_codon_heatmap_groups(group_rows, grouped_length_codon_ratio_values):
    values_by_taxon_bin = defaultdict(list)
    bin_starts_by_taxon = defaultdict(set)
    length_bins_by_start = {}

    for display_taxon_id, length, codon_ratio_value in grouped_length_codon_ratio_values:
        length_bin = build_length_bin_definition(length)
        values_by_taxon_bin[(display_taxon_id, length_bin.start)].append(codon_ratio_value)
        bin_starts_by_taxon[display_taxon_id].add(length_bin.start)
        length_bins_by_start[length_bin.start] = length_bin

    summary_rows = []
    for row in group_rows:
        for bin_start in sorted(bin_starts_by_taxon[row["display_taxon_id"]]):
            summary = build_codon_ratio_summary(values_by_taxon_bin[(row["display_taxon_id"], bin_start)])
            if summary is None:
                continue
            length_bin = length_bins_by_start[bin_start]
            summary_rows.append(
                {
                    "taxon_id": row["display_taxon_id"],
                    "taxon_name": row["display_taxon_name"],
                    "rank": row["display_taxon_rank"],
                    "taxon_observation_count": row["observation_count"],
                    "length_bin_start": length_bin.start,
                    "length_bin_end": length_bin.end,
                    "length_bin_key": length_bin.key,
                    "length_bin_label": length_bin.label,
                    "observation_count": len(values_by_taxon_bin[(row["display_taxon_id"], bin_start)]),
                    **summary,
                }
            )
    return summary_rows


def build_numeric_histogram_bins(values):
    if not values:
        return []

    sorted_values = sorted(values)
    minimum = float(sorted_values[0])
    maximum = float(sorted_values[-1])
    if minimum == maximum:
        normalized_value = normalize_numeric_summary_value(minimum)
        return [
            {
                "start": normalized_value,
                "end": normalized_value,
                "label": str(normalized_value),
                "count": len(sorted_values),
                "midpoint": normalized_value,
            }
        ]

    bin_count = min(10, max(1, ceil(sqrt(len(sorted_values)))))
    bin_width = (maximum - minimum) / bin_count
    bin_rows = []
    for index in range(bin_count):
        start = minimum + (index * bin_width)
        end = maximum if index == bin_count - 1 else minimum + ((index + 1) * bin_width)
        if index == bin_count - 1:
            count = sum(start <= value <= end for value in sorted_values)
        else:
            count = sum(start <= value < end for value in sorted_values)
        normalized_start = normalize_numeric_summary_value(start)
        normalized_end = normalize_numeric_summary_value(end)
        bin_rows.append(
            {
                "start": normalized_start,
                "end": normalized_end,
                "label": f"{normalized_start}-{normalized_end}",
                "count": count,
                "midpoint": normalize_numeric_summary_value(start + ((end - start) / 2)),
            }
        )
    return bin_rows


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


def normalize_numeric_summary_value(value: float):
    rounded = round(value, 3)
    if float(rounded).is_integer():
        return int(rounded)
    return rounded


def normalize_length_summary_value(value: float):
    return normalize_numeric_summary_value(value)
