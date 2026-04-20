from __future__ import annotations

from collections import defaultdict
from math import ceil, floor


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


def normalize_numeric_summary_value(value: float):
    rounded = round(value, 3)
    if float(rounded).is_integer():
        return int(rounded)
    return rounded


def normalize_length_summary_value(value: float):
    return normalize_numeric_summary_value(value)
