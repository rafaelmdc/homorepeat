from __future__ import annotations

from collections.abc import Iterable, Mapping
from itertools import chain

from apps.imports.models import ImportBatch

from .import_batches import latest_completed_import_batch_for_run
from .models import PipelineRun


BROWSER_METADATA_RAW_COUNT_KEYS = (
    "genomes",
    "sequences",
    "proteins",
    "repeat_calls",
    "repeat_call_contexts",
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


def resolve_browser_facets(
    *,
    pipeline_run: PipelineRun | None = None,
    pipeline_runs=None,
) -> dict[str, list[str]]:
    if pipeline_run is not None:
        return resolve_run_browser_metadata(pipeline_run)["facets"]

    if pipeline_runs is None:
        pipeline_runs = PipelineRun.objects.order_by("run_id")

    if hasattr(pipeline_runs, "prefetch_related"):
        pipeline_runs = pipeline_runs.prefetch_related("run_parameters", "accession_call_count_rows")

    methods: set[str] = set()
    residues: set[str] = set()
    for current_run in pipeline_runs:
        facets = resolve_run_browser_metadata(current_run)["facets"]
        methods.update(facets["methods"])
        residues.update(facets["residues"])

    return {
        "methods": sorted(methods),
        "residues": sorted(residues),
    }


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
    run_parameter_residues = pipeline_run.run_parameters.order_by().values_list("repeat_residue", flat=True).distinct()
    accession_count_residues = (
        pipeline_run.accession_call_count_rows.order_by().values_list("repeat_residue", flat=True).distinct()
    )
    return {
        "methods": _normalize_string_list(methods),
        "residues": _normalize_string_list(chain(run_parameter_residues, accession_count_residues)),
    }


def _latest_completed_import_batch(pipeline_run: PipelineRun) -> ImportBatch | None:
    return latest_completed_import_batch_for_run(pipeline_run)


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
