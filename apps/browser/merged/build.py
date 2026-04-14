from __future__ import annotations

from collections import defaultdict

from apps.browser.models.merged import (
    MergedProteinOccurrence,
    MergedProteinSummary,
    MergedResidueOccurrence,
    MergedResidueSummary,
)
from apps.browser.models.repeat_calls import RepeatCall
from apps.browser.models.runs import PipelineRun

from .identity import (
    _identity_merged_protein_groups_from_repeat_calls,
    _identity_merged_residue_groups_from_repeat_calls,
)
from .repeat_calls import _merged_repeat_call_queryset


MERGED_SUMMARY_BATCH_SIZE = 1000


def rebuild_merged_summaries_for_run(pipeline_run: PipelineRun) -> None:
    for accession in _rebuild_accessions_for_run(pipeline_run):
        _rebuild_merged_summaries_for_accession(pipeline_run, accession)


def _rebuild_merged_summaries_for_accession(
    pipeline_run: PipelineRun,
    accession: str,
) -> None:
    old_protein_keys = _existing_protein_occurrence_keys_for_run(
        pipeline_run,
        accession=accession,
    )
    old_residue_keys = _existing_residue_occurrence_keys_for_run(
        pipeline_run,
        accession=accession,
    )

    MergedProteinOccurrence.objects.filter(
        pipeline_run=pipeline_run,
        summary__accession=accession,
    ).delete()
    MergedResidueOccurrence.objects.filter(
        pipeline_run=pipeline_run,
        summary__accession=accession,
    ).delete()

    run_repeat_calls = _source_repeat_calls_for_accession(
        accession=accession,
        pipeline_run=pipeline_run,
    )
    protein_occurrence_groups = _protein_occurrence_groups_for_run(run_repeat_calls)
    residue_occurrence_groups = _residue_occurrence_groups_for_run(run_repeat_calls)

    new_protein_keys = {key for key, _taxon_id in protein_occurrence_groups.keys()}
    new_residue_keys = {key for key, _taxon_id in residue_occurrence_groups.keys()}
    touched_protein_keys = old_protein_keys | new_protein_keys
    touched_residue_keys = old_residue_keys | new_residue_keys

    source_repeat_calls = _source_repeat_calls_for_accession(accession=accession)
    protein_summaries_by_key = _refresh_protein_summaries(
        touched_protein_keys,
        source_repeat_calls=source_repeat_calls,
    )
    residue_summaries_by_key = _refresh_residue_summaries(
        touched_residue_keys,
        source_repeat_calls=source_repeat_calls,
    )

    _create_protein_occurrences(
        pipeline_run,
        protein_occurrence_groups,
        protein_summaries_by_key,
    )
    _create_residue_occurrences(
        pipeline_run,
        residue_occurrence_groups,
        residue_summaries_by_key,
    )


def merged_summaries_populated_for_run(pipeline_run: PipelineRun) -> bool:
    return MergedProteinOccurrence.objects.filter(pipeline_run=pipeline_run).exists()


def backfill_merged_summaries_for_run(
    pipeline_run: PipelineRun,
    *,
    force: bool = False,
) -> bool:
    if not force and merged_summaries_populated_for_run(pipeline_run):
        return False

    rebuild_merged_summaries_for_run(pipeline_run)
    return True


def _rebuild_accessions_for_run(pipeline_run: PipelineRun) -> list[str]:
    return sorted(
        _current_repeat_call_accessions_for_run(pipeline_run)
        | _existing_occurrence_accessions_for_run(pipeline_run)
    )


def _current_repeat_call_accessions_for_run(pipeline_run: PipelineRun) -> set[str]:
    return set(
        RepeatCall.objects.filter(pipeline_run=pipeline_run)
        .exclude(accession="")
        .order_by()
        .values_list("accession", flat=True)
        .distinct()
    )


def _existing_occurrence_accessions_for_run(pipeline_run: PipelineRun) -> set[str]:
    return set(
        MergedProteinOccurrence.objects.filter(pipeline_run=pipeline_run)
        .order_by()
        .values_list("summary__accession", flat=True)
        .distinct()
    ) | set(
        MergedResidueOccurrence.objects.filter(pipeline_run=pipeline_run)
        .order_by()
        .values_list("summary__accession", flat=True)
        .distinct()
    )


def _existing_protein_occurrence_keys_for_run(
    pipeline_run: PipelineRun,
    *,
    accession: str | None = None,
) -> set[tuple[str, str, str]]:
    queryset = MergedProteinOccurrence.objects.filter(pipeline_run=pipeline_run)
    if accession is not None:
        queryset = queryset.filter(summary__accession=accession)
    return set(
        queryset.values_list(
            "summary__accession",
            "summary__protein_id",
            "summary__method",
        )
    )


def _existing_residue_occurrence_keys_for_run(
    pipeline_run: PipelineRun,
    *,
    accession: str | None = None,
) -> set[tuple[str, str, str, str]]:
    queryset = MergedResidueOccurrence.objects.filter(pipeline_run=pipeline_run)
    if accession is not None:
        queryset = queryset.filter(summary__accession=accession)
    return set(
        queryset.values_list(
            "summary__accession",
            "summary__protein_id",
            "summary__method",
            "summary__repeat_residue",
        )
    )


def _protein_occurrence_groups_for_run(
    run_repeat_calls: list[RepeatCall],
) -> dict[tuple[tuple[str, str, str], int], dict[str, object]]:
    groups: dict[tuple[tuple[str, str, str], int], dict[str, object]] = {}
    calls_by_taxon_id: dict[int, list[RepeatCall]] = defaultdict(list)
    for repeat_call in run_repeat_calls:
        calls_by_taxon_id[repeat_call.taxon_id].append(repeat_call)

    for taxon_id, taxon_calls in calls_by_taxon_id.items():
        for group in _identity_merged_protein_groups_from_repeat_calls(taxon_calls):
            key = (group["accession"], group["protein_id"], group["method"])
            groups[(key, taxon_id)] = group

    return groups


def _residue_occurrence_groups_for_run(
    run_repeat_calls: list[RepeatCall],
) -> dict[tuple[tuple[str, str, str, str], int], dict[str, object]]:
    groups: dict[tuple[tuple[str, str, str, str], int], dict[str, object]] = {}
    calls_by_taxon_id: dict[int, list[RepeatCall]] = defaultdict(list)
    for repeat_call in run_repeat_calls:
        calls_by_taxon_id[repeat_call.taxon_id].append(repeat_call)

    for taxon_id, taxon_calls in calls_by_taxon_id.items():
        for group in _identity_merged_residue_groups_from_repeat_calls(taxon_calls):
            key = (group["accession"], group["protein_id"], group["method"], group["repeat_residue"])
            groups[(key, taxon_id)] = group

    return groups


def _refresh_protein_summaries(
    touched_keys: set[tuple[str, str, str]],
    *,
    source_repeat_calls: list[RepeatCall] | None = None,
) -> dict[tuple[str, str, str], MergedProteinSummary]:
    if not touched_keys:
        return {}

    groups_by_key = (
        _global_protein_groups_by_key(touched_keys)
        if source_repeat_calls is None
        else _protein_groups_by_key_from_repeat_calls(source_repeat_calls, keys=touched_keys)
    )
    existing_by_key = _existing_protein_summaries_by_key(touched_keys)
    stale_keys = touched_keys - groups_by_key.keys()
    if stale_keys:
        MergedProteinSummary.objects.filter(pk__in=[existing_by_key[key].pk for key in stale_keys if key in existing_by_key]).delete()

    to_create: list[MergedProteinSummary] = []
    to_update: list[MergedProteinSummary] = []
    for key, group in groups_by_key.items():
        summary = existing_by_key.get(key)
        if summary is None:
            summary = MergedProteinSummary(
                accession=group["accession"],
                protein_id=group["protein_id"],
                method=group["method"],
            )
            _apply_protein_summary_group(summary, group)
            to_create.append(summary)
            continue
        _apply_protein_summary_group(summary, group)
        to_update.append(summary)

    if to_create:
        MergedProteinSummary.objects.bulk_create(to_create, batch_size=MERGED_SUMMARY_BATCH_SIZE)
    if to_update:
        MergedProteinSummary.objects.bulk_update(
            to_update,
            [
                "protein_name",
                "protein_length",
                "gene_symbol_label",
                "methods_label",
                "repeat_residues_label",
                "coordinate_label",
                "protein_length_label",
                "representative_protein",
                "representative_repeat_call",
                "source_runs_count",
                "source_taxa_count",
                "source_proteins_count",
                "source_repeat_calls_count",
                "residue_groups_count",
                "collapsed_repeat_calls_count",
            ],
            batch_size=MERGED_SUMMARY_BATCH_SIZE,
        )

    return _existing_protein_summaries_by_key(groups_by_key.keys())


def _refresh_residue_summaries(
    touched_keys: set[tuple[str, str, str, str]],
    *,
    source_repeat_calls: list[RepeatCall] | None = None,
) -> dict[tuple[str, str, str, str], MergedResidueSummary]:
    if not touched_keys:
        return {}

    groups_by_key = (
        _global_residue_groups_by_key(touched_keys)
        if source_repeat_calls is None
        else _residue_groups_by_key_from_repeat_calls(source_repeat_calls, keys=touched_keys)
    )
    existing_by_key = _existing_residue_summaries_by_key(touched_keys)
    stale_keys = touched_keys - groups_by_key.keys()
    if stale_keys:
        MergedResidueSummary.objects.filter(pk__in=[existing_by_key[key].pk for key in stale_keys if key in existing_by_key]).delete()

    to_create: list[MergedResidueSummary] = []
    to_update: list[MergedResidueSummary] = []
    for key, group in groups_by_key.items():
        summary = existing_by_key.get(key)
        if summary is None:
            summary = MergedResidueSummary(
                accession=group["accession"],
                protein_id=group["protein_id"],
                method=group["method"],
                repeat_residue=group["repeat_residue"],
            )
            _apply_residue_summary_group(summary, group)
            to_create.append(summary)
            continue
        _apply_residue_summary_group(summary, group)
        to_update.append(summary)

    if to_create:
        MergedResidueSummary.objects.bulk_create(to_create, batch_size=MERGED_SUMMARY_BATCH_SIZE)
    if to_update:
        MergedResidueSummary.objects.bulk_update(
            to_update,
            [
                "protein_name",
                "protein_length",
                "gene_symbol_label",
                "methods_label",
                "coordinate_label",
                "protein_length_label",
                "start",
                "end",
                "length",
                "length_label",
                "normalized_purity",
                "purity_label",
                "representative_protein",
                "representative_repeat_call",
                "source_runs_count",
                "source_taxa_count",
                "source_proteins_count",
                "source_count",
            ],
            batch_size=MERGED_SUMMARY_BATCH_SIZE,
        )

    return _existing_residue_summaries_by_key(groups_by_key.keys())


def _global_protein_groups_by_key(
    touched_keys: set[tuple[str, str, str]],
) -> dict[tuple[str, str, str], dict[str, object]]:
    if not touched_keys:
        return {}

    source_repeat_calls: list[RepeatCall] = []
    for accession in sorted({key[0] for key in touched_keys}):
        source_repeat_calls.extend(_source_repeat_calls_for_accession(accession=accession))
    return _protein_groups_by_key_from_repeat_calls(source_repeat_calls, keys=touched_keys)


def _global_residue_groups_by_key(
    touched_keys: set[tuple[str, str, str, str]],
) -> dict[tuple[str, str, str, str], dict[str, object]]:
    if not touched_keys:
        return {}

    source_repeat_calls: list[RepeatCall] = []
    for accession in sorted({key[0] for key in touched_keys}):
        source_repeat_calls.extend(_source_repeat_calls_for_accession(accession=accession))
    return _residue_groups_by_key_from_repeat_calls(source_repeat_calls, keys=touched_keys)


def _source_repeat_calls_for_accession(
    *,
    accession: str,
    pipeline_run: PipelineRun | None = None,
) -> list[RepeatCall]:
    queryset = _merged_repeat_call_queryset().filter(accession=accession)
    if pipeline_run is not None:
        queryset = queryset.filter(pipeline_run=pipeline_run)
    return list(queryset.order_by())


def _protein_groups_by_key_from_repeat_calls(
    source_repeat_calls: list[RepeatCall],
    *,
    keys: set[tuple[str, str, str]] | None = None,
) -> dict[tuple[str, str, str], dict[str, object]]:
    key_set = set(keys) if keys is not None else None
    groups_by_key: dict[tuple[str, str, str], dict[str, object]] = {}
    for group in _identity_merged_protein_groups_from_repeat_calls(source_repeat_calls):
        key = (group["accession"], group["protein_id"], group["method"])
        if key_set is not None and key not in key_set:
            continue
        groups_by_key[key] = group
    return groups_by_key


def _residue_groups_by_key_from_repeat_calls(
    source_repeat_calls: list[RepeatCall],
    *,
    keys: set[tuple[str, str, str, str]] | None = None,
) -> dict[tuple[str, str, str, str], dict[str, object]]:
    key_set = set(keys) if keys is not None else None
    groups_by_key: dict[tuple[str, str, str, str], dict[str, object]] = {}
    for group in _identity_merged_residue_groups_from_repeat_calls(source_repeat_calls):
        key = (group["accession"], group["protein_id"], group["method"], group["repeat_residue"])
        if key_set is not None and key not in key_set:
            continue
        groups_by_key[key] = group
    return groups_by_key


def _existing_protein_summaries_by_key(
    keys,
) -> dict[tuple[str, str, str], MergedProteinSummary]:
    keys = set(keys)
    if not keys:
        return {}
    accessions = {key[0] for key in keys}
    protein_ids = {key[1] for key in keys}
    methods = {key[2] for key in keys}
    return {
        (summary.accession, summary.protein_id, summary.method): summary
        for summary in MergedProteinSummary.objects.filter(
            accession__in=accessions,
            protein_id__in=protein_ids,
            method__in=methods,
        )
        if (summary.accession, summary.protein_id, summary.method) in keys
    }


def _existing_residue_summaries_by_key(
    keys,
) -> dict[tuple[str, str, str, str], MergedResidueSummary]:
    keys = set(keys)
    if not keys:
        return {}
    accessions = {key[0] for key in keys}
    protein_ids = {key[1] for key in keys}
    methods = {key[2] for key in keys}
    residues = {key[3] for key in keys}
    return {
        (summary.accession, summary.protein_id, summary.method, summary.repeat_residue): summary
        for summary in MergedResidueSummary.objects.filter(
            accession__in=accessions,
            protein_id__in=protein_ids,
            method__in=methods,
            repeat_residue__in=residues,
        )
        if (summary.accession, summary.protein_id, summary.method, summary.repeat_residue) in keys
    }


def _apply_protein_summary_group(summary: MergedProteinSummary, group: dict[str, object]) -> None:
    representative_repeat_call = group["representative_repeat_call"]
    summary.protein_name = group["protein_name"]
    summary.protein_length = group["protein_length"] or 0
    summary.gene_symbol_label = group["gene_symbol_label"]
    summary.methods_label = group["methods_label"]
    summary.repeat_residues_label = group["repeat_residues_label"]
    summary.coordinate_label = group["coordinate_label"]
    summary.protein_length_label = group["protein_length_label"]
    summary.representative_protein = representative_repeat_call.protein
    summary.representative_repeat_call = representative_repeat_call
    summary.source_runs_count = group["source_runs_count"]
    summary.source_taxa_count = len({repeat_call.taxon_id for repeat_call in group["source_repeat_calls"]})
    summary.source_proteins_count = group["source_proteins_count"]
    summary.source_repeat_calls_count = group["source_repeat_calls_count"]
    summary.residue_groups_count = group["residue_groups_count"]
    summary.collapsed_repeat_calls_count = group["collapsed_repeat_calls_count"]


def _apply_residue_summary_group(summary: MergedResidueSummary, group: dict[str, object]) -> None:
    representative_repeat_call = group["representative_repeat_call"]
    summary.protein_name = group["protein_name"]
    summary.protein_length = group["protein_length"] or 0
    summary.gene_symbol_label = group["gene_symbol_label"]
    summary.methods_label = group["methods_label"]
    summary.coordinate_label = group["coordinate_label"]
    summary.protein_length_label = group["protein_length_label"]
    summary.start = group["start"]
    summary.end = group["end"]
    summary.length = group["length"]
    summary.length_label = group["length_label"]
    summary.normalized_purity = group["normalized_purity"]
    summary.purity_label = group["purity_label"]
    summary.representative_protein = representative_repeat_call.protein
    summary.representative_repeat_call = representative_repeat_call
    summary.source_runs_count = group["source_runs_count"]
    summary.source_taxa_count = len({repeat_call.taxon_id for repeat_call in group["source_repeat_calls"]})
    summary.source_proteins_count = group["source_proteins_count"]
    summary.source_count = group["source_count"]


def _create_protein_occurrences(
    pipeline_run: PipelineRun,
    groups: dict[tuple[tuple[str, str, str], int], dict[str, object]],
    summaries_by_key: dict[tuple[str, str, str], MergedProteinSummary],
) -> None:
    if not groups:
        return

    occurrence_objects: list[MergedProteinOccurrence] = []
    for (key, taxon_id), group in groups.items():
        summary = summaries_by_key.get(key)
        if summary is None:
            continue
        representative_repeat_call = group["representative_repeat_call"]
        occurrence_objects.append(
            MergedProteinOccurrence(
                summary=summary,
                pipeline_run=pipeline_run,
                taxon_id=taxon_id,
                representative_protein=representative_repeat_call.protein,
                representative_repeat_call=representative_repeat_call,
                source_proteins_count=group["source_proteins_count"],
                source_repeat_calls_count=group["source_repeat_calls_count"],
                residue_groups_count=group["residue_groups_count"],
                collapsed_repeat_calls_count=group["collapsed_repeat_calls_count"],
            )
        )

    if occurrence_objects:
        MergedProteinOccurrence.objects.bulk_create(occurrence_objects, batch_size=MERGED_SUMMARY_BATCH_SIZE)


def _create_residue_occurrences(
    pipeline_run: PipelineRun,
    groups: dict[tuple[tuple[str, str, str, str], int], dict[str, object]],
    summaries_by_key: dict[tuple[str, str, str, str], MergedResidueSummary],
) -> None:
    if not groups:
        return

    occurrence_objects: list[MergedResidueOccurrence] = []
    for (key, taxon_id), group in groups.items():
        summary = summaries_by_key.get(key)
        if summary is None:
            continue
        representative_repeat_call = group["representative_repeat_call"]
        occurrence_objects.append(
            MergedResidueOccurrence(
                summary=summary,
                pipeline_run=pipeline_run,
                taxon_id=taxon_id,
                representative_protein=representative_repeat_call.protein,
                representative_repeat_call=representative_repeat_call,
                source_proteins_count=group["source_proteins_count"],
                source_count=group["source_count"],
            )
        )

    if occurrence_objects:
        MergedResidueOccurrence.objects.bulk_create(occurrence_objects, batch_size=MERGED_SUMMARY_BATCH_SIZE)
