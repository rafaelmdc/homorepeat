"""Phase 5 validation helpers for completed pipeline outputs."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Sequence

from .repeat_features import validate_call_row
from .tsv_io import ContractError


def build_validation_report(
    *,
    taxonomy_rows: Sequence[dict[str, str]],
    genomes_rows: Sequence[dict[str, str]],
    proteins_rows: Sequence[dict[str, str]],
    call_rows: Sequence[dict[str, str]],
    summary_rows: Sequence[dict[str, str]],
    regression_rows: Sequence[dict[str, str]],
    acquisition_validation_status: str = "",
    sqlite_validation_status: str = "",
) -> dict[str, object]:
    """Build a Phase 5 validation report from finalized outputs."""

    taxonomy_by_id = {row.get("taxon_id", ""): row for row in taxonomy_rows}
    proteins_by_id = {row.get("protein_id", ""): row for row in proteins_rows}

    for row in call_rows:
        validate_call_row(row)

    expected_summary = _build_expected_summary(call_rows, proteins_by_id, taxonomy_by_id)
    expected_regression = _build_expected_regression(call_rows, taxonomy_by_id)

    actual_summary = {
        (row.get("method", ""), row.get("repeat_residue", ""), row.get("taxon_id", "")): row
        for row in summary_rows
    }
    actual_regression = {
        (
            row.get("method", ""),
            row.get("repeat_residue", ""),
            row.get("group_label", ""),
            int(row.get("repeat_length", "0")),
        ): row
        for row in regression_rows
    }

    genome_taxids = {row.get("taxon_id", "") for row in genomes_rows if row.get("taxon_id", "")}
    call_taxids = {row.get("taxon_id", "") for row in call_rows if row.get("taxon_id", "")}
    taxonomy_taxids = set(taxonomy_by_id)

    checks = {
        "taxonomy_has_all_genome_taxids": genome_taxids.issubset(taxonomy_taxids),
        "taxonomy_has_all_call_taxids": call_taxids.issubset(taxonomy_taxids),
        "taxonomy_parent_links_exist": _taxonomy_parent_links_exist(taxonomy_rows),
        "summary_group_keys_match": set(expected_summary) == set(actual_summary),
        "summary_values_match": _summary_values_match(expected_summary, actual_summary),
        "summary_taxon_names_match_taxonomy": _summary_taxon_names_match(summary_rows, taxonomy_by_id),
        "summary_codon_fields_empty": _all_rows_have_empty_fields(
            summary_rows,
            ("codon_metric_name", "mean_codon_metric"),
        ),
        "regression_keys_match": set(expected_regression) == set(actual_regression),
        "regression_values_match": _regression_values_match(expected_regression, actual_regression),
        "regression_labels_match_taxonomy": _regression_labels_match(regression_rows, taxonomy_by_id),
        "regression_codon_fields_empty": _all_rows_have_empty_fields(
            regression_rows,
            ("codon_metric_name", "mean_codon_metric", "filtered_max_length", "transformed_codon_metric"),
        ),
    }

    warnings: list[str] = []
    if acquisition_validation_status:
        checks["acquisition_validation_not_fail"] = acquisition_validation_status in {"pass", "warn"}
        if acquisition_validation_status == "warn":
            warnings.append("acquisition validation status is warn")
    if sqlite_validation_status:
        checks["sqlite_validation_pass"] = sqlite_validation_status == "pass"

    status = "pass"
    if not all(checks.values()):
        status = "fail"
    elif warnings:
        status = "warn"

    return {
        "status": status,
        "scope": "phase5_validation",
        "counts": {
            "taxonomy_rows": len(taxonomy_rows),
            "genomes_rows": len(genomes_rows),
            "proteins_rows": len(proteins_rows),
            "call_rows": len(call_rows),
            "summary_rows": len(summary_rows),
            "regression_rows": len(regression_rows),
        },
        "checks": checks,
        "upstream_status": {
            "acquisition_validation": acquisition_validation_status,
            "sqlite_validation": sqlite_validation_status,
        },
        "warnings": warnings,
    }


def write_validation_report(path: Path | str, payload: dict[str, object]) -> None:
    """Write a stable JSON validation report."""

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _build_expected_summary(
    call_rows: Sequence[dict[str, str]],
    proteins_by_id: dict[str, dict[str, str]],
    taxonomy_by_id: dict[str, dict[str, str]],
) -> dict[tuple[str, str, str], dict[str, object]]:
    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in call_rows:
        grouped[(row.get("method", ""), row.get("repeat_residue", ""), row.get("taxon_id", ""))].append(row)

    expected: dict[tuple[str, str, str], dict[str, object]] = {}
    for key, rows in grouped.items():
        method, repeat_residue, taxon_id = key
        lengths = [int(row.get("length", "0")) for row in rows]
        purities = [float(row.get("purity", "0")) for row in rows]
        genome_ids = {row.get("genome_id", "") for row in rows if row.get("genome_id", "")}
        protein_ids = {row.get("protein_id", "") for row in rows if row.get("protein_id", "")}
        start_fractions: list[float] = []
        for row in rows:
            protein_length_text = proteins_by_id.get(row.get("protein_id", ""), {}).get("protein_length", "")
            if not protein_length_text:
                continue
            protein_length = int(protein_length_text)
            if protein_length <= 0:
                continue
            start_fractions.append(int(row.get("start", "0")) / protein_length)

        expected[key] = {
            "method": method,
            "repeat_residue": repeat_residue,
            "taxon_id": taxon_id,
            "taxon_name": taxonomy_by_id.get(taxon_id, {}).get("taxon_name", ""),
            "n_genomes": len(genome_ids),
            "n_proteins": len(protein_ids),
            "n_calls": len(rows),
            "mean_length": mean(lengths),
            "mean_purity": mean(purities),
            "median_length": median(lengths),
            "max_length": max(lengths),
            "mean_start_fraction": mean(start_fractions) if start_fractions else None,
        }
    return expected


def _build_expected_regression(
    call_rows: Sequence[dict[str, str]],
    taxonomy_by_id: dict[str, dict[str, str]],
) -> dict[tuple[str, str, str, int], dict[str, object]]:
    grouped: dict[tuple[str, str, str, int], int] = defaultdict(int)
    for row in call_rows:
        taxon_id = row.get("taxon_id", "")
        group_label = taxonomy_by_id.get(taxon_id, {}).get("taxon_name", "")
        key = (
            row.get("method", ""),
            row.get("repeat_residue", ""),
            group_label,
            int(row.get("length", "0")),
        )
        grouped[key] += 1

    return {
        key: {
            "method": key[0],
            "repeat_residue": key[1],
            "group_label": key[2],
            "repeat_length": key[3],
            "n_observations": count,
        }
        for key, count in grouped.items()
    }


def _taxonomy_parent_links_exist(taxonomy_rows: Sequence[dict[str, str]]) -> bool:
    taxon_ids = {row.get("taxon_id", "") for row in taxonomy_rows if row.get("taxon_id", "")}
    for row in taxonomy_rows:
        parent_taxon_id = row.get("parent_taxon_id", "")
        if parent_taxon_id and parent_taxon_id not in taxon_ids:
            return False
    return True


def _summary_taxon_names_match(
    summary_rows: Sequence[dict[str, str]],
    taxonomy_by_id: dict[str, dict[str, str]],
) -> bool:
    for row in summary_rows:
        taxon_id = row.get("taxon_id", "")
        expected_name = taxonomy_by_id.get(taxon_id, {}).get("taxon_name", "")
        if row.get("taxon_name", "") != expected_name:
            return False
    return True


def _regression_labels_match(
    regression_rows: Sequence[dict[str, str]],
    taxonomy_by_id: dict[str, dict[str, str]],
) -> bool:
    valid_names = {row.get("taxon_name", "") for row in taxonomy_by_id.values()}
    for row in regression_rows:
        if row.get("group_label", "") not in valid_names:
            return False
    return True


def _summary_values_match(
    expected: dict[tuple[str, str, str], dict[str, object]],
    actual: dict[tuple[str, str, str], dict[str, str]],
) -> bool:
    if set(expected) != set(actual):
        return False
    for key, expected_row in expected.items():
        actual_row = actual[key]
        if int(actual_row.get("n_genomes", "0")) != expected_row["n_genomes"]:
            return False
        if int(actual_row.get("n_proteins", "0")) != expected_row["n_proteins"]:
            return False
        if int(actual_row.get("n_calls", "0")) != expected_row["n_calls"]:
            return False
        if int(actual_row.get("max_length", "0")) != expected_row["max_length"]:
            return False
        if not _float_matches(actual_row.get("mean_length", ""), expected_row["mean_length"]):
            return False
        if not _float_matches(actual_row.get("mean_purity", ""), expected_row["mean_purity"]):
            return False
        if not _float_matches(actual_row.get("median_length", ""), expected_row["median_length"]):
            return False
        if expected_row["mean_start_fraction"] is None:
            if actual_row.get("mean_start_fraction", "") != "":
                return False
        elif not _float_matches(actual_row.get("mean_start_fraction", ""), expected_row["mean_start_fraction"]):
            return False
    return True


def _regression_values_match(
    expected: dict[tuple[str, str, str, int], dict[str, object]],
    actual: dict[tuple[str, str, str, int], dict[str, str]],
) -> bool:
    if set(expected) != set(actual):
        return False
    for key, expected_row in expected.items():
        actual_row = actual[key]
        if int(actual_row.get("n_observations", "0")) != expected_row["n_observations"]:
            return False
    return True


def _all_rows_have_empty_fields(rows: Sequence[dict[str, str]], fieldnames: Sequence[str]) -> bool:
    return all(all((row.get(field, "") or "") == "" for field in fieldnames) for row in rows)


def _float_matches(actual_text: str, expected_value: object, *, tolerance: float = 1e-9) -> bool:
    if actual_text == "" or expected_value is None:
        return actual_text == "" and expected_value is None
    actual_value = float(actual_text)
    return abs(actual_value - float(expected_value)) <= tolerance


def require_validation_pass(payload: dict[str, object]) -> None:
    """Raise on Phase 5 validation failure."""

    status = str(payload.get("status", ""))
    if status == "fail":
        raise ContractError("Phase 5 validation failed; see validation_report.json for details")
