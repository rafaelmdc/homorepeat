from __future__ import annotations

from collections.abc import Iterable, Mapping

from django.db.models import Q

from apps.imports.models import ImportBatch

from .models import PipelineRun


BROWSER_METADATA_RAW_COUNT_KEYS = (
    "genomes",
    "sequences",
    "proteins",
    "repeat_calls",
    "accession_status_rows",
    "accession_call_count_rows",
    "download_manifest_entries",
    "normalization_warnings",
)


def build_browser_metadata(
    pipeline_run: PipelineRun,
    *,
    raw_counts: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "raw_counts": _normalize_raw_counts(raw_counts),
        "facets": _build_browser_facets(pipeline_run),
    }


def resolve_run_browser_metadata(pipeline_run: PipelineRun) -> dict[str, object]:
    stored_metadata = pipeline_run.browser_metadata if isinstance(pipeline_run.browser_metadata, Mapping) else {}
    if browser_metadata_is_complete(stored_metadata):
        return {
            "raw_counts": _normalize_raw_counts(stored_metadata.get("raw_counts")),
            "facets": _normalize_facets(stored_metadata.get("facets")),
        }

    latest_batch = _latest_completed_import_batch(pipeline_run)
    raw_counts = None
    if latest_batch is not None:
        raw_counts = latest_batch.row_counts

    return build_browser_metadata(
        pipeline_run,
        raw_counts=raw_counts,
    )


def backfill_run_browser_metadata(
    pipeline_run: PipelineRun,
    *,
    force: bool = False,
) -> tuple[dict[str, object], bool]:
    current_metadata = pipeline_run.browser_metadata if isinstance(pipeline_run.browser_metadata, Mapping) else {}
    if not force and browser_metadata_is_complete(current_metadata):
        normalized_current = {
            "raw_counts": _normalize_raw_counts(current_metadata.get("raw_counts")),
            "facets": _normalize_facets(current_metadata.get("facets")),
        }
        return normalized_current, False

    if force:
        latest_batch = _latest_completed_import_batch(pipeline_run)
        metadata = build_browser_metadata(
            pipeline_run,
            raw_counts=latest_batch.row_counts if latest_batch is not None else None,
        )
    else:
        metadata = resolve_run_browser_metadata(pipeline_run)
    pipeline_run.browser_metadata = metadata
    pipeline_run.save(update_fields=["browser_metadata"])
    return metadata, True


def browser_metadata_is_complete(metadata: Mapping[str, object] | None) -> bool:
    if not isinstance(metadata, Mapping):
        return False

    raw_counts = metadata.get("raw_counts")
    facets = metadata.get("facets")
    if not isinstance(raw_counts, Mapping) or not isinstance(facets, Mapping):
        return False

    if any(key not in raw_counts for key in BROWSER_METADATA_RAW_COUNT_KEYS):
        return False

    return "methods" in facets and "residues" in facets


def _build_browser_facets(pipeline_run: PipelineRun) -> dict[str, list[str]]:
    methods = pipeline_run.run_parameters.order_by("method").values_list("method", flat=True).distinct()
    residues = list(pipeline_run.run_parameters.order_by().values_list("repeat_residue", flat=True))
    residues.extend(pipeline_run.accession_call_count_rows.order_by().values_list("repeat_residue", flat=True))
    return {
        "methods": _normalize_string_list(methods),
        "residues": _normalize_string_list(residues),
    }


def _latest_completed_import_batch(pipeline_run: PipelineRun) -> ImportBatch | None:
    filters = Q(pipeline_run=pipeline_run)
    if pipeline_run.publish_root:
        filters |= Q(source_path=pipeline_run.publish_root)
    return (
        ImportBatch.objects.filter(filters, status=ImportBatch.Status.COMPLETED)
        .order_by("-finished_at", "-started_at", "-pk")
        .first()
    )


def _normalize_raw_counts(raw_counts: Mapping[str, object] | None) -> dict[str, int]:
    source = raw_counts if isinstance(raw_counts, Mapping) else {}
    normalized: dict[str, int] = {}
    for key in BROWSER_METADATA_RAW_COUNT_KEYS:
        value = source.get(key, 0)
        try:
            normalized[key] = int(value)
        except (TypeError, ValueError):
            normalized[key] = 0
    return normalized


def _normalize_facets(facets: object) -> dict[str, list[str]]:
    source = facets if isinstance(facets, Mapping) else {}
    return {
        "methods": _normalize_string_list(source.get("methods", [])),
        "residues": _normalize_string_list(source.get("residues", [])),
    }


def _normalize_string_list(values: object) -> list[str]:
    if isinstance(values, str):
        iterable: Iterable[object] = [values]
    elif isinstance(values, Iterable):
        iterable = values
    else:
        iterable = []
    normalized = {str(value).strip() for value in iterable if str(value).strip()}
    return sorted(normalized)
