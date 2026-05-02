from __future__ import annotations

from dataclasses import dataclass, field

from apps.browser.models import PipelineRun


@dataclass
class TablePlan:
    table: str
    action: str  # "delete" | "repair" | "retain" | "never_touch"
    row_count: int
    estimated: bool = False


@dataclass
class DeletionPlan:
    pipeline_run_id: int
    run_id: str
    lifecycle_status: str
    active_job_id: int | None
    tables: list[TablePlan] = field(default_factory=list)
    artifact_roots: list[str] = field(default_factory=list)
    catalog_version: int = 0
    warnings: list[str] = field(default_factory=list)


def build_deletion_plan(pipeline_run: PipelineRun) -> DeletionPlan:
    """Return a read-only plan describing the full impact of deleting pipeline_run."""
    raise NotImplementedError
